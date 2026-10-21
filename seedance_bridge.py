"""Thin orchestrator: guards, provider dispatch, persisted job files, polling and original-audio restore.

Files in a run folder: `seedance-request.json` (payload, no secrets, written by the adapter),
`seedance-response.json` {'requestId','provider','endpoint'?}, `generation.json`
{'request_id','provider','prompt','mode','video','draft_id'?}, `provider-status.json` while polling,
`hd/request.json` + `hd/response.json` for the finalize request.
"""
from pathlib import Path
import json,time,shutil
from audio_workflow import finish_preview
from providers import get_provider,default_provider,PROVIDERS
from providers.base import build_prompt,download_result

DEFAULT_PROMPT="@Image1 defines the character's identity only (face, hair, outfit, proportions); do not copy its pose, expression, props, background or lighting. Pose, motion, timing and lip-sync come from @Video1."

def provider_for(folder):
    """Provider name saved with the request in this folder (hd folders carry their own response.json); legacy runs are Enhancor."""
    folder=Path(folder)
    for name in (['response.json'] if folder.name=='hd' else [])+['seedance-response.json','generation.json']:
        path=folder/name
        if not path.exists():continue
        try:saved=json.loads(path.read_text()).get('provider')
        except (ValueError,AttributeError):continue
        if saved in PROVIDERS:return saved
    return 'enhancor'

def submit(folder,prompt,char1,char2=None,provider=None,status=print):
    folder=Path(folder)
    from mask_review import require_approved,is_mesh
    require_approved(folder)
    if (folder/'seedance-response.json').exists():raise ValueError('This job already has a provider response. Resume it; prepare a new job for a deliberate variation.')
    if not (folder/'audio-manifest.json').exists():raise ValueError('Audio preparation must complete before submission.')
    name=provider or default_provider()
    if name not in PROVIDERS:raise ValueError(f'Unknown provider {name!r}; choose one of: '+', '.join(PROVIDERS))
    adapter=get_provider(name);adapter.require_configured()
    from audio_workflow import prepare_seedance_video
    clean_dialogue=bool(json.loads((folder/'audio-manifest.json').read_text() or '{}').get('clean_dialogue'))
    prepared=folder/'seedance-input.mp4'
    if not is_mesh(folder) and not prepared.exists():
        status('Embedding audio in the prepared video');prepared=prepare_seedance_video(folder,clean_dialogue)
    refs={'char1':Path(char1),'char2':Path(char2) if char2 else None}
    full_prompt,mode=build_prompt(prompt,folder,refs)
    ident=adapter.submit_draft(prepared,refs,prompt,folder=folder,status=status)
    response={'requestId':ident,'provider':name}
    if adapter.draft_endpoint:response['endpoint']=adapter.draft_endpoint
    (folder/'seedance-response.json').write_text(json.dumps(response))
    (folder/'generation.json').write_text(json.dumps({'request_id':ident,'provider':name,'prompt':full_prompt,'mode':mode,'video':'seedance-result.mp4'}))
    status('Seedance draft submitted: '+ident)
    return ident

def wait_and_finish(folder,request_id,status=print):
    """Poll the saved provider every 10 s; on completion download the clip and restore the original audio."""
    folder=Path(folder);adapter=get_provider(provider_for(folder))
    for _ in range(360):
        state=adapter.poll(request_id,folder=folder)
        (folder/'provider-status.json').write_text(json.dumps(state,indent=2,default=str))
        if state.get('state')=='done':
            download_result(state.get('result_url'),folder)
            generation=folder/'generation.json'
            if generation.exists() and state.get('draft_id') is not None:
                data=json.loads(generation.read_text());data['draft_id']=state['draft_id'];generation.write_text(json.dumps(data))
            status('Restoring entire original source audio · discarding generated audio')
            finish_preview(folder/'seedance-result.mp4',folder)
            return
        if state.get('state')=='error':raise RuntimeError(state.get('status') or 'Seedance failed')
        if state.get('status'):status(state['status'])
        time.sleep(10)
    raise TimeoutError('Seedance is still pending. Request ID saved; do not resubmit automatically.')

def submit_hd(folder):
    """Complete the accepted draft at the provider's final resolution; never resubmits an existing HD request."""
    folder=Path(folder)
    if (folder/'hd/response.json').exists():raise ValueError('HD already submitted. Resume its saved request.')
    if not (folder/'final-preview.mp4').exists():raise ValueError('A completed draft is required before generating the final resolution.')
    generation=json.loads((folder/'generation.json').read_text())
    name=provider_for(folder);adapter=get_provider(name)
    if not adapter.capabilities().get('finalize'):raise ValueError(adapter.label+' cannot complete drafts.')
    hd=folder/'hd';hd.mkdir(exist_ok=True)
    # Keep the draft intact and use the exact source audio for the HD export.
    source=hd/'upload.mp4'
    if not source.exists():shutil.copy2(folder/'upload.mp4',source)
    ident=adapter.finalize(generation['request_id'],folder=folder)
    response={'requestId':ident,'provider':name}
    if adapter.final_endpoint:response['endpoint']=adapter.final_endpoint
    (hd/'response.json').write_text(json.dumps(response))
    return ident
