"""Runs a chain for a run folder and keeps `run.json`, `stages/<stage>/report.json`, `log.txt` and `calls.jsonl`.

`run_chain(folder, chain, status)` runs the preparation stages (input_doctor … face) in order, then builds the
prepared clip exactly as before (`seedance-input.mp4`, `manifest.json`, `workflow-mode.json`). `from_stage`
starts later (a branch re-runs that stage and everything after it; the earlier stages were linked in).
`run_mode` is what the legacy entry points (`pipeline.run`, `face_mesh.run`, `face_mesh.run_depth`) call.

run.json: {id, parent, created, preset, changed, chain: {stage: {tool, params, key, cached_from}}, cost_usd_total,
mode, state, error, started, finished}
"""
from pathlib import Path
from datetime import datetime,timezone
import json,time,shutil,traceback,uuid
from .base import STAGES,PREP_STAGES,get_tool,fresh
from .report import new_report,write_report,read_report,merge_result,now
from . import cache,calls
from .presets import normalize_chain,mode_for_chain,chain_for_mode,legacy_provider

def log(folder,line):
    """Append one timestamped line to the run's log.txt (never a key value)."""
    try:
        with (Path(folder)/'log.txt').open('a') as f:f.write(datetime.now(timezone.utc).isoformat(timespec='seconds')+' '+str(line).rstrip()+'\n')
    except OSError:pass

def load_run(folder):
    path=Path(folder)/'run.json'
    if not path.exists():return None
    try:return json.loads(path.read_text())
    except ValueError:return None

def save_run(folder,run):
    (Path(folder)/'run.json').write_text(json.dumps(run,indent=1,ensure_ascii=False,default=str))

def new_run(folder,chain,mode,parent=None,changed=None,preset=None):
    folder=Path(folder)
    return {'id':folder.name,'parent':parent,'created':now(),'preset':preset,'changed':changed,
            'chain':{stage:{'tool':chain[stage]['tool'],'params':chain[stage]['params'],'key':None,'cached_from':None} for stage in STAGES},
            'cost_usd_total':0.0,'mode':mode,'state':'running','error':None,'started':now(),'finished':None}

def plain_error(exc):
    """A sentence a non-engineer understands plus a suggested fix; the traceback goes to log.txt."""
    message=str(exc).strip() or type(exc).__name__
    fix=getattr(exc,'fix',None)
    if fix is None:
        lower=message.lower()
        if 'offline' in lower:fix='Start the app without PUPPETEER_OFFLINE to allow paid and network calls.'
        elif 'token' in lower or 'key' in lower or '.env' in lower:fix='Add the missing key to the .env file in the project folder and restart the app.'
        elif 'credit' in lower or 'billing' in lower or 'quota' in lower or 'rate limit' in lower:fix='Top up or wait for the provider account, then re-run this stage; nothing is retried automatically.'
        elif 'setup-face-mesh' in lower:fix='Run bash setup-face-mesh.sh once (Python 3.12), then re-run the face stage.'
        elif 'lost face' in lower or 'tracking gaps' in lower:fix='Use the Expressive preset (lenient gaps) or a clip where the face stays visible, then re-run from the face stage.'
        elif 'no masks' in lower or 'found no subject' in lower:fix='Try one short noun phrase such as "person" for the mask stage and re-run from there.'
        elif 'frame alignment' in lower:fix='Re-run from the mask stage; the depth, mask and original clips must have the same number of frames.'
        elif '30 seconds' in lower:fix='Trim the clip to 30 seconds or less and upload it again.'
        elif 'no audio' in lower:fix='Use a source clip with an audio track, or add one before uploading.'
        else:fix='Open the run\'s log.txt for details and re-run from the failed stage.'
    return message,fix

def inputs_for(folder,chain,mode,source):
    from .costs import clip_seconds
    return {'folder':Path(folder),'chain':chain,'mode':mode,'source':Path(source) if source else Path(folder)/'upload.mp4','seconds':clip_seconds(folder)}

def link_artifact(src,dst):
    """Hard link (fallback copy) one file or folder; never writes to `src`."""
    src=Path(src);dst=Path(dst)
    if src.is_dir():
        dst.mkdir(parents=True,exist_ok=True)
        for path in src.rglob('*'):
            target=dst/path.relative_to(src)
            if path.is_dir():target.mkdir(parents=True,exist_ok=True)
            else:link_artifact(path,target)
        return
    dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists() or dst.is_symlink():dst.unlink()
    try:
        import os;os.link(src,dst)
    except OSError:shutil.copy2(src,dst)

def execute_stage(folder,stage,chain,inputs,status,run,reuse_cache=True):
    folder=Path(folder);entry=chain[stage];tool=get_tool(stage,entry['tool']);params=tool.normalize_params(entry.get('params'))
    input_hashes=cache.hash_artifacts(folder,tool.inputs);key=cache.cache_key(stage,tool.name,params,input_hashes)
    report=new_report(stage,tool.name,params,inputs=input_hashes,key=key,started=now())
    hit=cache.lookup(folder.parent,stage,key,exclude=folder) if (reuse_cache and tool.paid and tool.name!='off') else None
    if hit is not None:
        source,cached=hit
        for name in (cached.get('outputs') or {}):
            if (source/name).exists():link_artifact(source/name,folder/name)
        report.update(outputs=cached.get('outputs') or {},frames=cached.get('frames') or report['frames'],gaps=cached.get('gaps') or [],warnings=list(cached.get('warnings') or []),
                      health=(cached.get('health') or '')+f' (reused from run {source.name}, nothing re-billed)',seconds=0.0,cost_usd=0.0,cached_from=source.name,finished=now(),state='cached')
        log(folder,f'{stage}: reused {tool.name} outputs from {source.name} (same inputs, tool and params)')
        write_report(folder,stage,report);run['chain'][stage].update(tool=tool.name,params=params,key=key,cached_from=source.name);return report
    calls.set_context(folder,stage,tool.name);before=len(calls.read_calls(folder));clock=time.time()
    log(folder,f'{stage}: running {tool.name} '+json.dumps(params,default=str))
    try:result=tool.run(inputs,params,folder,status)
    except Exception as exc:
        message,fix=plain_error(exc)
        partial=getattr(tool,'partial_result',None)
        if partial:
            try:merge_result(report,partial(folder))
            except Exception:pass
        report['outputs']={name:cache.artifact_hash(folder/name) for name in tool.outputs if (folder/name).exists()}
        report.update(seconds=round(time.time()-clock,2),finished=now(),state='error',error={'message':message,'fix':fix},
                      cost_usd=round(sum(float(c.get('cost_usd') or 0) for c in calls.read_calls(folder)[before:]),4))
        if not report['health']:report['health']=message
        write_report(folder,stage,report);run['chain'][stage].update(tool=tool.name,params=params,key=key,cached_from=None)
        log(folder,f'{stage}: FAILED {type(exc).__name__}: {message}\n'+traceback.format_exc())
        raise
    finally:calls.clear_context(folder)
    merge_result(report,result)
    report['outputs']={name:cache.artifact_hash(folder/name) for name in report['outputs'] if (folder/name).exists()}
    report.update(seconds=round(time.time()-clock,2),finished=now(),state='off' if tool.name=='off' else 'done',
                  cost_usd=round(sum(float(c.get('cost_usd') or 0) for c in calls.read_calls(folder)[before:]),4))
    write_report(folder,stage,report);run['chain'][stage].update(tool=tool.name,params=params,key=key,cached_from=None)
    log(folder,f'{stage}: done in {report["seconds"]} s · {report["health"]}')
    return report

def prepare_clip(folder,chain,mode,status,source=None):
    """seedance-input.mp4 + manifest.json + workflow-mode.json, exactly as the legacy pipeline wrote them."""
    import audio_workflow
    folder=Path(folder);clean=chain['audio']['tool']=='clean_dialogue'
    status('Embedding isolated vocals (clean dialogue)' if clean else 'Embedding original source audio')
    fresh(folder/'seedance-input.mp4')
    audio_workflow.prepare_seedance_video(folder,clean)
    if mode in ('face_mesh','original'):manifest={'mode':mode,'clean_dialogue':bool(clean)}
    else:
        probe=read_report(folder,'input_doctor') or {};meta=dict(((probe.get('data') or {}).get('normalized')) or {})
        try:mask_method=json.loads((folder/'sam-report.json').read_text()).get('method') or 'SAM 3 raw PNG masks'
        except (OSError,ValueError):mask_method='SAM 3 raw PNG masks'
        meta.update(prompt=chain['mask']['params'].get('prompt','person'),depth_provider=legacy_provider(chain),mask_method=mask_method,clean_dialogue=bool(clean));manifest=meta
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2))
    (folder/'workflow-mode.json').write_text(json.dumps({'mode':mode}))
    face=read_report(folder,'face')
    if face is not None and (folder/'seedance-input.mp4').exists():
        face['outputs']={**(face.get('outputs') or {}),'seedance-input.mp4':cache.artifact_hash(folder/'seedance-input.mp4')};write_report(folder,'face',face)

def run_chain(folder,chain,status=print,*,mode=None,from_stage=None,parent=None,changed=None,preset=None,source=None,stages=None,reuse_cache=True):
    """Run `chain` in `folder` from `from_stage` (or the start) through the preparation stages; returns run.json data."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);chain=normalize_chain(chain);mode=mode or mode_for_chain(chain)
    stages=list(stages or PREP_STAGES)
    run=load_run(folder) or new_run(folder,chain,mode,parent,changed,preset)
    run.update(mode=mode,state='running',error=None,started=run.get('started') or now(),finished=None)
    for stage in STAGES:run['chain'].setdefault(stage,{}).update(tool=chain[stage]['tool'],params=chain[stage]['params'])
    if parent:run['parent']=parent
    if changed:run['changed']=changed
    if preset:run['preset']=preset
    save_run(folder,run);(folder/'workflow-mode.json').write_text(json.dumps({'mode':mode}))
    def say(line):
        log(folder,line)
        try:status(line)
        except Exception:pass
    log(folder,'run start · mode '+mode+(' · from '+from_stage if from_stage else '')+(' · parent '+parent if parent else ''))
    inputs=inputs_for(folder,chain,mode,source);start=STAGES.index(from_stage) if from_stage else 0
    try:
        for stage in stages:
            if STAGES.index(stage)<start:continue
            execute_stage(folder,stage,chain,inputs,say,run,reuse_cache=reuse_cache)
            save_run(folder,run)
        if 'face' in stages and start<=STAGES.index('face'):prepare_clip(folder,chain,mode,say,source)
        run.update(state='done',finished=now(),cost_usd_total=calls.total_cost(folder));save_run(folder,run)
        log(folder,'run done · estimated spend $'+str(run['cost_usd_total']))
    except Exception as exc:
        message,fix=plain_error(exc)
        run.update(state='error',error={'message':message,'fix':fix},finished=now(),cost_usd_total=calls.total_cost(folder));save_run(folder,run)
        raise
    return run

def run_mode(mode,src,folder,status=print,prompt='person',provider='replicate',clean_dialogue=False):
    """Legacy entry: run a mode's chain in `folder` with `src` as the upload (copied in when it lives elsewhere)."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);src=Path(src);upload=folder/'upload.mp4'
    if src.exists() and src.resolve()!=upload.resolve():shutil.copy2(src,upload)
    chain=chain_for_mode(mode,prompt,provider,clean_dialogue)
    return run_chain(folder,chain,status,mode=mode,source=src)

def final_status(folder):
    """The one-line completion message the legacy entry points printed."""
    folder=Path(folder);run=load_run(folder);mode=run.get('mode') if run else 'depth'
    from face_mesh import tracking_summary
    if mode=='face_mesh':return 'Face mesh ready · '+tracking_summary(folder)+' · review tracking and embedded audio'
    if mode=='depth_mesh':return 'Depth + face mesh ready · '+tracking_summary(folder)+' · full mask and facial tracking review required'
    return 'Complete'
