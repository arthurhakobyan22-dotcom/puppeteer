"""Stage 1, input_doctor: probe the upload and normalize it to `original.mp4` (24 fps, up to 960 px).

`probe` wraps today's `pipeline.normalize` unchanged and adds a pure-PyAV read of the source (resolution, fps,
duration, audio present) to the report. `doctor` (the default for every preset and legacy mode) does the same and
then checks the working copy: brightness (mean luma, share of near-black frames), face size (MediaPipe through the
`.venv-face` worker `face_probe.py`, searching zoomed tiles when the full frame shows nothing), shake (mean global
shift between consecutive frames, `cv2.phaseCorrelate`) and audio. Safe fixes touch only the working copy:
fps normalisation (always, by `pipeline.normalize`), a bounded gamma brighten when the clip is dark, and a zoomed
copy `tracking-source.mp4` (+ `tracking-source.json`) that the face stage tracks on when the face is small. The
upload is never altered; `original.mp4` is rewritten only when the clip is actually dark. Everything else is
advice. The doctor never blocks: only an unreadable or over-long upload raises (with a plain fix). See
docs/INPUT-DOCTOR.md.
"""
from pathlib import Path
import json,math,os,subprocess
from .base import Tool,register,fresh
from config import ROOT

class UnreadableVideo(ValueError):
    fix='Upload an MP4 or MOV exported from your camera or editor (H.264 or HEVC video); images, documents and audio-only files cannot be prepared.'

def normalize_or_explain(src,dst):
    """`pipeline.normalize`, but a file that is not a video fails with a plain sentence instead of a decoder error."""
    import pipeline,av
    try:return pipeline.normalize(src,dst) or {}
    except av.FFmpegError as exc:   # decoder errors (PyAV's InvalidDataError is also a ValueError, so test this first)
        raise UnreadableVideo('This file could not be read as a video ('+type(exc).__name__+'), so nothing was prepared.') from exc
    except ValueError:raise         # the 30-second limit and other plain messages pass through
    except Exception as exc:
        raise UnreadableVideo('This file could not be read as a video ('+type(exc).__name__+'), so nothing was prepared.') from exc

def probe_source(path):
    """Resolution, fps, duration and audio presence of a clip; never raises (returns what it could read)."""
    info={'width':None,'height':None,'fps':None,'seconds':None,'audio':None,'readable':False}
    try:
        import av
        with av.open(str(path)) as c:
            s=c.streams.video[0];rate=s.average_rate or s.guessed_rate or s.base_rate
            info.update(width=s.width,height=s.height,fps=round(float(rate),3) if rate else None,
                        seconds=round(float(c.duration/av.time_base),3) if c.duration else (round(float(s.duration*s.time_base),3) if s.duration and s.time_base else None),
                        audio=bool(c.streams.audio),readable=True)
    except Exception as exc:info['error']=type(exc).__name__
    return info

class Probe(Tool):
    name='probe';stage='input_doctor';label='Check and normalize';description='Reads the upload (size, frame rate, length, audio) and writes the 24 fps working copy original.mp4.'
    inputs=('upload.mp4',);outputs=('original.mp4',)
    def run(self,inputs,params,folder,status):
        import pipeline
        folder=Path(folder);src=inputs.get('source') or folder/'upload.mp4';info=probe_source(src);warnings=[]
        if not info['readable']:warnings.append('The upload could not be probed before normalizing; the next step will report the real problem if there is one.')
        if info.get('audio') is False:warnings.append('The source has no audio track, so the prepared clip cannot carry dialogue.')
        if info.get('seconds') and info['seconds']>30:warnings.append(f'The clip lasts {info["seconds"]:.1f} s; the hosted workflow is limited to 30 s.')
        if info.get('width') and min(info['width'],info['height'])<300:warnings.append('The source is smaller than 300 px on one side; Seedance needs at least 300 px.')
        status('Preparing video · 24 fps');fresh(folder/'original.mp4')
        meta=normalize_or_explain(src,folder/'original.mp4')
        frames=meta.get('frames')
        health=(f'{info["width"]}×{info["height"]} at {info["fps"]} fps, {info["seconds"]} s' if info['readable'] else 'Source probed by the normalizer only')+(', audio present' if info.get('audio') else (', no audio' if info.get('audio') is False else ''))
        health+=f' → {meta.get("width")}×{meta.get("height")} at 24 fps, {frames} frames.' if meta.get('width') else '.'
        return {'outputs':['original.mp4'],'frames':{'covered':frames,'filled':0,'missing':0},'warnings':warnings,'health':health,'data':{'source':info,'normalized':meta}}

# ---------------------------------------------------------------- the doctor

NEAR_BLACK=0.06       # a frame whose mean luma is below this counts as near-black
PURE_BLACK=0.02       # pixels below this (letterbox bars, padding) are left out of the picture's mean luma
SAMPLES=12            # frames analysed for brightness, face size and shake

def luma(rgb):
    """Mean luma (0–1) of the picture, leaving out pure-black pixels (letterbox bars and padding would otherwise make a bright clip look dark)."""
    import numpy as np
    a=rgb.astype('float32');y=(0.299*a[...,0]+0.587*a[...,1]+0.114*a[...,2])/255.0
    lit=y[y>=PURE_BLACK]
    return float(lit.mean()) if lit.size else 0.0

def sample_indices(frames,n=SAMPLES):
    if frames<=0:return []
    import numpy as np
    return sorted({int(i) for i in np.linspace(0,frames-1,min(n,frames))})

def analyse_frames(video,n=SAMPLES):
    """Sampled RGB frames plus the frame after each sample (for shake), from the working copy. Returns (samples, pairs, frames)."""
    import av
    samples={};pairs={};wanted=[];frames=0
    with av.open(str(video)) as c:
        total=c.streams.video[0].frames or 0
        wanted=sample_indices(total,n) if total else []
        after={i+1 for i in wanted}
        for i,f in enumerate(c.decode(video=0)):
            frames=i+1
            if not total and i%max(1,int(24*2))==0:wanted.append(i);after.add(i+1)   # unknown length: every two seconds
            if i in wanted:samples[i]=f.to_ndarray(format='rgb24')
            elif i in after:pairs[i-1]=f.to_ndarray(format='rgb24')
    return samples,pairs,frames

def measure_shake(samples,pairs):
    """Mean global shift between a sampled frame and the next one, as a fraction of the frame height (phase correlation)."""
    import cv2,numpy as np
    shifts=[]
    for i,a in samples.items():
        b=pairs.get(i)
        if b is None:continue
        h,w=a.shape[:2];scale=min(1.0,480/max(h,w));size=(max(8,int(w*scale)),max(8,int(h*scale)))
        ga=cv2.cvtColor(cv2.resize(a,size,interpolation=cv2.INTER_AREA),cv2.COLOR_RGB2GRAY).astype(np.float32)
        gb=cv2.cvtColor(cv2.resize(b,size,interpolation=cv2.INTER_AREA),cv2.COLOR_RGB2GRAY).astype(np.float32)
        window=cv2.createHanningWindow(size,cv2.CV_32F)
        (dx,dy),response=cv2.phaseCorrelate(ga,gb,window)
        shifts.append(math.hypot(dx,dy)/size[1])
    return (sum(shifts)/len(shifts)) if shifts else None,len(shifts)

def detect_faces(video,indices):
    """Face boxes on the given frames of `video`: {'frames': [{frame, box: [x0,y0,x1,y1] normalized | None, zoomed}], 'detector': str}
    or None when no detector is available. MediaPipe in .venv-face (face_probe.py) first; OpenCV's Haar cascade when that build has it.
    Module-level so tests can patch it."""
    worker=ROOT/'.venv-face/bin/python'
    if worker.exists() and (ROOT/'face_probe.py').exists():
        try:
            result=subprocess.run([str(worker),str(ROOT/'face_probe.py'),str(video),','.join(str(i) for i in indices)],capture_output=True,text=True,timeout=300)
            if result.returncode==0:
                line=[l for l in result.stdout.splitlines() if l.strip().startswith('{')]
                if line:return json.loads(line[-1])
        except (OSError,ValueError,subprocess.SubprocessError):pass
    try:
        import cv2,av
        cascade_file=Path(getattr(getattr(cv2,'data',None),'haarcascades','') or '')/'haarcascade_frontalface_default.xml'
        if not hasattr(cv2,'CascadeClassifier') or not cascade_file.exists():return None
        cascade=cv2.CascadeClassifier(str(cascade_file));out=[];wanted=set(indices)
        with av.open(str(video)) as c:
            for i,f in enumerate(c.decode(video=0)):
                if i not in wanted:
                    if i>max(wanted):break
                    continue
                g=cv2.cvtColor(f.to_ndarray(format='rgb24'),cv2.COLOR_RGB2GRAY);h,w=g.shape
                faces=cascade.detectMultiScale(cv2.equalizeHist(g),1.1,5,minSize=(16,16))
                box=max(faces,key=lambda b:b[3]) if len(faces) else None
                out.append({'frame':i,'box':[box[0]/w,box[1]/h,(box[0]+box[2])/w,(box[1]+box[3])/h] if box is not None else None,'zoomed':False})
        return {'frames':out,'detector':'haar'}
    except Exception:return None

def brighten(video,gamma):
    """Rewrite `video` (the working copy) through a gamma curve: out = 255 * (in / 255) ** (1 / gamma). Returns the new mean luma."""
    import numpy as np,av,pipeline
    video=Path(video);temp=video.with_name(video.stem+'.brighten.tmp.mp4')
    lut=(255.0*((np.arange(256)/255.0)**(1.0/gamma))).round().clip(0,255).astype(np.uint8)
    out=stream=None;total=0.0;count=0
    with av.open(str(video)) as inp:
        for i,f in enumerate(inp.decode(video=0)):
            a=lut[f.to_ndarray(format='rgb24')]
            if out is None:out,stream=pipeline.writer(temp,a.shape[1],a.shape[0])
            pipeline.put(out,stream,a,i)
            if i%8==0:total+=luma(a);count+=1
    if out is None:raise ValueError('The working copy has no frames to brighten.')
    pipeline.finish(out,stream);os.replace(temp,video)
    return total/max(1,count)

def write_tracking_source(video,boxes,face_fraction,target=None):
    """A zoomed copy of the working copy around the face for the tracker: crop (same aspect ratio, face about 30 % of its height), 2x upscale.
    Returns the crop description written to tracking-source.json."""
    import av,numpy as np,pipeline
    from PIL import Image
    video=Path(video);folder=video.parent;target=target or folder/'tracking-source.mp4'
    with av.open(str(video)) as inp:
        s=inp.streams.video[0];W,H=s.width,s.height
    xs0=[b[0] for b in boxes];ys0=[b[1] for b in boxes];xs1=[b[2] for b in boxes];ys1=[b[3] for b in boxes]
    cx=(min(xs0)+max(xs1))/2*W;cy=(min(ys0)+max(ys1))/2*H
    face_h=max(2.0,face_fraction*H)
    crop_h=min(H,max(face_h/0.30,(max(ys1)-min(ys0))*H+2*face_h));crop_w=min(W,crop_h*W/H);crop_h=min(crop_h,crop_w*H/W)
    x0=int(round(min(max(0,cx-crop_w/2),W-crop_w)));y0=int(round(min(max(0,cy-crop_h/2),H-crop_h)));cw=int(crop_w)//2*2;ch=int(crop_h)//2*2
    scale=min(2.0,1920/max(cw,1),1920/max(ch,1));ow=int(cw*scale)//2*2;oh=int(ch*scale)//2*2
    out=stream=None
    with av.open(str(video)) as inp:
        for i,f in enumerate(inp.decode(video=0)):
            a=np.asarray(Image.fromarray(f.to_ndarray(format='rgb24')[y0:y0+ch,x0:x0+cw]).resize((ow,oh),Image.Resampling.LANCZOS))
            if out is None:out,stream=pipeline.writer(target,ow,oh)
            pipeline.put(out,stream,a,i)
    if out is not None:pipeline.finish(out,stream)
    info={'crop':{'x0':x0,'y0':y0,'w':cw,'h':ch},'scale':round(ow/cw,3),'original':{'width':W,'height':H},'size':{'width':ow,'height':oh},'face_fraction':round(face_fraction,4),
          'note':'Zoomed copy for face tracking only; landmarks are mapped back to the original frame. Every other artifact uses original.mp4.'}
    (folder/'tracking-source.json').write_text(json.dumps(info,indent=1))
    return info

class Doctor(Tool):
    name='doctor';stage='input_doctor';label='Input doctor (checks + safe fixes)'
    description='Checks resolution, frame rate, length, brightness, face size, shake and audio; normalises to 24 fps, brightens a dark clip and writes a zoomed tracking copy for a small face. Never blocks; the rest is advice.'
    params={'dark_luma':{'type':'number','default':0.12,'label':'Dark below (mean luma)','hint':'0–1. Below this the working copy is brightened (a dark-background interview with a lit face measures about 0.17).'},
            'target_luma':{'type':'number','default':0.35,'label':'Brighten towards','hint':'Mean luma the gamma curve aims for.'},
            'max_gain':{'type':'number','default':1.8,'label':'Max gamma','hint':'The brighten curve never exceeds this exponent.'},
            'small_face':{'type':'number','default':0.12,'label':'Small face below','hint':'Face height as a fraction of the frame height; below this a zoomed tracking copy is written.'},
            'shake':{'type':'number','default':0.02,'label':'Shake warning above','hint':'Mean frame-to-frame global shift as a fraction of the height (a static camera with a moving subject measures about 0.01).'},
            'fix_brightness':{'type':'bool','default':True,'label':'Brighten dark clips'},
            'fix_face':{'type':'bool','default':True,'label':'Zoomed tracking copy for small faces'}}
    inputs=('upload.mp4',);outputs=('original.mp4','input-doctor.json','tracking-source.mp4','tracking-source.json')
    def run(self,inputs,params,folder,status):
        import pipeline
        folder=Path(folder);src=inputs.get('source') or folder/'upload.mp4';info=probe_source(src)
        checks=[];warnings=[];advice=[];fixes=[];measure={'source':info}
        for name in self.outputs:fresh(folder/name)
        status('Input doctor · reading the upload')
        meta=normalize_or_explain(src,folder/'original.mp4')
        measure['normalized']=meta
        # --- resolution, fps, length, audio (from the source probe)
        if info['readable']:
            short=min(info['width'],info['height'])
            checks.append(f'Resolution: {info["width"]}×{info["height"]}; working copy {meta.get("width")}×{meta.get("height")}.')
            if short<300:warnings.append('The source is smaller than 300 px on one side; Seedance needs at least 300 px.');advice.append('Upload a larger clip (at least 720 px on the short side) for a cleaner result.')
            elif short<540:advice.append(f'The clip is only {short} px on its short side; a 720 px or larger upload tracks and composites better.')
            if info['fps']:
                checks.append(f'Frame rate: {info["fps"]} fps'+(' (already 24).' if abs(info['fps']-24)<0.01 else ', normalised to 24 fps for the working copy.'))
                if abs(info['fps']-24)>=0.01:fixes.append({'name':'fps','before':info['fps'],'after':24,'note':f'Frame rate: {info["fps"]} fps → 24 fps (working copy only; the original upload is untouched).'})
            if info['seconds'] is not None:
                checks.append(f'Length: {info["seconds"]:.1f} s ({meta.get("frames")} frames at 24 fps).')
                if info['seconds']>30:warnings.append(f'The clip lasts {info["seconds"]:.1f} s; the hosted workflow is limited to 30 s.')
                elif info['seconds']<1.5:advice.append('The clip is very short; Seedance works best with 2–15 s of motion.')
            if info.get('audio'):checks.append('Audio: present (it will drive the lip-sync and is restored on the final export).')
            else:checks.append('Audio: none.');warnings.append('The source has no audio track, so the prepared clip cannot carry dialogue.');advice.append('Add the dialogue track before uploading if the character should speak.')
        else:warnings.append('The upload could not be probed before normalizing; the next step will report the real problem if there is one.')
        # --- the working copy: brightness, shake, face
        try:samples,pairs,frames=analyse_frames(folder/'original.mp4')
        except Exception as exc:
            warnings.append(f'The working copy could not be analysed ({type(exc).__name__}), so the brightness, face and shake checks were skipped.');samples={};pairs={};frames=meta.get('frames') or 0
        mean=None
        if samples:
            lumas={i:luma(a) for i,a in samples.items()};mean=sum(lumas.values())/len(lumas);dark_share=sum(1 for v in lumas.values() if v<NEAR_BLACK)/len(lumas)
            measure['luma']={'mean':round(mean,3),'near_black_share':round(dark_share,3),'samples':len(lumas),'note':'mean luma of the picture without pure-black pixels (letterbox bars, padding)'}
            checks.append(f'Brightness: mean luma {mean:.2f} of the picture on {len(lumas)} sampled frames'+(f', {round(dark_share*100)}% of them near black' if dark_share else '')+('; dark.' if mean<float(params['dark_luma']) else '; fine.'))
            if mean<float(params['dark_luma']):
                if params.get('fix_brightness',True) and mean>0:
                    gamma=min(float(params['max_gain']),max(1.0,math.log(max(mean,1e-4))/math.log(float(params['target_luma']))))
                    status(f'Input doctor · brightening the working copy (gamma {gamma:.2f})')
                    try:
                        after=brighten(folder/'original.mp4',gamma)
                        fixes.append({'name':'brightness','before':round(mean,3),'after':round(after,3),'gamma':round(gamma,3),'note':f'Brightness: mean luma {mean:.2f} → {after:.2f} (gamma {gamma:.2f}, capped at {float(params["max_gain"]):.1f}); the original upload is untouched.'})
                        measure['luma']['after']=round(after,3)
                        if after<float(params['dark_luma']):advice.append(f'The clip is still dark after the bounded brighten (mean luma {after:.2f}): film with more light or raise the exposure before uploading.')
                        samples,pairs,_=analyse_frames(folder/'original.mp4')
                    except Exception as exc:warnings.append(f'The working copy could not be brightened ({type(exc).__name__}); it is used as it is.')
                else:advice.append(f'The clip is dark (mean luma {mean:.2f}): film with more light, or switch on the brighten fix in the input doctor.')
            if dark_share>=0.5:advice.append('Most sampled frames are near black; the trackers and the depth model will have little to work with.')
        # --- shake
        if samples and pairs:
            shake,pairs_used=measure_shake(samples,pairs);measure['shake']={'mean_shift_fraction':round(shake,5) if shake is not None else None,'pairs':pairs_used}
            if shake is not None:
                px=shake*(meta.get('height') or samples[next(iter(samples))].shape[0])
                checks.append(f'Shake: average global motion {px:.1f} px per frame'+('; the camera is unsteady.' if shake>float(params['shake']) else '; steady.'))
                if shake>float(params['shake']):warnings.append(f'The camera shakes (about {px:.0f} px per frame on average); tracking and depth may wobble.');advice.append('Stabilise the clip (or use a tripod) before uploading; the app does not stabilise.')
        # --- face size
        if samples:
            status('Input doctor · looking for the face')
            found=detect_faces(folder/'original.mp4',sorted(samples))
            if found is None:advice.append('Face size could not be checked: set up the face mesh once (bash setup-face-mesh.sh) and the doctor will measure it.')
            else:
                boxes=[f['box'] for f in found.get('frames',[]) if f.get('box')];zoomed=[f for f in found.get('frames',[]) if f.get('box') and f.get('zoomed')]
                heights=sorted(b[3]-b[1] for b in boxes);measure['face']={'detector':found.get('detector'),'frames_sampled':len(found.get('frames',[])),'frames_with_face':len(boxes),'zoomed_hits':len(zoomed),
                                                                        'median_height_fraction':round(heights[len(heights)//2],4) if heights else None}
                if not boxes:
                    checks.append(f'Face: none found on {len(found.get("frames",[]))} sampled frames.')
                    advice.append('No face was found in the sampled frames: if a face should be tracked, move closer or crop before uploading; the depth presets still work without one.')
                else:
                    frac=heights[len(heights)//2];checks.append(f'Face: about {round(frac*100)}% of the frame height on {len(boxes)} of {len(found.get("frames",[]))} sampled frames'+(' (only found when zoomed in)' if zoomed and len(zoomed)==len(boxes) else '')+('; small.' if frac<float(params['small_face']) else '; fine.'))
                    if frac<float(params['small_face']) or (zoomed and len(zoomed)==len(boxes)):   # a face found only when zoomed in is small for the tracker
                        advice.append(f'Face is small ({round(frac*100)}% of frame height): move closer or crop before uploading for better facial tracking.')
                        if params.get('fix_face',True):
                            status('Input doctor · writing a zoomed copy for face tracking')
                            try:
                                tinfo=write_tracking_source(folder/'original.mp4',boxes,frac)
                                fixes.append({'name':'tracking_source','before':round(frac,3),'after':round(min(1.0,frac*tinfo['original']['height']/max(1,tinfo['crop']['h'])),3),'note':f'Face size: {round(frac*100)}% → about {round(min(100,frac*tinfo["original"]["height"]/max(1,tinfo["crop"]["h"])*100))}% of the frame in tracking-source.mp4 (a zoomed copy used for face tracking only, landmarks mapped back; every other artifact and the original upload are untouched).'})
                            except Exception as exc:warnings.append(f'The zoomed tracking copy could not be written ({type(exc).__name__}); the face stage tracks the working copy as it is.')
                    if len(boxes)<len(found.get('frames',[]))*0.5:advice.append(f'The face was found on only {len(boxes)} of {len(found.get("frames",[]))} sampled frames; the face mesh may have gaps (the Expressive preset only warns about them).')
        measure['params']=params
        (folder/'input-doctor.json').write_text(json.dumps({'checks':checks,'warnings':warnings,'advice':advice,'fixes':fixes,'measurements':measure},indent=1,default=str))
        health=(f'{info["width"]}×{info["height"]} at {info["fps"]} fps, {info["seconds"]} s' if info['readable'] else 'Source probed by the normalizer only')+(', audio present' if info.get('audio') else (', no audio' if info.get('audio') is False else ''))
        health+=f' → {meta.get("width")}×{meta.get("height")} at 24 fps, {meta.get("frames")} frames' if meta.get('width') else ''
        names={'fps':'24 fps','brightness':'brightened','tracking_source':'zoomed tracking copy'}
        health+='; fixes: '+', '.join(names.get(f['name'],f['name']) for f in fixes)+'.' if fixes else '; no fix needed.'
        if advice:health+=f' {len(advice)} piece{"s" if len(advice)>1 else ""} of advice.'
        return {'outputs':[n for n in self.outputs if (folder/n).exists()],'frames':{'covered':meta.get('frames'),'filled':0,'missing':0},'warnings':warnings,'health':health,
                'data':{'source':info,'normalized':meta,'checks':checks,'fixes':fixes,'advice':advice,'measurements':{k:v for k,v in measure.items() if k not in ('source','normalized','params')}}}

register(Probe);register(Doctor)
