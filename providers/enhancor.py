"""Enhancor Seedance 2.5 adapter: 1080p draft (edit or multi_reference), POST /status polling, draft completion."""
from pathlib import Path
import json,concurrent.futures,requests
from config import credential,setting
from media_host import upload
from .base import Provider,build_prompt,probe_video

RATIOS={'16:9':16/9,'9:16':9/16,'1:1':1,'4:3':4/3,'3:4':3/4,'21:9':21/9}

def base_url():
    return setting('ENHANCOR_BASE_URL','https://apireq.enhancor.ai/api/seedance2.5/v1').rstrip('/')+'/'

class Enhancor(Provider):
    name='enhancor'
    label='Enhancor'

    def capabilities(self):
        return {'name':'enhancor','label':'Enhancor','draft_resolution':'1080p draft','final_resolution':'1080p','finalize':'complete_draft','finalize_identical':True,
                'finalize_label':'Approve & generate 1080p →','finalize_hint':'Enhancor completes the approved draft at 1080p with its original parameters.',
                'needs_webhook':True,'hosting':'tmpfiles','max_seconds':30,'video_identity_reference':True}

    def require_configured(self):
        credential('ENHANCOR_API_KEY')
        if not setting('ENHANCOR_WEBHOOK_URL'):raise ValueError('Webhook URL required. Install cloudflared and restart the app, or set ENHANCOR_WEBHOOK_URL.')

    def submit_draft(self,prepared,refs,prompt,*,folder,status=print):
        folder=Path(folder);self.require_configured();key=credential('ENHANCOR_API_KEY')
        char1=Path(refs['char1']);char2=refs.get('char2')
        full_prompt,mode=build_prompt(prompt,folder,refs)
        from stages.calls import record_call
        record_call(folder,'enhancor','seedance2.5/v1/queue (is_draft)')
        status('Uploading the prepared video and character references')
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:urls=list(pool.map(upload,[prepared,char1]+([Path(char2)] if char2 else [])))
        p={'resolution':'1080p','output_format':'mp4','pass_faces':True,'webhook_url':setting('ENHANCOR_WEBHOOK_URL','')}
        p.update(mode='edit',is_draft=True,aspect_ratio='adaptive',videos=[urls[0]],audios=[],images=urls[1:],prompt=full_prompt)
        if mode=='multi_reference':
            info=probe_video(prepared);ratio=info['width']/info['height']
            p.update(mode='multi_reference',duration=str(max(4,min(30,round(info['seconds'])))),aspect_ratio=min(RATIOS,key=lambda r:abs(RATIOS[r]-ratio)))
            p['videos']=[urls[0],urls[1]];p['images']=urls[2:]
        (folder/'seedance-request.json').write_text(json.dumps(p,indent=2))
        r=requests.post(base_url()+'queue',headers={'x-api-key':key},json=p,timeout=90)
        if not r.ok:
            (folder/'submission-error.json').write_text(r.text)
            raise ValueError(f'Enhancor rejected submission ({r.status_code}): {r.text[:500]}')
        ident=r.json().get('requestId')
        if not ident:raise ValueError('Seedance did not return a request ID.')
        return ident

    def poll(self,request_id,*,folder):
        r=requests.post(base_url()+'status',headers={'x-api-key':credential('ENHANCOR_API_KEY')},json={'request_id':request_id},timeout=30);r.raise_for_status();j=r.json()
        state=j.get('status')
        if state=='COMPLETED':
            url=j.get('result')
            if not isinstance(url,str) or not url.startswith('https://'):raise ValueError('Seedance result URL missing.')
            return {'state':'done','status':'Enhancor render complete','result_url':url,'raw':j}
        if state in ['FAILED','CANCELED']:return {'state':'error','status':'Seedance failed: '+str(j.get('error') or state),'result_url':None,'raw':j}
        return {'state':'running','status':'Enhancor · '+str(state or 'pending').lower()+' · '+request_id,'result_url':None,'raw':j}

    def finalize(self,request_id,*,folder):
        """Complete the accepted draft; Enhancor reuses its original parameters (payload identical to the draft)."""
        folder=Path(folder);key=credential('ENHANCOR_API_KEY')
        original=json.loads((folder/'seedance-request.json').read_text())
        if not original.get('is_draft'):raise ValueError('A completed draft is required before generating 1080p.')
        from stages.calls import record_call
        record_call(folder,'enhancor','seedance2.5/v1/queue (draft_id)')
        payload={'draft_id':request_id,'webhook_url':original.get('webhook_url','')}
        hd=folder/'hd';hd.mkdir(exist_ok=True);(hd/'request.json').write_text(json.dumps(payload,indent=2))
        response=requests.post(base_url()+'queue',headers={'x-api-key':key},json=payload,timeout=90)
        response.raise_for_status();ident=response.json().get('requestId')
        if not ident:raise ValueError('Enhancor did not return a request ID.')
        return ident
