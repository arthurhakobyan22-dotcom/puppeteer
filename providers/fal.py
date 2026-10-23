"""fal Seedance 2.5 adapter: 480p drafts via reference-to-video, true 1080p completion via draft/complete.

Local files go to fal storage with `fal_client.upload_file` (no tmpfiles/catbox). `fal_client` reads
FAL_KEY from the environment; `config.load_env()` copies .env there. The key is never logged or persisted.
"""
from pathlib import Path
import json
import fal_client
from config import credential,load_env,setting
from .base import Provider,build_prompt,is_video,check_video_constraints,check_image_constraints

DRAFT_APP='bytedance/seedance-2.5/reference-to-video'
COMPLETE_APP='bytedance/seedance-2.5/draft/complete'
TASKS=('auto','reference','editing','extension')

def _redact(text):
    key=setting('FAL_KEY')
    return text.replace(key,'[FAL_KEY]') if key else text

def _call(function,*args,**kwargs):
    """Run a fal_client call; re-raise as RuntimeError with the key redacted and no chained traceback."""
    try:return function(*args,**kwargs)
    except Exception as exc:
        raise RuntimeError('fal request failed ('+type(exc).__name__+'): '+_redact(str(exc))[:500]) from None

class Fal(Provider):
    name='fal'
    label='fal · Seedance 2.5'
    draft_endpoint=DRAFT_APP
    final_endpoint=COMPLETE_APP

    def capabilities(self):
        return {'name':'fal','label':'fal · Seedance 2.5','draft_resolution':'480p','final_resolution':'1080p','finalize':'complete_draft','finalize_identical':True,
                'finalize_label':'Approve & complete at 1080p →','finalize_hint':'fal completes this exact draft at 1080p (same draft id, valid for 7 days). No webhook or tunnel needed.',
                'needs_webhook':False,'hosting':'fal_storage','max_seconds':30,'video_identity_reference':True,
                # generator keys (providers/capabilities.py; fal OpenAPI for reference-to-video read 2026-10-24: image_urls "up to 30 images", total files ≤50)
                'resolutions':['480p','720p','1080p'],'draft':True,'audio':True,'tasks':list(TASKS),'ref_images_max':30,
                'slots':{'set_ref':True,'look_ref':True,'char2':True,'identity_video':True},'control':'video','fps':24,'prompt':True}

    def require_configured(self):
        load_env()
        credential('FAL_KEY')

    def _task(self,explicit=None):
        """The Seedance task: the explicit one from the request (the Set slot: original set → editing, a changed set → reference) when given, else FAL_TASK (default editing)."""
        if explicit not in (None,'','auto'):
            task=str(explicit).strip().lower()
            if task not in TASKS:raise ValueError('The task must be one of: '+', '.join(TASKS))
            return task
        task=(setting('FAL_TASK','editing') or 'editing').strip().lower()
        if task not in TASKS:raise ValueError('FAL_TASK must be one of: '+', '.join(TASKS))
        return task

    def _endpoint(self,folder,request_id):
        folder=Path(folder)
        for name in ['response.json','seedance-response.json']:
            path=folder/name
            if not path.exists():continue
            try:saved=json.loads(path.read_text())
            except ValueError:continue
            if saved.get('requestId')==request_id and saved.get('endpoint'):return saved['endpoint']
        return COMPLETE_APP if folder.name=='hd' else DRAFT_APP

    def submit_draft(self,prepared,refs,prompt,*,folder,status=print,task=None):
        folder=Path(folder);self.require_configured();task=self._task(task)
        char1=Path(refs['char1']);char2=refs.get('char2')
        videos=[Path(prepared)];images=[]
        check_video_constraints(prepared)
        if is_video(char1):check_video_constraints(char1);videos.append(char1)
        else:check_image_constraints(char1);images.append(char1)
        if char2:check_image_constraints(char2);images.append(Path(char2))
        full_prompt,mode=build_prompt(prompt,folder,refs)
        from stages.calls import record_call
        record_call(folder,'fal',DRAFT_APP)
        status('Uploading the prepared video and character references to fal storage')
        video_urls=[_call(fal_client.upload_file,path) for path in videos]
        image_urls=[_call(fal_client.upload_file,path) for path in images]
        payload={'prompt':full_prompt,'video_urls':video_urls,'task':task,'draft':True,'resolution':'480p','generate_audio':True}
        if image_urls:payload['image_urls']=image_urls
        (folder/'seedance-request.json').write_text(json.dumps(payload,indent=2))
        status('Submitting the draft to fal')
        handle=_call(fal_client.submit,DRAFT_APP,arguments=payload)
        ident=getattr(handle,'request_id',None)
        if not ident:raise ValueError('fal did not return a request ID.')
        return ident

    def poll(self,request_id,*,folder):
        folder=Path(folder);self.require_configured();app=self._endpoint(folder,request_id)
        current=_call(fal_client.status,app,request_id,with_logs=False)
        if isinstance(current,fal_client.Queued):
            return {'state':'queued','status':f'Queued at fal · position {current.position} · {request_id}','result_url':None,'endpoint':app}
        if isinstance(current,fal_client.InProgress):
            return {'state':'running','status':'fal is rendering · '+request_id,'result_url':None,'endpoint':app}
        if isinstance(current,fal_client.Completed):
            if getattr(current,'error',None):
                return {'state':'error','status':'fal failed: '+_redact(str(current.error)),'result_url':None,'endpoint':app}
            result=_call(fal_client.result,app,request_id)
            (folder/'fal-result.json').write_text(json.dumps(result,indent=2,default=str))
            url=(result.get('video') or {}).get('url') if isinstance(result,dict) else None
            if not isinstance(url,str) or not url.startswith('https://'):raise ValueError('fal result video URL missing.')
            return {'state':'done','status':'fal render complete','result_url':url,'draft_id':result.get('draft_id'),'seed':result.get('seed'),'endpoint':app}
        return {'state':'running','status':'fal status: '+type(current).__name__,'result_url':None,'endpoint':app}

    def finalize(self,request_id,*,folder):
        """Complete the saved draft at 1080p. Needs the draft_id fal returned with the 480p result."""
        folder=Path(folder);self.require_configured()
        draft_id=None
        for name in ['fal-result.json','generation.json']:
            path=folder/name
            if path.exists():
                draft_id=json.loads(path.read_text()).get('draft_id')
                if draft_id:break
        if not draft_id:raise ValueError('This fal draft has no draft_id, so it cannot be completed at 1080p. Create a new draft (fal keeps draft ids for 7 days).')
        from stages.calls import record_call
        record_call(folder,'fal',COMPLETE_APP)
        payload={'draft_id':draft_id,'resolution':'1080p'}
        hd=folder/'hd';hd.mkdir(exist_ok=True);(hd/'request.json').write_text(json.dumps(payload,indent=2))
        handle=_call(fal_client.submit,COMPLETE_APP,arguments=payload)
        ident=getattr(handle,'request_id',None)
        if not ident:raise ValueError('fal did not return a request ID.')
        return ident
