"""Wan 2.2 Animate (replace mode) on fal: pose-native character replacement, one render, no draft/complete.

`fal-ai/wan/v2.2-14b/animate/replace` takes exactly one video (`video_url`, our prepared clip) and one image
(`image_url`, the Character 1 reference) and returns the clip with the person replaced: pose, expression, timing,
background and lighting come from the video, the look comes from the image. There is no prompt, no second
reference, no set / style slot, no audio generation (the orchestrator restores the original audio anyway) and no
draft id: the first render is the final. Schema and price read from fal on 2026-10-24 (docs/GENERATORS.md).

Files are uploaded with `fal_client.upload_file`; FAL_KEY comes from the environment through `config.load_env()`
and is never logged or written. The payload is saved as `wan-request.json` and, for the orchestrator and the UI
that read it, as `seedance-request.json` too.
"""
from pathlib import Path
import json
import fal_client
from config import credential,load_env,setting
from .base import Provider,is_video,check_video_constraints,check_image_constraints

APP='fal-ai/wan/v2.2-14b/animate/replace'
RESOLUTIONS=('480p','580p','720p')
DEFAULT_RESOLUTION='480p'
BILLED_FPS=16                      # fal bills "16 frames per video second" (model page, 2026-10-24)
USD_PER_BILLED_SECOND={'480p':0.04,'580p':0.06,'720p':0.08}
NEAREST='Seedance via fal'
NO_FINALIZE='Wan Animate has no draft to complete: the first render is the final. Re-run the generate stage at 720p for a sharper clip, or use '+NEAREST+' for a 480p draft that completes at 1080p.'

def _redact(text):
    key=setting('FAL_KEY')
    return text.replace(key,'[FAL_KEY]') if key else text

def _call(function,*args,**kwargs):
    """Run a fal_client call; re-raise as RuntimeError with the key redacted and no chained traceback."""
    try:return function(*args,**kwargs)
    except Exception as exc:
        raise RuntimeError('fal request failed ('+type(exc).__name__+'): '+_redact(str(exc))[:500]) from None

def resolution_for(folder=None,requested=None):
    """Resolution to render at: explicit > `<folder>/wan-options.json` {"resolution"} > WAN_RESOLUTION > 480p."""
    value=requested
    if not value and folder is not None:
        path=Path(folder)/'wan-options.json'
        if path.exists():
            try:value=json.loads(path.read_text()).get('resolution')
            except ValueError:value=None
    value=(value or setting('WAN_RESOLUTION',DEFAULT_RESOLUTION) or DEFAULT_RESOLUTION).strip().lower()
    if value not in RESOLUTIONS:raise ValueError('Wan Animate renders at '+', '.join(RESOLUTIONS)+f'; {value!r} is not one of them. Pick 480p for a quick look or 720p for the sharpest result.')
    return value

class Wan(Provider):
    name='wan'
    label='Wan 2.2 Animate · replace (fal)'
    draft_endpoint=APP
    final_endpoint=None

    def __init__(self,resolution=None):
        self.resolution=resolution

    def capabilities(self):
        return {'name':'wan','label':self.label,'endpoint':APP,'draft_resolution':DEFAULT_RESOLUTION,'final_resolution':'720p','finalize':None,'finalize_identical':False,
                'finalize_label':'','finalize_hint':NO_FINALIZE,'needs_webhook':False,'hosting':'fal_storage','max_seconds':30,'video_identity_reference':False,
                'resolutions':list(RESOLUTIONS),'draft':False,'audio':False,'tasks':[],'ref_images_max':1,
                'slots':{'set_ref':False,'look_ref':False,'char2':False,'identity_video':False},'control':'pose','fps':BILLED_FPS,'prompt':False,
                'notes':['Pose, expression, timing, background and lighting come from the prepared clip; only the person is replaced.',
                         'No prompt is sent: the set, look and light slots only matter for Seedance here.',
                         'No audio is generated; the original audio is restored over the result as usual.']}

    def require_configured(self):
        load_env()
        credential('FAL_KEY')

    def _endpoint(self,folder,request_id):
        return APP

    def submit_draft(self,prepared,refs,prompt,*,folder,status=print,task=None,resolution=None):
        """`prompt` and `task` are accepted for the shared orchestrator call and ignored: the endpoint takes neither (it always
        keeps the pose and timing of the prepared clip), so `seedance-request.json` has no `task` and generation.json says 'not applicable'."""
        folder=Path(folder);self.require_configured()
        char1=Path(refs['char1']);char2=refs.get('char2')
        if is_video(char1):raise ValueError('Wan Animate needs an image for Character 1; it does not take an identity video. Pick one clear frame of the identity video as the Character 1 image, or use '+NEAREST+' for a video identity.')
        if char2:raise ValueError('Wan Animate takes one reference image: Character 2 cannot be sent. Remove Character 2, or use '+NEAREST+' for two characters.')
        chosen=resolution_for(folder,resolution or self.resolution)
        check_video_constraints(prepared);check_image_constraints(char1)
        from stages.calls import record_call
        record_call(folder,'fal',APP)
        status('Uploading the prepared video and the Character 1 image to fal storage')
        video_url=_call(fal_client.upload_file,Path(prepared))
        image_url=_call(fal_client.upload_file,char1)
        payload={'video_url':video_url,'image_url':image_url,'resolution':chosen}
        text=json.dumps(payload,indent=2)
        (folder/'wan-request.json').write_text(text);(folder/'seedance-request.json').write_text(text)
        status('Submitting to Wan 2.2 Animate (replace) on fal · '+chosen)
        handle=_call(fal_client.submit,APP,arguments=payload)
        ident=getattr(handle,'request_id',None)
        if not ident:raise ValueError('fal did not return a request ID.')
        return ident

    def poll(self,request_id,*,folder):
        folder=Path(folder);self.require_configured();app=self._endpoint(folder,request_id)
        current=_call(fal_client.status,app,request_id,with_logs=False)
        if isinstance(current,fal_client.Queued):
            return {'state':'queued','status':f'Queued at fal · position {current.position} · {request_id}','result_url':None,'endpoint':app}
        if isinstance(current,fal_client.InProgress):
            return {'state':'running','status':'Wan Animate is rendering · '+request_id,'result_url':None,'endpoint':app}
        if isinstance(current,fal_client.Completed):
            if getattr(current,'error',None):
                return {'state':'error','status':'Wan Animate failed: '+_redact(str(current.error)),'result_url':None,'endpoint':app}
            result=_call(fal_client.result,app,request_id)
            (folder/'wan-result.json').write_text(json.dumps(result,indent=2,default=str))
            url=(result.get('video') or {}).get('url') if isinstance(result,dict) else None
            if not isinstance(url,str) or not url.startswith('https://'):raise ValueError('Wan result video URL missing.')
            return {'state':'done','status':'Wan Animate render complete','result_url':url,'draft_id':None,'seed':result.get('seed'),'auto_prompt':result.get('prompt'),'endpoint':app}
        return {'state':'running','status':'fal status: '+type(current).__name__,'result_url':None,'endpoint':app}

    def finalize(self,request_id,*,folder):
        raise ValueError(NO_FINALIZE)
