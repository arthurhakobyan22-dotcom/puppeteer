"""Chains and presets.

A chain is `{stage: {'tool': name, 'params': {...}}}` for every stage. The three legacy modes map to chains
(`chain_for_mode`) and back (`mode_for_chain`, so `workflow-mode.json` and the review fingerprint keep working).
`presets.json` at the project root holds the four built-ins plus user-saved presets (`save_preset`).
"""
from pathlib import Path
import json,copy,threading
from config import ROOT
from .base import STAGES,get_tool

PRESETS_FILE=ROOT/'presets.json'
_lock=threading.Lock()
MODES=('depth','face_mesh','depth_mesh','original')
MODE_LABELS={'depth':'Advanced · Depth + SAM','face_mesh':'Fast · Face mesh','depth_mesh':'Advanced + Face mesh','original':'Original video only'}

def chain_for_mode(mode,prompt='person',provider='replicate',clean_dialogue=False,prompt_text=None,generator=None):
    """The chain a legacy mode runs: identical tools and parameters to today's pipeline."""
    from .depth import BY_PROVIDER
    if mode not in MODES:raise ValueError('Unknown workflow mode')
    depth_tool=BY_PROVIDER.get(provider,'depth_anything_replicate')   # unknown providers fell back to the default model before as well
    depth_on=mode in ('depth','depth_mesh');mesh_on=mode in ('face_mesh','depth_mesh')
    chain={'input_doctor':{'tool':'doctor','params':{}},   # the input doctor (checks + safe fixes) is the default; `probe` stays available
           'audio':{'tool':'clean_dialogue' if clean_dialogue else 'original','params':{}},
           'depth':{'tool':depth_tool if depth_on else 'off','params':{}},
           'mask':{'tool':'sam3_replicate' if depth_on else 'off','params':{'prompt':prompt} if depth_on else {}},
           'composite':{'tool':'depth_cutout' if depth_on else 'original','params':{}},
           'face':{'tool':'mediapipe_mesh' if mesh_on else 'off','params':{'strict':mode=='face_mesh','pad':1.8,'max_gap':6} if mesh_on else {}},
           'prompt':{'tool':'identity_only','params':{'text':prompt_text} if prompt_text else {}},
           'generate':{'tool':generator or 'fal','params':{}},
           'finish':{'tool':'restore_original_audio','params':{}}}
    return normalize_chain(chain)

def normalize_chain(chain):
    """Every stage present, tools known, params filled with their defaults (so cache keys are stable)."""
    out={}
    for stage in STAGES:
        entry=dict((chain or {}).get(stage) or {})
        tool_name=entry.get('tool') or ('off' if stage in ('depth','mask') else {'input_doctor':'probe','audio':'original','composite':'original','face':'off','prompt':'identity_only','generate':'fal','finish':'restore_original_audio'}[stage])
        tool=get_tool(stage,tool_name)
        out[stage]={'tool':tool.name,'params':tool.normalize_params(entry.get('params') or {})}
    return out

def mode_for_chain(chain):
    depth_on=(chain.get('depth') or {}).get('tool','off')!='off' or (chain.get('composite') or {}).get('tool')=='depth_cutout'
    mesh_on=(chain.get('face') or {}).get('tool','off')!='off'
    return 'depth_mesh' if depth_on and mesh_on else 'depth' if depth_on else 'face_mesh' if mesh_on else 'original'

def legacy_provider(chain):
    from .depth import PROVIDER_OF
    return PROVIDER_OF.get((chain.get('depth') or {}).get('tool'),'replicate')

def paid_stages(chain):
    return [stage for stage in STAGES if get_tool(stage,chain[stage]['tool']).paid]

def describe_chain(chain):
    """One plain line per stage, e.g. 'mask: sam3_replicate (prompt: person, hands)'."""
    parts=[]
    for stage in STAGES:
        entry=chain.get(stage) or {};params=entry.get('params') or {}
        shown=', '.join(f'{k}: {v}' for k,v in params.items() if v not in (None,'',[],{}) and not (stage=='prompt'))
        parts.append(f"{stage}: {entry.get('tool','off')}"+(f' ({shown})' if shown else ''))
    return parts

BUILTIN=[
    {'name':'Talking head','description':'Fast: the face mesh drawn on the original video, no depth or SAM calls (free preparation).','mode':'face_mesh','builtin':True},
    {'name':'Full body','description':'Advanced: Depth Anything plus a SAM 3 cutout of the subject; full mask review.','mode':'depth','builtin':True},
    {'name':'Expressive','description':'Advanced + Face mesh: the depth cutout with facial motion drawn on top; gaps only warn.','mode':'depth_mesh','builtin':True},
    {'name':'Profile-heavy','description':'Advanced with the face mesh off: best when the speaker turns away from the camera a lot.','mode':'depth','builtin':True},
]

def builtin_presets():
    out=[]
    for preset in BUILTIN:
        chain=chain_for_mode(preset['mode'])
        out.append({**preset,'chain':chain,'summary':describe_chain(chain)})
    return out

def _read_file():
    try:data=json.loads(PRESETS_FILE.read_text())
    except (OSError,ValueError):return []
    return [p for p in data.get('presets',[]) if isinstance(p,dict) and p.get('name') and not p.get('builtin')]

def list_presets():
    """Built-ins first (always current), then the user-saved presets from presets.json."""
    saved=[]
    for preset in _read_file():
        try:chain=normalize_chain(preset.get('chain') or {})
        except ValueError:continue
        saved.append({'name':preset['name'],'description':preset.get('description',''),'mode':mode_for_chain(chain),'builtin':False,'chain':chain,'summary':describe_chain(chain),'source_run':preset.get('source_run'),'created':preset.get('created')})
    return builtin_presets()+saved

def get_preset(name):
    wanted=str(name).strip().lower()
    for preset in list_presets():
        if preset['name'].lower()==wanted:return preset
    raise ValueError(f'No preset named {name!r}; choose one of: '+', '.join(p['name'] for p in list_presets()))

def save_preset(name,description,chain,source_run=None):
    from .report import now
    name=str(name).strip()
    if not name:raise ValueError('Give the preset a name.')
    if any(p['name'].lower()==name.lower() for p in builtin_presets()):raise ValueError(f'{name!r} is a built-in preset; choose another name.')
    chain=normalize_chain(chain)
    entry={'name':name,'description':str(description or '').strip(),'chain':chain,'source_run':source_run,'created':now(),'builtin':False}
    with _lock:
        saved=[p for p in _read_file() if p['name'].lower()!=name.lower()]+[entry]
        write_file(saved)
    return {**entry,'mode':mode_for_chain(chain),'summary':describe_chain(chain)}

def write_file(saved):
    data={'note':'Built-in presets are defined in stages/presets.py and listed here for reference; everything under "presets" with builtin: false was saved from a run.',
          'builtin':[{'name':p['name'],'description':p['description'],'mode':p['mode']} for p in BUILTIN],'presets':saved}
    PRESETS_FILE.write_text(json.dumps(data,indent=1,ensure_ascii=False))

def ensure_file():
    if not PRESETS_FILE.exists():
        try:write_file([])
        except OSError:pass
