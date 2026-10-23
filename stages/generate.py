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
            'char2':{'type':'string','default':'','label':'Character 2 reference','hint':'Optional image.'},
            'task':{'type':'choice','default':'auto','choices':['auto','reference','editing'],'label':'Task','hint':'auto follows the Set slot (original set → editing, anything else → reference) or FAL_TASK; Enhancor has no task setting.'}}
    inputs=('seedance-input.mp4',);outputs=('seedance-request.json','seedance-response.json','generation.json','seedance-result.mp4','final-preview.mp4')
    def normalize_params(self,params):
        merged=super().normalize_params(params)
        if merged.get('task') in (None,'','auto'):merged.pop('task',None)   # the default is dropped: legacy params {char1, char2} and their keys are unchanged
        return merged
    def estimate_cost(self,inputs,params):return costs.estimate_tool(self.name,inputs.get('seconds'),params)
    def run(self,inputs,params,folder,status):
        import seedance_bridge
        folder=Path(folder);chain=inputs.get('chain') or {}
        text=(chain.get('prompt') or {}).get('params',{}).get('text') or seedance_bridge.DEFAULT_PROMPT
        char1=folder/str(params.get('char1') or 'char1-reference.png');char2=folder/params['char2'] if params.get('char2') else None
        if not char1.exists():raise ValueError('Character 1 reference is missing; add it in the draft panel before generating.')
        task=params.get('task') if params.get('task') in ('reference','editing') else None
        request_id=seedance_bridge.submit(folder,text,char1,char2,provider=self.name,status=status,task=task)
        seedance_bridge.wait_and_finish(folder,request_id,status)
        return {'outputs':[n for n in self.outputs if (folder/n).exists()],'health':f'Draft rendered by {self.label} ({request_id}).','cost_usd':self.estimate_cost(inputs,params)}

class FalTool(SeedanceProvider):
    name='fal';label='fal · Seedance 2.5';description='480p draft via bytedance/seedance-2.5/reference-to-video; the same draft completes at 1080p.'

class EnhancorTool(SeedanceProvider):
    name='enhancor';label='Enhancor · Seedance 2.5';description='1080p draft through Enhancor (needs the callback webhook); completes via draft_id.'

class WanTool(Tool):
    """Wan 2.2 Animate (replace) on fal (providers/wan.py, docs/GENERATORS.md): the person in the prepared clip is replaced by the
    Character 1 image, pose and timing kept. One render (no draft/complete), no prompt, no task, no second reference."""
    name='wan_fal';label='Wan 2.2 Animate · replace (fal)';stage='generate';paid=True;provider='wan'
    description='Pose-native character replacement via fal-ai/wan/v2.2-14b/animate/replace: one image in, one render out (480p/580p/720p), no draft to complete.'
    params={'char1':{'type':'string','default':'char1-reference.png','label':'Character 1 reference','hint':'An image only: Wan Animate takes no identity video and no second character.'},
            'resolution':{'type':'choice','default':'480p','choices':['480p','580p','720p'],'label':'Resolution','hint':'The only render; 720p is the sharpest it offers (about twice the 480p price).'}}
    inputs=SeedanceProvider.inputs;outputs=('wan-options.json','wan-request.json','wan-result.json')+SeedanceProvider.outputs
    def estimate_cost(self,inputs,params):return costs.estimate_tool(self.name,inputs.get('seconds'),params)
    def run(self,inputs,params,folder,status):
        import seedance_bridge
        folder=Path(folder);chain=inputs.get('chain') or {}
        text=(chain.get('prompt') or {}).get('params',{}).get('text') or seedance_bridge.DEFAULT_PROMPT   # kept in generation.json for the record; the endpoint takes no prompt
        char1=folder/str(params.get('char1') or 'char1-reference.png')
        if not char1.exists():raise ValueError('Character 1 reference is missing; add it in the draft panel before generating.')
        write_wan_options(folder,params.get('resolution'))
        request_id=seedance_bridge.submit(folder,text,char1,None,provider=self.provider,status=status)
        seedance_bridge.wait_and_finish(folder,request_id,status)
        return {'outputs':[n for n in self.outputs if (folder/n).exists()],'health':f'Rendered by {self.label} ({request_id}); the first render is the final.','cost_usd':self.estimate_cost(inputs,params)}

register(FalTool);register(EnhancorTool);register(WanTool)
TOOL_FOR_PROVIDER={'wan':'wan_fal'}   # generate tool per provider name when they differ (the report's `tool` is the registry name)

def write_wan_options(folder,resolution=None):
    """`<run>/wan-options.json` {"resolution"} for providers.wan: the explicit value, else the slots' generator.resolution, else 480p."""
    from .base import fresh
    from .slots import read as read_slots
    from providers.wan import RESOLUTIONS,DEFAULT_RESOLUTION
    folder=Path(folder);value=str(resolution or '').strip().lower()
    if not value:
        try:value=str((read_slots(folder).get('generator') or {}).get('resolution') or '').strip().lower()
        except Exception:value=''
    if value not in RESOLUTIONS:value=DEFAULT_RESOLUTION
    path=folder/'wan-options.json';fresh(path);path.write_text(json.dumps({'resolution':value}))
    return value

def record_submission(folder,provider,request_id,prompt=None,mode=None,task=None):
    """Write the generate report when a draft is submitted (called by seedance_bridge.submit). `task`: the Seedance task sent
    (reference | editing | …), or 'not applicable' for a provider without one (Enhancor, Wan)."""
    folder=Path(folder);seconds=costs.clip_seconds(folder)
    report=new_report('generate',TOOL_FOR_PROVIDER.get(provider,provider),{'provider':provider,**({'task':task} if task else {})},started=now())
    report.update(state='running',health=f'Draft submitted to {provider} ({request_id}); waiting for the render.',cost_usd=costs.price_for(provider,seconds) or 0.0,
                  outputs={n:None for n in ('seedance-request.json','seedance-response.json','generation.json') if (folder/n).exists()},data={'request_id':request_id,'mode':mode,'prompt':prompt,'task':task})
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
