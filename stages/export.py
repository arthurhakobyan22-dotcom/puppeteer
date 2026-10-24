"""Export kit (stage 3, Agent 4): one folder + zip per export with everything a downstream tool needs, free and local.

`build_export(folder, items, preset, runs_root, status)` writes `runs/<id>/export/<preset>-<yyyymmdd-hhmmss>/` and the
matching `.zip` next to it, always with a README.txt that names every file, the fps / frame count / size, the run (and
the edits) it came from and the preset's reasoning. Items and presets are data in `stages/export_presets.py`;
docs/EXPORT.md has the reasoning per choice. The route (`app.py`, section "export kit") saves pending timeline edits
first through the same function as `POST /jobs/{id}/edits/save` and exports the child, so every export carries the edits.

Tools: ffmpeg (/opt/homebrew/bin/ffmpeg: prores_ks, png, libvpx-vp9) through subprocess for ProRes and the audio files,
PyAV + PIL + numpy for the frame work (mesh on transparent, person alpha, PNG sequences). Nothing here is paid or
reaches the network, and nothing is written into the run except under `export/`.
"""
from pathlib import Path
import datetime,json,shutil,subprocess,uuid,zipfile
from fractions import Fraction
from .base import fresh
from . import export_presets as P

FFMPEG_CANDIDATES=('/opt/homebrew/bin/ffmpeg','/usr/local/bin/ffmpeg','/usr/bin/ffmpeg')
FFMPEG_FIX='Install ffmpeg: brew install ffmpeg (then start the app again).'
REF_EXT=('png','jpg','jpeg','webp')
RECORD_SUFFIX='.json'

class ExportError(ValueError):
    """A plain refusal: `str(e)` is the sentence, `.fix` the suggestion, `.status` the HTTP code."""
    def __init__(self,message,fix,status=400):super().__init__(message);self.fix=fix;self.status=status

def ffmpeg_path():
    """ffmpeg on PATH first, then the Homebrew / system places; None when there is none."""
    found=shutil.which('ffmpeg')
    if found:return found
    return next((c for c in FFMPEG_CANDIDATES if Path(c).exists()),None)

def ffprobe_path():
    f=ffmpeg_path()
    if not f:return shutil.which('ffprobe')
    sibling=Path(f).with_name('ffprobe')
    return str(sibling) if sibling.exists() else shutil.which('ffprobe')

def ffmpeg_problem():
    """(message, fix) when ffmpeg is missing, else None."""
    return None if ffmpeg_path() else ('ffmpeg is not installed, so the export cannot be made.',FFMPEG_FIX)

def fps_text(fps):
    return str(Fraction(fps).limit_denominator(1001))

def now_iso():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')

def export_name(preset):
    """`<preset>-<yyyymmdd-hhmmss>` (a short suffix keeps two exports in the same second apart)."""
    return f'{preset}-{datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:4]}'

# ---------------------------------------------------------------- what the run has

def clip_info(folder):
    """{frames, fps, width, height, seconds, source} of the prepared picture: composite-silent.mp4, else original.mp4, else seedance-input.mp4."""
    from .wand import frame_shape
    folder=Path(folder)
    for name in ('composite-silent.mp4','original.mp4','seedance-input.mp4','depth-composite-silent.mp4'):
        path=folder/name
        if not path.exists():continue
        try:h,w,n,fps=frame_shape(path)
        except Exception:continue
        return {'frames':int(n),'fps':float(fps),'width':int(w),'height':int(h),'seconds':round(n/fps,3) if fps else None,'source':name}
    return {'frames':0,'fps':24.0,'width':0,'height':0,'seconds':None,'source':None}

def has_audio(path):
    import av
    try:
        with av.open(str(path)) as c:return bool(c.streams.audio)
    except Exception:return False

def audio_codec(path):
    import av
    try:
        with av.open(str(path)) as c:return c.streams.audio[0].codec_context.name if c.streams.audio else None
    except Exception:return None

def mask_source(folder):
    """'mask.mp4' | 'clean-masks' | 'raw-masks' | None."""
    folder=Path(folder)
    if (folder/'mask.mp4').exists():return 'mask.mp4'
    for name in ('clean-masks','raw-masks'):
        if (folder/name).is_dir() and any((folder/name).glob('mask_*.png')):return name
    return None

def read_json(path):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return None

def run_data(folder):
    """run.json, or the reconstructed chain for a legacy run (nothing written)."""
    from .runner import load_run
    from .migrate import reconstruct
    folder=Path(folder);run=load_run(folder)
    if run is not None:return run
    try:return reconstruct(folder,with_keys=False,write=False)[0]
    except Exception:return None

def saved_reference(folder,slot):
    """char1-reference.<ext> / char2-reference.<ext> when saved with the run (images only; an identity video is @Video2, not a ref image)."""
    folder=Path(folder)
    for ext in REF_EXT:
        p=folder/f'{slot}-reference.{ext}'
        if p.exists():return p
    return None

def asset_path(name,runs_root,folder=None):
    """A set / look image by asset name (runs/_assets/<name>, Agent 1's store), else the run's own set-plate.*; None when neither exists."""
    if not name or not isinstance(name,str) or '/' in name or name.startswith('.'):return None
    p=Path(runs_root)/'_assets'/name
    if p.exists():return p
    if folder:
        for ext in REF_EXT:
            q=Path(folder)/f'set-plate.{ext}'
            if q.exists():return q
    return None

def refs_list(folder,runs_root):
    """The reference images in attachment order: char1, char2, the set image (slots.set.mode == set_ref), the look image
    (slots.look.mode == style_ref). [{'n', 'token', 'slot', 'file', 'path', 'job'}] — the same order and numbering the prompt uses."""
    folder=Path(folder);out=[]
    jobs={'char1':"defines the character's identity only (face, hair, outfit, proportions)",'char2':"defines the second character's identity only",
          'set':'defines the set only (walls, floor, furniture, depth of the room)','look':'defines the rendering style only (palette, grain, contrast, brushwork)'}
    for slot in ('char1','char2'):
        p=saved_reference(folder,slot)
        if p:out.append({'slot':slot,'path':p,'job':jobs[slot]})
    slots=read_json(folder/'slots.json') or {}
    s=slots.get('set') or {};l=slots.get('look') or {}
    if s.get('mode')=='set_ref' and s.get('image'):
        p=asset_path(s.get('image'),runs_root,folder)
        if p:out.append({'slot':'set','path':p,'job':jobs['set']})
    if l.get('mode')=='style_ref' and l.get('image'):
        p=asset_path(l.get('image'),runs_root)
        if p:out.append({'slot':'look','path':p,'job':jobs['look']})
    for i,r in enumerate(out,1):
        r.update(n=i,token=f'@Image{i}',file=f'ref-{i:02d}-{r["slot"]}{r["path"].suffix.lower()}')
    return out

def availability(folder,runs_root):
    """{key: {available, reason, files}} for every item of this run. `reason` is a plain sentence when it is missing."""
    from . import words as W
    folder=Path(folder);out={}
    def put(key,ok,reason=None):out[key]={'key':key,'label':P.ITEM_BY_KEY[key]['label'],'what':P.ITEM_BY_KEY[key]['what'],'available':bool(ok),'reason':None if ok else reason}
    put('composite_audio',(folder/'seedance-input.mp4').exists(),'This run has no prepared clip yet (seedance-input.mp4). Finish the preparation first.')
    put('composite_silent',(folder/'composite-silent.mp4').exists(),'This run has no silent composite (composite-silent.mp4). Finish the preparation first.')
    put('depth',(folder/'depth.mp4').exists(),'This run has no depth video: Fast · Face mesh runs skip depth. Use an Advanced preset for one.')
    lm=(folder/'face-landmarks.json').exists()
    put('mesh_alpha',lm,'This run has no face mesh (face-landmarks.json). Use a face-mesh preset, or import landmarks on the face card.')
    put('landmarks',lm,'This run has no face mesh (face-landmarks.json). Use a face-mesh preset, or import landmarks on the face card.')
    mask=mask_source(folder)
    put('mask',mask is not None,'This run has no mask: Fast · Face mesh runs skip SAM. Use an Advanced preset, or import a mask on the mask card.')
    put('alpha',mask is not None and (folder/'composite-silent.mp4').exists(),'The person cut-out needs the silent composite and a mask; this run has no mask (Fast · Face mesh runs skip SAM).')
    up=folder/'upload.mp4'
    put('audio_original',up.exists() and has_audio(up),'The source clip has no audio track.' if up.exists() else 'This run has no source clip (upload.mp4).')
    put('audio_vocals',(folder/'vocals.wav').exists(),'No isolated vocals: run the audio stage with Clean dialogue (paid, Demucs) first.')
    put('audio_music',(folder/'music.wav').exists(),'No separated music: run the audio stage with Clean dialogue (paid, Demucs) first.')
    try:words,source,_=W.current(folder,runs_root)
    except Exception:words,source=[],None
    put('words',bool(words),'No transcript yet: open the Words track in step 02 and click Transcribe (free).')
    out['words']['source']=source
    put('prompt',True)
    refs=refs_list(folder,runs_root)
    put('refs',bool(refs),'No reference image saved yet: choose Character 1 in step 03 (or in Quick) and it is kept with the run.')
    out['refs']['files']=[r['file'] for r in refs]
    put('run',True)
    return out

def describe(folder,runs_root):
    """What the UI needs before an export: presets, items with availability, the clip facts, ffmpeg."""
    problem=ffmpeg_problem()
    return {'presets':P.listing(),'items':[availability(folder,runs_root)[k] for k in P.ITEM_KEYS],'clip':clip_info(folder),'formats':{'rgba':list(P.RGBA_FORMATS)},
            'ffmpeg':problem is None,'ffmpeg_problem':({'message':problem[0],'fix':problem[1]} if problem else None)}

# ---------------------------------------------------------------- the prompt

def prompt_text(folder,runs_root):
    """The final prompt: stages.promptkit.assemble when it exists (Agent 2), else today's prompt text (generation.json, else
    run.json chain.prompt.params.text, else the default) plus the dialogue beats block (pending word edits first) and the ref list."""
    from . import words as W
    folder=Path(folder);refs=refs_list(folder,runs_root)
    try:words,source,_=W.current(folder,runs_root)
    except Exception:words,source=[],None
    beats=W.beats_text(words) if words else ''
    try:
        from . import promptkit   # Agent 2 adds it later; until then today's text below
        slots=read_json(folder/'slots.json') or {}
        out=promptkit.assemble(folder,slots,[{k:(str(v) if k=='path' else v) for k,v in r.items()} for r in refs],words=words or None)
        text=(out or {}).get('text') if isinstance(out,dict) else None
        if text:
            if beats and 'Dialogue beats' not in text:text=text.rstrip()+'\n\n'+beats
            return text.rstrip()+'\n'+ref_lines(refs),'promptkit'
    except Exception:pass   # a missing or changed prompt kit never blocks an export; the plain text below is always right
    gen=read_json(folder/'generation.json') or {}
    text=gen.get('prompt') if isinstance(gen.get('prompt'),str) else None
    if not text:
        run=run_data(folder) or {};text=(((run.get('chain') or {}).get('prompt') or {}).get('params') or {}).get('text')
    if not text:
        from seedance_bridge import DEFAULT_PROMPT
        text=DEFAULT_PROMPT
    text=text.rstrip()
    if beats and 'Dialogue beats' not in text:text+='\n\n'+beats
    return text+'\n'+ref_lines(refs),('generation.json' if gen.get('prompt') else 'run.json')

def ref_lines(refs):
    if not refs:return '\nReferences: @Video1 is the prepared clip (composite.mp4). No reference image is saved with this run yet.\n'
    return '\nReferences (attach in this order; @Video1 is the prepared clip):\n'+''.join(f'  {r["token"]}  {r["file"]}  — {r["job"]}\n' for r in refs)

# ---------------------------------------------------------------- ffmpeg helpers

def run_ffmpeg(args,what,stdin=None):
    """ffmpeg with plain errors; the last lines of stderr go into the message so the README / notice says what went wrong."""
    f=ffmpeg_path()
    if not f:raise ExportError(*ffmpeg_problem())
    cmd=[f,'-hide_banner','-nostdin','-y','-v','error',*[str(a) for a in args]]
    try:r=subprocess.run(cmd,input=stdin,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=3600)
    except subprocess.TimeoutExpired:raise ExportError(f'ffmpeg took more than an hour writing {what}; the export stopped.','Try a shorter clip or fewer items.')
    if r.returncode!=0:
        tail=' '.join(r.stderr.decode('utf-8','replace').strip().splitlines()[-3:])[:400]
        raise ExportError(f'ffmpeg could not write {what}'+(f' ({tail})' if tail else '')+'.','Check that ffmpeg is a full build (brew install ffmpeg) and that the run still has its files, then export again.')
    return r

class FFmpegPipe:
    """ffmpeg reading raw RGBA frames on stdin; `write(frame)` per numpy (h, w, 4) frame, `close()` waits and checks."""
    def __init__(self,out,w,h,fps,codec_args,what):
        f=ffmpeg_path()
        if not f:raise ExportError(*ffmpeg_problem())
        self.what=what;self.out=Path(out)
        self.p=subprocess.Popen([f,'-hide_banner','-nostdin','-y','-v','error','-f','rawvideo','-pix_fmt','rgba','-s',f'{w}x{h}','-r',fps_text(fps),'-i','-',*codec_args,str(out)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    def write(self,frame):
        try:self.p.stdin.write(frame.astype('uint8').tobytes())
        except BrokenPipeError:self.close()
    def close(self):
        if self.p.stdin and not self.p.stdin.closed:
            try:self.p.stdin.close()
            except OSError:pass
        _,err=self.p.communicate(timeout=3600)
        if self.p.returncode!=0:
            tail=' '.join(err.decode('utf-8','replace').strip().splitlines()[-3:])[:400]
            raise ExportError(f'ffmpeg could not write {self.what}'+(f' ({tail})' if tail else '')+'.','Check that ffmpeg has the prores_ks encoder (brew install ffmpeg), then export again.')

PRORES_4444=('-c:v','prores_ks','-profile:v','4444','-pix_fmt','yuva444p10le','-vendor','apl0')
PRORES_422HQ=('-c:v','prores_ks','-profile:v','3','-pix_fmt','yuv422p10le','-vendor','apl0')

# ---------------------------------------------------------------- frame sources

def decode_frames(path,fmt='rgb24'):
    import av
    with av.open(str(path)) as c:
        for f in c.decode(video=0):yield f.to_ndarray(format=fmt)

def mask_frames(folder,source,shape):
    """Boolean person masks, one per frame, from mask.mp4 (luma) or the mask PNG folders."""
    import numpy as np
    from PIL import Image
    folder=Path(folder)
    if source=='mask.mp4':
        for g in decode_frames(folder/'mask.mp4','gray'):
            if g.shape!=shape:g=np.asarray(Image.fromarray(g).resize((shape[1],shape[0]),Image.Resampling.NEAREST))
            yield g>127
        return
    from .wand import read_mask
    files=sorted((folder/source).glob('mask_*.png'))
    for i in range(len(files)):yield read_mask(folder/source,i,shape)

def landmark_frames(landmarks,n):
    """The face points per frame (or None): index i of face-landmarks.json frames (by `frame` number when present)."""
    frames=(landmarks or {}).get('frames') or []
    by={};order=[]
    for k,fr in enumerate(frames):
        i=fr.get('frame',k)
        try:i=int(i)
        except (TypeError,ValueError):i=k
        by[i]=fr
    for i in range(n):
        fr=by.get(i)
        faces=(fr or {}).get('faces') or []
        yield ([(p['x'],p['y']) for p in faces[0]],fr.get('status')) if faces and isinstance(faces[0],list) and faces[0] else (None,(fr or {}).get('status'))

def mesh_rgba_frames(landmarks,n,w,h):
    """The mesh lines alone on a transparent canvas (alpha 255 on the lines, 0 elsewhere), drawn exactly like the face stage."""
    import numpy as np
    from PIL import Image
    from .meshedit import draw_face
    for points,state in landmark_frames(landmarks,n):
        im=Image.new('RGBA',(w,h),(0,0,0,0))
        if points:draw_face(im,points,state)
        yield np.asarray(im)

def alpha_rgba_frames(folder,source):
    """composite-silent.mp4 colours with the mask as alpha; stops at the shorter of the two."""
    import numpy as np
    rgb=decode_frames(Path(folder)/'composite-silent.mp4')
    first=next(rgb,None)
    if first is None:return
    masks=mask_frames(folder,source,first.shape[:2])
    for frame,m in zip([first,*rgb],masks):
        a=np.zeros((frame.shape[0],frame.shape[1],4),np.uint8);a[:,:,:3]=frame;a[:,:,3]=np.where(m,255,0).astype(np.uint8)
        yield a

def write_rgba(frames,dst,fmt,fps,w,h,status,label,every=24):
    """RGBA frames → ProRes 4444 .mov (fmt 'prores') or RGBA PNGs frame_%05d.png in the folder `dst` (fmt 'png'). Returns the frame count."""
    from PIL import Image
    count=0
    if fmt=='png':
        Path(dst).mkdir(parents=True,exist_ok=True)
        for i,a in enumerate(frames):
            Image.fromarray(a,'RGBA').save(Path(dst)/f'frame_{i:05d}.png',format='PNG');count=i+1
            if i%every==0:status(f'{label} · frame {i+1}')
        return count
    pipe=FFmpegPipe(dst,w,h,fps,PRORES_4444,label)
    try:
        for i,a in enumerate(frames):
            pipe.write(a);count=i+1
            if i%every==0:status(f'{label} · frame {i+1}')
    finally:pipe.close()
    return count

def write_video(src,dst,fmt,status,label):
    """A run video as mp4 (copied as is), ProRes 422 HQ .mov, or a PNG sequence folder. Returns the frame count written (None for a copy)."""
    from PIL import Image
    if fmt=='png':
        Path(dst).mkdir(parents=True,exist_ok=True);count=0
        for i,a in enumerate(decode_frames(src)):
            Image.fromarray(a).save(Path(dst)/f'frame_{i:05d}.png',format='PNG');count=i+1
            if i%24==0:status(f'{label} · frame {i+1}')
        return count
    if fmt=='prores422':
        status(f'{label} · ProRes 422 HQ');run_ffmpeg(['-i',src,'-an',*PRORES_422HQ,dst],label);return None
    status(f'{label} · copy');shutil.copyfile(src,dst);return None

def write_composite_audio(src,dst,status,clip):
    """H.264 + AAC mp4 ≤ 1080p: the picture is copied (re-encoded only when it is larger than 1080p), the audio copied when it is AAC."""
    status('Prepared clip · H.264 + AAC');codec=audio_codec(src)
    video=['-c:v','copy'] if clip['height']<=1080 and clip['width']<=1920 else ['-vf',"scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",'-c:v','libx264','-crf','18','-pix_fmt','yuv420p']
    audio=['-c:a','copy'] if codec=='aac' else ['-c:a','aac','-b:a','192k'] if codec else ['-an']
    run_ffmpeg(['-i',src,*video,*audio,'-movflags','+faststart',dst],'composite.mp4')

def write_audio(src,dst,fmt,status):
    status('Original audio · '+('48 kHz wav' if fmt=='wav' else 'm4a'))
    if fmt=='m4a':run_ffmpeg(['-i',src,'-vn',*(['-c:a','copy'] if audio_codec(src)=='aac' else ['-c:a','aac','-b:a','192k']),dst],'audio-original.m4a')
    else:run_ffmpeg(['-i',src,'-vn','-ar','48000','-c:a','pcm_s16le',dst],'audio-original.wav')

# ---------------------------------------------------------------- the export

def parse_items(items,preset):
    """The item keys to export: a list, a comma-separated string or JSON; the preset's defaults when empty. ValueError on unknown keys."""
    if items in (None,''):chosen=list(P.preset(preset)['items'])
    elif isinstance(items,str):
        text=items.strip()
        if text.startswith('['):
            parsed=json.loads(text)
            if not isinstance(parsed,list):raise ValueError('items must be a list of item names.')
            chosen=[str(x) for x in parsed]
        else:chosen=[s.strip() for s in text.split(',') if s.strip()]
    elif isinstance(items,(list,tuple)):chosen=[str(x) for x in items]
    else:raise ValueError('items must be a list of item names.')
    unknown=[k for k in chosen if k not in P.ITEM_BY_KEY]
    if unknown:raise ValueError(f'There is no export item called {unknown[0]!r}. Use: '+', '.join(P.ITEM_KEYS)+'.')
    return [k for k in P.ITEM_KEYS if k in chosen]   # table order, duplicates dropped

def readme_text(ctx):
    """README.txt: what each file is, the clip facts, which run and edits, the preset's reasoning."""
    c=ctx;clip=c['clip'];lines=[]
    lines.append(f'Puppeteer export · {c["preset_label"]}');lines.append(f'Made {c["created"]} · export name {c["name"]}')
    lines.append(f'Run: {c["run"]}'+(f' · exported from the new version {c["exported_run"]} saved first from {c["requested_run"]}' if c.get('exported_run') and c.get('exported_run')!=c.get('requested_run') else ''))
    lines.append(f'Clip: {clip["frames"]} frames at {fps_text(clip["fps"])} fps · {clip["width"]}×{clip["height"]} · {clip["seconds"]} s'+(f' (from {clip["source"]})' if clip.get('source') else ''))
    lines.append('Mode: '+str(c.get('mode') or 'unknown')+(' · preset '+c['run_preset'] if c.get('run_preset') else ''))
    lines.append('')
    lines.append('Edits: '+c['edits_line'])
    lines.append('')
    lines.append('Why this preset:')
    for w in c['why']:lines.append('  '+w)
    lines.append('')
    lines.append('Files:')
    width=max([len(f['file']) for f in c['files']]+[len('README.txt')])+2
    for f in c['files']:lines.append('  '+f['file'].ljust(width)+f['what'])
    lines.append('  '+'README.txt'.ljust(width)+'This file.')
    if c.get('warnings'):
        lines.append('');lines.append('Notes:')
        for w in c['warnings']:lines.append('  '+w)
    lines.append('')
    lines.append('Frame rate and count are the same in every video and sequence here; set the same fps on the loader or the comp. Alpha files are straight (unpremultiplied) alpha.')
    lines.append('Made by Puppeteer, locally and free; nothing was sent anywhere.')
    return '\n'.join(lines)+'\n'

def build_export(folder,items,preset,runs_root,status=lambda s:None,*,mesh_format='prores',alpha_format='prores',name=None,requested_run=None,edits_line=None,record_in=None):
    """Write `runs/<id>/export/<name>/` and `<name>.zip`; returns {folder, zip, files, readme, fps, frames, width, height, name, run,
    exported_run, requested_run, preset, items, warnings, created, seconds}. `items` = keys (or None for the preset's defaults).
    `record_in` = the folder of the run the export was asked on (a `.json` record is written there under export/ so the
    listing and the download work from either run). Raises ExportError with a plain message and fix."""
    import numpy as np
    folder=Path(folder);runs_root=Path(runs_root);ident=folder.name
    try:spec=P.preset(preset)
    except ValueError as e:raise ExportError(str(e),'Pick one of the presets listed by GET /jobs/{id}/export.')
    try:keys=parse_items(items,preset)
    except (ValueError,TypeError) as e:raise ExportError(str(e),'Tick the items listed by GET /jobs/{id}/export.')
    if not keys:raise ExportError('Nothing is ticked, so there is nothing to export.','Tick at least one item (the Custom preset starts empty).')
    problem=ffmpeg_problem()
    if problem:raise ExportError(*problem)
    avail=availability(folder,runs_root)
    if items in (None,''):keys=[k for k in keys if avail[k]['available']] or keys   # the preset's defaults: optional items the run lacks are left out (the route and the panel do the same)
    missing=[k for k in keys if not avail[k]['available']]
    if missing:raise ExportError(f'This run cannot export {P.ITEM_BY_KEY[missing[0]]["label"].lower()}: '+(avail[missing[0]]['reason'] or ''),'Untick it, or pick a run that has it.')
    fmts=P.formats_for(preset,mesh_format,alpha_format);clip=clip_info(folder)
    if not clip['frames']:raise ExportError('This run has no prepared picture to export (no composite-silent.mp4 or original.mp4).','Finish the preparation first, then export.')
    name=name or export_name(preset);root=folder/'export';root.mkdir(exist_ok=True);out=root/name
    if out.exists():raise ExportError(f'An export called {name} already exists.','Export again; every export gets its own name.')
    out.mkdir();files=[];warnings=[];fps=clip['fps'];n=clip['frames'];w,h=clip['width'],clip['height']
    def add(file,what,item):files.append({'file':file,'what':what,'item':item})
    try:
        for key in keys:
            item=P.ITEM_BY_KEY[key];status(f'Export · {item["label"]}')
            if key=='composite_audio':
                write_composite_audio(folder/'seedance-input.mp4',out/'composite.mp4',status,clip);add('composite.mp4',item['what'],key)
            elif key in ('composite_silent','depth','mask'):
                fmt=fmts[key];src=folder/{'composite_silent':'composite-silent.mp4','depth':'depth.mp4','mask':'mask.mp4'}[key]
                if key=='mask' and not src.exists():
                    source=mask_source(folder);status('Mask · from the PNG masks')
                    if fmt=='png':
                        (out/'mask').mkdir();count=0
                        from PIL import Image
                        for i,m in enumerate(mask_frames(folder,source,(h,w))):
                            Image.fromarray(np.where(m,255,0).astype(np.uint8)).save(out/'mask'/f'frame_{i:05d}.png');count=i+1
                        add('mask/frame_%05d.png',item['what']+f' ({count} PNGs, from {source}/)',key)
                    else:
                        target=out/('mask.mov' if fmt=='prores422' else 'mask.mp4')
                        codec=PRORES_422HQ if fmt=='prores422' else ('-c:v','libx264','-crf','18','-pix_fmt','yuv420p')
                        pipe=FFmpegPipe(target,w,h,fps,codec,'mask');count=0
                        try:
                            for i,m in enumerate(mask_frames(folder,source,(h,w))):
                                a=np.zeros((h,w,4),np.uint8);a[:,:,:3]=np.where(m,255,0)[:,:,None].astype(np.uint8);a[:,:,3]=255;pipe.write(a);count=i+1
                        finally:pipe.close()
                        add(target.name,item['what']+f' (from {source}/)',key)
                    continue
                dst=out/item['names'][fmt].split('/')[0]
                count=write_video(src,dst,fmt,status,item['label'])
                add(item['names'][fmt],item['what']+({'png':f' ({count} PNGs)','prores422':' (ProRes 422 HQ)','mp4':' (H.264, copied as is)'}[fmt]),key)
            elif key=='mesh_alpha':
                landmarks=read_json(folder/'face-landmarks.json') or {}
                dst=out/item['names'][fmts[key]].split('/')[0]
                count=write_rgba(mesh_rgba_frames(landmarks,n,w,h),dst,fmts[key],fps,w,h,status,'Face mesh on transparent')
                off=sum(1 for p,_ in landmark_frames(landmarks,n) if not p)
                add(item['names'][fmts[key]],item['what']+(' (ProRes 4444, yuva444p10le)' if fmts[key]=='prores' else f' ({count} RGBA PNGs)')+(f'; {off} frame{"s" if off!=1 else ""} without a mesh (face missing or switched off)' if off else ''),key)
            elif key=='alpha':
                source=mask_source(folder);dst=out/item['names'][fmts[key]].split('/')[0]
                count=write_rgba(alpha_rgba_frames(folder,source),dst,fmts[key],fps,w,h,status,'Person with alpha')
                if count!=n:warnings.append(f'person-alpha has {count} frames where the clip has {n}: the mask ({source}) and the composite differ in length.')
                add(item['names'][fmts[key]],item['what']+(' (ProRes 4444, yuva444p10le)' if fmts[key]=='prores' else f' ({count} RGBA PNGs)')+f'; alpha from {source}',key)
            elif key=='audio_original':
                fmt=fmts[key];write_audio(folder/'upload.mp4',out/item['names'][fmt],fmt,status);add(item['names'][fmt],item['what']+(' (48 kHz 16-bit PCM)' if fmt=='wav' else ' (AAC in m4a)'),key)
            elif key in ('audio_vocals','audio_music'):
                src=folder/item['names']['default'];shutil.copyfile(src,out/src.name);add(src.name,item['what'],key)
            elif key=='landmarks':
                shutil.copyfile(folder/'face-landmarks.json',out/'face-landmarks.json');add('face-landmarks.json',item['what'],key)
            elif key=='words':
                from . import words as W,subtitles as S
                words,source,meta=W.current(folder,runs_root)
                (out/'words.srt').write_text(S.srt(S.cues(words,clip['seconds'])),encoding='utf-8')
                (out/'words.json').write_text(json.dumps({'version':1,'source':source,**{k:v for k,v in (meta or {}).items() if v is not None},'fps':fps,'words':words},indent=1,ensure_ascii=False))
                add('words.srt',f'Subtitle phrases from the transcript ({len(words)} words, from {"your pending word edits" if source=="edits" else "words.json"}).',key)
                add('words.json','Word timings {text, start, end} in seconds, same source.',key)
            elif key=='prompt':
                text,source=prompt_text(folder,runs_root);(out/'prompt.txt').write_text(text,encoding='utf-8')
                add('prompt.txt',f'The generation prompt (from {source}) with the timed dialogue beats and the reference list. Paste it as is.',key)
            elif key=='refs':
                for r in refs_list(folder,runs_root):
                    shutil.copyfile(r['path'],out/r['file']);add(r['file'],f'{r["token"]} · {r["slot"]} reference: {r["job"]}.',key)
            elif key=='run':
                run=run_data(folder)
                if (folder/'run.json').exists():shutil.copyfile(folder/'run.json',out/'run.json')
                else:(out/'run.json').write_text(json.dumps(run or {},indent=1))
                add('run.json','The run record: every stage with its tool, params and cache key'+('' if (folder/'run.json').exists() else ' (reconstructed from a run made before the stage rack)')+'.',key)
                if (folder/'slots.json').exists():shutil.copyfile(folder/'slots.json',out/'slots.json');add('slots.json','Set / Look / Light slots of this run.',key)
                if (folder/'edit-layer.json').exists():shutil.copyfile(folder/'edit-layer.json',out/'edit-layer.json');add('edit-layer.json','The timeline edits this version was saved from.',key)
        if preset=='comfyui' or any(fmts.get(k)=='png' for k in keys if P.ITEM_BY_KEY[k]['kind'] in ('video','rgba')):
            (out/'frames.json').write_text(json.dumps({'fps':fps,'fps_text':fps_text(fps),'frames':n,'width':w,'height':h},indent=1));add('frames.json','{fps, frames, width, height} for the sequence loader (PNGs carry no frame rate).','run')
        run=run_data(folder) or {}
        ctx={'name':name,'preset_label':spec['label'],'created':now_iso(),'run':ident,'exported_run':ident,'requested_run':requested_run or ident,'clip':clip,'mode':run.get('mode'),'run_preset':run.get('preset'),
             'edits_line':edits_line or (('this version was saved from timeline edits: '+str(run.get('changed'))) if run.get('edits') else 'no pending timeline edits; the run exported as it is.'),
             'why':spec['why'],'files':files,'warnings':warnings}
        readme=readme_text(ctx);(out/'README.txt').write_text(readme,encoding='utf-8')
        status('Export · zipping');zip_path=root/(name+'.zip')
        with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(out.rglob('*')):
                if p.is_file():z.write(p,f'{name}/{p.relative_to(out).as_posix()}')
    except ExportError:
        shutil.rmtree(out,ignore_errors=True);(root/(name+'.zip')).unlink(missing_ok=True);raise
    except Exception as e:
        shutil.rmtree(out,ignore_errors=True);(root/(name+'.zip')).unlink(missing_ok=True)
        raise ExportError(f'The export stopped while writing {files[-1]["file"] if files else "its first file"} ({type(e).__name__}: {str(e)[:200]}).','Check that the run still has its files, then export again.')
    result={'name':name,'run':ident,'exported_run':ident,'requested_run':requested_run or ident,'preset':preset,'preset_label':spec['label'],'items':keys,'formats':{k:fmts[k] for k in keys if k in fmts},
            'folder':out,'zip':zip_path,'files':files,'readme':readme,'fps':fps,'frames':n,'width':w,'height':h,'seconds':clip['seconds'],'warnings':warnings,'created':ctx['created'],
            'zip_bytes':zip_path.stat().st_size,'edits':ctx['edits_line']}
    write_record(folder,result)
    if record_in and Path(record_in).resolve()!=folder.resolve():write_record(record_in,result)
    return result

def record_of(result):
    """The JSON-safe record kept next to the zip (export/<name>.json), also the poll / listing shape."""
    return {k:(str(v) if isinstance(v,Path) else v) for k,v in result.items() if k!='readme'}|{'readme':result.get('readme'),'state':'done'}

def write_record(run_folder,result):
    root=Path(run_folder)/'export';root.mkdir(exist_ok=True);path=root/(result['name']+RECORD_SUFFIX)
    fresh(path);path.write_text(json.dumps(record_of(result),indent=1,ensure_ascii=False,default=str))

def list_exports(folder):
    """Earlier exports of a run (records under export/, newest first), each with `zip_exists`."""
    root=Path(folder)/'export';out=[]
    if not root.is_dir():return out
    for path in root.glob('*'+RECORD_SUFFIX):
        rec=read_json(path)
        if not isinstance(rec,dict) or not rec.get('name'):continue
        rec['zip_exists']=Path(rec.get('zip') or '').exists();out.append(rec)
    out.sort(key=lambda r:r.get('created') or '',reverse=True)
    return out

def zip_for(folder,name):
    """The zip of export `name` as seen from `folder`: its own export/<name>.zip, else the one its record points to (an export made from a child)."""
    folder=Path(folder);z=folder/'export'/(name+'.zip')
    if z.exists():return z
    rec=read_json(folder/'export'/(name+RECORD_SUFFIX)) or {}
    z=Path(rec.get('zip') or '')
    return z if rec and z.exists() else None
