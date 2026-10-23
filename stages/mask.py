"""Stage 4, mask: SAM 3 raw masks on Replicate (`raw_masks.segment_raw` + `clean_border_fragments`), unchanged.

One prediction per comma-separated term (unioned), retry on the RGB frames when the depth pass finds nothing,
then `SAM_FALLBACK_MODEL`; every prediction is in `sam-attempts.json`, the chosen route in `sam-report.json`.
The mask wand tools (`local_propagate`, `brush`, `sam3_points_fal`, `sam2_points_replicate`, and `edit_layer` = the
timeline editor's saved mask, see stages/masktrack.py) edit an existing
mask: they are run as a branch at this stage, start from the parent run's masks (`base = parent`, found through
`base_run` or run.json's parent) and write the same artifact set (`raw-masks/`, `clean-masks/`, `sam-report.json`
with a `wand` section, `mask-edits.json` with the click history), so composite and face re-run unchanged.
See docs/MASK-WAND.md.
"""
from pathlib import Path
import json,time
import numpy as np
from .base import Tool,register,allow_off,fresh
from . import wand

class Sam3Replicate(Tool):
    name='sam3_replicate';stage='mask';label='SAM 3 on Replicate';paid=True;description='Segments the subject on the depth video with SAM 3 (one job per comma-separated term, unioned); retries on RGB frames, then the fallback model.'
    params={'prompt':{'type':'string','default':'person','label':'Subject to replace','hint':'One short noun phrase; comma-separated terms run as separate SAM jobs (each billed) and are combined.'}}
    inputs=('depth.mp4','original.mp4');outputs=('raw-masks','clean-masks','sam-report.json','sam-attempts.json','sam-raw-request.json','mask-cleanup-report.json')
    def run(self,inputs,params,folder,status):
        import raw_masks
        folder=Path(folder);prompt=str(params.get('prompt') or 'person')
        for name in self.outputs:fresh(folder/name)
        for extra in folder.glob('raw-masks-*'):fresh(extra)
        video=folder/'depth.mp4' if (folder/'depth.mp4').exists() else folder/'original.mp4'
        status(f'SAM 3 · segmenting {prompt!r} on the depth video' if video.name=='depth.mp4' else f'SAM 3 · segmenting {prompt!r} on the original video')
        raw_dir=raw_masks.clean_border_fragments(raw_masks.segment_raw(video,folder,prompt,rgb_video=folder/'original.mp4',status=status))
        report=self.summarize(folder);warnings=[]
        if report.get('source')=='rgb':warnings.append('SAM found nothing on the depth frames and used the original RGB frames instead.')
        if report.get('model') and report['model']!=raw_masks.PRIMARY_MODEL:warnings.append(f'The primary SAM 3 model found nothing; the fallback model {report["model"]} produced these masks.')
        return {'outputs':[n for n in self.outputs if (folder/n).exists()]+[p.name for p in folder.glob('raw-masks-*') if p.is_dir()],**report,'warnings':warnings,'data':{'clean_masks':str(Path(raw_dir).name)}}
    @staticmethod
    def summarize(folder):
        """frames / health / method from sam-report.json (also used by the legacy migration)."""
        folder=Path(folder)
        try:report=json.loads((folder/'sam-report.json').read_text())
        except (OSError,ValueError):return {'frames':{'covered':None,'filled':0,'missing':None},'health':'No SAM report found.'}
        frames=report.get('frames');attempts=report.get('attempts') or []
        covered=max([a.get('frames_with_mask') or 0 for a in attempts],default=0)
        matched=[a['term'] for a in attempts if a.get('frames_with_mask')]
        missing=(frames-covered) if frames is not None else None
        if report.get('method') is None:health='SAM returned no masks for '+repr(report.get('prompt'))+'.'
        elif frames is None:health='Masks written'+(f" from {report.get('source')} frames" if report.get('source') else '')+'.'
        else:health=f"Masks on {covered} of {frames} frames from {report.get('source')} frames"+(f"; terms matched: {', '.join(matched)}" if matched else '')+'.'
        return {'frames':{'covered':covered,'filled':0,'missing':missing},'health':health,'source':report.get('source'),'model':report.get('model'),'method':report.get('method'),'terms':report.get('terms')}

# ---------------------------------------------------------------- mask wand tools (edits of an existing mask, run as a branch at this stage)

def parse_edits(value):
    """`edits` as a list of {frame, x, y, label}; accepts a JSON string. Raises ValueError with a plain sentence."""
    if value in (None,''):return []
    data=json.loads(value) if isinstance(value,str) else value
    if not isinstance(data,list):raise ValueError('The edits must be a list of clicks ({frame, x, y, label}).')
    out=[]
    for k,e in enumerate(data):
        if not isinstance(e,dict):raise ValueError(f'Click {k+1} is not an object with frame, x, y and label.')
        try:frame=int(e.get('frame',0));x=float(e.get('x'));y=float(e.get('y'))
        except (TypeError,ValueError):raise ValueError(f'Click {k+1} needs a frame number and x, y between 0 and 1.')
        if not (0<=x<=1 and 0<=y<=1):raise ValueError(f'Click {k+1} is outside the picture (x and y must be between 0 and 1).')
        label=1 if str(e.get('label',1)).strip().lower() in ('1','true','include','+') else 0
        out.append({'frame':frame,'x':round(x,5),'y':round(y,5),'label':label,'object_id':str(e.get('object_id') or ('add' if label else 'remove'))})
    return out

def parse_strokes(value):
    """`strokes` as a list of {frame_from, frame_to, mode, points, radius}; accepts a JSON string."""
    if value in (None,''):return []
    data=json.loads(value) if isinstance(value,str) else value
    if not isinstance(data,list):raise ValueError('The strokes must be a list of {frame_from, frame_to, mode, points, radius}.')
    out=[]
    for k,s in enumerate(data):
        if not isinstance(s,dict) or not isinstance(s.get('points'),list) or not s['points']:raise ValueError(f'Stroke {k+1} has no points.')
        try:
            pts=[[round(float(x),5),round(float(y),5)] for x,y in s['points']]
            a=int(s.get('frame_from',0));b=int(s.get('frame_to',a));radius=float(s.get('radius',0.02))
        except (TypeError,ValueError):raise ValueError(f'Stroke {k+1} needs numeric points, frames and a radius.')
        if any(not (0<=x<=1 and 0<=y<=1) for x,y in pts):raise ValueError(f'Stroke {k+1} leaves the picture (points must be between 0 and 1).')
        out.append({'frame_from':min(a,b),'frame_to':max(a,b),'mode':'erase' if str(s.get('mode','paint')).lower() in ('erase','exclude') else 'paint','points':pts,'radius':max(0.002,min(0.5,radius))})
    return out

class WandTool(Tool):
    """Shared plumbing: base masks, merge + write, the sam-report `wand` section and the mask-edits history."""
    stage='mask';inputs=('depth.mp4','original.mp4');outputs=('raw-masks','clean-masks','sam-report.json','mask-edits.json')
    base_params={'base':{'type':'choice','default':'parent','choices':['parent','replace'],'label':'Start from','hint':'parent: edit the run this branch came from; replace: start from an empty mask.'},
                 'base_run':{'type':'string','default':'','label':'Base run','hint':'Run id whose masks are edited (filled in by the wand; the parent run when empty).'}}
    def regions(self,inputs,params,folder,status):
        """Return (per_frame {frame: [(mode, region)]}, notes, data) for the edit; regions may be at work resolution."""
        raise NotImplementedError
    def run(self,inputs,params,folder,status):
        folder=Path(folder);base=params.get('base') or 'parent'
        for name in self.outputs:fresh(folder/name)
        for extra in folder.glob('raw-masks-*'):fresh(extra)
        h,w,frames,fps=wand.frame_shape(folder/'original.mp4')
        base_masks,base_folder=wand.load_base(folder.parent,params.get('base_run'),folder);warnings=[]
        if base=='parent' and base_masks is None:warnings.append('No earlier mask was found to start from, so the edit starts from an empty mask.')
        per_frame,notes,data=self.regions(inputs,params,folder,status)
        result=wand.write_edited_masks(folder,base_masks,per_frame,(h,w),frames,base=base,status=status)
        changed=result['changed']
        # sam-report.json: the base run's report plus a `wand` section; manifest.json reads `method` from it
        report={}
        if base_folder is not None and (base_folder/'sam-report.json').exists():
            try:report=json.loads((base_folder/'sam-report.json').read_text())
            except (OSError,ValueError):report={}
        report.setdefault('frames',frames)
        report['method']=((report.get('method') or 'masks')+' + mask wand ('+self.label+')') if base=='parent' else 'mask wand ('+self.label+') from an empty mask'
        report['wand']={'tool':self.name,'label':self.label,'base':base,'base_run':base_folder.name if base_folder is not None else None,'frames_changed':changed,'notes':notes,**data}
        (folder/'sam-report.json').write_text(json.dumps(report,indent=1))
        entry={'time':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'tool':self.name,'base':base,'base_run':report['wand']['base_run'],'frames_changed':len(changed),**{k:params[k] for k in ('edits','strokes') if params.get(k)}}
        (folder/'mask-edits.json').write_text(json.dumps({'note':'Mask wand click and stroke history; each entry is one branch at the mask stage.','history':wand.history(base_folder)+[entry]},indent=1,default=str))
        ranges=self.changed_ranges(changed,fps)
        return {'outputs':[n for n in self.outputs if (folder/n).exists()],'frames':{'covered':result['covered'],'filled':0,'missing':frames-result['covered']},'warnings':warnings,
                'health':self.health(notes,changed,fps,frames),'data':{'wand':report['wand'],'changed_ranges':ranges,'coverage':result['coverage'],'fps':fps}}
    @staticmethod
    def changed_ranges(changed,fps):
        from .report import seconds_ranges
        return seconds_ranges(changed,fps)
    def health(self,notes,changed,fps,frames):
        if not changed:return 'The edit changed no frame of the mask.'
        return f'Mask edited on {len(changed)} of {frames} frames ({self.changed_ranges(changed,fps)[0]["start_s"]}–{self.changed_ranges(changed,fps)[-1]["end_s"]} s).'

class LocalPropagate(WandTool):
    name='local_propagate';label='Local propagation (free, rougher edges)';paid=False
    description='Grows a region from each click using the depth and colour of the clicked frame, then follows it forward and backward with optical flow. Free and offline; edges are rougher than SAM.'
    params={'edits':{'type':'string','default':'','label':'Clicks','hint':'JSON list of {frame, x, y, label}; label 1 adds the region, 0 removes it (coordinates 0–1).'},
            'max_frames':{'type':'number','default':120,'label':'Max frames each way','hint':'How far an edit may travel forward and backward from the clicked frame.'},
            'depth_tol':{'type':'number','default':24,'label':'Depth tolerance','hint':'0–255: how different in depth a pixel may be from the click and still belong to the region.'},
            'color_tol':{'type':'number','default':32,'label':'Colour tolerance','hint':'0–255 per channel.'},
            **WandTool.base_params}
    def regions(self,inputs,params,folder,status):
        edits=parse_edits(params.get('edits'))
        if not edits:raise ValueError('No clicks were given for the local propagation. Click + or − on the clip first.')
        per_frame,notes,shape,fps=wand.local_propagate(folder,edits,max_frames=int(params.get('max_frames') or 120),depth_tol=int(params.get('depth_tol') or 24),color_tol=int(params.get('color_tol') or 32),status=status)
        return per_frame,notes,{'edits':edits}
    def health(self,notes,changed,fps,frames):
        if not notes:return 'Nothing to propagate.'
        parts=[]
        for n in notes:
            verb='Added' if n['mode']=='include' else 'Removed'
            parts.append(f"{verb} a region from frame {n['frame']} forward to {round((n['last_frame']+1)/fps,1)} s ({wand.stop_words(n['forward_stop'])}) and back to {round(n['first_frame']/fps,1)} s ({wand.stop_words(n['backward_stop'],backward=True)}) on {n['frames']} frames")
        return '; '.join(parts)+'.'

class Brush(WandTool):
    name='brush';label='Brush (free)';paid=False
    description='Paints or erases the mask by hand on a range of frames: the last-1% fallback when nothing else fits.'
    params={'strokes':{'type':'string','default':'','label':'Strokes','hint':'JSON list of {frame_from, frame_to, mode: paint|erase, points: [[x, y], …], radius} (0–1 coordinates, radius as a fraction of the height).'},
            **WandTool.base_params}
    inputs=('original.mp4',)
    def regions(self,inputs,params,folder,status):
        strokes=parse_strokes(params.get('strokes'))
        if not strokes:raise ValueError('No brush strokes were given. Paint or erase on the clip first.')
        h,w,frames,fps=wand.frame_shape(Path(folder)/'original.mp4')
        status(f'Mask wand · painting {len(strokes)} stroke(s)')
        per_frame=wand.brush_regions(strokes,(h,w),frames)
        notes=[{'stroke':k,'mode':'exclude' if s['mode']=='erase' else 'include','frame_from':s['frame_from'],'frame_to':min(frames-1,s['frame_to']),'points':len(s['points'])} for k,s in enumerate(strokes)]
        return per_frame,notes,{'strokes':strokes}
    def health(self,notes,changed,fps,frames):
        if not changed:return 'The strokes changed no frame.'
        painted=sum(1 for n in notes if n['mode']=='include');erased=len(notes)-painted
        return f"{'Painted' if painted else 'Erased'} {len(notes)} stroke(s) on {len(changed)} frames ({round(min(changed)/fps,2)}–{round((max(changed)+1)/fps,2)} s)"+(f', {erased} erasing' if painted and erased else '')+'.'

class HostedWand(WandTool):
    """Shared part of the hosted point-prompt tools: one call per mode (include points, exclude points), result merged."""
    paid=True
    hosted_params={'edits':{'type':'string','default':'','label':'Clicks','hint':'JSON list of {frame, x, y, label}; label 1 = include, 0 = exclude.'},
                   'prompt':{'type':'string','default':'person','label':'Subject','hint':'Text prompt sent with the clicks when starting from an empty mask (inherited from the parent).'},
                   'source':{'type':'choice','default':'auto','choices':['auto','depth','rgb'],'label':'Video sent','hint':'auto: the frames the parent mask came from (depth by default).'},
                   **WandTool.base_params}
    def groups(self,params):
        edits=parse_edits(params.get('edits'))
        if not edits:raise ValueError('No clicks were given. Click + or − on the clip first.')
        inc=[e for e in edits if e['label']==1];exc=[e for e in edits if e['label']==0]
        return edits,[(mode,pts) for mode,pts in (('include',inc),('exclude',exc)) if pts]
    def video_for(self,folder,params):
        folder=Path(folder);source=params.get('source') or 'auto'
        if source=='auto':
            masks,base_folder=wand.load_base(folder.parent,params.get('base_run'),folder);source='depth'
            if base_folder is not None and (base_folder/'sam-report.json').exists():
                try:source=json.loads((base_folder/'sam-report.json').read_text()).get('source') or 'depth'
                except (OSError,ValueError):pass
        video=folder/('depth.mp4' if source=='depth' else 'original.mp4')
        if not video.exists():video=folder/'original.mp4'
        return video,('depth' if video.name=='depth.mp4' else 'rgb')
    def estimate_cost(self,inputs,params):
        from . import costs
        return costs.estimate_tool(self.name,inputs.get('seconds'),params)

class Sam3PointsFal(HostedWand):
    name='sam3_points_fal';label='SAM 3 on fal (point prompts)';endpoint='fal-ai/sam-3/video-rle'
    description='Sends the clicks (and the subject prompt when replacing) to SAM 3 on fal, which tracks the clicked objects through the clip; include objects are added, exclude objects subtracted. Paid: one call per click type.'
    params=HostedWand.hosted_params
    def regions(self,inputs,params,folder,status):
        import fal_client,requests
        from config import load_env,credential
        from .calls import record_call
        from . import costs
        folder=Path(folder);edits,groups=self.groups(params);video,source=self.video_for(folder,params)
        h,w,frames,fps=wand.frame_shape(video);per_frame={};notes=[];raw={}
        seconds=inputs.get('seconds') or costs.clip_seconds(folder)
        url=None
        for mode,pts in groups:
            record_call(folder,'fal',self.endpoint,cost_usd=costs.price_for(self.name,seconds))   # before any I/O (offline mode stops here)
            load_env();credential('FAL_KEY')
            if url is None:
                status(f'SAM 3 on fal · uploading the {source} clip');url=fal_client.upload_file(str(video))
            arguments={'video_url':url,'apply_mask':False,
                       'point_prompts':[{'x':p['x']*w,'y':p['y']*h,'label':1,'frame_index':p['frame'],'object_id':mode} for p in pts]}
            if (params.get('base') or 'parent')=='replace' and mode=='include' and params.get('prompt'):arguments['prompt']=str(params['prompt'])
            status(f'SAM 3 on fal · tracking the {mode} region ({len(pts)} click(s))')
            handle=fal_client.submit(self.endpoint,arguments=arguments);result=handle.get()
            raw[mode]={'request_id':getattr(handle,'request_id',None),'arguments':{k:v for k,v in arguments.items() if k!='video_url'},'result_keys':sorted(result.keys()) if isinstance(result,dict) else type(result).__name__}
            masks=decode_fal_rle(result,frames,(h,w),download=lambda u:requests.get(u,timeout=120).content)
            for f,m in masks.items():per_frame.setdefault(f,[]).append((mode,m))
            notes.append({'mode':mode,'clicks':len(pts),'frames_with_mask':sum(1 for m in masks.values() if m.any()),'request_id':raw[mode]['request_id']})
        (folder/'wand-hosted.json').write_text(json.dumps({'provider':'fal','endpoint':self.endpoint,'source':source,'calls':raw},indent=1,default=str))
        return per_frame,notes,{'edits':edits,'provider':'fal','endpoint':self.endpoint,'source':source}

class Sam2PointsReplicate(HostedWand):
    name='sam2_points_replicate';label='SAM 2 on Replicate (point prompts)';endpoint='meta/sam-2-video'
    description='Sends the clicks to SAM 2 video on Replicate (binary PNG masks, one per frame); include objects are added, exclude objects subtracted. Paid: one prediction per click type.'
    params=HostedWand.hosted_params
    outputs=WandTool.outputs+('sam-attempts.json','sam-raw-request.json')
    def regions(self,inputs,params,folder,status):
        import raw_masks
        folder=Path(folder);edits,groups=self.groups(params);video,source=self.video_for(folder,params)
        h,w,frames,fps=wand.frame_shape(video);per_frame={};notes=[]
        headers=raw_masks._headers()
        status(f'SAM 2 on Replicate · uploading the {source} clip')
        url=raw_masks._upload(video,headers,folder)             # record_call happens inside, before the upload
        version=raw_masks._model_version(self.endpoint,headers)
        for mode,pts in groups:
            body={'version':version,'input':{'input_video':url,'click_coordinates':','.join(f'[{int(round(p["x"]*w))},{int(round(p["y"]*h))}]' for p in pts),
                  'click_labels':','.join('1' for _ in pts),'click_frames':','.join(str(p['frame']) for p in pts),'click_object_ids':','.join(mode for _ in pts),
                  'mask_type':'binary','output_video':False,'output_format':'png','output_frame_interval':1}}
            status(f'SAM 2 on Replicate · tracking the {mode} region ({len(pts)} click(s))')
            j=raw_masks._predict(headers,body,folder,f'{self.endpoint} · wand {mode}')
            output=j.get('output') or [];urls=output if isinstance(output,list) else [output]
            got=0
            for i,u in enumerate(urls[:frames]):
                if not isinstance(u,str):continue
                m=raw_masks._png_mask(raw_masks._download(u))
                if m.shape!=(h,w):m=wand.upscale(m,(h,w))
                per_frame.setdefault(i,[]).append((mode,m));got+=1
            notes.append({'mode':mode,'clicks':len(pts),'frames_with_mask':got,'prediction':j.get('id')})
        return per_frame,notes,{'edits':edits,'provider':'replicate','endpoint':self.endpoint,'source':source}

def decode_fal_rle(result,frames,shape,download=None):
    """Per-frame bool masks from a fal `sam-3/video-rle` result. The shape of `rle` is unverified (see docs/MASK-WAND.md):
    handles a list of COCO RLEs (one per frame), one RLE string per frame, a JSON string of either, or a File {url}."""
    rle=result.get('rle') if isinstance(result,dict) else result
    if isinstance(rle,dict) and rle.get('url'):
        if download is None:raise ValueError('fal returned the masks as a file but no downloader was given.')
        rle=json.loads(download(rle['url']).decode('utf-8'))
    if isinstance(rle,str):
        try:parsed=json.loads(rle)
        except ValueError:parsed=None
        if isinstance(parsed,(list,dict)):rle=parsed
    if isinstance(rle,dict) and 'counts' in rle:rle=[rle]
    if not isinstance(rle,list):raise ValueError('fal returned masks in a form the app does not understand yet (expected one RLE per frame); see docs/MASK-WAND.md.')
    size=None
    meta=result.get('metadata') if isinstance(result,dict) else None
    if isinstance(meta,dict):
        if meta.get('size'):size=meta['size']
        elif meta.get('height') and meta.get('width'):size=[meta['height'],meta['width']]
    masks={}
    for i,item in enumerate(rle[:frames]):
        if item in (None,''):continue
        m=wand.rle_decode(item,size or list(shape))
        if m.shape!=tuple(shape):m=wand.upscale(m,shape)
        masks[i]=m
    return masks

class EditLayerMask(WandTool):
    """The mask the timeline editor built (clicks applied in one propagation pass, brush strokes, Grab hands), saved
    with "Save edits". `stages/masktrack.py` copies the final mask set into `edit-layer/mask/` of the child before the
    child runs; this tool copies it into raw-masks/ + clean-masks/ and writes sam-report.json (+ `wand`) and
    mask-edits.json like the other wand tools, so composite and face re-run unchanged on it."""
    name='edit_layer';label='Timeline edits (free)';paid=False
    description='Uses the mask you edited on the timeline (applied clicks, brush strokes, Grab hands). Free and local; saved with "Save edits".'
    params={'layer_sha':{'type':'string','default':'','label':'Edit layer','hint':'sha256 of the saved mask edits (filled in by Save edits).'},
            'result':{'type':'string','default':'','label':'Result','hint':'Id of the edited mask set in the edit session.'},
            **WandTool.base_params}
    inputs=('original.mp4','edit-layer/mask')
    def run(self,inputs,params,folder,status):
        import shutil
        folder=Path(folder);src=folder/'edit-layer'/'mask'
        if not src.is_dir() or not any(src.glob('mask_*.png')):raise ValueError('The timeline mask edits are missing from this run (edit-layer/mask/). Save the edits again from the run you edited.')
        for name in self.outputs:fresh(folder/name)
        for extra in folder.glob('raw-masks-*'):fresh(extra)
        h,w,frames,fps=wand.frame_shape(folder/'original.mp4')
        base_masks,base_folder=wand.load_base(folder.parent,params.get('base_run'),folder)
        raw=folder/'raw-masks';clean=folder/'clean-masks';raw.mkdir(parents=True);clean.mkdir(parents=True)
        changed=[];covered=0;missing=[];coverage={}
        status('Mask · copying the timeline edits')
        for i in range(frames):
            name=f'mask_{i:05d}.png';path=src/name
            if path.exists():
                shutil.copyfile(path,raw/name);shutil.copyfile(path,clean/name)
            else:
                missing.append(i);wand.write_mask(np.zeros((h,w),bool) if base_masks is None else wand.read_mask(base_masks,i,(h,w)),raw/name);shutil.copyfile(raw/name,clean/name)
            after=wand.read_mask(clean,i,(h,w))
            if after.any():covered+=1
            if not np.array_equal(after,wand.read_mask(base_masks,i,(h,w))):changed.append(i);coverage[i]=round(float(after.mean()),4)
        try:record=json.loads((folder/'edit-layer'/'mask.json').read_text())
        except (OSError,ValueError):record={}
        report={}
        if base_folder is not None and (base_folder/'sam-report.json').exists():
            try:report=json.loads((base_folder/'sam-report.json').read_text())
            except (OSError,ValueError):report={}
        report.setdefault('frames',frames)
        report['method']=(report.get('method') or 'masks')+' + timeline edits'
        report['wand']={'tool':self.name,'label':self.label,'base':'parent','base_run':base_folder.name if base_folder is not None else None,'frames_changed':changed,
                        'layer_sha':params.get('layer_sha'),'result':params.get('result'),'fixes':record.get('fixes') or [],'summary':record.get('summary') or []}
        (folder/'sam-report.json').write_text(json.dumps(report,indent=1))
        entry={'time':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'tool':self.name,'base':'parent','base_run':report['wand']['base_run'],'frames_changed':len(changed),'layer_sha':params.get('layer_sha'),'fixes':record.get('fixes') or []}
        (folder/'mask-edits.json').write_text(json.dumps({'note':'Mask wand click and stroke history; each entry is one branch at the mask stage.','history':wand.history(base_folder)+[entry]},indent=1,default=str))
        warnings=[f'{len(missing)} frame(s) were missing from the timeline edits and kept the earlier mask.'] if missing else []
        lines=record.get('summary') or []
        health=('Mask from the timeline edits ('+'; '.join(lines)+'): ' if lines else 'Mask from the timeline edits: ')+(f'{len(changed)} of {frames} frames differ from run {report["wand"]["base_run"]}.' if changed else 'no frame differs from the earlier mask.')
        return {'outputs':[n for n in self.outputs if (folder/n).exists()],'frames':{'covered':covered,'filled':0,'missing':frames-covered},'warnings':warnings,'health':health,
                'data':{'wand':report['wand'],'changed_ranges':self.changed_ranges(changed,fps) if changed else [],'coverage':coverage,'fps':fps}}

register(Sam3Replicate);register(LocalPropagate);register(Brush);register(Sam3PointsFal);register(Sam2PointsReplicate);register(EditLayerMask);allow_off('mask')
