"""Legacy runs: reconstruct `run.json` and the stage reports from the files a run folder already has.

Runs made before the stage rack have no `run.json`. `reconstruct(folder)` builds the chain and reports in memory
from `workflow-mode.json`, `manifest.json`, `audio-manifest.json`, `sam-report.json`, `face-tracking.json`,
`generation.json`, `status.json` and the artifacts present; `write=True` also writes them into the folder (used
for copies of old runs, never for the originals under runs/ by the app itself).
"""
from pathlib import Path
import json
from .base import STAGES,get_tool
from .report import new_report,write_report,now
from .runner import new_run,save_run
from .presets import normalize_chain,mode_for_chain
from . import cache

OUTPUTS={'input_doctor':['original.mp4','input-doctor.json','tracking-source.mp4','tracking-source.json'],
         'audio':['original-audio.wav','vocals.wav','music.wav','drums.wav','bass.wav','other.wav','audio-prediction.json','audio-manifest.json'],
         'depth':['depth-raw.mp4','depth.mp4'],
         'mask':['raw-masks','clean-masks','sam-report.json','sam-attempts.json','sam-raw-request.json','mask-cleanup-report.json','sam-masks.zip','rgb-repair','mask-edits.json','wand-hosted.json'],
         'composite':['mask.mp4','composite.mp4','depth-composite-silent.mp4'],
         'face':['composite-silent.mp4','face-landmarks.json','face-tracking.json','preview.jpg','seedance-input.mp4'],
         'prompt':['prompt.txt'],
         'generate':['seedance-request.json','seedance-response.json','generation.json','seedance-result.mp4','final-preview.mp4','fal-result.json','provider-status.json','submission-error.json','duration-adjustment.json','seedance-duration-aligned.mp4'],
         'finish':['hd/request.json','hd/response.json','hd/final-preview.mp4','hd/seedance-result.mp4','hd/status.json']}

def read_json(path):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return {}

def legacy_mode(folder):
    folder=Path(folder);mode=read_json(folder/'workflow-mode.json').get('mode')
    if mode:return mode
    mesh=(folder/'face-tracking.json').exists() or (folder/'face-landmarks.json').exists();depth=(folder/'depth.mp4').exists() or (folder/'depth-raw.mp4').exists()
    return 'depth_mesh' if mesh and depth else 'face_mesh' if mesh else 'depth'

def legacy_chain(folder):
    """The chain the files imply (tool per stage plus the parameters that were used)."""
    from .depth import BY_PROVIDER
    folder=Path(folder);mode=legacy_mode(folder);manifest=read_json(folder/'manifest.json');audio=read_json(folder/'audio-manifest.json');sam=read_json(folder/'sam-report.json')
    generation=read_json(folder/'generation.json');tracking=read_json(folder/'face-tracking.json')
    depth_on=mode in ('depth','depth_mesh');mesh_on=mode in ('face_mesh','depth_mesh') and ((folder/'face-tracking.json').exists() or (folder/'face-landmarks.json').exists())
    clean=bool(manifest.get('clean_dialogue',audio.get('clean_dialogue',False)))
    prompt=sam.get('prompt') or manifest.get('prompt') or 'person'
    chain={'input_doctor':{'tool':'probe','params':{}},
           'audio':{'tool':'clean_dialogue' if clean else 'original','params':{}},
           'depth':{'tool':BY_PROVIDER.get(manifest.get('depth_provider','replicate'),'depth_anything_replicate') if depth_on else 'off','params':{}},
           'mask':{'tool':'sam3_replicate' if depth_on else 'off','params':{'prompt':prompt} if depth_on else {}},
           'composite':{'tool':'depth_cutout' if depth_on else 'original','params':{}},
           'face':{'tool':'mediapipe_mesh' if mesh_on else 'off','params':{'strict':bool(tracking.get('strict',mode=='face_mesh')),'pad':1.8,'max_gap':int(tracking.get('max_gap_frames',6) or 6)} if mesh_on else {}},
           'prompt':{'tool':'identity_only','params':{'text':generation['prompt']} if generation.get('prompt') else {}},
           'generate':{'tool':generation.get('provider') if generation.get('provider') in ('fal','enhancor') else 'fal','params':{}},
           'finish':{'tool':'complete_draft' if (folder/'hd/response.json').exists() else 'restore_original_audio','params':{}}}
    return normalize_chain(chain),mode

def stage_health(folder,stage,tool,present):
    """A plain sentence per stage from the legacy files."""
    folder=Path(folder)
    if tool=='off':return {'health':stage.replace('_',' ').capitalize()+' was off.'}
    if stage=='input_doctor':
        from .input_doctor import probe_source
        info=probe_source(folder/'original.mp4') if (folder/'original.mp4').exists() else {}
        return {'health':(f'Working copy {info.get("width")}×{info.get("height")} at {info.get("fps")} fps, {info.get("seconds")} s.' if info.get('readable') else 'No working copy found.'),'frames':{'covered':read_json(folder/'manifest.json').get('frames'),'filled':0,'missing':0}}
    if stage=='audio':
        audio=read_json(folder/'audio-manifest.json')
        return {'health':'Vocals isolated with Demucs; the prepared clip carries only the voice.' if tool=='clean_dialogue' and (folder/'vocals.wav').exists() else 'Original audio kept, copied packet for packet.' if audio.get('audio_remux')!='reencoded' else 'Original audio kept (re-encoded because the source codec cannot live in MP4).'}
    if stage=='depth':return {'health':'Depth video present.' if 'depth.mp4' in present else 'Depth video missing.'}
    if stage=='mask':
        from .mask import Sam3Replicate
        return Sam3Replicate.summarize(folder)
    if stage=='composite':return {'health':'Subject cut out over the original background.' if present else 'No composite found.'}
    if stage=='face':
        from .face import tracking_report
        return tracking_report(folder) or {'health':'Face mesh drawn.' if present else 'No face tracking found.'}
    if stage=='prompt':
        generation=read_json(folder/'generation.json');return {'health':'Prompt sent with the draft.' if generation.get('prompt') else 'No draft submitted yet.'}
    if stage=='generate':
        generation=read_json(folder/'generation.json')
        if not generation:return {'health':'No draft submitted yet.'}
        return {'health':f"Draft {'rendered' if (folder/'final-preview.mp4').exists() else 'submitted'} by {generation.get('provider','the provider')} ({generation.get('request_id','')}).",'data':{'request_id':generation.get('request_id'),'mode':generation.get('mode'),'draft_id':generation.get('draft_id')}}
    if stage=='finish':
        if (folder/'hd/final-preview.mp4').exists():return {'health':'HD version rendered with the original audio restored.'}
        if (folder/'final-preview.mp4').exists():return {'health':'Final preview carries the entire original source audio.'}
        return {'health':'Nothing to finish yet.'}
    return {'health':''}

def reconstruct(folder,with_keys=False,write=False):
    """Return (run, reports) for a legacy run; with_keys computes cache keys and output hashes (reads every artifact)."""
    folder=Path(folder);chain,mode=legacy_chain(folder);status=read_json(folder/'status.json')
    run=new_run(folder,chain,mode);run.update(state=status.get('state','unknown') if status else 'unknown',migrated=True,started=None)
    try:
        import datetime
        stamp=(folder/'upload.mp4' if (folder/'upload.mp4').exists() else folder).stat().st_mtime
        run['created']=datetime.datetime.fromtimestamp(stamp,datetime.timezone.utc).isoformat(timespec='seconds')
    except OSError:pass
    reports={}
    for stage in STAGES:
        entry=chain[stage];tool=get_tool(stage,entry['tool'])
        names=[n for n in OUTPUTS[stage] if (folder/n).exists()]+[p.name for p in folder.glob('raw-masks-*') if stage=='mask' and p.is_dir()]
        if stage=='generate':names+=[p.name for p in folder.glob('char*-reference.*')]
        if stage=='composite' and chain['face']['tool']=='off' and 'depth-composite-silent.mp4' not in names and (folder/'composite-silent.mp4').exists():pass   # the cutout lives under the face stage's name; branch() aliases it
        outputs={n:(cache.artifact_hash(folder/n) if with_keys else None) for n in names}
        input_hashes=cache.hash_artifacts(folder,tool.inputs) if with_keys else {}
        key=cache.cache_key(stage,tool.name,entry['params'],input_hashes) if with_keys else None
        report=new_report(stage,tool.name,entry['params'],inputs=input_hashes,outputs=outputs,key=key,started=None,finished=None)
        report.update(stage_health(folder,stage,tool.name,names))
        if tool.name=='off':report['state']='off'
        elif names:report['state']='done'
        else:report['state']='missing';report['health']=(report.get('health') or '')+(' Nothing recorded for this stage.' if not report.get('health') else '')
        if run['state']=='error' and stage==failing_stage(folder,chain) :report.update(state='error',error={'message':str(status.get('status','')),'fix':'Re-run from this stage after fixing the cause.'})
        report['migrated']=True;reports[stage]=report
        run['chain'][stage].update(key=key,cached_from=None)
    from . import calls
    run['cost_usd_total']=calls.total_cost(folder)
    if write:
        save_run(folder,run)
        for stage,report in reports.items():write_report(folder,stage,report)
    return run,reports

def failing_stage(folder,chain):
    """Best guess of the stage a legacy error run stopped at: the first stage with a tool on and no outputs."""
    folder=Path(folder);tracking=read_json(folder/'face-tracking.json')
    if tracking and tracking.get('ok') is False:return 'face'
    for stage in STAGES[:6]:
        tool=get_tool(stage,chain[stage]['tool'])
        if tool.name=='off' or not tool.outputs:continue
        if not any((folder/n).exists() for n in OUTPUTS[stage]):return stage
    if (folder/'face-tracking.json').exists() and not (folder/'seedance-input.mp4').exists():return 'face'
    return None

def run_info(folder):
    """run.json + reports for any run, migrated in memory when needed (used by GET /jobs/{id}/run)."""
    from .runner import load_run
    from .report import all_reports
    folder=Path(folder);run=load_run(folder)
    if run is not None:return {'run':run,'reports':all_reports(folder),'migrated':False}
    run,reports=reconstruct(folder,with_keys=False,write=False)
    return {'run':run,'reports':reports,'migrated':True}
