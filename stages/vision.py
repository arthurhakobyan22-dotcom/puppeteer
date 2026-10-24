"""Claude vision fill for the SET and LIGHT slots (World stage, Agent 2): one frame of the prepared clip, the person masked out,
described in two short labelled lines by Claude through the Anthropic Messages API.

`describe_frame(folder, t=None, runs_root=None)` -> {'set', 'light', 'model', 'usd', 'frame_s', 'frame', 'warnings', 'estimated_usd'}

- The frame is the middle one of `original.mp4` (or the one at `t` seconds: index = round(t × fps)). When the run has `clean-masks/`
  (or `raw-masks/`) the person's mask region is filled with neutral gray before the frame is encoded, so the model sees the room, not
  the performer. The frame is scaled to at most 1024 px on its long side and sent as a base64 JPEG.
- The instruction asks for the set (architecture, furniture, materials, depth) and the light (direction, quality, colour temperature,
  practicals) only, never people, clothing or faces, as two lines `SET:` and `LIGHT:`. Sentences that still mention a person are
  stripped and reported in `warnings`.
- Plain HTTP with `requests` (the `anthropic` package is not installed), model `claude-sonnet-5-5`, key from
  `config.setting('ANTHROPIC_API_KEY')`: never logged, never written into a run folder, never put in a URL.
- Paid: `record_call(folder, 'anthropic', 'messages', cost_usd=…)` runs before the request, so `PUPPETEER_OFFLINE=1` raises
  `OfflineError` before anything is sent. The price is `stages.costs.PRICES['claude_vision']` (about a cent); the real spend is
  computed from the response's `usage` and returned as `usd`.
- No key -> `VisionError` ('No Anthropic key yet.', with the how-to as `.fix`); the route turns it into a plain 400.
"""
from pathlib import Path
import base64,io,re
import numpy as np
from PIL import Image
import requests
from config import setting

MODEL='claude-sonnet-5-5'
URL='https://api.anthropic.com/v1/messages'
API_VERSION='2023-06-01'
MAX_SIDE=1024
JPEG_QUALITY=85
MAX_TOKENS=300
GRAY=(128,128,128)
NO_KEY_MESSAGE='No Anthropic key yet.'
NO_KEY_FIX='Add a line ANTHROPIC_API_KEY=sk-ant-… to the .env file in the project folder (console.anthropic.com → API keys), then restart the app.'
INSTRUCTION=('You describe film sets for a video generation prompt. Look only at the room in this frame: describe the SET (architecture, '
             'furniture, materials, surfaces, depth of the space, what is near and far) and the LIGHT (direction, quality — hard or soft, '
             'colour temperature, practical lamps or windows, contrast). Never describe people, bodies, clothing, hair or faces; a gray '
             'shape where a person was masked out is not part of the set and must not be mentioned. Answer with exactly two lines and '
             'nothing else:\nSET: <one sentence, at most 40 words>\nLIGHT: <one sentence, at most 30 words>')
QUESTION='Describe the set and the light of this frame in the two labelled lines.'
PERSON=re.compile(r"\b(person|people|man|woman|men|women|girl|boy|child|children|guy|lady|someone|figure|performer|actor|actress|he|she|his|her|they|their|face|faces|hair|shirt|dress|jacket|clothing|clothes|outfit|wearing|hand|hands|arm|arms|body|silhouette|subject)\b",re.I)
LABEL=re.compile(r'^\s*\**\s*(SET|LIGHT)\s*\**\s*:\s*(.*)$',re.I)

class VisionError(ValueError):
    """A plain refusal: str(e) is the sentence, .fix the suggestion, .status the HTTP code the route answers with."""
    def __init__(self,message,fix,status=400):super().__init__(message);self.fix=fix;self.status=status

def has_key():return bool(setting('ANTHROPIC_API_KEY'))

def estimate():
    from . import costs
    return costs.price_for('claude_vision') or 0.0

# ---------------------------------------------------------------- the frame

def frame_index(folder,t=None):
    """(index, frames, fps): the middle frame, or round(t × fps) clamped into the clip."""
    from .wand import frame_shape
    folder=Path(folder)
    if not (folder/'original.mp4').exists():raise VisionError('This run has no prepared clip yet (original.mp4), so there is no frame to describe.','Prepare the clip first; the description works on the prepared video.')
    h,w,n,fps=frame_shape(folder/'original.mp4');n=max(1,int(n));fps=float(fps or 24.0)
    if t in (None,''):index=n//2
    else:
        try:index=int(round(float(t)*fps))
        except (TypeError,ValueError):raise VisionError('The time must be a number of seconds.','Pause the video on a frame and try again, or leave the time out for the middle frame.')
    return max(0,min(n-1,index)),n,fps

def frame_image(folder,t=None):
    """(PIL RGB image, index, fps, masked): the frame with the person's mask region filled neutral gray when the run has masks, scaled to ≤ MAX_SIDE."""
    from .wand import decode_frame,mask_dir,read_mask
    folder=Path(folder);index,n,fps=frame_index(folder,t)
    rgb=np.array(decode_frame(folder/'original.mp4',index),dtype=np.uint8,copy=True)
    masks=mask_dir(folder);masked=False
    if masks is not None:
        mask=read_mask(masks,index,rgb.shape[:2])
        if mask.any():rgb[mask]=GRAY;masked=True
    img=Image.fromarray(rgb,'RGB');scale=MAX_SIDE/max(img.size)
    if scale<1:img=img.resize((max(1,round(img.size[0]*scale)),max(1,round(img.size[1]*scale))),Image.Resampling.LANCZOS)
    return img,index,fps,masked

def encode_jpeg(img,quality=JPEG_QUALITY):
    buf=io.BytesIO();img.save(buf,'JPEG',quality=quality);return buf.getvalue()

# ---------------------------------------------------------------- the answer

def strip_people(text):
    """Drop the sentences that still talk about a person; (clean text, True when something was dropped)."""
    parts=[s for s in re.split(r'(?<=[.!?;])\s+',text.strip()) if s.strip()]
    kept=[s for s in parts if not PERSON.search(s)]
    return ' '.join(kept).strip(),len(kept)!=len(parts)

def parse(text):
    """{'set', 'light', 'warnings'} from the model's two labelled lines (anything unlabelled is ignored; people sentences are stripped)."""
    out={'set':'','light':''};warnings=[]
    for line in (text or '').splitlines():
        m=LABEL.match(line)
        if m:
            key=m.group(1).lower();out[key]=(out[key]+' '+m.group(2).strip()).strip()
    for key in ('set','light'):
        clean,dropped=strip_people(out[key])
        if dropped:warnings.append(f'The {key} line mentioned a person; that part was removed. Read the line before you use it.')
        out[key]=clean
    if not out['set'] and not out['light']:warnings.append('Claude did not answer with the SET: / LIGHT: lines; nothing was filled in.')
    return {**out,'warnings':warnings}

def usage_usd(usage):
    """Real spend from the response's token counts at the claude_vision prices (None when the response had no usage)."""
    if not isinstance(usage,dict):return None
    from . import costs
    entry=costs.PRICES['claude_vision'];rate_in=entry['usd_per_million_input'];rate_out=entry['usd_per_million_output']
    tokens_in=sum(int(usage.get(k) or 0) for k in ('input_tokens','cache_creation_input_tokens','cache_read_input_tokens'))
    return round(tokens_in*rate_in/1e6+int(usage.get('output_tokens') or 0)*rate_out/1e6,4)

def describe_frame(folder,t=None,runs_root=None):
    """One paid Messages call; see the module docstring. Raises VisionError (plain, with .fix), OfflineError, or RuntimeError for a network failure."""
    folder=Path(folder);key=setting('ANTHROPIC_API_KEY')
    if not key:raise VisionError(NO_KEY_MESSAGE,NO_KEY_FIX)
    img,index,fps,masked=frame_image(folder,t);data=base64.standard_b64encode(encode_jpeg(img)).decode('ascii')
    from .calls import record_call
    guess=estimate();record_call(folder,'anthropic','messages',cost_usd=guess)   # OfflineError here, before any request
    payload={'model':MODEL,'max_tokens':MAX_TOKENS,'system':INSTRUCTION,'output_config':{'effort':'low'},
             'messages':[{'role':'user','content':[{'type':'image','source':{'type':'base64','media_type':'image/jpeg','data':data}},{'type':'text','text':QUESTION}]}]}
    try:r=requests.post(URL,headers={'x-api-key':key,'anthropic-version':API_VERSION,'content-type':'application/json'},json=payload,timeout=90)
    except requests.RequestException as e:raise RuntimeError('The Anthropic API could not be reached ('+type(e).__name__+').') from None
    if r.status_code==401:raise VisionError('The Anthropic key was not accepted.','Check the ANTHROPIC_API_KEY line in .env (console.anthropic.com → API keys), then restart the app.',status=502)
    if r.status_code==429:raise VisionError('Anthropic is rate-limiting this key right now.','Wait a minute and click Describe again.',status=502)
    if not r.ok:
        try:detail=str(((r.json() or {}).get('error') or {}).get('message') or '')[:200]
        except ValueError:detail=''
        raise VisionError(f'Anthropic answered {r.status_code}'+(f': {detail}' if detail else '.'),'Try again; if it happens again, check the model name and your account at console.anthropic.com.',status=502)
    body=r.json();content=body.get('content') or []
    if body.get('stop_reason')=='refusal':raise VisionError('Claude declined to describe this frame.','Pick another frame (pause the video elsewhere) and try again.',status=502)
    text='\n'.join(b.get('text','') for b in content if isinstance(b,dict) and b.get('type')=='text')
    parsed=parse(text);usd=usage_usd(body.get('usage'))
    return {'set':parsed['set'],'light':parsed['light'],'model':body.get('model') or MODEL,'usd':usd if usd is not None else guess,'estimated_usd':guess,
            'frame_s':round(index/fps,3),'frame':index,'fps':fps,'masked':masked,'warnings':parsed['warnings'],'raw':text}
