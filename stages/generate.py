"""Stage 8, generate: the Seedance draft through fal or Enhancor (`seedance_bridge.submit` + `wait_and_finish`).

The two tools wrap the existing adapters unchanged. The stage report is written by `record_submission` when the
draft is submitted (from `seedance_bridge.submit`) and completed by `record_result` when the clip arrives.
"""
from pathlib import Path
import json
from .base import Tool,register
from .report import new_report,read_report,write_report,now
from . import costs

class SeedanceProvider(Tool):
    stage='generate';paid=True
    params={'char1':{'type':'string','default':'char1-reference.png','label':'Character 1 reference','hint':'Image, or an identity video for Character 1 only.'},
            'char2':{'type':'string','default':'','label':'Character 2 reference','hint':'Optional image.'}}
    inputs=('seedance-input.mp4',);outputs=('seedance-request.json','seedance-response.json','generation.json','seedance-result.mp4','final-preview.mp4')
    def estimate_cost(self,inputs,params):return costs.estimate_tool(self.name,inputs.get('seconds'),params)
    def run(self,inputs,params,folder,status):
        import seedance_bridge
        folder=Path(folder);chain=inputs.get('chain') or {}
        text=(chain.get('prompt') or {}).get('params',{}).get('text') or seedance_bridge.DEFAULT_PROMPT
        char1=folder/str(params.get('char1') or 'char1-reference.png');char2=folder/params['char2'] if params.get('char2') else None
        if not char1.exists():raise ValueError('Character 1 reference is missing; add it in the draft panel before generating.')
        request_id=seedance_bridge.submit(folder,text,char1,char2,provider=self.name,status=status)
        seedance_bridge.wait_and_finish(folder,request_id,status)
        return {'outputs':[n for n in self.outputs if (folder/n).exists()],'health':f'Draft rendered by {self.label} ({request_id}).','cost_usd':self.estimate_cost(inputs,params)}

class FalTool(SeedanceProvider):
    name='fal';label='fal · Seedance 2.5';description='480p draft via bytedance/seedance-2.5/reference-to-video; the same draft completes at 1080p.'

class EnhancorTool(SeedanceProvider):
    name='enhancor';label='Enhancor · Seedance 2.5';description='1080p draft through Enhancor (needs the callback webhook); completes via draft_id.'

register(FalTool);register(EnhancorTool)

def record_submission(folder,provider,request_id,prompt=None,mode=None):
    """Write the generate report when a draft is submitted (called by seedance_bridge.submit)."""
    folder=Path(folder);seconds=costs.clip_seconds(folder)
    report=new_report('generate',provider,{'provider':provider},started=now())
    report.update(state='running',health=f'Draft submitted to {provider} ({request_id}); waiting for the render.',cost_usd=costs.price_for(provider,seconds) or 0.0,
                  outputs={n:None for n in ('seedance-request.json','seedance-response.json','generation.json') if (folder/n).exists()},data={'request_id':request_id,'mode':mode,'prompt':prompt})
    write_report(folder,'generate',report);return report

def record_result(folder,ok=True,message=None):
    """Complete the generate report once the draft clip is downloaded (or failed)."""
    folder=Path(folder);report=read_report(folder,'generate') or new_report('generate','unknown',{})
    report.update(finished=now(),state='done' if ok else 'error')
    if ok:
        report['health']='Draft rendered'+(f" by {report.get('tool')}" if report.get('tool') else '')+'; original audio restored over it.'
        report['outputs']={n:None for n in ('seedance-request.json','seedance-response.json','generation.json','seedance-result.mp4','final-preview.mp4') if (folder/n).exists()}
    else:report['health']='The draft failed: '+str(message or 'unknown reason');report['error']={'message':str(message or 'unknown reason'),'fix':'Check the provider status in provider-status.json and resume the saved request instead of resubmitting.'}
    write_report(folder,'generate',report);return report
