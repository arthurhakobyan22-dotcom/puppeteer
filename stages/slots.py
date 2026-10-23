"""Set, Look and Light slots: what the generation should show, stored per run in `slots.json` (World stage, Agent 1).

{"version":1,
 "set":{"mode":"original|original_depth|set_ref|prompt|true_swap","image":"<asset name>|null","prompt":"","fit":{}},
 "look":{"mode":"follow|style_ref|prompt","image":"<asset name>|null","prompt":""},
 "light":"",
 "generator":{"name":"fal|enhancor|…","task":"auto|reference|editing","resolution":null},
 "updated":"<iso>"}

Writing a slot never re-runs anything and never creates a branch. `write()` calls `fresh()` on `slots.json` and `run.json`
first so a hard-linked copy of a run never writes through into the run it was copied from, then mirrors the slots into
`run.json` as `slots` and into `chain.prompt.params` as flat keys (`set_mode`, `set_image`, `set_prompt`, `look_mode`,
`look_image`, `look_prompt`, `light`) so they travel with branches. `task_for(slots)` derives the Seedance task from the set
mode (`original` → editing, anything else → reference); `generator.task` = `auto` means "use the derived one", an explicit
value overrides it until the set mode changes again (`write()` resets it to `auto` then). Agent 2's prompt builder reads
these; Agent 3's generator picker writes `generator`.
"""
from pathlib import Path
import json
from .base import fresh
from .report import now

SET_MODES=('original','original_depth','set_ref','prompt','true_swap')
LOOK_MODES=('follow','style_ref','prompt')
TASKS=('auto','reference','editing')
FLAT_KEYS=('set_mode','set_image','set_prompt','look_mode','look_image','look_prompt','light')
BACKGROUND_FOR={'original_depth':'full_depth','true_swap':'set_image'}   # set modes that need a composite branch, and the Background they map to
MAX_TEXT=4000

class SlotError(ValueError):
    def __init__(self,message,fix,status=400):super().__init__(message);self.fix=fix;self.status=status

def defaults():
    return {'version':1,'set':{'mode':'original','image':None,'prompt':'','fit':{}},'look':{'mode':'follow','image':None,'prompt':''},'light':'',
            'generator':{'name':None,'task':'auto','resolution':None},'updated':None}

def task_for(slots):
    """The Seedance task the set mode implies: keep the room → editing; any other set → reference."""
    return 'editing' if ((slots or {}).get('set') or {}).get('mode','original')=='original' else 'reference'

def effective_task(slots):
    """What is sent: the explicit generator.task when it is reference / editing, else the derived one."""
    task=((slots or {}).get('generator') or {}).get('task') or 'auto'
    return task if task in ('reference','editing') else task_for(slots)

def read(folder):
    """slots.json merged over the defaults; without the file, what run.json carries (`slots`, else the flat keys a branch
    inherited in chain.prompt.params and chain.generate.params.task); else the defaults alone."""
    base=defaults();folder=Path(folder);path=folder/'slots.json'
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):data=None
    if isinstance(data,dict):return merge(base,data)
    from .runner import load_run
    run=load_run(folder) or {}
    if isinstance(run.get('slots'),dict):return merge(base,run['slots'])
    return merge(base,unflat(run.get('chain') or {}))

def unflat(chain):
    """Slots rebuilt from a chain's flat prompt keys (a branch inherits them from its parent); {} when there are none."""
    params=((chain.get('prompt') or {}).get('params') or {});task=((chain.get('generate') or {}).get('params') or {}).get('task')
    if not any(k in params for k in FLAT_KEYS) and not task:return {}
    return {'set':{'mode':params.get('set_mode') or 'original','image':params.get('set_image') or None,'prompt':params.get('set_prompt') or ''},
            'look':{'mode':params.get('look_mode') or 'follow','image':params.get('look_image') or None,'prompt':params.get('look_prompt') or ''},
            'light':params.get('light') or '','generator':{'task':task if task in TASKS else 'auto'}}

def merge(base,patch):
    out=json.loads(json.dumps(base))
    for key,value in (patch or {}).items():
        if key in ('set','look','generator') and isinstance(value,dict):out[key]={**out.get(key,{}),**value}
        elif key in out or key in ('light','updated','version'):out[key]=value
    return out

def _asset(value,what):
    from .plates import NAME
    if value in (None,'','null'):return None
    if not NAME.match(str(value)):raise SlotError(f'The {what} image is not an asset name.','Upload the image with the picker (it is stored as <16 hex>.<ext>) and choose it there.')
    return str(value)

def _text(value,what):
    text=str(value if value is not None else '')
    if len(text)>MAX_TEXT:raise SlotError(f'The {what} text is longer than {MAX_TEXT} characters.','Shorten it; the prompt builder adds the rules for you.')
    return text

def validate(slots):
    """Modes, asset names and text lengths checked; returns the cleaned slots or raises SlotError with a plain sentence."""
    s=merge(defaults(),slots);set_=s['set'];look=s['look'];gen=s['generator']
    if set_.get('mode') not in SET_MODES:raise SlotError(f'Unknown set mode {set_.get("mode")!r}.','Choose one of: '+', '.join(SET_MODES)+'.')
    if look.get('mode') not in LOOK_MODES:raise SlotError(f'Unknown look mode {look.get("mode")!r}.','Choose one of: '+', '.join(LOOK_MODES)+'.')
    if gen.get('task') not in TASKS:raise SlotError(f'Unknown task {gen.get("task")!r}.','Choose one of: '+', '.join(TASKS)+' (auto follows the set mode).')
    set_['image']=_asset(set_.get('image'),'set');look['image']=_asset(look.get('image'),'look')
    set_['prompt']=_text(set_.get('prompt'),'set');look['prompt']=_text(look.get('prompt'),'look');s['light']=_text(s.get('light'),'light')
    from .plates import parse_fit,fit_is_default
    set_['fit']={} if fit_is_default(set_.get('fit') or {}) else parse_fit(set_.get('fit'))
    gen['name']=str(gen['name']) if gen.get('name') else None
    gen['resolution']=str(gen['resolution']) if gen.get('resolution') else None
    s['version']=1
    return s

def flat(slots):
    """The flat keys mirrored into chain.prompt.params."""
    s=merge(defaults(),slots)
    return {'set_mode':s['set']['mode'],'set_image':s['set'].get('image') or '','set_prompt':s['set'].get('prompt') or '','look_mode':s['look']['mode'],'look_image':s['look'].get('image') or '','look_prompt':s['look'].get('prompt') or '','light':s.get('light') or ''}

def write(folder,patch):
    """Merge `patch` into the run's slots, validate, save slots.json and mirror into run.json (when the run has one). Returns the slots."""
    folder=Path(folder);current=read(folder);patch=patch or {}
    if not isinstance(patch,dict):raise SlotError('The slots must be a JSON object.','Send {"set": {"mode": "prompt"}} and the like.')
    merged=merge(current,patch)
    new_mode=(merged.get('set') or {}).get('mode');old_mode=(current.get('set') or {}).get('mode')
    if new_mode!=old_mode and 'task' not in ((patch.get('generator') or {}) if isinstance(patch.get('generator'),dict) else {}):merged['generator']['task']='auto'   # the derived task applies again
    slots=validate(merged);slots['updated']=now()
    path=folder/'slots.json';fresh(path);path.write_text(json.dumps(slots,indent=1,ensure_ascii=False))
    mirror(folder,slots)
    return slots

def mirror(folder,slots):
    """run.json gets `slots` and the flat keys in chain.prompt.params; nothing is written when the run has no run.json (legacy runs are reconstructed in memory)."""
    from .runner import load_run
    folder=Path(folder);run=load_run(folder)
    if run is None:return False
    run['slots']=slots;chain=run.setdefault('chain',{});prompt=chain.setdefault('prompt',{'tool':'identity_only','params':{},'key':None,'cached_from':None})
    prompt['params']={**(prompt.get('params') or {}),**flat(slots)}
    fresh(folder/'run.json');(folder/'run.json').write_text(json.dumps(run,indent=1,ensure_ascii=False,default=str))
    return True

def view(folder,chain=None):
    """What GET /jobs/{id}/slots answers: the slots plus the effective task and how it was chosen."""
    from .composite import background_of
    slots=read(folder);task=effective_task(slots);derived=task_for(slots)
    background,label=background_of(chain or {})
    needed=BACKGROUND_FOR.get(slots['set']['mode']);plate=(((chain or {}).get('composite') or {}).get('params') or {}).get('set_image') or None
    applied=needed is None or (background==needed and (needed!='set_image' or plate==slots['set'].get('image')))
    return {**slots,'task':task,'task_source':'set' if (slots['generator'].get('task') or 'auto')=='auto' else 'user','derived_task':derived,'file':(Path(folder)/'slots.json').exists(),
            'background':background,'background_label':label,'background_needed':needed,'background_applied':applied}
