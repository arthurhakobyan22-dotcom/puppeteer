"""Stage 9, finish: restore the original audio over the generated clip and, on approval, complete the draft in HD.

`restore_original_audio` wraps `audio_workflow.finish_preview`; `complete_draft` wraps `seedance_bridge.submit_hd`
plus the same restore under `hd/`. Reports are written by `record_restore` / `record_hd` from the orchestrator.
"""
from pathlib import Path
from .base import Tool,register
from .report import new_report,read_report,write_report,now
from . import costs

class RestoreOriginalAudio(Tool):
    name='restore_original_audio';stage='finish';label='Restore original audio';description='Remuxes the entire source audio over the generated clip (generated audio is discarded).'
    inputs=('seedance-result.mp4','upload.mp4');outputs=('final-preview.mp4',)
    def run(self,inputs,params,folder,status):
        import audio_workflow
        folder=Path(folder);status('Restoring entire original source audio · discarding generated audio')
        audio_workflow.finish_preview(folder/'seedance-result.mp4',folder)
        return {'outputs':['final-preview.mp4'],'health':'Final preview carries the entire original source audio.'}

class CompleteDraft(Tool):
    name='complete_draft';stage='finish';label='Complete the draft in HD';paid=True;description='Completes the approved draft at the provider\'s final resolution (fal draft/complete or Enhancor draft_id), then restores the original audio under hd/.'
    inputs=('final-preview.mp4',);outputs=('hd/request.json','hd/response.json','hd/final-preview.mp4')
    def estimate_cost(self,inputs,params):
        provider=(params or {}).get('provider') or 'fal'
        return costs.price_for(provider+'_complete',inputs.get('seconds'))
    def run(self,inputs,params,folder,status):
        import seedance_bridge
        folder=Path(folder);request_id=seedance_bridge.submit_hd(folder)
        seedance_bridge.wait_and_finish(folder/'hd',request_id,status)
        return {'outputs':[n for n in self.outputs if (folder/n).exists()],'health':f'HD version rendered ({request_id}) with the original audio restored.'}

register(RestoreOriginalAudio);register(CompleteDraft)

def record_restore(folder):
    """Finish report for the draft (called after finish_preview in seedance_bridge.wait_and_finish)."""
    folder=Path(folder)
    if folder.name=='hd':return record_hd(folder.parent,done=True)
    report=read_report(folder,'finish') or new_report('finish','restore_original_audio',{},started=now())
    if report.get('tool')!='complete_draft':
        report.update(tool='restore_original_audio',finished=now(),state='done',health='Final preview carries the entire original source audio.',outputs={'final-preview.mp4':None})
    else:report.update(data={**(report.get('data') or {}),'draft_restored':now()})
    write_report(folder,'finish',report);return report

def record_hd(folder,provider=None,request_id=None,done=False,message=None):
    """Finish report for the HD completion (submitted, done or failed)."""
    folder=Path(folder);report=read_report(folder,'finish') or new_report('finish','complete_draft',{})
    report['tool']='complete_draft'
    if request_id:
        report.update(params={'provider':provider},started=now(),state='running',health=f'HD completion submitted to {provider} ({request_id}).',cost_usd=costs.price_for((provider or 'fal')+'_complete',costs.clip_seconds(folder)) or 0.0,data={**(report.get('data') or {}),'hd_request_id':request_id})
    if done:report.update(finished=now(),state='done',health='HD version rendered with the original audio restored.',outputs={n:None for n in ('hd/request.json','hd/response.json','hd/final-preview.mp4') if (folder/n).exists()})
    if message:report.update(finished=now(),state='error',health='HD completion failed: '+str(message),error={'message':str(message),'fix':'Resume the saved HD request (workflow.py resume --hd) instead of submitting again.'})
    write_report(folder,'finish',report);return report
