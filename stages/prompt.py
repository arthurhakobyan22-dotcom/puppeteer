"""Stage 7, prompt: the creative prompt sent with the draft.

`identity_only` is today's default text (`seedance_bridge.DEFAULT_PROMPT`); `text` is the user's prompt. The
provider adapter appends the @Video1/@Image rules through `providers.base.build_prompt` at submission time, so
this stage only records the base text. Its report is written when a draft is submitted (`record`).
"""
from pathlib import Path
from .base import Tool,register
from .report import new_report,write_report,now

def default_prompt():
    from seedance_bridge import DEFAULT_PROMPT
    return DEFAULT_PROMPT

class IdentityOnly(Tool):
    name='identity_only';stage='prompt';label='Identity-only prompt';description='The built-in prompt: the reference defines identity only; pose, motion, timing and lip-sync come from the prepared clip. Edit the text to change it.'
    params={'text':{'type':'string','default':None,'label':'Prompt','hint':'Shown before submission; the provider appends the reference rules.'},
            # Set / Look / Light slots (stages/slots.py), mirrored here so they travel with branches; the slots panel in the draft step edits them
            'set_mode':{'type':'choice','default':'original','choices':['original','original_depth','set_ref','prompt','true_swap'],'label':'Set','hint':'From the Set slot: keep the room, keep its depth only, a set reference image, a described set, or a true swap (set image as the background).'},
            'set_image':{'type':'string','default':'','label':'Set image','hint':'Asset name of the set plate (runs/_assets).'},
            'set_prompt':{'type':'string','default':'','label':'Set description','hint':'Words for the set when the Set slot is "prompt".'},
            'look_mode':{'type':'choice','default':'follow','choices':['follow','style_ref','prompt'],'label':'Look','hint':'From the Look slot: follow the references, a style image, or a described style.'},
            'look_image':{'type':'string','default':'','label':'Look image','hint':'Asset name of the style image (runs/_assets).'},
            'look_prompt':{'type':'string','default':'','label':'Look description','hint':'Words for the rendering style when the Look slot is "prompt".'},
            'light':{'type':'string','default':'','label':'Light','hint':'One line about the lighting (direction, quality, colour).'}}
    inputs=();outputs=('prompt.txt',)
    def defaults(self):return {'text':default_prompt()}   # only `text`: the slot keys appear in params when a slot is written, so legacy chains stay `{text}`
    def run(self,inputs,params,folder,status):
        text=params.get('text') or default_prompt();folder=Path(folder)
        (folder/'prompt.txt').write_text(text)
        return {'outputs':['prompt.txt'],'health':f'Prompt ready ({len(text.split())} words).','data':{'text':text}}

register(IdentityOnly)

def record(folder,text,full_prompt=None,mode=None):
    """Write the prompt stage report at submission time (called by seedance_bridge.submit)."""
    folder=Path(folder);report=new_report('prompt','identity_only',{'text':text},started=now())
    report.update(finished=now(),state='done',health=f'Prompt sent ({len((full_prompt or text).split())} words'+(f', {mode} mode' if mode else '')+').',outputs={},data={'text':text,'full_prompt':full_prompt,'mode':mode})
    write_report(folder,'prompt',report);return report
