"""Mask track of the edit layer (Agent 2): pending clicks and brush strokes, "Apply to clip" (every pending click of
every frame in ONE propagation pass), quick / full quality, Grab hands, problem ticks and the save hook (the
`edit_layer` mask tool in stages/mask.py). docs/TIMELINE-SPEC.md §4 and §A2.

Layer value (`layer.mask`):
  points:  [{id, frame, x, y, label}]                          pending clicks (label 1 include, 0 exclude; x, y 0–1)
  strokes: [{id, frame_from, frame_to, mode, points, radius}]  pending brush strokes (mode paint | erase)
  applied: [{id, kind: fix | hands, tool, quality, points, strokes, frames, base, result, frames_changed, intended_tool?}]
           in order; each entry is a full mask set built on the previous one (`base` = the previous result or null)
Nothing here writes into a run folder. Files live in RUNS/_sessions/<id>/mask/:
  results/<key>/mask_00000.png … + mask.mp4 (B/W) + areas.json + problems.json   one full mask set per applied entry;
                                  key = sha256 of the entry's inputs (base, fixes, quality, tool), so the same Apply is never computed twice
  previews/preview-<frame>-<hash>.png   what the clicks / strokes on one frame select (transparent overlay, no propagation)
  work/                                 symlinks to the run's clips for the hosted tools and the hands worker (their logs and
                                        calls land in the session: stages.calls routes a path under _sessions/<id>/ to its calls.jsonl)
Current mask = applied[-1].result, else the run's own masks (clean-masks, else raw-masks). Undo of an Apply drops the
entry; the previous result is still on disk, so undo / redo are instant.
"""
from pathlib import Path
import copy,hashlib,json,os,shutil,subprocess,time,uuid
import numpy as np
from .editlayer import Track,register_track,EditError,session_dir,note,layer_sha,SESSIONS
from . import wand

ROOT=Path(__file__).resolve().parents[1]
SIDES={'quick':240,'full':480}      # working size (longest side) of the local propagation per quality
HOSTED=('sam3_points_fal','sam2_points_replicate')
TOOLS=('local_propagate',)+HOSTED
# Problem ticks (documented in TIMELINE-SPEC §A2):
JUMP=0.12          # |area[i] - area[i-1]| > 12 % of the median area = a "jump" tick at frame i
JUMP_SPAN=24       # a drop followed by a rise within 24 frames flags the frames in between (for Grab hands)
JUMP_EDGE=8        # an unpaired rise flags the 8 frames before it, an unpaired drop the 8 frames after it
SMALL=4            # components are found on masks downscaled 4x
LIMB_MIN=0.002     # a separate part counts when it covers at least 0.2 % of the frame
LIMB_OVERLAP=0.2   # it "vanished" at frame i when less than 20 % of it is still covered (mask dilated by 2 px at 1/4 size)
LIMB_RETURN=24     # and the gap is reported up to its return within 24 frames
HAND_DEPTH_TOL=20  # Grab hands: depth flood tolerance from each landmark
HAND_GROW=0.35     # the landmarks' hull is grown by 35 % of the hand size before the depth rule cuts it
HAND_MODEL_URL='https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task'

def plural(n,word,many=None):return f'{n} {word if n==1 else (many or word+"s")}'

def frames_text(frames):
    frames=sorted(set(int(f) for f in frames))
    if not frames:return ''
    return f' on frame {frames[0]}' if len(frames)==1 else f' on frames {frames[0]}–{frames[-1]}'

def items(value):
    value=value if isinstance(value,dict) else {}
    return [x for x in value.get('points') or [] if isinstance(x,dict)],[x for x in value.get('strokes') or [] if isinstance(x,dict)],[x for x in value.get('applied') or [] if isinstance(x,dict)]

def mask_root(sdir):return Path(sdir)/'mask'
def results_root(sdir):return mask_root(sdir)/'results'
def current_key(value):
    applied=items(value)[2];return applied[-1].get('result') if applied else None
def video_url(ident,key):return f'/runs/{SESSIONS}/{ident}/mask/results/{key}/mask.mp4'

def session_value(runs_root,ident):
    from .editlayer import load
    session=load(runs_root,ident)
    return session,((session or {}).get('layer') or {}).get('mask') or {}

def current_masks(sdir,folder,value):
    """The mask folder the next edit builds on: the latest applied result, else the run's own masks (None when it has none)."""
    key=current_key(value)
    if key:
        found=results_root(sdir)/key
        if found.is_dir():return found
        raise EditError('The applied mask fixes are missing from the edit session.','Undo the last Apply, or Discard the edits and start again.')
    return wand.mask_dir(folder)

# ---------------------------------------------------------------- writing a result (one full mask set) + its B/W video

def encode_mask_video(frames_iter,path,fps,shape):
    """B/W mask video for the editor's views (libx264 ultrafast; odd sizes padded by one pixel)."""
    import av
    from fractions import Fraction
    h,w=shape;H,W=h+(h%2),w+(w%2);tmp=Path(path).with_suffix('.tmp.mp4')
    with av.open(str(tmp),'w') as c:
        s=c.add_stream('libx264',rate=int(round(fps)) or 24);s.width=W;s.height=H;s.pix_fmt='yuv420p';s.options={'crf':'20','preset':'ultrafast'}
        for i,m in enumerate(frames_iter):
            a=np.zeros((H,W,3),np.uint8);a[:h,:w][np.asarray(m,bool)]=255
            f=av.VideoFrame.from_ndarray(a,format='rgb24');f.pts=i;f.time_base=Fraction(1,int(round(fps)) or 24)
            for p in s.encode(f):c.mux(p)
        for p in s.encode():c.mux(p)
    os.replace(tmp,path)

def write_result(sdir,key,base_masks,per_frame,shape,frames,fps,status=lambda s:None):
    """Merge `per_frame` {frame: [(mode, region)]} into `base_masks` as results/<key>/ (+ mask.mp4, areas.json).
    Unchanged frames are hard-linked from a session result or copied from the run (never linked to a run file).
    Returns (folder, changed frames, areas, reused)."""
    root=results_root(sdir);final=root/key
    if (final/'areas.json').exists():
        data=json.loads((final/'areas.json').read_text());return final,data['changed'],data['areas'],True
    root.mkdir(parents=True,exist_ok=True);tmp=root/(key+'.tmp-'+uuid.uuid4().hex[:6]);tmp.mkdir()
    in_session=base_masks is not None and Path(base_masks).resolve().is_relative_to(Path(sdir).resolve())
    changed=[];areas=[];masks=[]
    try:
        for i in range(frames):
            name=f'mask_{i:05d}.png';before=wand.read_mask(base_masks,i,shape)
            regions=[(mode,wand.upscale(region,shape)) for mode,region in per_frame.get(i,[])]
            after=wand.merge_frame(before,regions) if regions else before
            if regions and not np.array_equal(before,after):changed.append(i);wand.write_mask(after,tmp/name)
            else:
                src=Path(base_masks)/name if base_masks is not None else None
                if src is not None and src.exists():
                    try:
                        if not in_session:raise OSError
                        os.link(src,tmp/name)
                    except OSError:shutil.copyfile(src,tmp/name)
                else:wand.write_mask(after,tmp/name)
            areas.append(int(after.sum()));masks.append(np.packbits(after,axis=None))
            if i%60==0:status(f'Mask · writing frame {i+1} of {frames}')
        status('Mask · encoding the B/W preview')
        encode_mask_video((np.unpackbits(p,count=shape[0]*shape[1]).reshape(shape).astype(bool) for p in masks),tmp/'mask.mp4',fps,shape)
        (tmp/'areas.json').write_text(json.dumps({'areas':areas,'changed':changed,'shape':list(shape),'fps':fps}))
        try:os.replace(tmp,final)
        except OSError:shutil.rmtree(tmp,ignore_errors=True)   # the same result was written meanwhile
    except Exception:
        shutil.rmtree(tmp,ignore_errors=True);raise
    return final,changed,areas,False

def entry_key(ident,base,kind,payload):
    return hashlib.sha256(json.dumps({'run':ident,'base':base,'kind':kind,**payload},sort_keys=True,default=str).encode()).hexdigest()[:24]

def work_dir(sdir,folder):
    """A session folder with links to the run's clips: hosted tools and the hands worker run here, so whatever they
    write (call logs, request records) lands in the session, never in the run folder."""
    work=mask_root(sdir)/'work';work.mkdir(parents=True,exist_ok=True)
    for name in ('original.mp4','depth.mp4','upload.mp4'):
        src=Path(folder)/name;dst=work/name
        if src.exists() and not dst.exists():
            try:dst.symlink_to(src.resolve())
            except OSError:shutil.copyfile(src,dst)
    return work

# ---------------------------------------------------------------- preview (one frame, no propagation)

def preview(runs_root,ident,folder,frame,points=None,strokes=None):
    """What the pending clicks / strokes on `frame` select, drawn over the current session mask's outline (transparent PNG)."""
    from .mask import parse_edits,parse_strokes
    session,value=session_value(runs_root,ident);sdir=session_dir(runs_root,ident)
    pending_points,pending_strokes,_=items(value)
    edits=parse_edits(points) if points is not None else parse_edits([{k:p.get(k) for k in ('frame','x','y','label')} for p in pending_points])
    strokes=parse_strokes(strokes) if strokes is not None else parse_strokes([{k:s.get(k) for k in ('frame_from','frame_to','mode','points','radius')} for s in pending_strokes])
    here=[e for e in edits if e['frame']==frame];strokes_here=[s for s in strokes if s['frame_from']<=frame<=s['frame_to']]
    t0=time.time()
    name,info=wand.preview_png(folder,frame,here,strokes=strokes_here,out_dir=mask_root(sdir)/'previews',base_masks=current_masks(sdir,folder,value),transparent=True)
    seconds=round(time.time()-t0,3)
    note(runs_root,ident,f'mask preview: {plural(len(here),"point")}'+(f', {plural(len(strokes_here),"stroke")}' if strokes_here else '')+f' on frame {frame} ({seconds} s, this frame only)')
    return {'id':ident,'url':f'/runs/{SESSIONS}/{ident}/mask/previews/{name}',**info,'points_on_frame':len(here),'strokes_on_frame':len(strokes_here),'server_seconds':seconds}

# ---------------------------------------------------------------- Apply to clip

def plan_apply(runs_root,ident,folder,quality='quick',tool='local_propagate',replace=None,rev=None):
    """Validate an Apply and say what it would cost; nothing runs. Raises EditError with a plain sentence."""
    from .editlayer import check_rev
    from . import costs
    quality='full' if str(quality or 'quick').strip().lower()=='full' else 'quick'
    tool=str(tool or 'local_propagate').strip()
    if tool not in TOOLS:raise EditError(f'Unknown mask tool {tool!r}.','Choose one of: '+', '.join(TOOLS)+'.')
    session,value=session_value(runs_root,ident)
    if not session:raise EditError('There are no mask fixes to apply.','Click + on a missed region, − on spill, or paint with the brush first.')
    check_rev(session,rev)
    points,strokes,applied=items(value)
    if replace:
        if not applied or applied[-1].get('id')!=replace:raise EditError('Only the latest applied fix can be redone at full quality.','Undo the fixes applied after it first, then accept it again.')
        entry=applied[-1]
        if entry.get('kind')=='hands':raise EditError('Grab hands already runs at full quality.','Nothing to accept for a hands pass.')
        points,strokes,base=entry.get('points') or [],entry.get('strokes') or [],entry.get('base')
        if tool=='local_propagate' and entry.get('intended_tool') in HOSTED:tool=entry['intended_tool']
    else:
        if not points and not strokes:raise EditError('There are no pending mask fixes to apply.','Click + on a missed region, − on spill, or paint with the brush first.')
        base=current_key(value)
    if not (Path(folder)/'original.mp4').exists():raise EditError('This run has no prepared clip yet, so there is no mask to fix.','Prepare the clip first (a depth preset).')
    effective=(tool if (tool not in HOSTED or quality=='full') else 'local_propagate') if points else 'brush'
    if points and not (Path(folder)/'depth.mp4').exists():raise EditError('This run has no depth video, so clicks cannot be followed through the clip.','Use the brush, or prepare the clip with a depth preset.')
    seconds=costs.clip_seconds(folder)
    estimate=costs.estimate_tool(effective,seconds,{'edits':points}) if effective in HOSTED else 0.0
    return {'ident':ident,'folder':Path(folder),'runs_root':Path(runs_root),'rev':session.get('rev',0),'value':value,'points':points,'strokes':strokes,'base':base,'quality':quality,
            'tool':tool,'effective':effective,'replace':replace,'estimate':round(float(estimate or 0),4),'seconds':seconds}

def source_of(folder):
    try:return 'rgb' if json.loads((Path(folder)/'sam-report.json').read_text()).get('source')=='rgb' else 'depth'
    except (OSError,ValueError):return 'depth'

def fix_regions(folder,sdir,points,strokes,quality,tool,seconds,status):
    """{frame: [(mode, region)]} for one Apply: every click in ONE propagation pass (local) or one hosted call per click
    type, then the strokes. Returns (per_frame, notes, (h, w), frames, fps)."""
    folder=Path(folder);h,w,n,fps=wand.frame_shape(folder/'original.mp4');per={};notes=[]
    edits=[{'frame':int(p['frame']),'x':float(p['x']),'y':float(p['y']),'label':1 if int(p.get('label',1)) else 0} for p in points]
    if edits:
        bad=[e['frame'] for e in edits if not 0<=e['frame']<n]
        if bad:raise EditError(f'A click on frame {bad[0]} is outside the clip (0–{n-1}).','Remove that click and apply again.')
        if tool in HOSTED:
            from .base import get_tool
            t=get_tool('mask',tool);work=work_dir(sdir,folder)
            params=t.normalize_params({'edits':json.dumps(edits),'base_run':folder.name,'source':source_of(folder),'base':'parent'})
            per,notes,_=t.regions({'folder':work,'seconds':seconds},params,work,status)
        else:
            per,notes,_,_=wand.local_propagate(folder,edits,work_side=SIDES[quality],status=status,fast_decode=True)
    if strokes:
        from .mask import parse_strokes
        for f,regions in wand.brush_regions(parse_strokes([{k:s.get(k) for k in ('frame_from','frame_to','mode','points','radius')} for s in strokes]),(h,w),n).items():per.setdefault(f,[]).extend(regions)
    return per,notes,(h,w),n,fps

def apply_line(points,strokes,quality,tool,changed,reused=False,accept=False):
    frames=sorted({int(p['frame']) for p in points})
    if points:head=f'mask propagation{" (accept at full quality)" if accept else ""}: {plural(len(points),"point")} on {plural(len(frames),"frame")}'+(f', {plural(len(strokes),"brush stroke")}' if strokes else '')
    else:head=f'mask brush{" (accept at full quality)" if accept else ""}: {plural(len(strokes),"brush stroke")}'+frames_text(f for s in strokes for f in (s.get('frame_from',0),s.get('frame_to',0)))
    return f'{head}, {quality}, {tool} → {plural(len(changed),"frame")} changed'+(' (same fixes as before: result reused, nothing recomputed)' if reused else '')

def run_apply(plan,status=lambda s:None):
    """Run a planned Apply: one result folder, one log line, one layer commit. Returns the edits view + {apply: …}."""
    from .editlayer import put
    ident,folder,runs_root=plan['ident'],plan['folder'],plan['runs_root'];sdir=session_dir(runs_root,ident)
    points,strokes,quality,effective=plan['points'],plan['strokes'],plan['quality'],plan['effective']
    base_masks=results_root(sdir)/plan['base'] if plan['base'] else wand.mask_dir(folder)
    if plan['base'] and not base_masks.is_dir():raise EditError('The mask this fix builds on is missing from the edit session.','Undo the last Apply, or Discard the edits and start again.')
    key=entry_key(ident,plan['base'],'fix',{'points':[[p['frame'],p['x'],p['y'],p.get('label',1)] for p in points],'strokes':[[s.get(k) for k in ('frame_from','frame_to','mode','points','radius')] for s in strokes],'quality':quality,'tool':effective})
    t0=time.time();notes=[]
    if (results_root(sdir)/key/'areas.json').exists():result,changed,areas,reused=write_result(sdir,key,base_masks,{},(0,0),0,24)
    else:
        per,notes,shape,n,fps=fix_regions(folder,sdir,points,strokes,quality,effective,plan['seconds'],status)
        result,changed,areas,reused=write_result(sdir,key,base_masks,per,shape,n,fps,status)
    seconds=round(time.time()-t0,2)
    note(runs_root,ident,apply_line(points,strokes,quality,effective,changed,reused,accept=bool(plan['replace']))+f' ({seconds} s)')
    value=copy.deepcopy(plan['value']) if isinstance(plan['value'],dict) else {}
    entry={'id':'a'+uuid.uuid4().hex[:10],'kind':'fix','tool':effective,'quality':quality,'points':points,'strokes':strokes,'base':plan['base'],'result':key,'frames_changed':len(changed),
           'notes':[{k:n.get(k) for k in ('mode','frame','first_frame','last_frame','frames','forward_stop','backward_stop') if k in n} for n in notes][:50]}
    if plan['tool'] in HOSTED and effective!=plan['tool']:entry['intended_tool']=plan['tool']
    if plan['replace']:
        value['applied']=value.get('applied')[:-1]+[entry];label=f'Accept mask fix at full quality ({plural(len(points),"point")})'
    else:
        value['applied']=(value.get('applied') or [])+[entry];value['points']=[];value['strokes']=[]
        label=f'Apply {plural(len(points)+len(strokes),"mask fix","mask fixes")} to the clip ({quality})'
    view=put(runs_root,ident,folder,plan['rev'],label,track='mask',value=value)
    return {**view,'apply':{'entry':entry['id'],'result':key,'video':video_url(ident,key),'frames_changed':len(changed),'quality':quality,'tool':effective,'seconds':seconds,'reused':reused,
                            'estimated_cost_usd':plan['estimate'],'intended_tool':entry.get('intended_tool')}}

# ---------------------------------------------------------------- problem ticks

_problem_cache={}

def mask_files(masks):
    return sorted(Path(masks).glob('mask_*.png')) if masks is not None else []

def small_masks(masks,count):
    import cv2
    from PIL import Image
    out=[]
    for i in range(count):
        path=Path(masks)/f'mask_{i:05d}.png'
        if not path.exists():out.append(None);continue
        a=np.asarray(Image.open(path).convert('L'))
        out.append(cv2.resize(a,(max(1,a.shape[1]//SMALL),max(1,a.shape[0]//SMALL)),interpolation=cv2.INTER_AREA)>127)
    return out

def report_areas(folder,count):
    try:rows=json.loads((Path(folder)/'mask-cleanup-report.json').read_text())
    except (OSError,ValueError):return None
    areas=[None]*count
    for row in rows if isinstance(rows,list) else []:
        try:i=int(''.join(c for c in str(row.get('frame','')) if c.isdigit()))
        except ValueError:continue
        if 0<=i<count:areas[i]=int(row.get('mask_pixels') or 0)
    return areas if all(a is not None for a in areas) else None

def find_problems(areas,smalls):
    """Ticks from per-frame areas (jumps) and the downscaled masks (a separate part that vanishes). Pure; tested."""
    import cv2
    n=len(areas);known=sorted(a for a in areas if a is not None);median=known[len(known)//2] if known else 0
    out=[];spans={}
    jumps=[i for i in range(1,n) if median and areas[i] is not None and areas[i-1] is not None and abs(areas[i]-areas[i-1])>JUMP*median]
    returns={}
    for i in jumps:   # a drop and the next rise within JUMP_SPAN frames: the frames in between lost a part
        if areas[i]<areas[i-1]:
            back=next((j for j in jumps if i<j<=i+JUMP_SPAN and areas[j]>areas[j-1] and j not in returns.values()),None)
            if back is not None:returns[i]=back
    for i in jumps:
        delta=areas[i]-areas[i-1]
        if i in returns:span=[i,returns[i]-1]
        elif i in returns.values():span=[i,i]
        elif delta>0:span=[max(0,i-JUMP_EDGE),i]      # a part appears: it may have been missing just before
        else:span=[i,min(n-1,i+JUMP_EDGE)]           # a part goes and does not come back soon
        where=f' (missing on frames {span[0]}–{span[1]})' if i in returns else ''
        out.append({'frame':i,'kind':'jump','note':f'mask area {"drops" if delta<0 else "grows"} by {abs(delta)/median*100:.0f} % of the median from frame {i-1}'+where,'span':span})
    kernel=np.ones((3,3),np.uint8)
    comps=[]
    for m in smalls:
        if m is None:comps.append([]);continue
        count,labels,stats,_=cv2.connectedComponentsWithStats(m.astype(np.uint8),connectivity=8)
        minimum=LIMB_MIN*m.size;parts=[(labels==k,int(stats[k,cv2.CC_STAT_AREA]),stats[k]) for k in range(1,count) if stats[k,cv2.CC_STAT_AREA]>=minimum]
        parts.sort(key=lambda p:-p[1]);comps.append(parts)
    grown=[cv2.dilate(m.astype(np.uint8),kernel,iterations=2)>0 if m is not None else None for m in smalls]
    seen=set()
    for i in range(1,n):
        if smalls[i] is None or smalls[i-1] is None:continue
        h,w=smalls[i].shape
        for part,area,st in comps[i-1][1:]:   # every part but the largest (the body)
            x,y,bw,bh=int(st[0]),int(st[1]),int(st[2]),int(st[3])
            if x<=0 or y<=0 or x+bw>=w or y+bh>=h:continue   # touching the edge: it may simply have left the picture
            if (part&grown[i]).sum()>=LIMB_OVERLAP*area:continue
            near=cv2.dilate(part.astype(np.uint8),kernel,iterations=3)>0
            back=next((j for j in range(i+1,min(n,i+LIMB_RETURN+1)) if smalls[j] is not None and (near&smalls[j]).sum()>=LIMB_OVERLAP*area),None)
            if i in seen:continue
            seen.add(i);pct=area/smalls[i].size*100
            out.append({'frame':i,'kind':'limb','span':[i,(back-1) if back else min(n-1,i+2)],
                        'note':f'a separate part ({pct:.1f} % of the frame, likely a hand or limb) '+(f'is missing on frames {i}–{back-1}' if back and back-1>i else f'is missing on frame {i}' if back else f'vanishes at frame {i} and does not come back')})
    out.sort(key=lambda p:(p['frame'],p['kind']))
    flagged=sorted({f for p in out for f in range(p['span'][0],p['span'][1]+1)})
    return out,flagged,median

def problems(runs_root,ident,folder,value=None):
    """GET /jobs/{id}/mask/problems: ticks on the current mask (the session's latest Apply, else the run's masks)."""
    if value is None:_,value=session_value(runs_root,ident)
    sdir=session_dir(runs_root,ident);key=current_key(value)
    try:masks=current_masks(sdir,folder,value)
    except EditError:masks=wand.mask_dir(folder);key=None
    thresholds={'jump':JUMP,'jump_span':JUMP_SPAN,'jump_edge':JUMP_EDGE,'limb_min':LIMB_MIN,'limb_overlap':LIMB_OVERLAP,'limb_return':LIMB_RETURN,'downscale':SMALL}
    if masks is None:return {'frames':[],'areas':[],'flagged':[],'median':0,'source':None,'result':None,'thresholds':thresholds}
    files=mask_files(masks);count=(int(files[-1].stem.split('_')[-1])+1) if files else 0
    if key and (masks/'problems.json').exists():
        try:return json.loads((masks/'problems.json').read_text())
        except ValueError:pass
    stamp=(str(masks),masks.stat().st_mtime,count)
    if not key and stamp in _problem_cache:return _problem_cache[stamp]
    source='session' if key else 'report';areas=None
    if key:
        try:areas=json.loads((masks/'areas.json').read_text())['areas']
        except (OSError,ValueError,KeyError):areas=None
    elif masks.parent==Path(folder):areas=report_areas(folder,count)
    smalls=small_masks(masks,count)
    if areas is None or len(areas)!=count:
        source='session' if key else 'masks'
        from PIL import Image
        areas=[int((np.asarray(Image.open(masks/f'mask_{i:05d}.png').convert('L'))>127).sum()) if (masks/f'mask_{i:05d}.png').exists() else 0 for i in range(count)]
    found,flagged,median=find_problems(areas,smalls)
    out={'frames':found,'areas':areas,'flagged':flagged,'median':median,'source':source,'result':key,'thresholds':thresholds}
    if key:
        try:(masks/'problems.json').write_text(json.dumps(out))
        except OSError:pass   # the session was saved (moved) meanwhile; the answer is still right
    else:_problem_cache[stamp]=out
    return out

# ---------------------------------------------------------------- Grab hands (free local MediaPipe Hand Landmarker in .venv-face)

def hand_model():return ROOT/'models'/'hand_landmarker.task'

def hand_landmarks(folder,frames,sdir):
    """{frame: [[(x, y) × 21], …]} for the requested frames, from hands_worker.py in .venv-face (tests mock this)."""
    from .calls import offline
    python=ROOT/'.venv-face'/'bin'/'python'
    if not python.exists():raise EditError('Grab hands needs the local MediaPipe setup, which is not installed.','Run bash setup-face-mesh.sh once (Python 3.12), then try again.')
    if not hand_model().exists() and offline():raise EditError('The hand model is not downloaded yet, and offline mode (PUPPETEER_OFFLINE=1) blocks the download.',f'Start the app once without PUPPETEER_OFFLINE (the free model is fetched on first use), or save {HAND_MODEL_URL} as models/hand_landmarker.task.')
    work=work_dir(sdir,folder);out=work/f'hands-{uuid.uuid4().hex[:8]}.json'
    result=subprocess.run([str(python),str(ROOT/'hands_worker.py'),str(work/'original.mp4'),str(out),','.join(str(f) for f in frames)],capture_output=True,text=True,timeout=600)
    if result.returncode!=0:
        lines=[l for l in (result.stderr or result.stdout).splitlines() if l.strip()]
        raise EditError('The hand finder stopped: '+(lines[-1].split(': ',1)[-1][:240] if lines else f'exit code {result.returncode}'),'Check the edit session log, then try again on fewer frames.')
    data=json.loads(out.read_text());out.unlink(missing_ok=True)
    return {int(f):[[(float(x),float(y)) for x,y in hand['points']] for hand in hands] for f,hands in (data.get('frames') or {}).items()}

def hand_region(rgb,depth,points):
    """A hand region at work size: the landmarks' hull grown by HAND_GROW × hand size, cut by a depth flood from every
    landmark (the depth/colour seed rule); the plain hull when the depth rule finds too little."""
    import cv2
    h,w=depth.shape[:2]
    px=np.array([[min(w-1,max(0,int(round(x*w)))),min(h-1,max(0,int(round(y*h))))] for x,y in points],np.int32)
    hull=np.zeros((h,w),np.uint8);cv2.fillConvexPoly(hull,cv2.convexHull(px),1)
    size=max(4,int(max(px[:,0].max()-px[:,0].min(),px[:,1].max()-px[:,1].min())));k=max(3,int(size*HAND_GROW))|1
    grown=cv2.dilate(hull,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(k,k)))>0
    flood=np.zeros((h,w),bool)
    for x,y in {(int(a),int(b)) for a,b in px}:flood|=wand._flood(depth,x,y,HAND_DEPTH_TOL)
    region=grown&flood
    if region.sum()<0.5*hull.sum():region|=hull>0
    return cv2.morphologyEx(region.astype(np.uint8),cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))>0

def plan_hands(runs_root,ident,folder,source='problems',start=None,end=None,rev=None):
    from .editlayer import load,check_rev
    session=load(runs_root,ident)
    if session:check_rev(session,rev)
    value=((session or {}).get('layer') or {}).get('mask') or {}
    if not (Path(folder)/'original.mp4').exists():raise EditError('This run has no prepared clip yet.','Prepare the clip first (a depth preset).')
    if not (Path(folder)/'depth.mp4').exists():raise EditError('This run has no depth video, which Grab hands uses to cut the hand out.','Prepare the clip with a depth preset first.')
    h,w,n,fps=wand.frame_shape(Path(folder)/'original.mp4')
    if source=='range':
        try:a,b=int(start),int(end)
        except (TypeError,ValueError):raise EditError('Select a range on the timeline first.','Drag across the ruler to select frames, then Grab hands on the range.')
        a,b=max(0,min(a,b)),min(n-1,max(a,b));frames=list(range(a,b+1))
    else:
        frames=problems(runs_root,ident,folder,value)['flagged']
    if not frames:raise EditError('No frames are flagged, so there is nothing for Grab hands to look at.','Select a range on the timeline first, then Grab hands on the range.')
    return {'ident':ident,'folder':Path(folder),'runs_root':Path(runs_root),'rev':(session or {}).get('rev',0),'value':value,'frames':frames,'source':source,'shape':(h,w),'frames_total':n,'fps':fps}

def run_hands(plan,status=lambda s:None):
    """Hands-only pass on the flagged frames, OR-ed into the current mask on those frames only. One result, one log line, one commit."""
    import cv2
    from .editlayer import put
    ident,folder,runs_root,frames=plan['ident'],plan['folder'],plan['runs_root'],plan['frames'];sdir=session_dir(runs_root,ident)
    value=copy.deepcopy(plan['value']) if isinstance(plan['value'],dict) else {}
    base=current_key(value);base_masks=current_masks(sdir,folder,value)
    t0=time.time();status(f'Grab hands · looking for hands on {plural(len(frames),"frame")}')
    found=hand_landmarks(folder,frames,sdir);wanted=set(frames)
    h,w=plan['shape'];scale=wand.work_scale(h,w);per={}
    if any(f in wanted and hands for f,hands in found.items()):
        rgb=wand.decode_video(folder/'original.mp4',scale,fast=True);depth=wand.decode_video(folder/'depth.mp4',scale,gray=True,fast=True)
        for f,hands in sorted(found.items()):
            if f not in wanted or not hands or f>=len(depth):continue
            region=np.zeros(depth[f].shape[:2],bool)
            for points in hands:
                if len(points)>=3:region|=hand_region(rgb[f],depth[f],points)
            if region.any():per[f]=[('include',region)]
    key=entry_key(ident,base,'hands',{'frames':frames,'hands':{str(f):[[list(p) for p in hand] for hand in found.get(f,[])] for f in frames}})
    result,changed,areas,reused=write_result(sdir,key,base_masks,per,(h,w),plan['frames_total'],plan['fps'],status)
    seconds=round(time.time()-t0,2);with_hands=sorted(f for f in frames if found.get(f))
    note(runs_root,ident,f'grab hands: {plural(len(frames),"flagged frame")} ({plan["source"]}), mediapipe_hands → hands on {plural(len(with_hands),"frame")}, {plural(len(changed),"frame")} changed ({seconds} s)')
    entry={'id':'h'+uuid.uuid4().hex[:10],'kind':'hands','tool':'mediapipe_hands','quality':'full','frames':frames,'hands_on':with_hands,'base':base,'result':key,'frames_changed':len(changed),'source':plan['source']}
    value['applied']=(value.get('applied') or [])+[entry];value.setdefault('points',[]);value.setdefault('strokes',[])
    view=put(runs_root,ident,folder,plan['rev'],f'Grab hands on {plural(len(frames),"frame")}',track='mask',value=value)
    return {**view,'hands':{'entry':entry['id'],'result':key,'video':video_url(ident,key),'frames':frames,'hands_on':with_hands,'frames_changed':len(changed),'changed':changed,'seconds':seconds}}

# ---------------------------------------------------------------- the save hook

def fix_summary(applied):
    fixes=[a for a in applied if a.get('kind')!='hands'];hands=[a for a in applied if a.get('kind')=='hands'];lines=[]
    points=[p for a in fixes for p in a.get('points') or []];strokes=[s for a in fixes for s in a.get('strokes') or []]
    if points:lines.append(f'{plural(len(points),"click")}{frames_text(p.get("frame",0) for p in points)} applied')
    if strokes:lines.append(plural(len(strokes),'brush stroke'))
    if hands:lines.append(f'hands added on {plural(len({f for a in hands for f in a.get("hands_on") or []}),"frame")}')
    if any(a.get('quality')=='quick' for a in fixes):lines.append('quick quality')
    return lines

class MaskTrack(Track):
    label='mask';empty={}
    def items(self,value):return items(value)
    def count(self,value):
        points,strokes,applied=items(value);return len(points)+len(strokes)+len(applied)
    def summary(self,value):
        points,strokes,applied=items(value);lines=[]
        if points:lines.append(f'{plural(len(points),"click")}{frames_text(p.get("frame",0) for p in points)} not applied')
        if strokes:lines.append(f'{plural(len(strokes),"brush stroke")} not applied')
        return lines+fix_summary(applied)
    def check(self,value,session_dir):
        points,strokes,_=items(value)
        if points or strokes:
            what=' and '.join(x for x in [plural(len(points),'mask click') if points else '',plural(len(strokes),'brush stroke') if strokes else ''] if x)
            return (f'{what} {"is" if len(points)+len(strokes)==1 else "are"} not applied yet. Apply them to the clip first, or remove them.','Use "Apply now" to follow them through the clip, or "Save without them" to drop them.')
        return None
    def change(self,value,parent_folder,session_dir):
        key=current_key(value)
        return ('mask','edit_layer',{'layer_sha':layer_sha(value),'base_run':Path(parent_folder).name,'result':key}) if key else None
    def materialize(self,value,child_folder,session_dir,parent_folder):
        key=current_key(value)
        if not key:return
        src=results_root(session_dir)/key
        if not src.is_dir():raise ValueError('The applied mask fixes are missing from the edit session; undo the last Apply and apply again.')
        dst=Path(child_folder)/'edit-layer'/'mask';dst.mkdir(parents=True,exist_ok=True)
        for path in sorted(src.glob('mask_*.png')):shutil.copyfile(path,dst/path.name)
        applied=items(value)[2]
        record={'result':key,'base_run':Path(parent_folder).name,'summary':fix_summary(applied),
                'fixes':[{'kind':a.get('kind'),'tool':a.get('tool'),'quality':a.get('quality'),'points':len(a.get('points') or []),'strokes':len(a.get('strokes') or []),'frames':a.get('frames'),'frames_changed':a.get('frames_changed')} for a in applied]}
        (Path(child_folder)/'edit-layer'/'mask.json').write_text(json.dumps(record,indent=1))

register_track('mask',MaskTrack)
