"""Branching: change one stage of a run and get a child run, never overwriting the parent.

`branch(parent, stage, tool, params)` creates `runs/<new id>/` with `run.json.parent = <parent id>`, hard-links
(fallback: copies) every artifact of the stages before `stage` from the parent, copies their reports with
`cached_from`, and records `changed` as one plain line. The parent folder is never written to. The caller then
runs the child from `stage` with `runner.run_chain(child, chain, from_stage=stage)`.
"""
from pathlib import Path
import copy,json,shutil,uuid
from .base import STAGES,PREP_STAGES,get_tool
from .report import write_report,now
from .runner import load_run,new_run,save_run,link_artifact,log
from .presets import normalize_chain,mode_for_chain,describe_chain
from . import cache

COPY_NOT_LINK={'audio-manifest.json'}   # rewritten in place by later steps, so the child needs its own copy
CARRY=['words.json','mouth-guidance.json','subtitles.json']   # non-stage artifacts a child inherits when the parent has them (Agent 4 extends); a writer calls fresh() first

def parent_state(parent):
    """The parent's run.json and reports, reconstructed in memory for legacy runs (the parent is never written)."""
    from .migrate import reconstruct
    parent=Path(parent);run=load_run(parent)
    if run is None:return reconstruct(parent,with_keys=True,write=False)
    from .report import all_reports
    return run,all_reports(parent)

HIDDEN_PARAMS=('base_run',)

def shown_value(key,value):
    """A param value in words: booleans lower-case, lists of clicks or strokes summarised, never raw JSON."""
    if isinstance(value,bool):return str(value).lower()
    if isinstance(value,str) and value.lstrip().startswith(('[','{')):
        try:value=json.loads(value)
        except ValueError:return value
    if isinstance(value,list):
        if key=='edits':
            frames=sorted({int(e.get('frame',0)) for e in value if isinstance(e,dict)});inc=sum(1 for e in value if isinstance(e,dict) and int(e.get('label',1))==1);exc=len(value)-inc
            where=('frame '+str(frames[0])) if len(frames)==1 else (f'frames {frames[0]}–{frames[-1]}' if frames else 'the clip')
            return f'{len(value)} click{"s" if len(value)!=1 else ""} on {where} ({inc} include, {exc} exclude)'
        if key=='strokes':
            lo=min((int(s.get('frame_from',0)) for s in value if isinstance(s,dict)),default=0);hi=max((int(s.get('frame_to',s.get('frame_from',0))) for s in value if isinstance(s,dict)),default=lo)
            return f'{len(value)} brush stroke{"s" if len(value)!=1 else ""} on frames {lo}–{hi}'
        return f'{len(value)} items'
    if isinstance(value,dict):return f'{len(value)} settings'
    return value

def shown_params(params):
    return ', '.join(f'{k}: {shown_value(k,v)}' for k,v in (params or {}).items() if v not in (None,'',[],{}) and k not in HIDDEN_PARAMS)

def describe_change(stage,old,new):
    """One plain line: 'face: mediapipe_mesh (strict: false) → off' or 'face: mediapipe_mesh strict: false → true'."""
    old_tool,new_tool=old.get('tool','off'),new.get('tool','off');old_params,new_params=old.get('params') or {},new.get('params') or {}
    if old_tool!=new_tool:
        return f'{stage}: {old_tool}'+(f' ({shown_params(old_params)})' if shown_params(old_params) else '')+f' → {new_tool}'+(f' ({shown_params(new_params)})' if shown_params(new_params) else '')
    diffs=[f'{k}: {shown_value(k,old_params.get(k))} → {shown_value(k,v)}' for k,v in new_params.items() if old_params.get(k)!=v and k not in HIDDEN_PARAMS]
    return f'{stage}: {new_tool} '+(', '.join(diffs) if diffs else 'run again with the same settings')

def changed_chain(run_chain,stage,tool=None,params=None):
    """The chain of a would-be branch plus its one-line `changed` text; no files are touched."""
    if stage not in STAGES:raise ValueError(f'Unknown stage {stage!r}; stages are: '+', '.join(STAGES))
    chain={s:{'tool':((run_chain or {}).get(s) or {}).get('tool','off'),'params':dict(((run_chain or {}).get(s) or {}).get('params') or {})} for s in STAGES}
    chain=normalize_chain(chain);old=copy.deepcopy(chain[stage])
    new_tool=get_tool(stage,tool or old['tool'])
    base=old['params'] if new_tool.name==old['tool'] else {}
    chain[stage]={'tool':new_tool.name,'params':new_tool.normalize_params({**base,**(params or {})})}
    return chain,describe_change(stage,old,chain[stage])

def also_chain(chain,stage,changed,also):
    """Apply the extra stage changes of a multi-stage branch on top of `chain`; every one must come after `stage`."""
    lines=[changed]
    for other,entry in (also or {}).items():
        if other not in STAGES:raise ValueError(f'Unknown stage {other!r}; stages are: '+', '.join(STAGES))
        if STAGES.index(other)<=STAGES.index(stage):raise ValueError(f'The {other} change must come after the {stage} stage; branch at the earliest stage that changes.')
        entry=entry or {};chain,line=changed_chain(chain,other,entry.get('tool'),entry.get('params'));lines.append(line)
    return chain,' · '.join(lines)

def branch(parent,stage,tool=None,params=None,runs_root=None,preset=None,also=None):
    """Create the child folder and its run.json; returns (child_folder, chain, changed). Nothing runs yet.
    `also` = {later_stage: {tool, params}, …} changes more stages in the same child (one branch); `changed` lists all."""
    parent=Path(parent);runs_root=Path(runs_root) if runs_root else parent.parent
    run,reports=parent_state(parent)
    chain,changed=changed_chain(run['chain'],stage,tool,params)
    if also:chain,changed=also_chain(chain,stage,changed,also)
    ident=uuid.uuid4().hex;child=runs_root/ident;child.mkdir(parents=True)
    if (parent/'upload.mp4').exists():link_artifact(parent/'upload.mp4',child/'upload.mp4')
    index=STAGES.index(stage)
    for earlier in STAGES[:index]:
        report=reports.get(earlier)
        if report is None:continue
        outputs=dict(report.get('outputs') or {})
        if earlier=='composite' and chain['composite']['tool']=='depth_cutout' and 'depth-composite-silent.mp4' not in outputs and (parent/'composite-silent.mp4').exists() and chain['face']['tool']=='off' and index<=STAGES.index('face'):
            outputs['depth-composite-silent.mp4']=None;link_artifact(parent/'composite-silent.mp4',child/'depth-composite-silent.mp4')   # legacy depth run: the cutout only exists under the face stage's name
        for name in list(outputs):
            source=parent/name
            if not source.exists():outputs.pop(name,None);continue
            if name in COPY_NOT_LINK:shutil.copy2(source,child/name)
            elif name=='depth-composite-silent.mp4' and (child/name).exists():pass
            else:link_artifact(source,child/name)
            if outputs[name] is None:outputs[name]=cache.artifact_hash(child/name)
        write_report(child,earlier,{**report,'outputs':outputs,'cached_from':parent.name,'state':'cached' if report.get('state')!='off' else 'off','health':(report.get('health') or '')})
    if index>STAGES.index('audio') and (parent/'audio-manifest.json').exists() and not (child/'audio-manifest.json').exists():shutil.copy2(parent/'audio-manifest.json',child/'audio-manifest.json')
    for name in CARRY:
        if (parent/name).exists() and not (child/name).exists():link_artifact(parent/name,child/name)
    for later in PREP_STAGES[index:] if stage in PREP_STAGES else []:   # a re-run edit-layer tool (mask edit_layer, face mesh_edit) reads the parent's saved edits
        try:tool_inputs=get_tool(later,chain[later]['tool']).inputs
        except ValueError:continue
        for name in tool_inputs:
            if name.startswith('edit-layer/') and (parent/name).exists() and not (child/name).exists():link_artifact(parent/name,child/name)
    mode=mode_for_chain(chain);child_run=new_run(child,chain,mode,parent=parent.name,changed=changed,preset=preset)
    for earlier in STAGES[:index]:
        report=reports.get(earlier) or {}
        child_run['chain'][earlier].update(key=report.get('key'),cached_from=parent.name)
    child_run['state']='created';child_run['started']=None
    save_run(child,child_run);(child/'workflow-mode.json').write_text(json.dumps({'mode':mode}))
    log(child,f'branched from {parent.name} at {stage}: {changed}')
    return child,chain,changed

def run_branch(child,chain,stage,status=print):
    """Run the child from `stage` onward (the earlier stages are already linked)."""
    from .runner import run_chain
    from_stage=stage if stage in PREP_STAGES else None
    if from_stage is None:
        # A change at prompt/generate/finish keeps every prepared artifact; the run is ready for review and submission.
        run=load_run(child);run.update(state='done',finished=now());save_run(child,run);return run
    return run_chain(child,chain,status,from_stage=from_stage)

def tree(runs_root,summaries=None):
    """The forest of runs: roots (no parent, or parent missing) with nested children, each node a summary dict."""
    runs_root=Path(runs_root);nodes={}
    for folder in runs_root.iterdir():
        if not folder.is_dir() or len(folder.name)!=32 or not all(c in '0123456789abcdef' for c in folder.name):continue
        run=load_run(folder) or {}
        summary=dict((summaries or {}).get(folder.name) or {'id':folder.name})
        summary.update(parent=run.get('parent'),changed=summary.get('changed') or run.get('changed'),preset=run.get('preset'),children=[])   # the summary's text is already in plain words
        nodes[folder.name]=summary
    roots=[]
    for ident,node in nodes.items():
        parent=node.get('parent')
        if parent and parent in nodes:nodes[parent]['children'].append(node)
        else:roots.append(node)
    def sort(items):
        items.sort(key=lambda n:n.get('created') or '',reverse=True)
        for n in items:sort(n['children'])
    sort(roots)
    return roots
