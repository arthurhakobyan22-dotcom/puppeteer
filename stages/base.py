"""Stage rack: the stage order, the Tool interface and the registry of interchangeable tools per stage.

A stage is one step of the pipeline; a tool is one implementation of it. Tools are registered at import time
by the per-stage modules (`stages/<stage>.py`). Every tool has the same interface:

    run(inputs, params, folder, status) -> {'outputs': {...}, 'frames': {...}, 'gaps': [...], 'warnings': [...], 'health': str, ...}

The runner (`stages/runner.py`) turns that into `runs/<id>/stages/<stage>/report.json`.
"""
from pathlib import Path
import shutil

STAGES=['input_doctor','audio','depth','mask','composite','face','prompt','generate','finish']
PREP_STAGES=STAGES[:6]            # run automatically by the preparation chain
GENERATION_STAGES=STAGES[6:]      # recorded when the user submits, completes or finalizes a draft
LABELS={'input_doctor':'Input check','audio':'Audio','depth':'Depth','mask':'Mask','composite':'Composite','face':'Face mesh','prompt':'Prompt','generate':'Generate','finish':'Finish'}
REGISTRY={stage:{} for stage in STAGES}

class Tool:
    name=''                  # registry key, e.g. "sam3_replicate"
    stage=''                 # "mask"
    label=''                 # plain words for the UI: "SAM 3 on Replicate"
    paid=False
    experimental=False
    description=''           # one plain sentence for the UI
    params={}                # name -> {'type': 'bool'|'number'|'string'|'choice', 'default': ..., 'label': ..., 'choices': [...]}
    outputs=()               # artifact names (files or folders) this tool writes into the run folder
    inputs=()                # artifact names whose sha256 goes into the cache key (missing ones are skipped)

    def defaults(self):
        return {name:spec.get('default') for name,spec in self.params.items()}

    def normalize_params(self,params):
        """Defaults filled in, values coerced to the declared type, unknown keys kept as given."""
        merged=self.defaults();params=params or {}
        for key,value in params.items():
            spec=self.params.get(key)
            if spec is None:merged[key]=value;continue
            merged[key]=coerce(value,spec)
        return merged

    def estimate_cost(self,inputs,params):
        """USD before running, or None when the tool is free or the cost cannot be estimated."""
        if not self.paid:return 0.0
        from . import costs
        return costs.estimate_tool(self.name,inputs.get('seconds'),params)

    def run(self,inputs,params,folder,status):
        raise NotImplementedError

    def describe(self):
        return {'name':self.name,'stage':self.stage,'label':self.label,'paid':self.paid,'experimental':self.experimental,'description':self.description,
                'params':{k:{**v,'default':v.get('default')} for k,v in self.params.items()},'outputs':list(self.outputs),'inputs':list(self.inputs)}

class OffTool(Tool):
    """A stage that is switched off writes a report with tool "off" and produces nothing."""
    name='off';label='Off';description='This stage is skipped.'
    def __init__(self,stage):self.stage=stage
    def run(self,inputs,params,folder,status):return {'outputs':{},'health':LABELS.get(self.stage,self.stage)+' is off.'}

def coerce(value,spec):
    kind=spec.get('type','string')
    if value is None:return spec.get('default')
    if kind=='bool':
        if isinstance(value,str):return value.strip().lower() in ('1','true','on','yes')
        return bool(value)
    if kind=='number':
        try:
            number=float(value)
            return int(number) if number==int(number) and isinstance(spec.get('default'),int) else number
        except (TypeError,ValueError):return spec.get('default')
    if kind=='choice':
        return value if value in spec.get('choices',[]) else spec.get('default')
    return str(value)

def register(tool):
    """Register a Tool instance (or class, instantiated without arguments) under its stage."""
    if isinstance(tool,type):tool=tool()
    if tool.stage not in REGISTRY:raise ValueError(f'Unknown stage {tool.stage!r}; stages are: '+', '.join(STAGES))
    REGISTRY[tool.stage][tool.name]=tool
    return tool

def allow_off(stage):
    """Stages that may be switched off register an `off` tool."""
    return register(OffTool(stage))

def get_tool(stage,name):
    if stage not in REGISTRY:raise ValueError(f'Unknown stage {stage!r}; stages are: '+', '.join(STAGES))
    tool=REGISTRY[stage].get(name)
    if tool is None:raise ValueError(f'Unknown tool {name!r} for stage {stage!r}; choose one of: '+', '.join(REGISTRY[stage]) )
    return tool

def tools_for(stage):
    if stage not in REGISTRY:raise ValueError(f'Unknown stage {stage!r}; stages are: '+', '.join(STAGES))
    return list(REGISTRY[stage].values())

def registry():
    """Stage order plus every tool's description, for `GET /stages` and the UI dropdowns."""
    return {'stages':[{'name':s,'label':LABELS[s],'automatic':s in PREP_STAGES,'tools':[t.describe() for t in tools_for(s)]} for s in STAGES]}

def fresh(path):
    """Make `path` safe to (re)write inside a branch: drop a hard link shared with another run, or an old folder.

    Removing a directory entry never touches the other run's data; writing through a shared link would."""
    path=Path(path)
    if path.is_dir() and not path.is_symlink():shutil.rmtree(path,ignore_errors=True);return
    try:
        if path.exists() and path.stat().st_nlink>1:path.unlink()
    except OSError:pass

def artifact(folder,name):
    return Path(folder)/name
