"""Import my own: replace a stage's output with a file the user made elsewhere (docs/IMPORTS.md, TIMELINE-SPEC §7, §A4).

Tools (all free, labelled `imported: true`, registered after each stage's own tools so the defaults stay first):
`depth: import_depth` (grayscale or coloured video), `mask: import_mask` (B/W video, PNG sequence in a zip, or a video
with an alpha channel), `face: import_face` (an overlay video composited over the base clip on its non-black pixels,
or landmarks JSON in the face-landmarks.json schema drawn with `meshedit.render`), `composite: import_control` (a
finished control video; the face stage is switched off in the same branch). Plus `mask: keep_parent` (free: the
parent's masks unchanged), used when a depth import re-runs the mask stage so nothing is re-billed.

Uploads (`POST /jobs/{id}/import`) are stored content-addressed as `runs/_imports/<sha256>.<ext>` (+ `<sha256>.json`
with the original name); the branch's params are `{file: <sha256>, ext, name}`, so the cache key covers the file. Every
import is conformed to the run's clip: frame rate (resampled by time), frame count (trimmed, or padded by holding the
last frame) and size (resized); each change is a plain warning in the report, never an error. A copy of the import is
hard-linked into the child as `imported-<stage><ext>` for the record.
"""
from pathlib import Path
from fractions import Fraction
import hashlib,io,json,os,re,shutil,uuid,zipfile
import numpy as np
from .base import Tool,register,fresh
from .runner import link_artifact

IMPORTS='_imports'
MAX_BYTES=1_000_000_000
MAX_FRAMES=3600
VIDEO_EXT=('.mp4','.mov','.webm','.mkv','.m4v','.avi')
ACCEPT={'depth':VIDEO_EXT,'mask':VIDEO_EXT+('.zip',),'face':VIDEO_EXT+('.json',),'composite':VIDEO_EXT}
TOOL_OF={'depth':'import_depth','mask':'import_mask','face':'import_face','composite':'import_control'}
KIND={'depth':'depth video','mask':'mask','face':'face overlay','composite':'control video'}
HINT={'depth':'A depth video (grayscale or coloured): .mp4, .mov, .webm',
      'mask':'A black-and-white mask video, a .zip of PNG frames, or a video with transparency (ProRes 4444 / PNG in .mov, VP9 .webm with alpha)',
      'face':'An overlay video (black = keep the clip, anything else is drawn over it), or face landmarks as .json (face-landmarks.json schema)',
      'composite':'A finished control video (.mp4, .mov, .webm); the face mesh is switched off for it'}

class ImportError_(ValueError):
    """A plain refusal for the upload route: str(e) is the sentence, .fix the suggestion, .status the HTTP code."""
    def __init__(self,message,fix,status=400):super().__init__(message);self.fix=fix;self.status=status

def imports_dir(runs_root):return Path(runs_root)/IMPORTS
def stored_path(runs_root,sha,ext):return imports_dir(runs_root)/f'{sha}{ext}'

def accepted(stage):return ', '.join(ACCEPT.get(stage,()))

def store(fileobj,filename,runs_root,stage,limit=None):
    """Copy an upload into runs/_imports/<sha256>.<ext> while hashing it; returns (sha, ext, path, size)."""
    ext=Path(filename or '').suffix.lower();limit=limit or MAX_BYTES
    if stage not in ACCEPT:raise ImportError_(f'Imports go into the depth, mask, face or composite stage, not {stage!r}.','Pick one of: depth, mask, face, composite.')
    if ext not in ACCEPT[stage]:raise ImportError_(f'A {ext or "file without an extension"} cannot be imported as a {KIND[stage]}.',f'Use one of: {accepted(stage)}. {HINT[stage]}.')
    folder=imports_dir(runs_root);folder.mkdir(parents=True,exist_ok=True)
    tmp=folder/f'.upload-{uuid.uuid4().hex}{ext}';h=hashlib.sha256();size=0
    try:
        with tmp.open('wb') as out:
            while True:
                block=fileobj.read(1<<20)
                if not block:break
                size+=len(block)
                if size>limit:raise ImportError_(f'This file is larger than {limit//1_000_000} MB, the import limit.','Export a shorter or smaller version (the clip is at most 30 s), then import it again.',status=413)
                h.update(block);out.write(block)
        if not size:raise ImportError_('The file is empty.','Choose the exported file again and import it.')
        sha=h.hexdigest();path=stored_path(runs_root,sha,ext)
        if path.exists():tmp.unlink()
        else:os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()
    meta=folder/f'{sha}.json'
    if not meta.exists():meta.write_text(json.dumps({'sha256':sha,'ext':ext,'name':Path(filename).name,'size':size,'stage':stage}))
    return sha,ext,path,size

# ---------------------------------------------------------------- reading what was imported

def is_alpha(fmt):return any(fmt.startswith(p) for p in ('yuva','rgba','bgra','argb','abgr','gbrap','ya','pal8'))

def decoder_for(stream):
    """VP9 / VP8 alpha lives in Matroska side data that only libvpx decodes; everything else uses the stream's decoder."""
    import av
    name=stream.codec_context.name
    if name in ('vp9','vp8') and str((stream.metadata or {}).get('alpha_mode') or (stream.metadata or {}).get('ALPHA_MODE') or '')=='1':
        try:
            ctx=av.CodecContext.create('libvpx-vp9' if name=='vp9' else 'libvpx','r')
            if stream.codec_context.extradata:ctx.extradata=stream.codec_context.extradata
            return ctx
        except Exception:return None
    return None

def video_frames(path,info):
    """Yield (seconds, array) for every frame of a video (RGBA when it has an alpha channel, else RGB); fills `info`."""
    import av
    with av.open(str(path)) as c:
        if not c.streams.video:raise ImportError_('This file has no video stream.','Export it again as a video (.mp4, .mov or .webm).')
        s=c.streams.video[0];rate=s.average_rate or s.guessed_rate or s.base_rate
        info.update(fps=float(rate) if rate else None,size=(s.width,s.height),frames=0,alpha=False,codec=s.codec_context.name)
        ctx=decoder_for(s);start=float(s.start_time*s.time_base) if s.start_time is not None and s.time_base else 0.0
        def frames():
            if ctx is None:yield from c.decode(s)
            else:
                for packet in c.demux(s):
                    for f in ctx.decode(packet):f.pts=f.pts if f.pts is not None else packet.pts;yield f
        for i,f in enumerate(frames()):
            alpha=is_alpha(f.format.name);info['alpha']=info['alpha'] or alpha
            t=float(f.pts*s.time_base)-start if f.pts is not None and s.time_base else i/(info['fps'] or 24)
            info['frames']+=1
            if info['frames']>MAX_FRAMES:raise ImportError_(f'This video has more than {MAX_FRAMES} frames.','Trim it to the clip (at most 30 s), then import it again.')
            yield t,f.to_ndarray(format='rgba' if alpha else 'rgb24')

def png_frames(path,info,fps):
    """Yield (seconds, array) for every PNG in a zip, in natural name order (mask_00001.png < mask_00010.png)."""
    from PIL import Image
    try:z=zipfile.ZipFile(path)
    except zipfile.BadZipFile:raise ImportError_('This .zip could not be opened.','Zip the PNG frames again (one PNG per frame) and import the new zip.')
    with z:
        names=sorted((n for n in z.namelist() if n.lower().endswith('.png') and not n.startswith('__MACOSX') and not Path(n).name.startswith('.')),key=lambda n:[int(t) if t.isdigit() else t for t in re.split(r'(\d+)',n)])
        if not names:raise ImportError_('The .zip holds no PNG frames.','Put one PNG per frame in the zip (e.g. mask_00000.png, mask_00001.png, …) and import it again.')
        if len(names)>MAX_FRAMES:raise ImportError_(f'The .zip holds more than {MAX_FRAMES} frames.','Keep only the frames of the clip, then import it again.')
        info.update(fps=fps,frames=0,alpha=False,size=None,codec='png')
        for i,name in enumerate(names):
            try:im=Image.open(io.BytesIO(z.read(name)));im.load()
            except Exception:raise ImportError_(f'{Path(name).name} in the zip is not a readable PNG.','Export the frames again as PNG and zip them.')
            info['size']=info['size'] or im.size;info['frames']+=1
            if 'A' in im.getbands() or im.mode=='P' and 'transparency' in im.info:
                a=np.asarray(im.convert('RGBA'))
                if a[...,3].min()<255:info['alpha']=True;yield i/fps,a;continue
            yield i/fps,np.asarray(im.convert('RGB'))

def resized(a,size):
    from PIL import Image
    if (a.shape[1],a.shape[0])==tuple(size):return a
    return np.asarray(Image.fromarray(a).resize(tuple(size),Image.BILINEAR))

def conformed(source,n,size,fps,info):
    """Yield exactly `n` frames of `size` at `fps` from `source` ((seconds, array) pairs): each output frame takes the last
    source frame that starts before its middle (resampling by time); past the end the last frame is held."""
    prev=None;nxt=next(source,None);out=0;info['held']=0
    while out<n:
        middle=(out+0.5)/fps
        while nxt is not None and nxt[0]<=middle:prev=nxt;nxt=next(source,None)
        if prev is None:
            if nxt is None:break
            prev=nxt;nxt=next(source,None)
        if nxt is None and prev is not None and middle>prev[0]+1.0/(info.get('fps') or fps)+1e-6:info['held']+=1
        yield resized(prev[1],size);out+=1
    while nxt is not None:nxt=next(source,None)   # read to the end, so the source frame count is known for the warning

def conform_warnings(info,n,size,fps,kind):
    """Plain sentences for every change made to fit the clip ('Your mask had 200 frames; the clip has 195, so the last 5 were dropped.')."""
    out=[];src_n=info.get('frames') or 0;src_fps=info.get('fps') or fps
    if abs(src_fps-fps)>0.01:out.append(f'Your {kind} was {src_fps:g} fps; it was resampled to the clip\'s {fps:g} fps.')
    same=round(src_n*fps/src_fps) if src_fps else src_n
    if same>n:out.append(f'Your {kind} had {src_n} frames; the clip has {n}, so the last {same-n} {"was" if same-n==1 else "were"} dropped.' if abs(src_fps-fps)<=0.01 else f'Your {kind} was longer than the clip ({src_n/src_fps:.2f} s vs {n/fps:.2f} s), so the end was dropped.')
    elif same<n:
        held=n-same;out.append(f'Your {kind} had {src_n} frames; the clip has {n}, so the last frame was held for {held} more frame{"s" if held!=1 else ""}.' if abs(src_fps-fps)<=0.01 else f'Your {kind} was shorter than the clip ({src_n/src_fps:.2f} s vs {n/fps:.2f} s), so its last frame was held to the end.')
    src=tuple(info.get('size') or size)
    if src!=tuple(size):
        stretched=abs(src[0]/src[1]-size[0]/size[1])>0.01
        out.append(f'Your {kind} was {src[0]}×{src[1]}; it was resized to the clip\'s {size[0]}×{size[1]}'+(' (stretched: the shapes differ).' if stretched else '.'))
    return out

def mask_of(a):
    """A bool mask from a frame: the alpha channel when it has real transparency, else brightness above the middle."""
    if a.ndim==3 and a.shape[2]==4 and a[...,3].min()<250:return a[...,3]>127
    rgb=a[...,:3].astype(np.float32);return (0.299*rgb[...,0]+0.587*rgb[...,1]+0.114*rgb[...,2])>127

def frames_of(path,ext,info,fps):
    if ext=='.zip':return png_frames(path,info,fps)
    return video_frames(path,info)

def check_readable(path,ext,stage):
    """Open the stored file once before any branch is made; a plain ImportError_ when it cannot be used."""
    if ext=='.json':return landmarks_from(path)
    info={}
    try:
        first=next(frames_of(path,ext,info,24.0),None)
    except ImportError_:raise
    except Exception:first=None
    if first is None:raise ImportError_(f'This file could not be read as a {"PNG sequence" if ext==".zip" else "video"}.',f'Export it again ({accepted(stage)}) and import the new file. {HINT[stage]}.')
    return info

def landmarks_from(path):
    """Validate landmarks JSON in our schema ({fps?, frames: [{faces: [[{x, y} × 468 | 478]], status?}]}); returns the dict."""
    try:data=json.loads(Path(path).read_text())
    except (OSError,ValueError,UnicodeDecodeError):raise ImportError_('This .json could not be read.','Export the landmarks again as JSON in the face-landmarks.json schema ({"fps": 24, "frames": [{"faces": [[{"x": …, "y": …}, …]]}]}).')
    frames=data.get('frames') if isinstance(data,dict) else data if isinstance(data,list) else None
    if not isinstance(frames,list) or not frames:raise ImportError_('The .json has no "frames" list.','Use the face-landmarks.json schema: {"fps": 24, "frames": [{"faces": [[{"x": 0.5, "y": 0.4}, … 468 or 478 points]]}]}.')
    good=0
    for fr in frames:
        faces=(fr or {}).get('faces') if isinstance(fr,dict) else None
        if isinstance(faces,list) and faces and isinstance(faces[0],list) and len(faces[0]) in (468,478):good+=1
    if not good:raise ImportError_('No frame in the .json has a face with 468 or 478 points (MediaPipe Face Mesh).','Export MediaPipe face mesh landmarks (468 points, or 478 with irises) per frame, normalized 0–1, in the face-landmarks.json schema.')
    return {'fps':float(data.get('fps') or 24) if isinstance(data,dict) else 24.0,'frames':frames}

def point(p):
    if isinstance(p,dict):return {'x':float(p.get('x',0)),'y':float(p.get('y',0))}
    return {'x':float(p[0]),'y':float(p[1])}

def write_video(path,frames,fps,size,crf='18'):
    """libx264 yuv420p at `fps` (temporary name, then moved into place). Returns the frame count."""
    import av
    path=Path(path);tmp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex[:6]+'.mp4');n=0;rate=Fraction(fps).limit_denominator(1001)
    try:
        with av.open(str(tmp),'w') as out:
            s=out.add_stream('libx264',rate=rate);s.width,s.height=size;s.pix_fmt='yuv420p';s.options={'crf':crf}
            for a in frames:
                f=av.VideoFrame.from_ndarray(np.ascontiguousarray(a[...,:3]),format='rgb24');f.pts=n;f.time_base=1/rate
                for p in s.encode(f):out.mux(p)
                n+=1
            for p in s.encode():out.mux(p)
        fresh(path);os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()
    return n

# ---------------------------------------------------------------- the tools

class ImportTool(Tool):
    """Shared plumbing: find the stored file, conform it to the clip, record warnings and the `imported` label."""
    paid=False;imported=True
    params={'file':{'type':'string','default':'','label':'Imported file','hint':'sha256 of the uploaded file (runs/_imports/<sha256>.<ext>), filled in by Import my own.'},
            'ext':{'type':'string','default':'','label':'File type','hint':'The extension of the imported file.'},
            'name':{'type':'string','default':'','label':'File name','hint':'The name of the file you imported.'}}
    def source(self,folder,params):
        sha=str(params.get('file') or '');ext=str(params.get('ext') or '').lower()
        if not re.fullmatch(r'[0-9a-f]{64}',sha) or ext not in ACCEPT.get(self.stage,()):raise ValueError('The imported file is not recorded in this run\'s settings. Import it again.')
        path=stored_path(Path(folder).parent,sha,ext)
        if not path.exists():raise ValueError(f'The imported file {params.get("name") or sha[:12]} is missing from runs/_imports/. Import it again.')
        return path,ext
    def record(self,folder,path,ext):
        name=f'imported-{self.stage}{ext}';link_artifact(path,Path(folder)/name);return name
    def clip(self,folder):
        from .wand import frame_shape
        folder=Path(folder)
        if not (folder/'original.mp4').exists():raise ValueError('This run has no prepared clip (original.mp4), so there is nothing to fit the import to.')
        h,w,n,fps=frame_shape(folder/'original.mp4');return n,(w,h),fps
    def done(self,outputs,name,params,info,warnings,health,frames=None,extra=None):
        data={'imported':True,'file':params.get('file'),'name':params.get('name'),'source':{k:info.get(k) for k in ('frames','fps','size','alpha','codec') if k in info},**(extra or {})}
        return {'outputs':outputs+[name],'frames':frames or {'covered':None,'filled':0,'missing':0},'warnings':warnings,'health':health,'data':data}

class ImportDepth(ImportTool):
    name='import_depth';stage='depth';label='Import my own depth video (free)';description='Uses a depth video you made elsewhere (grayscale or coloured), fitted to the clip\'s frames, size and frame rate.'
    inputs=('original.mp4',);outputs=('depth-raw.mp4','depth.mp4')
    def run(self,inputs,params,folder,status):
        folder=Path(folder);path,ext=self.source(folder,params);n,size,fps=self.clip(folder);info={}
        for name in self.outputs:fresh(folder/name)
        status('Importing your depth video · fitting it to the clip')
        write_video(folder/'depth-raw.mp4',conformed(frames_of(path,ext,info,fps),n,size,fps,info),fps,size,crf='12')
        shutil.copyfile(folder/'depth-raw.mp4',folder/'depth.mp4')
        warnings=conform_warnings(info,n,size,fps,'depth video')
        return self.done(['depth-raw.mp4','depth.mp4'],self.record(folder,path,ext),params,info,warnings,f'Imported depth video "{params.get("name") or ext}" on {n} frames'+(' (fitted to the clip, see the warnings).' if warnings else '.'),{'covered':n,'filled':0,'missing':0})

class ImportMask(ImportTool):
    name='import_mask';stage='mask';label='Import my own mask (free)';description='Uses a mask you made elsewhere: a black-and-white video, a zip of PNG frames, or a video with transparency (the alpha channel is the mask).'
    inputs=('original.mp4',);outputs=('raw-masks','clean-masks','sam-report.json')
    def run(self,inputs,params,folder,status):
        from . import wand
        folder=Path(folder);path,ext=self.source(folder,params);n,size,fps=self.clip(folder);info={}
        for name in self.outputs:fresh(folder/name)
        for extra in folder.glob('raw-masks-*'):fresh(extra)
        raw=folder/'raw-masks';clean=folder/'clean-masks';raw.mkdir(parents=True);clean.mkdir(parents=True);covered=0;areas=[]
        status('Importing your mask · fitting it to the clip')
        for i,a in enumerate(conformed(frames_of(path,ext,info,fps),n,size,fps,info)):
            m=mask_of(a);wand.write_mask(m,raw/f'mask_{i:05d}.png');shutil.copyfile(raw/f'mask_{i:05d}.png',clean/f'mask_{i:05d}.png');covered+=bool(m.any());areas.append(round(float(m.mean()),4))
        if not areas:raise ValueError('No frame could be read from the imported mask.')
        warnings=conform_warnings(info,n,size,fps,'mask')
        if not covered:warnings.append('Every frame of your mask is empty (all black), so nothing will be cut out.')
        source='alpha channel' if info.get('alpha') else 'brightness (white = subject)'
        (folder/'sam-report.json').write_text(json.dumps({'prompt':None,'terms':[],'frames':n,'attempts':[],'method':f'imported mask ({params.get("name") or ext}, from its {source})','source':'imported','model':None,'imported':{'file':params.get('file'),'name':params.get('name'),'from':source}},indent=1))
        return self.done(['raw-masks','clean-masks','sam-report.json'],self.record(folder,path,ext),params,info,warnings,f'Imported mask "{params.get("name") or ext}" (from its {source}) on {covered} of {n} frames.',{'covered':covered,'filled':0,'missing':n-covered},{'mask_from':source,'coverage':areas})

class ImportFace(ImportTool):
    name='import_face';stage='face';label='Import my own face overlay or landmarks (free)';description='Draws your own face guidance: an overlay video (non-black pixels drawn over the base clip) or face landmarks JSON (drawn like the mesh).'
    inputs=('original.mp4','depth-composite-silent.mp4');outputs=('composite-silent.mp4','face-landmarks.json','face-tracking.json','preview.jpg')
    def run(self,inputs,params,folder,status):
        from .composite import base_clip
        folder=Path(folder);path,ext=self.source(folder,params);n,size,fps=self.clip(folder);base=base_clip(folder,inputs.get('chain') or {})
        if base.name=='composite-silent.mp4':raise ValueError('This run has no clean base clip (depth-composite-silent.mp4) to draw on. Re-run from the composite stage first.')
        if not base.exists():raise ValueError(f'The base clip {base.name} is missing. Re-run from the composite stage.')
        for name in self.outputs:fresh(folder/name)
        name=self.record(folder,path,ext)
        if ext=='.json':return self.from_landmarks(folder,path,params,n,fps,base,name,status)
        info={};status('Importing your face overlay · drawing it over the base clip')
        def merged():
            import av
            with av.open(str(base)) as c:
                for frame,over in zip(c.decode(video=0),conformed(frames_of(path,ext,info,fps),n,size,fps,info)):
                    b=frame.to_ndarray(format='rgb24')
                    if over.shape[2]==4:alpha=(over[...,3:4].astype(np.float32)/255);yield (b*(1-alpha)+over[...,:3]*alpha).astype(np.uint8)
                    else:yield np.where((over.max(axis=2)>24)[...,None],over,b)
        frames=list_preview(merged(),folder/'preview.jpg')
        count=write_video(folder/'composite-silent.mp4',frames,fps,size)
        warnings=conform_warnings(info,n,size,fps,'face overlay')+['An overlay video has no face landmarks, so mouth guidance cannot tell where the mouth is hidden.']
        return self.done(['composite-silent.mp4','preview.jpg'],name,params,info,warnings,f'Imported face overlay "{params.get("name") or ext}" drawn over the {"depth composite" if base.name!="original.mp4" else "original frames"} on {count} frames.',{'covered':count,'filled':0,'missing':0},{'kind':'overlay'})
    def from_landmarks(self,folder,path,params,n,fps,base,name,status):
        from mesh_tracking import evaluate
        from .meshedit import render
        data=landmarks_from(path);src=data['frames'];warnings=[];bad=0;frames=[]
        for i in range(n):
            fr=src[min(i,len(src)-1)] if src else {};faces=(fr or {}).get('faces') if isinstance(fr,dict) else None
            face=faces[0] if isinstance(faces,list) and faces and isinstance(faces[0],list) else None
            if face is not None and len(face) not in (468,478):face=None;bad+=1
            status_=(fr.get('status') if isinstance(fr,dict) and fr.get('status') in ('tracked','filled','missing') else None) or ('tracked' if face else 'missing')
            if face is None:status_='missing'
            frames.append({'frame':i,'time':round(i/fps,4),'status':status_,'source':'imported','faces':[[point(p) for p in face]] if face else []})
        if abs(data['fps']-fps)>0.01:warnings.append(f'Your landmarks were marked {data["fps"]:g} fps; they were used frame by frame on the clip\'s {fps:g} fps.')
        if len(src)>n:warnings.append(f'Your landmarks had {len(src)} frames; the clip has {n}, so the last {len(src)-n} {"was" if len(src)-n==1 else "were"} dropped.')
        elif len(src)<n:warnings.append(f'Your landmarks had {len(src)} frames; the clip has {n}, so the last frame was held for {n-len(src)} more frame{"s" if n-len(src)!=1 else ""}.')
        if bad:warnings.append(f'{bad} frame{"s" if bad!=1 else ""} had a face with a point count other than 468 or 478 and {"were" if bad!=1 else "was"} treated as missing.')
        st=[f['status'] for f in frames];depth=base.name!='original.mp4'
        landmarks={'fps':int(round(fps)),'frames':frames,'summary':{'frames':n,'tracked':st.count('tracked'),'filled':st.count('filled'),'missing':st.count('missing')},'imported':{'file':params.get('file'),'name':params.get('name')}}
        (folder/'face-landmarks.json').write_text(json.dumps(landmarks))
        tracking={**evaluate(st,int(round(fps)),strict=False),'fps':int(round(fps)),'missing_frames':[i for i,s in enumerate(st) if s=='missing'],'filled_frames':[i for i,s in enumerate(st) if s=='filled'],'imported':True,'tracking_source':'imported landmarks'}
        (folder/'face-tracking.json').write_text(json.dumps(tracking,indent=1))
        status('Importing your face landmarks · drawing the mesh locally')
        drawn=render(folder,landmarks,base,status)
        from .face import tracking_report
        result=tracking_report(folder)
        return self.done(['composite-silent.mp4','face-landmarks.json','face-tracking.json','preview.jpg'],name,params,{'frames':len(src),'fps':data['fps'],'codec':'json'},warnings+(result.get('warnings') or []),
                         f'Imported face landmarks "{params.get("name") or ".json"}" drawn locally over the {"depth composite" if depth else "original frames"} on {drawn["drawn"]} frames. '+(result.get('health') or ''),result.get('frames'),{'kind':'landmarks'})

def list_preview(frames,path,at=30):
    """Pass frames through, saving frame `at` (or the last one before it) as a JPEG preview."""
    from PIL import Image
    last=None
    for i,a in enumerate(frames):
        if i<=at:last=a
        if i==at:Image.fromarray(a).save(path,format='JPEG')
        yield a
    if last is not None and not Path(path).exists():Image.fromarray(last).save(path,format='JPEG')

class ImportControl(ImportTool):
    name='import_control';stage='composite';label='Import my own control video (free)';description='Uses a finished control video you made elsewhere as the prepared clip; the face mesh is switched off for it and it goes straight to review.'
    inputs=('original.mp4',);outputs=('imported-control.mp4',)
    def run(self,inputs,params,folder,status):
        folder=Path(folder);path,ext=self.source(folder,params);n,size,fps=self.clip(folder);info={}
        for name in self.outputs+('composite-silent.mp4',):fresh(folder/name)
        status('Importing your control video · fitting it to the clip')
        count=write_video(folder/'imported-control.mp4',conformed(frames_of(path,ext,info,fps),n,size,fps,info),fps,size)
        warnings=conform_warnings(info,n,size,fps,'control video')
        return self.done(['imported-control.mp4'],self.record(folder,path,ext),params,info,warnings,f'Imported control video "{params.get("name") or ext}" on {count} frames; the original audio is added when the prepared clip is built.',{'covered':count,'filled':0,'missing':0})

class KeepParentMask(Tool):
    """The parent's masks, unchanged (free). A depth import re-runs the mask stage; this keeps the mask instead of re-billing SAM."""
    name='keep_parent';stage='mask';label='Keep the earlier mask (free)';paid=False
    description='Copies the mask of the run this branch came from, unchanged (used when a new depth video is imported).'
    params={'base_run':{'type':'string','default':'','label':'Base run','hint':'Run id whose masks are kept (the parent when empty).'}}
    inputs=('original.mp4',);outputs=('raw-masks','clean-masks','sam-report.json')
    def run(self,inputs,params,folder,status):
        from . import wand
        folder=Path(folder);masks,base=wand.load_base(folder.parent,params.get('base_run'),folder)
        if masks is None:raise ValueError('The earlier run has no mask to keep. Import a mask or run the SAM mask tool instead.')
        for name in self.outputs:fresh(folder/name)
        status('Mask · keeping the earlier mask');link_artifact(masks,folder/'clean-masks');link_artifact(masks,folder/'raw-masks')
        report={}
        if base is not None and (base/'sam-report.json').exists():
            try:report=json.loads((base/'sam-report.json').read_text())
            except (OSError,ValueError):report={}
        report['method']=(report.get('method') or 'masks')+' (kept from run '+(base.name if base is not None else '?')+')';report['kept_from']=base.name if base is not None else None
        (folder/'sam-report.json').write_text(json.dumps(report,indent=1))
        n=len(list((folder/'clean-masks').glob('mask_*.png')))
        return {'outputs':list(self.outputs),'frames':{'covered':None,'filled':0,'missing':None},'health':f'Mask kept unchanged from run {base.name[:8] if base is not None else "?"} ({n} frames).'}

register(ImportDepth);register(ImportMask);register(KeepParentMask);register(ImportFace);register(ImportControl)
from .composite import BASE_OF
BASE_OF['import_control']='imported-control.mp4'   # the face stage (off) passes the imported control clip on as composite-silent.mp4

# ---------------------------------------------------------------- the branch an import makes

def plan(parent_folder,stage,sha,ext,name):
    """(stage, tool, params, also, changed line) for importing `sha` at `stage` into a child of `parent_folder`."""
    from .branch import parent_state
    parent_folder=Path(parent_folder);run,_=parent_state(parent_folder);chain=run.get('chain') or {}
    params={'file':sha,'ext':ext,'name':name};also={};old=(chain.get(stage) or {}).get('tool','off')
    has_masks=any((parent_folder/d).is_dir() for d in ('clean-masks','raw-masks'))
    if stage in ('depth','mask','composite') and not (parent_folder/'original.mp4').exists():raise ImportError_('This run has no prepared clip yet, so there is nothing to fit the import to.','Wait until the preparation finishes (or prepare the video first), then import.')
    if stage=='depth':
        if not has_masks:raise ImportError_('This run has no mask, so an imported depth video would not be used.','Import depth into a run made with a depth preset (Full body, Expressive, Profile-heavy), or import a finished control video into the composite stage instead.')
        also['mask']={'tool':'keep_parent','params':{'base_run':parent_folder.name}}
        if (chain.get('composite') or {}).get('tool')!='depth_cutout':also['composite']={'tool':'depth_cutout','params':{}}
    if stage=='mask':
        if not (parent_folder/'depth.mp4').exists():raise ImportError_('This run has no depth video, so an imported mask has nothing to cut out.','Import the mask into a run made with a depth preset, or import a finished control video into the composite stage.')
        if (chain.get('composite') or {}).get('tool')!='depth_cutout':also['composite']={'tool':'depth_cutout','params':{}}
    if stage=='composite':also['face']={'tool':'off','params':{}}
    tool=TOOL_OF[stage]
    extra=[f'{s}: {e["tool"]}' for s,e in also.items()]
    changed=f'{stage}: imported "{name}" (was {old})'+(' · '+' · '.join(extra) if extra else '')
    return stage,tool,params,also,changed

def imported_stages(chain):
    """Stages of a chain whose tool is an import (for the 'imported' chips)."""
    from .base import get_tool
    out=[]
    for stage,entry in (chain or {}).items():
        try:
            if getattr(get_tool(stage,(entry or {}).get('tool','off')),'imported',False):out.append(stage)
        except ValueError:continue
    return out
