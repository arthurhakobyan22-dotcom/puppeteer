"""Subtitles from the Words track: SRT export and a free local burn-in (docs/WORDS.md, TIMELINE-SPEC §6, §A4).

`cues(words)` groups words into phrases (≤ 42 characters, ≤ 5 s, split at pauses and sentence ends); `srt(cues)` is a
valid SRT file. `burn(src, dst, cues)` draws the cue text onto every frame with PIL (this FFmpeg build has no
`subtitles` / `drawtext` filter) and copies the audio packets unchanged. The layout is computed for a 380 px wide
picture and scaled to the real width (16 px text, 14 px side margins, 18 px from the bottom at 380 px), so the
subtitles read the same on a phone and on a large draft. The finish step's toggle state lives in `subtitles.json`
({version, burn, updated, source, words_sha, files}); the burned files are `final-preview-subtitled.mp4` and
`hd/final-preview-subtitled.mp4` next to the untouched finals.
"""
import hashlib,json,os,uuid
from pathlib import Path
from fractions import Fraction
from .base import fresh

MAX_CHARS=42
MAX_SECONDS=5.0
PAUSE=0.6
MIN_SHOW=0.5        # a cue stays at least this long unless the next one starts first
LAYOUT_WIDTH=380    # layout px: text 16, side margin 14, bottom margin 18, outline 2, shadow 2 (scaled to the real width)
FONTS=['/System/Library/Fonts/Supplemental/Arial Bold.ttf','/System/Library/Fonts/Supplemental/Arial Unicode.ttf','/System/Library/Fonts/Helvetica.ttc',
       '/Library/Fonts/Arial Unicode.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','DejaVuSans-Bold.ttf']
def clip_seconds(folder):
    from .words import clip_info
    return clip_info(folder)[2] or None

TARGETS=[('final-preview.mp4','final-preview-subtitled.mp4'),('hd/final-preview.mp4','hd/final-preview-subtitled.mp4')]

def cues(words,duration=None):
    """[{index, start, end, text}] — phrases of ≤ MAX_CHARS characters and ≤ MAX_SECONDS, split at pauses and sentence ends; never past `duration`."""
    from .words import phrases
    out=[]
    groups=phrases(words,PAUSE,MAX_SECONDS,MAX_CHARS)
    for i,g in enumerate(groups):
        start=g[0]['start'];end=g[-1]['end'];nxt=groups[i+1][0]['start'] if i+1<len(groups) else None
        end=max(end,start+MIN_SHOW);end=min(end,nxt) if nxt is not None and nxt>start else end
        if duration:end=max(min(end,duration),min(g[-1]['end'],duration))
        out.append({'index':i+1,'start':round(start,3),'end':round(end,3),'text':' '.join(w['text'] for w in g)})
    return out

def stamp(t):
    ms=int(round(max(0.0,t)*1000));h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

def srt(items):
    """SRT text: index, 'HH:MM:SS,mmm --> HH:MM:SS,mmm', text, blank line."""
    return ''.join(f'{c["index"]}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}\n\n' for c in items)

def words_sha(words):
    return hashlib.sha256(json.dumps([[w['text'],w['start'],w['end']] for w in words],ensure_ascii=False).encode()).hexdigest()

# ---------------------------------------------------------------- burn-in

_font_cache={}
def font(size):
    from PIL import ImageFont
    if size in _font_cache:return _font_cache[size]
    for path in FONTS:
        try:_font_cache[size]=ImageFont.truetype(path,size);return _font_cache[size]
        except OSError:continue
    try:_font_cache[size]=ImageFont.load_default(size=size)
    except TypeError:_font_cache[size]=ImageFont.load_default()
    return _font_cache[size]

def wrap(draw,text,face,width):
    lines=[];cur=''
    for word in text.split():
        trial=(cur+' '+word).strip()
        if cur and draw.textlength(trial,font=face)>width:lines.append(cur);cur=word
        else:cur=trial
    if cur:lines.append(cur)
    return lines

def draw_text(im,text):
    """White text with a black outline and a soft shadow, bottom-centred, wrapped to the 380 px layout width."""
    from PIL import ImageDraw
    k=im.width/LAYOUT_WIDTH;size=max(10,round(16*k));margin=14*k;bottom=18*k;stroke=max(1,round(2*k));shadow=max(1,round(2*k))
    d=ImageDraw.Draw(im);face=font(size);lines=wrap(d,text,face,im.width-2*margin);step=round(size*1.22)
    y=im.height-bottom-step*len(lines)
    for line in lines:
        w=d.textlength(line,font=face);x=(im.width-w)/2
        d.text((x+shadow,y+shadow),line,font=face,fill=(0,0,0),stroke_width=stroke,stroke_fill=(0,0,0))
        d.text((x,y),line,font=face,fill=(255,255,255),stroke_width=stroke,stroke_fill=(0,0,0))
        y+=step
    return im

def active(items,t):
    for c in items:
        if c['start']<=t+1e-6 and t<c['end']-1e-6:return c['text']
    return None

def burn(src,dst,items,status=lambda s:None):
    """Re-encode `src` with the cue text drawn on the frames (libx264 crf 18, yuv420p, same fps and size) and the audio
    packets copied unchanged. Written under a temporary name, then moved into place. Returns {frames, frames_with_text}."""
    import av
    src=Path(src);dst=Path(dst);tmp=dst.with_name('.'+dst.name+'.'+uuid.uuid4().hex[:6]+'.mp4');count=0;texted=0
    try:
        with av.open(str(src)) as inp,av.open(str(tmp),'w') as out:
            vin=inp.streams.video[0];ain=inp.streams.audio[0] if inp.streams.audio else None
            rate=vin.average_rate or vin.guessed_rate or Fraction(24);fps=Fraction(rate).limit_denominator(1001)
            vout=out.add_stream('libx264',rate=fps);vout.width=vin.width;vout.height=vin.height;vout.pix_fmt='yuv420p';vout.options={'crf':'18'}
            aout=out.add_stream_from_template(ain) if ain is not None else None
            for packet in inp.demux(*[s for s in (vin,ain) if s is not None]):
                if packet.stream.type=='audio':
                    if packet.dts is None:continue
                    packet.stream=aout;out.mux(packet);continue
                for frame in packet.decode():
                    t=float(frame.pts*frame.time_base) if frame.pts is not None and frame.time_base else count/float(fps)
                    t-=float((vin.start_time or 0)*vin.time_base) if vin.start_time else 0.0
                    im=frame.to_image().convert('RGB');text=active(items,t+0.5/float(fps))
                    if text:draw_text(im,text);texted+=1
                    vf=av.VideoFrame.from_image(im);vf.pts=count;vf.time_base=1/fps
                    for p in vout.encode(vf):out.mux(p)
                    count+=1
                    if count%48==0:status(f'Burning subtitles · frame {count}')
            for p in vout.encode():out.mux(p)
        fresh(dst);os.replace(tmp,dst)
    finally:
        if tmp.exists():tmp.unlink()
    return {'frames':count,'frames_with_text':texted}

# ---------------------------------------------------------------- the finish step's toggle (subtitles.json)

def read_state(folder):
    try:data=json.loads((Path(folder)/'subtitles.json').read_text())
    except (OSError,ValueError):data={}
    return data if isinstance(data,dict) else {}

def write_state(folder,data):
    path=Path(folder)/'subtitles.json';tmp=path.with_name('.subtitles.'+uuid.uuid4().hex[:6]);tmp.write_text(json.dumps(data,indent=1,ensure_ascii=False));fresh(path);os.replace(tmp,path)

def state(folder,runs_root):
    """What the finish step shows: {burn, words, source, cues, up_to_date, finals: [{final, subtitled, exists, url}]}."""
    from .words import current
    folder=Path(folder);data=read_state(folder);words,source,_=current(folder,runs_root);sha=words_sha(words) if words else None
    finals=[{'final':f,'subtitled':s,'has_final':(folder/f).exists(),'exists':(folder/s).exists(),'url':f'/runs/{folder.name}/{s}' if (folder/s).exists() else None} for f,s in TARGETS]
    made=[x for x in finals if x['has_final']]
    return {'id':folder.name,'burn':bool(data.get('burn')),'words':len(words),'source':source,'cues':len(cues(words,clip_seconds(folder))) if words else 0,'words_sha':sha,
            'up_to_date':bool(data.get('burn')) and bool(made) and all(x['exists'] for x in made) and data.get('words_sha')==sha,'finals':finals,'updated':data.get('updated'),'note':data.get('note')}

def set_burn(folder,runs_root,burn_on):
    """Turn the burn-in on (burn every final that exists, from the current words) or off (the subtitled files stay on disk, unused)."""
    from .words import current,WordsError
    from .report import now
    folder=Path(folder);data=read_state(folder)
    if not burn_on:
        data.update(version=1,burn=False,updated=now());write_state(folder,data);return state(folder,runs_root)
    words,source,_=current(folder,runs_root)
    if not words:raise WordsError('This run has no transcript yet, so there is nothing to burn in.','Transcribe on the Words track of the review step first (free), then turn this on again.')
    if not any((folder/f).exists() for f,_ in TARGETS):raise WordsError('There is no final preview in this run yet.','Create a draft first; the subtitles are burned into the finished preview.')
    items=cues(words,clip_seconds(folder));files={}
    for final,target in TARGETS:
        if (folder/final).exists():files[target]=burn(folder/final,folder/target,items)
    data.update(version=1,burn=True,updated=now(),source=source,words_sha=words_sha(words),cues=len(items),files=files,note='Burned locally with PIL over the untouched final; the audio packets are copied unchanged.')
    write_state(folder,data);return state(folder,runs_root)
