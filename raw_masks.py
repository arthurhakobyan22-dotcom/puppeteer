"""SAM 3 raw per-frame masks on Replicate, with real failure reasons and fallbacks.

Order of attempts in `segment_raw`:
1. `lucataco/sam3-video` (pinned version) on the given video, once per comma-separated prompt term; the
   per-term masks are unioned. SAM 3 text prompts are single noun phrases, so "person, hands" as one
   string matches nothing and the model returns a zip with no masks.
2. If every term comes back empty and an RGB video is supplied, the same runs on the RGB frames.
3. If still empty, or the primary model itself fails, `SAM_FALLBACK_MODEL` (default `8digit/gener8-sam3`,
   another SAM 3 video model on Replicate) is tried; its output is parsed defensively.
Auth, billing and rate-limit errors stop immediately with the provider's message: a fallback would hit
the same wall. Every prediction is recorded in `sam-attempts.json` (id, status, error, metrics, log tail)
and the chosen route in `sam-report.json`.
"""
from pathlib import Path
import json,time,zipfile,io,re,shutil
import requests
from config import setting,load_env

API='https://api.replicate.com/v1'
PRIMARY_MODEL='lucataco/sam3-video'
PRIMARY_VERSION='408f82fc20c300aac5d61d2e34ddb34cd0181e810e9f609d250aed14d5f81269'
DEFAULT_FALLBACK='8digit/gener8-sam3'
POLL_SECONDS=5;POLL_ATTEMPTS=180

class SamError(ValueError):
    """kind: auth | quota | failed | timeout | empty | bad_output | http"""
    def __init__(self,kind,message):super().__init__(message);self.kind=kind

def _headers():
    load_env();token=setting('REPLICATE_API_TOKEN')
    if not token:raise SamError('auth','REPLICATE_API_TOKEN is not set; SAM 3 segmentation runs on Replicate.')
    return {'Authorization':'Bearer '+token}

def _http_error(r,stage):
    try:
        body=r.json();detail=body.get('detail') or body.get('title') or body.get('error') or r.text
    except ValueError:detail=r.text
    detail=str(detail)[:300];code=r.status_code
    if code in (401,403):return SamError('auth',f'Replicate rejected the token during {stage} ({code}): {detail}')
    if code==402:return SamError('quota',f'Replicate billing or credit problem during {stage} ({code}): {detail}')
    if code==429:return SamError('quota',f'Replicate rate limit during {stage} ({code}): {detail}')
    return SamError('http',f'Replicate error during {stage} ({code}): {detail}')

def _upload(path,h):
    with open(path,'rb') as f:r=requests.post(API+'/files',headers=h,files={'content':f},timeout=120)
    if not r.ok:raise _http_error(r,'video upload')
    return r.json()['urls']['get']

def _record(folder,entry):
    path=Path(folder)/'sam-attempts.json'
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):data=[]
    data.append(entry);path.write_text(json.dumps(data,indent=1))

def _predict(h,body,folder,label):
    """Create a prediction, poll it, record the final state; return it. Raises SamError with the provider's reason."""
    r=requests.post(API+'/predictions',headers=h,json=body,timeout=60)
    if not r.ok:raise _http_error(r,f'SAM submission ({label})')
    j=r.json();(Path(folder)/'sam-raw-request.json').write_text(json.dumps(j,indent=2));print('SAM job',label+':',j.get('id'),flush=True)
    for _ in range(POLL_ATTEMPTS):
        if j.get('status') in ['succeeded','failed','canceled']:break
        time.sleep(POLL_SECONDS);r=requests.get(j['urls']['get'],headers=h,timeout=30)
        if not r.ok:raise _http_error(r,f'SAM polling ({label})')
        j=r.json()
    logs=(j.get('logs') or '').strip().splitlines()
    _record(folder,{'label':label,'id':j.get('id'),'status':j.get('status'),'error':j.get('error'),'metrics':j.get('metrics'),'input':j.get('input'),'output':j.get('output'),'logs_tail':logs[-30:]})
    if j.get('status') not in ['succeeded','failed','canceled']:
        raise SamError('timeout',f'SAM ({label}) is still {j.get("status")} on Replicate after {POLL_SECONDS*POLL_ATTEMPTS//60} minutes; prediction {j.get("id")} is saved in sam-attempts.json. Not resubmitted.')
    if j['status']!='succeeded':
        error=str(j.get('error') or j['status']);interesting=[l for l in logs if re.search(r'error|exception|traceback|cuda|memory',l,re.I)][-3:]
        kind='quota' if re.search(r'credit|quota|billing|insufficient|rate ?limit|payment',error,re.I) else 'failed'
        raise SamError(kind,f'SAM ({label}) {j["status"]} on Replicate: {error[:300]}'+(' | log: '+' / '.join(interesting)[:300] if interesting else ''))
    return j

def _download(url):
    r=requests.get(url,timeout=180)
    if not r.ok:raise SamError('http',f'Could not download SAM output ({r.status_code}) from {url[:80]}')
    return r.content

def _png_mask(data):
    import numpy as np
    from PIL import Image
    image=Image.open(io.BytesIO(data))
    a=np.asarray(image.convert('I') if image.mode in ('I;16','I;16B','I','F') else image.convert('L'))
    return a>0 if image.mode in ('I;16','I;16B','I','F') else a>127

def _save(mask,path):
    import numpy as np
    from PIL import Image
    Image.fromarray(mask.astype(np.uint8)*255).save(path)

def _collect(output,out_dir,label):
    """Write mask_00000.png … from whatever the model returned: a zip of PNGs, a mask video, one or more frame images."""
    import numpy as np
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True)
    urls=output if isinstance(output,list) else list(output.values()) if isinstance(output,dict) else [output]
    urls=[u for u in urls if isinstance(u,str) and u.startswith('http')]
    if not urls:raise SamError('bad_output',f'SAM ({label}) returned no downloadable output: {str(output)[:200]}')
    frames=[];videos=[]
    for url in urls:
        content=_download(url)
        if content[:4]==b'PK\x03\x04':
            # Zip of per-frame PNGs (the primary model). Other entries such as overlay.mp4 are previews, not masks.
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                for n in sorted(n for n in z.namelist() if n.lower().endswith('.png')):frames.append(_png_mask(z.read(n)))
        elif content[:8]==b'\x89PNG\r\n\x1a\n':frames.append(_png_mask(content))
        elif url.lower().endswith(('.mp4','.mkv','.webm','.mov')) or b'ftyp' in content[:64]:videos.append(content)
    if not frames and videos:
        # A label-map or black-and-white mask video (fallback models): any clearly non-black pixel is mask.
        import av,tempfile
        with tempfile.NamedTemporaryFile(suffix='.mp4',delete=False) as t:t.write(videos[0]);temp=t.name
        try:
            with av.open(temp) as c:
                for f in c.decode(video=0):frames.append(np.asarray(f.to_image().convert('L'))>64)
        except Exception as exc:raise SamError('bad_output',f'SAM ({label}) returned a video that could not be decoded as masks: {type(exc).__name__}')
        finally:Path(temp).unlink(missing_ok=True)
    for i,mask in enumerate(frames):_save(mask,out_dir/f'mask_{i:05d}.png')
    return sum(1 for m in frames if m.any())

def _union(dirs,out):
    """Union per-frame masks from several term runs; frame counts must agree."""
    import numpy as np
    out=Path(out);shutil.rmtree(out,ignore_errors=True);out.mkdir()
    dirs=[d for d in dirs if any(Path(d).glob('mask_*.png'))]
    if not dirs:return 0
    lists=[sorted(Path(d).glob('mask_*.png')) for d in dirs]
    if len({len(l) for l in lists})!=1:raise SamError('bad_output','SAM term runs returned different frame counts: '+str([len(l) for l in lists]))
    nonempty=0
    for i,group in enumerate(zip(*lists)):
        mask=None
        for p in group:
            m=_png_mask(p.read_bytes());mask=m if mask is None else (mask|m)
        _save(mask,out/f'mask_{i:05d}.png');nonempty+=bool(mask.any())
    return nonempty

def _model_version(name,h):
    r=requests.get(API+'/models/'+name,headers=h,timeout=30)
    if not r.ok:raise _http_error(r,f'resolving {name}')
    version=(r.json().get('latest_version') or {}).get('id')
    if not version:raise SamError('bad_output',f'Replicate model {name} has no published version.')
    return version

def segment_raw(video,folder,prompt='person',rgb_video=None,status=print):
    """Return a folder of mask_XXXXX.png (one per frame) or raise SamError with the real reason."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);h=_headers()
    terms=[t.strip() for t in str(prompt).split(',') if t.strip()] or ['person']
    out=folder/'raw-masks';report={'prompt':prompt,'terms':terms,'attempts':[]}
    for p in folder.glob('sam-attempts.json'):p.unlink()
    sources=[('depth',Path(video))]+([('rgb',Path(rgb_video))] if rgb_video and Path(rgb_video).resolve()!=Path(video).resolve() else [])
    urls={}
    for source,path in sources:
        urls[source]=_upload(path,h);dirs=[]
        for k,term in enumerate(terms):
            label=f'{PRIMARY_MODEL} · {term!r} on {source}';status(f'SAM 3 · segmenting {term!r} on {source} frames')
            j=_predict(h,{'version':PRIMARY_VERSION,'input':{'video':urls[source],'prompt':term,'mask_only':True,'return_zip':True}},folder,label)
            d=folder/f'raw-masks-{source}-{k}';count=_collect(j['output'],d,label);dirs.append(d)
            report['attempts'].append({'model':PRIMARY_MODEL,'source':source,'term':term,'id':j.get('id'),'frames_with_mask':count})
        if _union(dirs,out):
            matched=[a['term'] for a in report['attempts'] if a['source']==source and a['frames_with_mask']]
            report.update(method=f'SAM 3 ({PRIMARY_MODEL}) on {source} frames; terms matched: {matched}',source=source,model=PRIMARY_MODEL)
            (folder/'sam-report.json').write_text(json.dumps(report,indent=1));return out
        status(f'SAM 3 found nothing for {prompt!r} on {source} frames'+(' · retrying on the original RGB frames' if source=='depth' and len(sources)>1 else ''))
    fallback=setting('SAM_FALLBACK_MODEL',DEFAULT_FALLBACK).strip()
    if fallback:
        source='rgb' if 'rgb' in urls else 'depth';label=f'{fallback} · {prompt!r} on {source}';status(f'Fallback · {fallback} on {source} frames')
        try:
            j=_predict(h,{'version':_model_version(fallback,h),'input':{'video':urls[source],'prompt':prompt}},folder,label)
            count=_collect(j['output'],out,label)
        except SamError as e:
            if e.kind in ('auth','quota','timeout'):raise
            report['attempts'].append({'model':fallback,'source':source,'term':prompt,'error':str(e)});count=0
        else:report['attempts'].append({'model':fallback,'source':source,'term':prompt,'id':j.get('id'),'frames_with_mask':count})
        if count:
            report.update(method=f'fallback {fallback} on {source} frames',source=source,model=fallback);(folder/'sam-report.json').write_text(json.dumps(report,indent=1));return out
    report.update(method=None);(folder/'sam-report.json').write_text(json.dumps(report,indent=1))
    tried=', '.join(f"{a['model']} {a['term']!r} on {a['source']}" for a in report['attempts'])
    raise SamError('empty',f'SAM 3 returned no masks for prompt {prompt!r} (empty result, not a quota or model error: every prediction succeeded). Tried: {tried}. '
                   'Use one short noun phrase that names the visible subject, for example "person" or "man in a dark suit"; comma-separated terms are run as separate SAM jobs and unioned.')

def clean_border_fragments(folder):
    """Remove tiny, narrow disconnected edge fragments; preserve large edge subjects."""
    import numpy as np
    from PIL import Image
    from scipy.ndimage import label
    folder=Path(folder);output=folder.parent/'clean-masks';output.mkdir(exist_ok=True)
    report=[]
    for p in sorted(folder.glob('mask_*.png')):
        a=np.asarray(Image.open(p).convert('L'))>127;labels,_=label(a);h,w=a.shape;removed=0
        for ident in (set(labels[:,0])|set(labels[:,-1]))-{0}:
            y,x=np.where(labels==ident)
            if len(x)<h*w*.03 and x.max()-x.min()+1<=max(6,int(w*.05)):
                a[labels==ident]=False;removed+=len(x)
        Image.fromarray(a.astype(np.uint8)*255).save(output/p.name)
        report.append({'frame':p.stem,'removed_border_pixels':removed,'mask_pixels':int(a.sum()),'left_right_edge_pixels':int(a[:,0].sum()+a[:,-1].sum())})
    (folder.parent/'mask-cleanup-report.json').write_text(json.dumps(report,indent=2))
    return output
