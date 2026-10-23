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
    params={'text':{'type':'string','default':None,'label':'Prompt','hint':'Shown before submission; the provider appends the reference rules.'}}
    inputs=();outputs=('prompt.txt',)
    def defaults(self):return {'text':default_prompt()}
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
