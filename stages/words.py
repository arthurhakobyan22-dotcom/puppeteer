"""Words track: transcription, the edit-layer hooks, dialogue beats and mouth guidance (docs/WORDS.md, TIMELINE-SPEC §6, §A4).

Layer: `words = {words: [{id, text, start, end}], singing, edited?: [word ids], replaced?: {engine, language, words}}`
or null. On save the child gets `words.json` ({version, engine, language, singing, words: [{text, start, end}]}) and
`mouth-guidance.json`; nothing re-runs for a words-only session (the branch is at `prompt`).

Transcription (`transcribe`): the run's audio (vocals.wav when clean dialogue made one, else upload.mp4, else the
prepared clip) is decoded to 16 kHz mono, hashed, and transcribed by the free local engine (mlx-whisper in
`.venv-words`, `words_worker.py`) or the paid fal fallback (ElevenLabs speech-to-text, cost gate in app.py). Results are
cached as `runs/_cache/words/<audio sha>-<engine>-<singing>.json`, so a re-run is instant and free. `words.json` and
`mouth-guidance.json` are written into the run only when it has none (an additive analysis output, never overwritten);
a second transcription goes into the edit layer instead and lands in the child on save.
"""
import json,math,os,re,subprocess,threading,time,uuid
from pathlib import Path
from config import ROOT
from .base import fresh
from .editlayer import Track,register_track

VERSION=1
SAMPLE_RATE=16000
MODEL='whisper-large-v3-turbo'                 # chosen in docs/WORDS.md (accuracy + timing on the fixture, speed)
MODELS_DIR=ROOT/'models'/'whisper'
VENV_PYTHON=ROOT/'.venv-words'/'bin'/'python'
WORKER=ROOT/'words_worker.py'
FAL_ENDPOINT='fal-ai/elevenlabs/speech-to-text'
ENGINES={'local':{'label':'Whisper large-v3-turbo on this Mac (mlx-whisper)','paid':False,'note':'free, runs locally'},
         'fal':{'label':'ElevenLabs speech-to-text on fal','paid':True,'note':'paid, needs FAL_KEY and the internet'}}
SETUP_FIX='Run  bash setup-words.sh  once in the project folder (Python 3.12; downloads mlx-whisper and the model, about 1.6 GB), then transcribe again.'
MIN_WORD={False:0.06,True:0.20}     # seconds; singing holds notes, so blocks start longer
CLOSE_GAP={False:0.04,True:0.25}    # gaps shorter than this are closed by extending the earlier word (sung words are held)
PAUSE=0.4                           # a gap this long starts a new dialogue beat
TAIL,TAIL_GAP=0.15,0.02             # words shorter than 20 ms in the last 0.15 s are dropped (they cannot be heard; see docs/WORDS.md)
_locks={};_locks_lock=threading.Lock()

class WordsError(ValueError):
    """A plain refusal for the routes: str(e) is the sentence, .fix the suggestion, .status the HTTP code."""
    def __init__(self,message,fix,status=400):super().__init__(message);self.fix=fix;self.status=status

def plural(n,word):return f'{n} {word}{"" if n==1 else "s"}'

# ---------------------------------------------------------------- audio

def audio_source(folder):
    """The file whose audio is transcribed: isolated vocals when present (cleaner), else the untouched upload, else the prepared clip."""
    folder=Path(folder)
    for name in ('vocals.wav','upload.mp4','seedance-input.mp4','original.mp4'):
        path=folder/name
        if path.exists() and has_audio(path):return path
    return None

def has_audio(path):
    import av
    try:
        with av.open(str(path)) as c:return bool(c.streams.audio)
    except Exception:return False

def decode_audio(path):
    """16 kHz mono float32 samples of the first audio stream (PyAV resampler)."""
    import av,numpy as np
    chunks=[]
    with av.open(str(path)) as c:
        stream=c.streams.audio[0];res=av.AudioResampler(format='flt',layout='mono',rate=SAMPLE_RATE)
        for frame in c.decode(stream):
            for out in res.resample(frame):chunks.append(out.to_ndarray().reshape(-1))
        for out in res.resample(None):chunks.append(out.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype('float32') if chunks else np.zeros(0,'float32')

def write_wav(samples,path):
    import wave,numpy as np
    pcm=(np.clip(samples,-1,1)*32767).astype('<i2')
    with wave.open(str(path),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(SAMPLE_RATE);w.writeframes(pcm.tobytes())

def audio_sha(samples):
    import hashlib
    return hashlib.sha256(samples.tobytes()).hexdigest()

def clip_info(folder):
    """(frames, fps, seconds) of the prepared clip: original.mp4, else face-tracking.json, else the audio length at 24 fps."""
    folder=Path(folder)
    if (folder/'original.mp4').exists():
        try:
            from .wand import frame_shape
            h,w,n,fps=frame_shape(folder/'original.mp4');return n,fps,n/fps
        except Exception:pass
    try:
        t=json.loads((folder/'face-tracking.json').read_text());n=int(t['frames']);fps=float(t.get('fps') or 24);return n,fps,n/fps
    except (OSError,ValueError,KeyError,TypeError):pass
    from .costs import clip_seconds
    seconds=clip_seconds(folder) or 0.0;return int(round(seconds*24)),24.0,seconds

# ---------------------------------------------------------------- engines

def model_dir(name=MODEL):return MODELS_DIR/name

def local_ready(name=MODEL):
    """None when the local engine can run, else (message, fix)."""
    if not VENV_PYTHON.exists():return ('Local transcription is not installed yet (.venv-words is missing).',SETUP_FIX)
    folder=model_dir(name)
    if not (folder/'config.json').exists() or not any(folder.glob('*.safetensors')) and not any(folder.glob('*.npz')):
        return (f'The Whisper model ({name}) is not downloaded yet, so nothing can be transcribed'+(' offline.' if offline_mode() else '.'),SETUP_FIX)
    return None

def offline_mode():
    from .calls import offline
    return offline()

def run_local(wav,singing=False,language=None,model=MODEL,timeout=900):
    """Run words_worker.py in .venv-words; returns its JSON. No network: the model is a local folder and HF is forced offline."""
    problem=local_ready(model)
    if problem:raise WordsError(*problem)
    out=Path(wav).with_suffix('.json')
    args=[str(VENV_PYTHON),str(WORKER),str(wav),str(out),'--model',str(model_dir(model))]+(['--singing'] if singing else [])+(['--language',language] if language else [])
    env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
    try:result=subprocess.run(args,capture_output=True,text=True,timeout=timeout,env=env)
    except subprocess.TimeoutExpired:raise WordsError('The local transcription took too long and was stopped.','Try a shorter clip, or close other heavy apps and transcribe again.')
    if result.returncode!=0 or not out.exists():
        lines=[l for l in (result.stderr or result.stdout).splitlines() if l.strip()]
        raise WordsError('The local transcription failed: '+(lines[-1].split(': ',1)[-1][:300] if lines else f'worker exited with code {result.returncode}'),'Run  bash setup-words.sh  again to repair the install, then transcribe again.')
    try:return json.loads(out.read_text())
    finally:out.unlink(missing_ok=True)

def run_fal(folder,wav,seconds,language=None):
    """The paid fallback (ElevenLabs speech-to-text on fal). `record_call` comes first, so offline mode stops it before any I/O."""
    from .calls import record_call
    from . import costs
    record_call(folder,'fal',FAL_ENDPOINT,stage='words',tool='fal',cost_usd=costs.price_for('words_fal',seconds))
    import fal_client
    from config import load_env,credential
    load_env();credential('FAL_KEY')
    url=fal_client.upload_file(str(wav))
    arguments={'audio_url':url,'diarize':False,'tag_audio_events':False,**({'language_code':language} if language else {})}
    result=fal_client.submit(FAL_ENDPOINT,arguments=arguments).get()
    return {'engine':'fal','endpoint':FAL_ENDPOINT,'language':(result or {}).get('language_code') or language or '','text':(result or {}).get('text') or '','words':(result or {}).get('words') or []}

def parse(raw):
    """[{text, start, end}] from the local worker's segments or fal's words (only type == word)."""
    out=[]
    if isinstance(raw,dict) and isinstance(raw.get('segments'),list):
        for seg in raw['segments']:
            for w in (seg or {}).get('words') or []:out.append({'text':str(w.get('word','')),'start':w.get('start'),'end':w.get('end')})
    elif isinstance(raw,dict) and isinstance(raw.get('words'),list):
        for w in raw['words']:
            if (w or {}).get('type','word')=='word':out.append({'text':str(w.get('text','')),'start':w.get('start'),'end':w.get('end')})
    return out

def rows_of(words):
    rows=[]
    for w in words or []:
        if not isinstance(w,dict):continue
        text=re.sub(r'\s+',' ',str(w.get('text') or '')).strip()
        try:start=float(w.get('start') or 0);end=float(w.get('end') if w.get('end') is not None else start)
        except (TypeError,ValueError):continue
        if text and math.isfinite(start) and math.isfinite(end):rows.append([text,max(0.0,start),max(0.0,end)])
    return sorted(rows,key=lambda r:r[1])

def settle(rows,least,gap,duration):
    """In place: no overlap (a word starts at or after the previous end), at least `least` long, gaps under `gap` closed, inside the clip."""
    keep=least if gap<=0 else min(least,0.02)   # the shortest a word may become when it is trimmed to the next one
    for i,r in enumerate(rows):
        if duration:r[1]=min(r[1],max(0.0,duration-least))
        if i and r[1]<rows[i-1][2]:r[1]=rows[i-1][2]
        r[2]=max(r[2],r[1]+least)
        if i+1<len(rows):
            nxt=rows[i+1][1]
            if nxt-r[2]<gap and nxt>=r[1]+keep:r[2]=nxt   # close a small gap, or trim a small overlap
        if duration:r[2]=min(r[2],duration)
    return rows

def clean(words,singing=False,duration=None):
    """Sorted, trimmed, non-overlapping words with a minimum length; singing = longer minimum and held notes fill short gaps."""
    rows=rows_of(words)
    if duration:rows=[r for r in rows if not (r[2]-r[1]<TAIL_GAP and r[1]>=duration-TAIL)]   # zero-length words squeezed into the last moment: Whisper's tail artifact
    rows=settle(rows,MIN_WORD[bool(singing)],CLOSE_GAP[bool(singing)],duration)
    return [{'text':t,'start':round(s,3),'end':round(e,3)} for t,s,e in rows]

def normalize_words(words,fps=24.0,duration=None):
    """The layer's words made safe to save: text trimmed, sorted, at least one frame long, no overlap, inside the clip."""
    rows=settle(rows_of(words),1.0/(fps or 24),0.0,duration)
    return [{'text':t,'start':round(s,3),'end':round(e,3)} for t,s,e in rows]

def lock_for(key):
    with _locks_lock:return _locks.setdefault(key,threading.Lock())

def cache_file(runs_root,sha,engine,singing):return Path(runs_root)/'_cache'/'words'/f'{sha}-{engine}-{"singing" if singing else "speech"}.json'

def prepare(folder):
    """(source path, samples, sha, seconds) of the run's audio; plain WordsError when there is none."""
    source=audio_source(folder)
    if source is None:raise WordsError('This run has no audio track, so there is nothing to transcribe.','Use a source clip with sound; you can still add words by hand on the Words track.')
    try:samples=decode_audio(source)
    except Exception as e:raise WordsError(f'The audio of {source.name} could not be read ({type(e).__name__}).','Re-run the preparation, or add the words by hand on the Words track.')
    if not len(samples):raise WordsError('The audio track is empty, so there is nothing to transcribe.','Add the words by hand on the Words track.')
    return source,samples,audio_sha(samples),len(samples)/SAMPLE_RATE

def transcribe(folder,runs_root,engine='local',singing=False,language=None,prepared=None):
    """Transcribe the run (or reuse the cache). Returns {data (words.json shape), cached, written, guidance_written, seconds, sha, source}."""
    folder=Path(folder);engine=engine if engine in ENGINES else 'local';singing=bool(singing)
    source,samples,sha,seconds=prepared or prepare(folder)
    frames,fps,clip_seconds=clip_info(folder);duration=clip_seconds or seconds
    path=cache_file(runs_root,sha,engine,singing);clock=time.time()
    with lock_for(path.name):
        cached=path.exists()
        if cached:
            try:data=json.loads(path.read_text())
            except (OSError,ValueError):cached=False
        if not cached:
            path.parent.mkdir(parents=True,exist_ok=True)
            wav=path.parent/f'.{sha[:16]}-{uuid.uuid4().hex[:6]}.wav';write_wav(samples,wav)
            try:raw=run_fal(folder,wav,seconds,language) if engine=='fal' else run_local(wav,singing,language)
            finally:wav.unlink(missing_ok=True)
            words=clean(parse(raw),singing,duration)
            data={'version':VERSION,'engine':raw.get('engine') or ('mlx-whisper:'+MODEL),'language':raw.get('language') or language or '','singing':singing,'words':words,
                  'audio':{'source':source.name,'sha256':sha,'seconds':round(seconds,3)},'text':raw.get('text') or ' '.join(w['text'] for w in words),'seconds':round(time.time()-clock,2)}
            tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=1,ensure_ascii=False));os.replace(tmp,path)
    written=write_new(folder,'words.json',{k:data[k] for k in ('version','engine','language','singing','words','audio') if k in data})
    guidance=write_new(folder,'mouth-guidance.json',mouth_guidance(data['words'],folder)) if written or not (folder/'mouth-guidance.json').exists() else False
    return {'data':data,'cached':cached,'written':written,'guidance_written':guidance,'seconds':round(time.time()-clock,2),'sha':sha,'source':source.name}

def write_new(folder,name,data):
    """Write `name` into the run only when it is absent (an additive output; an existing one is never overwritten)."""
    path=Path(folder)/name
    if path.exists():return False
    tmp=path.with_name('.'+name+'.'+uuid.uuid4().hex[:6]);tmp.write_text(json.dumps(data,indent=1,ensure_ascii=False))
    try:os.link(tmp,path)   # fails if another request wrote it meanwhile: still never overwritten
    except FileExistsError:return False
    finally:tmp.unlink(missing_ok=True)
    return True

# ---------------------------------------------------------------- mouth guidance (data only, for a later stage)

def frame_span(start,end,fps):
    a=int(math.floor(start*fps+1e-6));b=max(a,int(math.ceil(end*fps-1e-6))-1);return a,b

def mouth_guidance(words,folder):
    """Per word {text, start, end, start_frame, end_frame} (inclusive frames) plus per frame {frame, word (index | null),
    mouth_hidden}: true where the face is missing or interpolated in face-tracking.json, or the mesh is switched off
    (`edited.off_frames`); null when the run has no face tracking."""
    frames,fps,_=clip_info(folder);fps=fps or 24.0
    try:tracking=json.loads((Path(folder)/'face-tracking.json').read_text())
    except (OSError,ValueError):tracking=None
    hidden=None
    if isinstance(tracking,dict):
        hidden=set(tracking.get('missing_frames') or [])|set(tracking.get('filled_frames') or [])|set(((tracking.get('edited') or {}).get('off_frames')) or [])
        if not tracking.get('missing_frames'):
            for g in tracking.get('gaps') or []:hidden|=set(range(int(g['start_frame']),int(g['end_frame'])+1))
        frames=frames or int(tracking.get('frames') or 0)
    rows=[];owner={}
    for i,w in enumerate(words):
        a,b=frame_span(float(w['start']),float(w['end']),fps);rows.append({'text':w['text'],'start':w['start'],'end':w['end'],'start_frame':a,'end_frame':b})
        for f in range(a,b+1):owner.setdefault(f,i)
    per=[{'frame':f,'word':owner.get(f),'mouth_hidden':(f in hidden) if hidden is not None else None} for f in range(frames)]
    spoken=[p for p in per if p['word'] is not None]
    return {'version':VERSION,'fps':fps,'frames':frames,'words':rows,'per_frame':per,
            'summary':{'words':len(rows),'frames_with_speech':len(spoken),'speech_frames_mouth_hidden':sum(1 for p in spoken if p['mouth_hidden']) if hidden is not None else None},
            'note':'Data only: which word is spoken on each frame and whether the mouth is hidden there (face lost or interpolated in face-tracking.json, or the mesh switched off). Nothing is generated from it yet.'}

def refresh_guidance(folder):
    """Rewrite mouth-guidance.json from the run's own words.json + face-tracking.json (after a branch re-ran the face stage)."""
    folder=Path(folder)
    try:words=json.loads((folder/'words.json').read_text()).get('words') or []
    except (OSError,ValueError,AttributeError):return False
    path=folder/'mouth-guidance.json';data=mouth_guidance(words,folder)
    try:
        if path.exists() and json.loads(path.read_text())==data:return False
    except (OSError,ValueError):pass
    tmp=path.with_name('.mouth-guidance.'+uuid.uuid4().hex[:6]);tmp.write_text(json.dumps(data,indent=1,ensure_ascii=False));fresh(path);os.replace(tmp,path)
    return True

# ---------------------------------------------------------------- the words a run has right now (pending edits first)

def run_words(folder):
    try:data=json.loads((Path(folder)/'words.json').read_text())
    except (OSError,ValueError):return None
    return data if isinstance(data,dict) else None

def current(folder,runs_root):
    """(words, source, meta): the pending layer's words when the session has any, else words.json, else ([], None, {})."""
    from . import editlayer
    session=editlayer.load(runs_root,Path(folder).name)
    value=(session or {}).get('layer',{}).get('words')
    frames,fps,seconds=clip_info(folder)
    if isinstance(value,dict) and isinstance(value.get('words'),list):
        return normalize_words(word_list(value),fps,seconds),'edits',{'singing':bool(value.get('singing'))}
    data=run_words(folder)
    if data:return normalize_words(data.get('words') or [],fps,seconds),'words.json',{k:data.get(k) for k in ('engine','language','singing')}
    return [],None,{}

# ---------------------------------------------------------------- dialogue beats for the prompt

def phrases(words,pause=PAUSE,max_seconds=None,max_chars=None,stop_at_sentence=True):
    """Group consecutive words into phrases, split at pauses (and sentence ends, length limits when given)."""
    out=[];cur=[]
    for w in words:
        if cur:
            gap=w['start']-cur[-1]['end'];text=' '.join(x['text'] for x in cur+[w])
            if gap>=pause or (stop_at_sentence and re.search(r'[.!?…]["”\')]*$',cur[-1]['text'])) or (max_seconds and w['end']-cur[0]['start']>max_seconds) or (max_chars and len(text)>max_chars):
                out.append(cur);cur=[]
        cur.append(w)
    if cur:out.append(cur)
    return out

def beats(words,pause=PAUSE):
    """Prompt lines grouped by pauses: '0.0–1.8 s says: "hello there"'."""
    lines=[]
    for group in phrases(words,pause):
        text=' '.join(w['text'] for w in group).replace('"','\'')
        lines.append(f'{group[0]["start"]:.1f}–{group[-1]["end"]:.1f} s says: "{text}"')
    return lines

def beats_text(words,pause=PAUSE):
    lines=beats(words,pause)
    return ('Dialogue beats (timing from the original audio; keep the lip-sync on these):\n'+'\n'.join(lines)) if lines else ''

# ---------------------------------------------------------------- edit-layer hooks

def word_list(value):
    value=value if isinstance(value,dict) else {}
    return [w for w in value.get('words') or [] if isinstance(w,dict) and str(w.get('text','')).strip()]

class WordsTrack(Track):
    label='words';empty=None
    def count(self,value):
        if not isinstance(value,dict):return 0
        edited=value.get('edited');replaced=1 if isinstance(value.get('replaced'),dict) else 0
        if isinstance(edited,list) and edited:return len(set(map(str,edited)))+replaced
        return replaced or len(word_list(value)) or (1 if 'words' in value else 0)
    def summary(self,value):
        n=self.count(value);words=word_list(value);lines=[]
        replaced=(value or {}).get('replaced') if isinstance(value,dict) else None
        if isinstance(replaced,dict):lines.append(f'transcribed again ({plural(len(words),"word")}'+(', singing mode' if value.get('singing') else '')+')')
        edited=(value or {}).get('edited') if isinstance(value,dict) else None
        if isinstance(edited,list) and edited:return lines+[plural(len(set(map(str,edited))),'word')+' edited']
        if lines:return lines
        return [f'transcript of {plural(len(words),"word")} edited' if words else 'transcript cleared']
    def materialize(self,value,child_folder,session_dir,parent_folder):
        if not isinstance(value,dict):return
        child=Path(child_folder);base=run_words(parent_folder) or {};replaced=value.get('replaced') if isinstance(value.get('replaced'),dict) else {}
        frames,fps,seconds=clip_info(child if (child/'original.mp4').exists() else parent_folder)
        words=normalize_words(word_list(value),fps,seconds)
        data={'version':VERSION,'engine':replaced.get('engine') or base.get('engine') or 'manual','language':replaced.get('language') or base.get('language') or '','singing':bool(value.get('singing',base.get('singing',False))),'edited':True,'words':words}
        path=child/'words.json';fresh(path);path.write_text(json.dumps(data,indent=1,ensure_ascii=False))
        guide=child/'mouth-guidance.json';fresh(guide);guide.write_text(json.dumps(mouth_guidance(words,child),indent=1,ensure_ascii=False))

register_track('words',WordsTrack)
