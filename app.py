from pathlib import Path
import threading,uuid,shutil,json
from fastapi import FastAPI,UploadFile,File,Form,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
import re
from pipeline import run
import stages
ROOT=Path(__file__).resolve().parent
RUNS=ROOT/'runs';RUNS.mkdir(exist_ok=True)
TRUE=('1','true','on','yes')

def truthy(value):return str(value or '').strip().lower() in TRUE

def fail(status,message,fix,**extra):
    """Every new error body: a plain sentence (`detail` for the old UI helper, `message`) plus a `fix` suggestion."""
    return JSONResponse(status_code=status,content={'detail':message,'message':message,'fix':fix,**extra})

def write_status(folder,data):
    """Save a run's status.json; `fresh()` first so a hard-linked copy never writes into the run it was linked from."""
    path=Path(folder)/'status.json';stages.fresh(path);path.write_text(json.dumps(data))

def cost_gate(estimate,confirm_cost,legacy,folder,what):
    """None when the request may run, else the 402 response. Every paid request needs confirm_cost=true; there is no
    legacy exception (`legacy` is kept in the signature for the callers but ignored), so no paid call ever starts
    without an explicit confirmation. `workflow.py` is a direct user action and does not go through this route."""
    estimate=float(estimate or 0)
    if estimate<=0 or truthy(confirm_cost):return None
    return fail(402,f'{what} costs about ${estimate:.2f}. Confirm the cost to run it.','Send confirm_cost=true with the same request to run it (the UI shows the estimate on the button).',estimated_cost_usd=round(estimate,4))

async def body_fields(request):
    """Form or JSON body as a plain dict (the new endpoints accept both)."""
    ctype=request.headers.get('content-type','')
    if 'application/json' in ctype:
        try:data=await request.json()
        except ValueError:return {}
        return data if isinstance(data,dict) else {}
    if 'form' in ctype or 'multipart' in ctype:
        form=await request.form();return {k:form.get(k) for k in form.keys()}
    return {}

def parse_params(value):
    if value in (None,''):return {}
    if isinstance(value,dict):return value
    data=json.loads(value) if isinstance(value,str) else value
    if not isinstance(data,dict):raise ValueError('params must be a JSON object')
    return data

def estimate_stages(chain,seconds,names):
    """Estimated USD for running the given stages of `chain` on a clip of `seconds` seconds, plus the paid ones."""
    total=0.0;paid=[]
    for stage in names:
        entry=chain[stage];tool=stages.get_tool(stage,entry['tool'])
        if not tool.paid:continue
        usd=float(tool.estimate_cost({'seconds':seconds},entry['params']) or 0);total+=usd
        paid.append({'stage':stage,'tool':tool.name,'label':tool.label,'estimated_cost_usd':round(usd,4)})
    return round(total,4),paid

def rerun_stages(stage):
    return stages.PREP_STAGES[stages.STAGES.index(stage):] if stage in stages.PREP_STAGES else [stage]

REFERENCE_SUFFIXES={'char1-reference':['.png','.jpg','.jpeg','.webp','.mp4','.mov','.webm'],'char2-reference':['.png','.jpg','.jpeg','.webp']}

def save_reference(folder,name,upload):
    """Save a character reference as `<name>.<ext>` in the run folder (the draft step finds it there); None when no file was sent."""
    if upload is None or not (upload.filename or '').strip():return None
    suffix=Path(upload.filename or '').suffix.lower()
    if suffix not in REFERENCE_SUFFIXES[name]:raise HTTPException(400,'Use an image, or an identity video for Character 1 only.')
    for old in Path(folder).glob(name+'.*'):old.unlink()
    path=Path(folder)/(name+suffix)
    with path.open('wb') as f:shutil.copyfileobj(upload.file,f)
    return path

def job_status(ident):
    """The run's status dict: the live job, else the saved status.json, else None (never raises)."""
    status=jobs.get(ident)
    if status is not None:return status
    try:return json.loads((RUNS/ident/'status.json').read_text())
    except (OSError,ValueError):return None

def chain_from_request(preset,chain_json,prompt,provider,clean):
    """A preset by name or an explicit chain, with the subject prompt, depth provider and clean-dialogue choice applied."""
    if chain_json.strip():
        chain=stages.normalize_chain(parse_params(chain_json));name=None
    else:
        found=stages.get_preset(preset);chain=stages.normalize_chain(found['chain']);name=found['name']
        from stages.depth import BY_PROVIDER
        if chain['mask']['tool']=='sam3_replicate':chain['mask']['params']['prompt']=prompt or 'person'
        if chain['depth']['tool']!='off' and provider in BY_PROVIDER:chain['depth']['tool']=BY_PROVIDER[provider]
        chain['audio']['tool']='clean_dialogue' if clean else 'original'
    return chain,name
from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(_):
    resume_saved_generations();yield
app=FastAPI(lifespan=lifespan);jobs={}

# ---------------------------------------------------------------- request body bounds (checked before the body is read)

import re as _re
IMPORT_PATH=_re.compile(r'^/jobs/[0-9a-f]{32}/import$');EDITS_PATH=_re.compile(r'^/jobs/[0-9a-f]{32}/edits$')

def body_limit(method,path):
    """(limit in bytes, message, fix) for the routes whose bodies are bounded, else None. Import my own: the 1 GB file limit
    plus 1 MB for the multipart envelope; PUT edits: twice the 2 MB layer limit (a form body escapes the JSON)."""
    from stages import imports,editlayer
    if method=='POST' and IMPORT_PATH.match(path):
        return (imports.MAX_BYTES+1_000_000,f'This file is larger than {imports.MAX_BYTES//1_000_000} MB, the import limit.','Export a shorter or smaller version (the clip is at most 30 s), then import it again.')
    if method=='PUT' and EDITS_PATH.match(path):
        return (2*editlayer.MAX_LAYER_BYTES,'These edits are too large to keep.','Keep pixel data in files under the session folder and reference them by hash.')
    return None

class BodyTooLarge(Exception):pass

class BodyLimit:
    """ASGI middleware: a bounded route with a Content-Length over its limit gets a plain 413 {message, fix} before a byte
    of the body is read (so Starlette never spools a huge upload to disk); a body without a usable Content-Length is
    counted as it streams and cut off with the same 413 once it passes the limit. The routes keep their own checks."""
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        rule=body_limit(scope.get('method'),scope.get('path','')) if scope.get('type')=='http' else None
        if rule is None:return await self.app(scope,receive,send)
        limit,message,fix=rule
        headers=dict(scope.get('headers') or [])
        try:length=int(headers.get(b'content-length',b'') or -1)
        except ValueError:length=-1
        async def refuse():
            await JSONResponse(status_code=413,content={'detail':message,'message':message,'fix':fix})(scope,receive,send)
        if length>limit:return await refuse()
        state={'seen':0,'over':False,'started':False}
        async def counted():
            msg=await receive()
            if msg.get('type')=='http.request':
                state['seen']+=len(msg.get('body') or b'')
                if state['seen']>limit:state['over']=True;raise BodyTooLarge()
            return msg
        async def guarded(msg):
            if state['over']:return   # the app's own reply to the cut-off body (a parse error) is replaced by the 413 below
            if msg.get('type')=='http.response.start':state['started']=True
            await send(msg)
        try:await self.app(scope,counted,guarded)
        except BodyTooLarge:pass
        except Exception:
            if not state['over']:raise
        if state['over'] and not state['started']:
            await JSONResponse(status_code=413,content={'detail':message,'message':message,'fix':fix})(scope,receive,send)

app.add_middleware(BodyLimit)
@app.get('/')
def index():return FileResponse(ROOT/'static/index.html')
@app.post('/jobs')
def create(video:UploadFile=File(...),prompt:str=Form('person'),provider:str=Form('replicate'),mode:str=Form('depth'),clean_dialogue:str=Form(''),preset:str=Form(''),chain:str=Form(''),confirm_cost:str|None=Form(None),char1:UploadFile|None=File(None),char2:UploadFile|None=File(None)):
    """Prepare a new run. Legacy: `mode` (depth | face_mesh | depth_mesh). New: `preset` (name) or `chain` (JSON) plus `confirm_cost`.
    `char1` / `char2` (optional) are saved as `char1-reference.<ext>` / `char2-reference.<ext>` so the draft step finds them later."""
    if mode not in ['depth','face_mesh','depth_mesh']:raise HTTPException(400,'Unknown workflow mode')
    clean=clean_dialogue.strip().lower() in ['1','true','on','yes']
    if provider not in ['huggingface','replicate','replicate-chenxwh']:raise HTTPException(400,'Unknown provider')
    rack=bool(preset.strip() or chain.strip());preset_name=None;chain_data=None
    if rack:
        try:chain_data,preset_name=chain_from_request(preset,chain,prompt,provider,clean)
        except ValueError as e:return fail(400,str(e),'Pick a preset from GET /presets or send a chain with the tools listed by GET /stages.')
    else:chain_data=stages.chain_for_mode(mode,prompt,provider,clean)
    ident=uuid.uuid4().hex;folder=RUNS/ident;folder.mkdir();src=folder/'upload.mp4'
    with src.open('wb') as out:shutil.copyfileobj(video.file,out)
    estimate,paid=estimate_stages(chain_data,stages.costs.clip_seconds(folder),stages.PREP_STAGES)
    refused=cost_gate(estimate,confirm_cost,legacy=not rack,folder=None,what='Preparing this video')
    if refused is not None:shutil.rmtree(folder,ignore_errors=True);return refused
    try:
        for name,upload in [('char1-reference',char1),('char2-reference',char2)]:save_reference(folder,name,upload)
    except HTTPException:shutil.rmtree(folder,ignore_errors=True);raise
    jobs[ident]={'state':'running','status':'Starting','id':ident,'estimated_cost_usd':estimate,'preset':preset_name}
    def work():
        try:
            if rack:stages.run_chain(folder,chain_data,lambda s:jobs[ident].update(status=s),preset=preset_name)
            elif mode=='face_mesh':
                from face_mesh import run as run_mesh
                run_mesh(src,folder,lambda s:jobs[ident].update(status=s),clean)
            elif mode=='depth_mesh':
                from face_mesh import run_depth
                run_depth(src,folder,prompt,provider,lambda s:jobs[ident].update(status=s),clean)
            else:run(src,folder,prompt,provider,lambda s:jobs[ident].update(status=s),clean)
            jobs[ident].update(state='done',status='Preparation complete · input review required')
            write_status(folder,jobs[ident])
        except Exception as e:
            message,fix=stages.runner.plain_error(e)
            jobs[ident].update(state='error',status=message,fix=fix)
            write_status(folder,jobs[ident])
    threading.Thread(target=work,daemon=True).start();return jobs[ident]
def plain_status(text):
    """Old status strings kept raw arrays; say the same thing in words for the Runs list."""
    import re
    text=re.sub(r'Frame alignment failed \(original/depth/SAM\): \[(\d+), (\d+), (\d+)\]\.?',r'The frame counts differ: original \1, depth \2, SAM masks \3.',text)
    return re.sub(r'\[[^\]]{0,200}\]','(details in the run folder)',text)

def plain_changed(folder,run):
    """`run.json.changed` in words. Branches made before 2026-10-23 stored list params as raw JSON; rebuild the line from the chains."""
    changed=run.get('changed')
    if not changed or not run.get('parent') or run.get('edits') or ('[' not in changed and 'base_run' not in changed):return changed   # a saved edit session's line is already in words
    try:
        stage=changed.split(':',1)[0].strip();parent=stages.load_run(RUNS/run['parent']) or {}
        if not parent:parent={'chain':stages.reconstruct(RUNS/run['parent'])[0].get('chain',{})}
        return stages.describe_change(stage,(parent.get('chain') or {}).get(stage) or {},(run.get('chain') or {}).get(stage) or {})
    except Exception:return plain_status(changed)

def run_summary(folder):
    """id, mode, state, status text, date and what exists, for the Runs list. Never reads key values."""
    import datetime
    ident=folder.name
    status=jobs.get(ident)
    if status is None:
        try:status=json.loads((folder/'status.json').read_text())
        except (OSError,ValueError):status={'state':'unknown','status':'No status saved (interrupted before preparation finished).'}
    mode='unknown'
    try:mode=json.loads((folder/'workflow-mode.json').read_text()).get('mode') or mode
    except (OSError,ValueError):
        mesh=(folder/'face-tracking.json').exists() or (folder/'face-landmarks.json').exists();depth=(folder/'depth.mp4').exists() or (folder/'depth-raw.mp4').exists()
        mode='depth_mesh' if mesh and depth else 'face_mesh' if mesh else 'depth' if depth else mode
    source=folder/'upload.mp4';stamp=(source if source.exists() else folder).stat().st_mtime
    run=stages.load_run(folder) or {}
    return {'id':ident,'mode':mode,'state':status.get('state','unknown'),'status':plain_status(str(status.get('status',''))[:200]),
            'created':run.get('created') or datetime.datetime.fromtimestamp(stamp).astimezone().isoformat(timespec='minutes'),
            'reviewed':(folder/'mask-review.json').exists(),'draft':(folder/'final-preview.mp4').exists(),'final':(folder/'hd/final-preview.mp4').exists(),'request':(folder/'seedance-response.json').exists(),
            'parent':run.get('parent'),'changed':plain_changed(folder,run),'preset':run.get('preset'),'cost_usd_total':stages.total_cost(folder),'fix':status.get('fix'),
            'imported':stages.imports.imported_stages(run.get('chain'))}

def run_folders():
    return [f for f in RUNS.iterdir() if f.is_dir() and len(f.name)==32 and all(c in '0123456789abcdef' for c in f.name)]

@app.get('/jobs')
def list_jobs():
    runs=[run_summary(f) for f in run_folders()]
    runs.sort(key=lambda r:r['created'],reverse=True)
    return {'runs':runs}

@app.get('/jobs/tree')
def jobs_tree():
    """The forest of runs: roots with nested `children`; each node is a Runs-list summary plus parent, changed and preset."""
    summaries={f.name:run_summary(f) for f in run_folders()}
    return {'runs':stages.tree(RUNS,summaries)}

@app.get('/jobs/{ident}')
def get(ident:str):
    if ident not in jobs:
        if len(ident)==32 and all(c in '0123456789abcdef' for c in ident) and (RUNS/ident/'status.json').exists():return json.loads((RUNS/ident/'status.json').read_text())
        raise HTTPException(404)
    return jobs[ident]
@app.post('/jobs/{ident}/seedance')
def seedance(ident:str,prompt:str=Form(...),char1:UploadFile=File(...),char2:UploadFile|None=File(None),provider:str=Form(''),confirm_cost:str|None=Form(None)):
    if len(ident)!=32 or not all(c in '0123456789abcdef' for c in ident):raise HTTPException(404)
    folder=RUNS/ident
    from providers import PROVIDERS,default_provider
    provider=provider.strip().lower()
    if provider and provider not in PROVIDERS:raise HTTPException(400,'Unknown Seedance provider; choose one of: '+', '.join(PROVIDERS))
    if not (folder/'audio-manifest.json').exists():raise HTTPException(400,'Audio preparation must complete first.')
    from mask_review import require_approved
    try:require_approved(folder)
    except ValueError as e:raise HTTPException(409,str(e))
    estimate=stages.costs.price_for(provider or default_provider(),stages.costs.clip_seconds(folder)) or 0
    refused=cost_gate(estimate,confirm_cost,legacy=True,folder=folder,what='Creating this draft')
    if refused is not None:return refused
    paths=[save_reference(folder,name,upload) for name,upload in [('char1-reference',char1),('char2-reference',char2)]]
    from seedance_bridge import submit
    try:request_id=submit(folder,prompt,*paths,provider=provider or None)
    except Exception as e:raise HTTPException(502,str(e))
    jobs[ident]={'id':ident,'state':'running','status':'Seedance rendering: '+request_id}
    def collect():
        from seedance_bridge import wait_and_finish
        try:
            wait_and_finish(folder,request_id,lambda s:jobs[ident].update(status=s))
            jobs[ident].update(state='done',status='Final preview ready · entire original source audio',final_url='/runs/'+ident+'/final-preview.mp4')
        except Exception as e:jobs[ident].update(state='error',status=str(e))
        write_status(folder,jobs[ident])
    threading.Thread(target=collect,daemon=True).start()
    return {'request_id':request_id,'id':ident,'state':'running','status':jobs[ident]['status']}

@app.get('/providers')
def list_providers():
    """Capabilities plus a configured flag per provider; never the key values."""
    from providers import PROVIDERS,get_provider,configured,default_provider
    return {'default':default_provider(),'providers':{name:{**get_provider(name).capabilities(),'configured':configured(name)} for name in PROVIDERS}}

@app.post('/jobs/{ident}/finish')
def finish(ident:str,video:UploadFile=File(...)):
    if len(ident)!=32 or not all(c in '0123456789abcdef' for c in ident):raise HTTPException(404)
    folder=RUNS/ident
    if not (folder/'upload.mp4').exists():raise HTTPException(400,'Original source is required.')
    target=folder/'seedance-result.mp4'
    with target.open('wb') as f:shutil.copyfileobj(video.file,f)
    from audio_workflow import finish_preview
    try:finish_preview(target,folder)
    except Exception as e:raise HTTPException(400,str(e))
    return {'url':'/runs/'+ident+'/final-preview.mp4'}

app.mount('/runs' ,StaticFiles(directory=RUNS),name='runs')

hd_jobs={}
hd_lock=threading.Lock()

def hd_folder(ident):
    if len(ident)!=32 or not all(c in '0123456789abcdef' for c in ident):raise HTTPException(404)
    folder=RUNS/ident
    if not folder.exists():raise HTTPException(404)
    return folder

@app.get('/jobs/{ident}/files')
def list_files(ident:str):
    """Relative paths of files in the run folder; the UI uses this instead of probing for optional files."""
    folder=hd_folder(ident)
    return {'files':sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file())}

@app.get('/jobs/{ident}/hd')
def get_hd(ident:str):
    folder=hd_folder(ident)
    if ident in hd_jobs:return hd_jobs[ident]
    saved=folder/'hd/status.json'
    if saved.exists():return json.loads(saved.read_text())
    return {'state':'idle','status':'Approve your draft to generate the full-resolution version.'}

@app.post('/jobs/{ident}/hd')
async def create_hd(ident:str,request:Request):
    folder=hd_folder(ident);confirm_cost=(await body_fields(request)).get('confirm_cost')
    with hd_lock:
        previous=get_hd(ident)
        if previous['state'] in ['running','done']:return previous
        if not (folder/'final-preview.mp4').exists():raise HTTPException(400,'Complete and review a draft first.')
        from seedance_bridge import provider_for
        from providers import get_provider
        estimate=stages.costs.price_for(provider_for(folder)+'_complete',stages.costs.clip_seconds(folder)) or 0
        refused=cost_gate(estimate,confirm_cost,legacy=True,folder=folder,what='Completing this draft in HD')
        if refused is not None:return refused
        caps=get_provider(provider_for(folder)).capabilities()
        hd=folder/'hd';hd.mkdir(exist_ok=True)
        hd_jobs[ident]={'state':'running','status':'Submitting approved draft for '+caps['final_resolution'],'id':ident,'provider':caps['name']}
        def save(): write_status(hd,hd_jobs[ident])
        save()
    def work_hd():
        from seedance_bridge import submit_hd,wait_and_finish
        try:
            request_id=submit_hd(folder)
            hd_jobs[ident].update(request_id=request_id,status='Generating '+caps['final_resolution']+' through '+caps['label']);save()
            wait_and_finish(hd,request_id,lambda s:hd_jobs[ident].update(status=s))
            hd_jobs[ident].update(state='done',status=caps['final_resolution']+' ready · original source audio restored')
        except Exception as e:hd_jobs[ident].update(state='error',status=str(e))
        save()
    threading.Thread(target=work_hd,daemon=True).start()
    return hd_jobs[ident]

@app.get('/jobs/{ident}/mask-review')
def get_mask_review(ident:str):
    """The review state; while the run is still preparing it says so (`preparing`), after a failure `failed` with the fix."""
    from mask_review import state
    return state(hd_folder(ident),job_status(ident))

@app.post('/jobs/{ident}/mask-review')
def save_mask_review(ident:str,approved:bool=Form(...),fingerprint:str=Form(...),note:str=Form('')):
    from mask_review import review
    try:return review(hd_folder(ident),approved,note,fingerprint)
    except ValueError as e:raise HTTPException(409,str(e))

app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

# ---------------------------------------------------------------- stage rack: runs, branches, calls, costs, presets, stages

@app.get('/jobs/{ident}/run')
def get_run(ident:str):
    """run.json plus every stage report; legacy runs are reconstructed in memory (`migrated: true`, nothing written)."""
    folder=hd_folder(ident);info=stages.run_info(folder)
    info['run']['cost_usd_total']=stages.total_cost(folder)
    status=jobs.get(ident)
    if status is None:
        try:status=json.loads((folder/'status.json').read_text())
        except (OSError,ValueError):status={'state':info['run'].get('state','unknown'),'status':''}
    info['status']=status;info['calls']=stages.read_calls(folder)
    seconds=stages.costs.clip_seconds(folder);info['seconds']=seconds   # for the cost meter on the draft / HD buttons
    info['estimates']={'draft':{p:stages.costs.price_for(p,seconds) for p in ('fal','enhancor')},'complete':{p:stages.costs.price_for(p+'_complete',seconds) for p in ('fal','enhancor')},'note':stages.costs.NOTE}
    return info

@app.post('/estimate')
async def estimate_preparation(request:Request):
    """Estimated cost of preparing a clip of `seconds` seconds with a `preset`, a legacy `mode` or a `chain`; nothing runs.
    Body (form or JSON): preset | mode | chain, seconds (default 10), prompt, provider, clean_dialogue."""
    data=await body_fields(request);preset=str(data.get('preset') or '').strip();chain_json=data.get('chain') or '';mode=str(data.get('mode') or '').strip()
    prompt=str(data.get('prompt') or 'person');provider=str(data.get('provider') or 'replicate');clean=truthy(data.get('clean_dialogue'))
    try:seconds=float(data.get('seconds') or stages.costs.DEFAULT_SECONDS)
    except (TypeError,ValueError):seconds=stages.costs.DEFAULT_SECONDS
    try:
        if preset or (isinstance(chain_json,str) and chain_json.strip()) or isinstance(chain_json,dict):
            chain,name=chain_from_request(preset,chain_json if isinstance(chain_json,str) else json.dumps(chain_json),prompt,provider,clean)
        elif mode:chain=stages.chain_for_mode(mode,prompt,provider,clean);name=None
        else:return fail(400,'Say what to estimate: a preset, a mode or a chain.','Send preset=<name>, mode=depth|face_mesh|depth_mesh or chain=<JSON>.')
    except ValueError as e:return fail(400,str(e),'Pick a preset from GET /presets, a mode (depth, face_mesh, depth_mesh) or a chain with the tools listed by GET /stages.')
    total,paid=estimate_stages(chain,seconds,stages.PREP_STAGES)
    return {'preset':name,'mode':stages.mode_for_chain(chain),'seconds':seconds,'estimated_cost_usd':total,'paid':paid,'free':total==0,'note':stages.costs.NOTE}

# ---------------------------------------------------------------- Lab: A/B picks (runs/_compare/picks.json; GET /jobs ignores the folder because its name is not 32 hex)

picks_lock=threading.Lock()

def picks_file():
    return RUNS/'_compare'/'picks.json'   # resolved per call so a patched RUNS (tests) is honoured

def read_picks():
    try:data=json.loads(picks_file().read_text())
    except (OSError,ValueError):return []
    return [p for p in data.get('picks',[]) if isinstance(p,dict) and p.get('comparison_id')]

def comparison_id(runs,stage):
    return ','.join(sorted(runs))+':'+stage

@app.get('/compare/picks')
def get_picks(comparison_id:str=''):
    """Every A/B pick, newest first; `?comparison_id=` narrows to one comparison."""
    picks=read_picks()
    if comparison_id:picks=[p for p in picks if p['comparison_id']==comparison_id]
    picks.sort(key=lambda p:p.get('time') or '',reverse=True)
    return {'picks':picks}

@app.post('/compare/picks')
async def post_pick(request:Request):
    """Record which run won a comparison: `runs` (comma-separated or list), `stage` (the compared output), `picked` (run id), `note`.
    One pick per comparison (the same runs and stage); picking again replaces it. Stored in runs/_compare/picks.json."""
    from datetime import datetime,timezone
    data=await body_fields(request);runs=data.get('runs') or []
    if isinstance(runs,str):runs=[r.strip() for r in runs.split(',') if r.strip()]
    runs=[str(r) for r in runs];stage=str(data.get('stage') or '').strip();picked=str(data.get('picked') or '').strip()
    if len(runs)<2 or any(len(r)!=32 or not all(c in '0123456789abcdef' for c in r) for r in runs):return fail(400,'A comparison needs at least two run ids.','Pick two to four runs in the Lab, then choose one.')
    if not stage:return fail(400,'Say which output was compared.','Send stage=<file name>, for example seedance-input.mp4.')
    if picked not in runs:return fail(400,'The picked run is not one of the compared runs.','Choose one of the runs in this comparison.')
    entry={'comparison_id':comparison_id(runs,stage),'runs':sorted(runs),'stage':stage,'picked':picked,'time':datetime.now(timezone.utc).isoformat(timespec='seconds'),'note':str(data.get('note') or '').strip()}
    with picks_lock:
        picks=[p for p in read_picks() if p['comparison_id']!=entry['comparison_id']]+[entry]
        picks_file().parent.mkdir(exist_ok=True);picks_file().write_text(json.dumps({'note':'A/B picks from the Lab compare view, one per comparison (sorted run ids + the compared output).','picks':picks},indent=1))
    return {'pick':entry}

@app.get('/jobs/{ident}/calls')
def get_calls(ident:str):
    folder=hd_folder(ident)
    return {'id':ident,'calls':stages.read_calls(folder),'cost_usd_total':stages.total_cost(folder),'note':stages.costs.NOTE}

@app.post('/jobs/{ident}/estimate')
async def estimate_branch(ident:str,request:Request):
    """Estimated cost of re-running from `stage` with `tool` / `params`; nothing is created."""
    folder=hd_folder(ident);data=await body_fields(request);stage=str(data.get('stage') or '').strip()
    if stage not in stages.STAGES:return fail(400,f'Unknown stage {stage!r}.','Use one of: '+', '.join(stages.STAGES)+'.')
    try:params=parse_params(data.get('params'))
    except ValueError as e:return fail(400,'The params field is not a JSON object.','Send params as JSON, for example {"strict": true}.')
    try:chain,changed=stages.changed_chain(stages.run_info(folder)['run']['chain'],stage,data.get('tool') or None,params)
    except ValueError as e:return fail(400,str(e),'Pick a tool listed by GET /stages for this stage.')
    refused=stages.branch_refusal(folder,stage,chain,runs_root=RUNS)
    if refused:return fail(400,*refused)
    names=rerun_stages(stage);total,paid=estimate_stages(chain,stages.costs.clip_seconds(folder),names)
    return {'id':ident,'stage':stage,'changed':changed,'stages_to_run':names,'estimated_cost_usd':total,'paid':paid,'free':total==0,'note':stages.costs.NOTE}

@app.post('/jobs/{ident}/branch')
async def branch_job(ident:str,request:Request):
    """Change one stage of a run: creates a child run, links the earlier artifacts and re-runs from that stage in the background."""
    folder=hd_folder(ident);data=await body_fields(request);stage=str(data.get('stage') or '').strip();tool=data.get('tool') or None
    if stage not in stages.STAGES:return fail(400,f'Unknown stage {stage!r}.','Use one of: '+', '.join(stages.STAGES)+'.')
    try:params=parse_params(data.get('params'))
    except ValueError:return fail(400,'The params field is not a JSON object.','Send params as JSON, for example {"strict": true}.')
    try:chain,changed=stages.changed_chain(stages.run_info(folder)['run']['chain'],stage,tool,params)
    except ValueError as e:return fail(400,str(e),'Pick a tool listed by GET /stages for this stage.')
    refused=stages.branch_refusal(folder,stage,chain,runs_root=RUNS)
    if refused:return fail(400,*refused)
    names=rerun_stages(stage);estimate,paid=estimate_stages(chain,stages.costs.clip_seconds(folder),names)
    refused=cost_gate(estimate,data.get('confirm_cost'),legacy=False,folder=folder,what=f'Re-running from the {stage} stage')
    if refused is not None:return refused
    return start_branch(folder,stage,tool,params,estimate)

def start_branch(folder,stage,tool,params,estimate):
    """Create the child run and run it from `stage` in a background thread (shared by /branch and the mask wand's /mask/apply)."""
    try:child,chain_data,changed=stages.branch(folder,stage,tool,params,runs_root=RUNS)
    except (ValueError,OSError) as e:return fail(400,'The branch could not be created: '+str(e),'Check that the parent run still has its files, then try again.')
    return run_child(folder,child,chain_data,stage,changed,estimate)

def run_child(folder,child,chain_data,stage,changed,estimate,lead='Branched from '):
    """Run an already created child from `stage` in a background thread (start_branch and the edit layer's save share it)."""
    ident=folder.name
    cid=child.name;jobs[cid]={'state':'running','status':lead+ident+' · '+changed,'id':cid,'parent':ident,'changed':changed,'estimated_cost_usd':estimate}
    write_status(child,jobs[cid])
    def work():
        try:
            stages.run_branch(child,chain_data,stage,lambda s:jobs[cid].update(status=s))
            try:stages.words.refresh_guidance(child)   # the face stage may have re-run: mouth guidance follows the child's own tracking
            except Exception as e:stages.runner.log(child,f'mouth guidance not refreshed: {type(e).__name__}: {e}')
            jobs[cid].update(state='done',status='Preparation complete · input review required' if stage in stages.PREP_STAGES else 'Ready · review the prepared input and create a draft')
        except Exception as e:
            message,fix=stages.runner.plain_error(e);jobs[cid].update(state='error',status=message,fix=fix)
        write_status(child,jobs[cid])
    threading.Thread(target=work,daemon=True).start()
    return jobs[cid]

# ---------------------------------------------------------------- edit layer: pending manual edits (RUNS/_sessions/<id>/), undo/redo, save as one branch

def edit_fail(e):
    return fail(e.status,str(e),e.fix,**e.extra)

def json_field(value,form):
    """A layer / value sent as a JSON string in a form body becomes the object; JSON bodies arrive parsed already."""
    if form and isinstance(value,str):
        try:return json.loads(value)
        except ValueError:return value
    return value

@app.get('/jobs/{ident}/edits')
def get_edits(ident:str):
    """The pending edit layer of a run: {run, rev, layer, can_undo, can_redo, undo_label, redo_label, pending, summary, stale}. Writes nothing."""
    return stages.editlayer.view(RUNS,ident,hd_folder(ident))

@app.put('/jobs/{ident}/edits')
async def put_edits(ident:str,request:Request):
    """Replace the layer `{rev, label, layer}` or one track `{rev, label, track, value}`; 409 with the current rev when `rev` is stale."""
    folder=hd_folder(ident);data=await body_fields(request);form='json' not in request.headers.get('content-type','')
    try:return stages.editlayer.put(RUNS,ident,folder,data.get('rev'),data.get('label'),layer=json_field(data.get('layer'),form),track=data.get('track'),value=json_field(data.get('value'),form))
    except stages.editlayer.EditError as e:return edit_fail(e)

@app.delete('/jobs/{ident}/edits')
def delete_edits(ident:str):
    """Discard the pending edits of a run (the UI asks first)."""
    folder=hd_folder(ident);stages.editlayer.discard(RUNS,ident)
    return stages.editlayer.view(RUNS,ident,folder)

@app.post('/jobs/{ident}/edits/undo')
async def undo_edits(ident:str,request:Request):
    folder=hd_folder(ident);data=await body_fields(request)
    try:return stages.editlayer.step(RUNS,ident,folder,'undo',data.get('rev'))
    except stages.editlayer.EditError as e:return edit_fail(e)

@app.post('/jobs/{ident}/edits/redo')
async def redo_edits(ident:str,request:Request):
    folder=hd_folder(ident);data=await body_fields(request)
    try:return stages.editlayer.step(RUNS,ident,folder,'redo',data.get('rev'))
    except stages.editlayer.EditError as e:return edit_fail(e)

@app.post('/jobs/{ident}/edits/save')
async def save_edits(ident:str,request:Request):
    """Save every pending edit as exactly one new branch run (`{confirm_cost?}`), then close the session. Returns the child job like /branch."""
    folder=hd_folder(ident);data=await body_fields(request)
    try:planned=stages.editlayer.plan(folder,RUNS)
    except stages.editlayer.EditError as e:return edit_fail(e)
    except ValueError as e:return fail(400,'The edits could not be prepared for saving: '+str(e),'Check that this run still has its files, then try again.')
    estimate,paid=estimate_stages(planned['chain'],stages.costs.clip_seconds(folder),rerun_stages(planned['stage']))
    refused=cost_gate(estimate,data.get('confirm_cost'),legacy=False,folder=folder,what='Saving these edits')
    if refused is not None:return refused
    try:child,chain_data,changed,stage=stages.editlayer.save(folder,RUNS,planned)
    except stages.editlayer.EditError as e:return edit_fail(e)
    except (ValueError,OSError) as e:return fail(400,'The new version could not be created: '+str(e),'Check that this run still has its files, then try again; your edits are kept.')
    return run_child(folder,child,chain_data,stage,changed,estimate,lead='Saved edits from ')

# ---------------------------------------------------------------- mask track of the edit layer: preview a click (no propagation), Apply to clip (one pass), Grab hands, problem ticks

def mask_track_error(ident,e,what):
    """Plain errors for the mask track routes; unexpected ones go to the session log, never to the screen raw."""
    if isinstance(e,stages.editlayer.EditError):return edit_fail(e)
    if isinstance(e,stages.OfflineError):return fail(400,str(e),e.fix)
    if isinstance(e,ValueError):return fail(400,str(e),'Fix the clicks or strokes and try again.')
    stages.editlayer.note(RUNS,ident,f'{what} failed: {type(e).__name__}: {e}')
    return fail(500,f'The {what} could not be finished.','Check the edit session log (runs/_sessions/<id>/log.txt) for the reason, then try again.')

@app.post('/jobs/{ident}/edits/mask/preview')
async def mask_track_preview(ident:str,request:Request):
    """What the pending clicks / strokes on one frame select, over the current session mask (free seed step only).
    Body: frame | time, optional points / strokes (else the session's pending ones). Writes runs/_sessions/<id>/mask/previews/."""
    folder=hd_folder(ident);data=await body_fields(request)
    try:frame,n,fps=wand_frame(data,folder);return stages.masktrack.preview(RUNS,ident,folder,frame,points=data.get('points'),strokes=data.get('strokes'))
    except Exception as e:return wand_error(e) if isinstance(e,ValueError) and not isinstance(e,stages.editlayer.EditError) else mask_track_error(ident,e,'mask preview')

@app.post('/jobs/{ident}/edits/mask/apply')
async def mask_track_apply(ident:str,request:Request):
    """Apply every pending mask fix in one pass: `quality` (quick | full), `tool` (local_propagate | sam3_points_fal |
    sam2_points_replicate), `replace` (an applied entry id: re-run it at full quality), `rev`, `confirm_cost`; `estimate_only`
    answers {estimated_cost_usd} without running. Returns the edits view + {apply: {result, video, frames_changed, …}}."""
    folder=hd_folder(ident);data=await body_fields(request)
    try:plan=stages.masktrack.plan_apply(RUNS,ident,folder,data.get('quality'),data.get('tool'),data.get('replace') or None,data.get('rev'))
    except Exception as e:return mask_track_error(ident,e,'mask apply')
    if truthy(data.get('estimate_only')):return {'id':ident,'tool':plan['effective'],'estimated_cost_usd':plan['estimate'],'free':plan['estimate']<=0,'note':stages.costs.NOTE}
    refused=cost_gate(plan['estimate'],data.get('confirm_cost'),legacy=False,folder=folder,what='Applying the mask fixes with '+stages.get_tool('mask',plan['effective']).label if plan['effective'] in stages.masktrack.HOSTED else 'Applying the mask fixes')
    if refused is not None:return refused
    try:return stages.masktrack.run_apply(plan)
    except Exception as e:return mask_track_error(ident,e,'mask apply')

@app.post('/jobs/{ident}/edits/mask/hands')
async def mask_track_hands(ident:str,request:Request):
    """Grab hands (free, local MediaPipe): `source` problems (the flagged frames) | range (`from`, `to`), `rev`.
    Hand regions are OR-ed into the current mask on those frames only. Returns the edits view + {hands: …}."""
    folder=hd_folder(ident);data=await body_fields(request)
    try:plan=stages.masktrack.plan_hands(RUNS,ident,folder,'range' if str(data.get('source') or '')=='range' else 'problems',data.get('from'),data.get('to'),data.get('rev'))
    except Exception as e:return mask_track_error(ident,e,'hands pass')
    try:return stages.masktrack.run_hands(plan)
    except Exception as e:return mask_track_error(ident,e,'hands pass')

@app.get('/jobs/{ident}/mask/problems')
def mask_problems(ident:str):
    """Problem ticks on the current mask (the edit session's latest Apply, else the run's masks):
    {frames: [{frame, kind: jump | limb, note, span}], areas, flagged, median, source, result, thresholds}."""
    folder=hd_folder(ident)
    try:return {'id':ident,**stages.masktrack.problems(RUNS,ident,folder)}
    except Exception as e:
        print(f'mask problems failed for {ident}: {type(e).__name__}: {e}',flush=True)   # a GET writes nothing, not even a log line in the run
        return fail(500,'The mask could not be checked for problems.','Reload the page; if it happens again, check the app log.')

# ---------------------------------------------------------------- mask wand: preview a click, apply edits as a branch at the mask stage, one frame with the outline

WAND_TOOLS=('local_propagate','brush','sam3_points_fal','sam2_points_replicate')

def wand_frame(data,folder):
    """Frame index from `frame` or `time` (seconds) in a request; raises ValueError with a plain sentence."""
    from stages import wand
    if not (folder/'original.mp4').exists():raise ValueError('This run has no prepared clip yet (original.mp4), so there is no frame to show.')
    h,w,n,fps=wand.frame_shape(folder/'original.mp4')
    if data.get('frame') not in (None,''):
        try:frame=int(float(data.get('frame')))
        except (TypeError,ValueError):raise ValueError('The frame must be a whole number.')
    elif data.get('time') not in (None,''):
        try:frame=int(round(float(data.get('time'))*fps))
        except (TypeError,ValueError):raise ValueError('The time must be a number of seconds.')
    else:frame=0
    frame=max(0,min(n-1,frame))
    return frame,n,fps

def wand_error(exc):
    text=str(exc);fix='Pause the video on a frame inside the clip and try again.'
    if 'depth video' in text:fix='Use the Brush, which needs no depth, or prepare the clip with a depth preset first.'
    elif 'original.mp4' in text:fix='Prepare the clip first; the wand works on the prepared video.'
    return fail(400,text,fix)

@app.post('/jobs/{ident}/mask/preview')
async def mask_preview(ident:str,request:Request):
    """What the pending clicks select on one frame (free local tool, no propagation, no branch).
    Body (form or JSON): frame | time, edits (JSON list of {frame, x, y, label}). Returns the overlay PNG's URL under wand-preview/."""
    from stages import wand
    from stages.mask import parse_edits
    folder=hd_folder(ident);data=await body_fields(request)
    try:
        frame,n,fps=wand_frame(data,folder);edits=parse_edits(data.get('edits'))
        here=[e for e in edits if e['frame']==frame]
        name,info=wand.preview_png(folder,frame,here)
    except ValueError as e:return wand_error(e)
    except Exception as e:
        stages.runner.log(folder,f'mask preview failed: {type(e).__name__}: {e}')
        return fail(500,'The preview could not be drawn for this frame.','Check the run\'s log.txt for the reason, then try another frame.')
    return {'id':ident,'url':'/runs/'+ident+'/'+name,**info,'pending_edits':len(edits),'edits_on_this_frame':len(here)}

@app.get('/jobs/{ident}/mask/frame')
def mask_frame(ident:str,i:int|None=None,t:float|None=None):
    """One JPEG of the prepared clip at frame `i` (or time `t`) with the current mask outline, for the wand canvas.
    Headers: X-Frame, X-Frames, X-Fps, X-Width, X-Height, X-Has-Masks, X-Mask-Fraction."""
    from fastapi.responses import Response
    from stages import wand
    folder=hd_folder(ident)
    try:
        frame,n,fps=wand_frame({'frame':i,'time':t},folder);data,info=wand.frame_jpeg(folder,frame)
    except ValueError as e:return wand_error(e)
    except Exception as e:
        stages.runner.log(folder,f'mask frame failed: {type(e).__name__}: {e}')
        return fail(500,'The frame could not be read from the prepared clip.','Check the run\'s log.txt for the reason, then try another frame.')
    headers={'X-Frame':str(info['frame']),'X-Frames':str(info['frames']),'X-Fps':str(info['fps']),'X-Width':str(info['width']),'X-Height':str(info['height']),
             'X-Has-Masks':'1' if info['has_masks'] else '0','X-Mask-Fraction':str(info['mask_fraction']),'Cache-Control':'no-store'}
    return Response(content=data,media_type='image/jpeg',headers=headers)

@app.post('/jobs/{ident}/mask/apply')
async def mask_apply(ident:str,request:Request):
    """Apply mask edits as a branch at the mask stage: `tool` (local_propagate | brush | sam3_points_fal | sam2_points_replicate),
    `edits` (clicks) or `strokes` (brush), `base` (parent | replace), `max_frames`, `source`, `confirm_cost` for the paid tools.
    Returns the child job like POST /jobs/{id}/branch; the UI then opens the child."""
    from stages.mask import parse_edits,parse_strokes
    folder=hd_folder(ident);data=await body_fields(request);tool=str(data.get('tool') or 'local_propagate').strip()
    if tool not in WAND_TOOLS:return fail(400,f'Unknown mask wand tool {tool!r}.','Choose one of: '+', '.join(WAND_TOOLS)+'.')
    if not (folder/'original.mp4').exists():return fail(400,'This run has no prepared clip yet, so there is no mask to fix.','Prepare the clip first (a depth preset), then use the wand on the review screen.')
    if tool!='brush' and not (folder/'depth.mp4').exists():return fail(400,'This run has no depth video, so there is no mask to fix with this tool.','Use the Brush, or prepare the clip with a depth preset (Full body, Expressive, Profile-heavy).')
    params={'base':'replace' if str(data.get('base') or 'parent').strip().lower()=='replace' else 'parent','base_run':ident}
    try:
        from stages import wand
        h,w,n,fps=wand.frame_shape(folder/'original.mp4')
        if tool=='brush':
            strokes=parse_strokes(data.get('strokes'))
            if not strokes:return fail(400,'No brush strokes were sent.','Paint or erase on the frame first, then apply.')
            if any(s['frame_from']>=n for s in strokes):return fail(400,f'A stroke starts after the last frame ({n-1}).','Pause inside the clip and paint again.')
            params['strokes']=json.dumps(strokes)
        else:
            edits=parse_edits(data.get('edits'))
            if not edits:return fail(400,'No clicks were sent.','Click + on a missed region or − on spill first, then apply.')
            bad=[e['frame'] for e in edits if not (0<=e['frame']<n)]
            if bad:return fail(400,f'Click on frame {bad[0]} is outside the clip (0–{n-1}).','Pause inside the clip and click again.')
            params['edits']=json.dumps(edits)
            if tool!='local_propagate':
                params['source']=str(data.get('source') or 'auto');params['prompt']=str(data.get('prompt') or stages.run_info(folder)['run']['chain'].get('mask',{}).get('params',{}).get('prompt') or 'person')
            elif data.get('max_frames') not in (None,''):params['max_frames']=data.get('max_frames')
    except ValueError as e:return fail(400,str(e),'Fix the clicks or strokes and apply again.')
    try:chain,changed=stages.changed_chain(stages.run_info(folder)['run']['chain'],'mask',tool,params)
    except ValueError as e:return fail(400,str(e),'Pick one of the mask wand tools.')
    estimate,paid=estimate_stages(chain,stages.costs.clip_seconds(folder),rerun_stages('mask'))
    refused=cost_gate(estimate,data.get('confirm_cost'),legacy=False,folder=folder,what='Fixing the mask with '+stages.get_tool('mask',tool).label)
    if refused is not None:return refused
    return start_branch(folder,'mask',tool,params,estimate)

@app.get('/costs')
def get_costs():
    return stages.costs.table()

@app.get('/stages')
def get_stages():
    """Stage order and the registry: every tool's name, label, paid / experimental flags and params schema with defaults."""
    return stages.registry()

@app.get('/presets')
def get_presets():
    return {'presets':stages.list_presets()}

@app.post('/presets')
async def post_preset(request:Request):
    """Save a run's chain as a named preset: `name`, `description`, `job` (run id)."""
    data=await body_fields(request);name=str(data.get('name') or '').strip();job=str(data.get('job') or '').strip()
    if not name:return fail(400,'The preset needs a name.','Send a short name such as "Studio talking head".')
    if len(job)!=32 or not all(c in '0123456789abcdef' for c in job) or not (RUNS/job).is_dir():return fail(404,'That run was not found.','Send the 32-character id of an existing run as job.')
    chain={s:{'tool':v.get('tool'),'params':v.get('params') or {}} for s,v in stages.run_info(RUNS/job)['run']['chain'].items()}
    try:preset=stages.save_preset(name,data.get('description') or '',chain,source_run=job)
    except ValueError as e:return fail(400,str(e),'Choose a name that is not one of the built-in presets.')
    return {'preset':preset}

# ---------------------------------------------------------------- words track: transcription, beats, subtitles (stages/words.py, stages/subtitles.py)

def words_fail(e):
    """Plain errors for the words / subtitles / import routes."""
    if isinstance(e,stages.OfflineError):return fail(400,str(e),e.fix)
    return fail(getattr(e,'status',400),str(e),getattr(e,'fix','Try again.'))

def engines_info(folder,seconds):
    out=[]
    for name,spec in stages.words.ENGINES.items():
        problem=stages.words.local_ready() if name=='local' else None
        estimate=stages.costs.price_for('words_fal',seconds) if spec['paid'] else 0.0
        out.append({'name':name,'label':spec['label'],'paid':spec['paid'],'note':spec['note'],'estimated_cost_usd':estimate,'ready':problem is None,
                    'problem':({'message':problem[0],'fix':problem[1]} if problem else None),'offline_blocked':spec['paid'] and stages.offline()})
    return out

@app.get('/jobs/{ident}/words')
def get_words(ident:str):
    """The words the run has right now (pending edits first, else words.json), and the transcription engines with their state and price."""
    folder=hd_folder(ident);words,source,meta=stages.words.current(folder,RUNS);frames,fps,seconds=stages.words.clip_info(folder)
    return {'id':ident,'words':words,'source':source,'meta':meta,'words_file':(folder/'words.json').exists(),'guidance_file':(folder/'mouth-guidance.json').exists(),
            'frames':frames,'fps':fps,'seconds':round(seconds or 0,3),'engines':engines_info(folder,seconds),'default_engine':'local','has_audio':stages.words.audio_source(folder) is not None}

@app.post('/jobs/{ident}/words/transcribe')
async def transcribe_words(ident:str,request:Request):
    """Transcribe the run's audio word by word: `engine` (local = free mlx-whisper | fal = paid), `singing`, `language`,
    `confirm_cost` (fal only), `estimate_only`. Cached by audio sha256; writes words.json + mouth-guidance.json into the
    run only when it has none. Returns {words, engine, cached, written, seconds, …}."""
    folder=hd_folder(ident);data=await body_fields(request)
    engine=str(data.get('engine') or 'local').strip().lower();singing=truthy(data.get('singing'));language=str(data.get('language') or '').strip() or None
    if engine not in stages.words.ENGINES:return fail(400,f'Unknown transcription engine {engine!r}.','Use local (free, on this Mac) or fal (paid).')
    if language and not re.fullmatch(r'[a-z]{2,3}',language):return fail(400,'The language must be a short code such as en or es.','Leave it empty to detect the language.')
    def work():
        prepared=stages.words.prepare(folder)
        cached=stages.words.cache_file(RUNS,prepared[2],engine,singing).exists()
        estimate=0.0 if cached or engine!='fal' else stages.costs.price_for('words_fal',prepared[3])
        return prepared,cached,estimate
    try:prepared,cached,estimate=await run_in_threadpool(work)
    except stages.words.WordsError as e:return words_fail(e)
    if truthy(data.get('estimate_only')):return {'id':ident,'engine':engine,'estimated_cost_usd':estimate,'free':estimate<=0,'cached':cached}
    refused=cost_gate(estimate,data.get('confirm_cost'),legacy=False,folder=folder,what='Transcribing with '+stages.words.ENGINES[engine]['label'])
    if refused is not None:return refused
    try:result=await run_in_threadpool(stages.words.transcribe,folder,RUNS,engine,singing,language,prepared)
    except (stages.words.WordsError,stages.OfflineError) as e:return words_fail(e)
    except Exception as e:
        print(f'transcription failed for {ident}: {type(e).__name__}: {e}',flush=True)
        message=str(e) if 'FAL_KEY' in str(e) else 'The transcription could not be finished.'
        return fail(502 if engine=='fal' else 500,message,'Add FAL_KEY to .env and restart the app.' if 'FAL_KEY' in str(e) else 'Try again; if it happens again, run bash setup-words.sh to repair the local install.')
    d=result['data']
    return {'id':ident,'engine':engine,'engine_label':stages.words.ENGINES[engine]['label'],'engine_name':d.get('engine'),'language':d.get('language'),'singing':d.get('singing'),'words':d['words'],
            'cached':result['cached'],'written':result['written'],'guidance_written':result['guidance_written'],'seconds':result['seconds'],'transcribe_seconds':d.get('seconds'),
            'source':result['source'],'estimated_cost_usd':estimate,'words_file':(folder/'words.json').exists()}

@app.get('/jobs/{ident}/words/beats')
def words_beats(ident:str,pause:float=stages.words.PAUSE):
    """Dialogue beats for the prompt from the run's words (pending edits first): {text, lines, source}. Writes nothing."""
    folder=hd_folder(ident);words,source,_=stages.words.current(folder,RUNS)
    if not words:return fail(404,'This run has no transcript yet, so there are no dialogue beats.','Open the Words track in step 02 and click Transcribe (free), then insert the beats again.')
    return {'id':ident,'source':source,'lines':stages.words.beats(words,max(0.1,min(3.0,pause))),'text':stages.words.beats_text(words,max(0.1,min(3.0,pause))),'words':len(words)}

@app.get('/jobs/{ident}/subtitles.srt')
def subtitles_srt(ident:str):
    """The run's words (pending edits first) as an SRT file download."""
    from fastapi.responses import Response
    folder=hd_folder(ident);words,source,_=stages.words.current(folder,RUNS)
    if not words:return fail(404,'This run has no transcript yet, so there are no subtitles to export.','Open the Words track in step 02 and click Transcribe (free), then export again.')
    return Response(content=stages.subtitles.srt(stages.subtitles.cues(words,stages.subtitles.clip_seconds(folder))).encode('utf-8'),media_type='application/x-subrip',headers={'Content-Disposition':f'attachment; filename="{ident[:8]}-subtitles.srt"','Cache-Control':'no-store'})

@app.get('/jobs/{ident}/subtitles')
def get_subtitles(ident:str):
    """The finish step's burn-in toggle: {burn (off by default), words, cues, up_to_date, finals: [{final, subtitled, exists, url}]}."""
    return stages.subtitles.state(hd_folder(ident),RUNS)

@app.post('/jobs/{ident}/subtitles')
async def post_subtitles(ident:str,request:Request):
    """`burn` true burns the words into every final preview of the run (free, local: final-preview-subtitled.mp4, hd/… when present); false turns it off."""
    folder=hd_folder(ident);data=await body_fields(request)
    try:return await run_in_threadpool(stages.subtitles.set_burn,folder,RUNS,truthy(data.get('burn')))
    except stages.words.WordsError as e:return words_fail(e)
    except Exception as e:
        print(f'subtitle burn-in failed for {ident}: {type(e).__name__}: {e}',flush=True)
        return fail(500,'The subtitles could not be burned into the final.','Try again; the untouched final is still there.')

# ---------------------------------------------------------------- downloads: folder artifacts as a zip

ZIP_ALIASES={'mask':('clean-masks','raw-masks'),'masks':('clean-masks','raw-masks')}
ZIP_ALWAYS={'clean-masks','raw-masks','edit-layer','stages'}

def folder_artifacts(folder):
    """Top-level folders this run's reports list as outputs (plus the mask folders, edit-layer/ and stages/)."""
    names=set(ZIP_ALWAYS)
    for report in stages.all_reports(folder).values():
        for name in (report.get('outputs') or {}):
            if '/' not in name:names.add(name)
    return names

@app.get('/jobs/{ident}/download/{name}')
def download_zip(ident:str,name:str):
    """A known folder artifact of the run as a zip (`mask.zip` = the clean masks as PNGs). Only top-level folders the run lists; no paths."""
    import io,zipfile
    from fastapi.responses import Response
    folder=hd_folder(ident)
    art=name[:-4] if name.endswith('.zip') else ''
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,80}',art):return fail(400,'That download is not allowed.','Use a Download link from the app, for example mask.zip.')
    known=folder_artifacts(folder);choices=ZIP_ALIASES.get(art,(art,))
    target=next((folder/c for c in choices if (c in known or art in ZIP_ALIASES) and (folder/c).is_dir() and not (folder/c).is_symlink()),None)
    if target is None or folder.resolve() not in target.resolve().parents:return fail(404,f'This run has no {art} folder to download.','Open a run that has it (masks exist in depth runs), or download single files from the stage cards.')
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(target.rglob('*')):
            if path.is_file() and not path.is_symlink() and folder.resolve() in path.resolve().parents:z.write(path,f'{art}/{path.relative_to(target).as_posix()}')
    return Response(content=buffer.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{ident[:8]}-{art}.zip"','Cache-Control':'no-store'})

# ---------------------------------------------------------------- Import my own (stages/imports.py): an uploaded file becomes a branch at its stage

@app.post('/jobs/{ident}/import')
def import_own(ident:str,stage:str=Form(''),file:UploadFile|None=File(None),confirm_cost:str|None=Form(None)):
    """Multipart `stage` (depth | mask | face | composite), `file`, `confirm_cost?` → stored as runs/_imports/<sha256>.<ext>, then a
    branch at that stage with the import tool (fitted to the clip; mismatches are warnings). Returns the child job like /branch."""
    from stages import imports
    folder=hd_folder(ident);stage=(stage or '').strip()
    if stage not in imports.ACCEPT:return fail(400,f'Imports go into the depth, mask, face or composite stage, not {stage!r}.','Send stage=depth, mask, face or composite.')
    if file is None or not (file.filename or '').strip():return fail(400,'No file was sent.',f'Choose the file to import first. {imports.HINT[stage]}.')
    if (job_status(ident) or {}).get('state')=='running':return fail(409,'This run is still preparing.','Wait until it finishes, then import.')
    from stages.branch import also_chain
    try:sha,ext,path,size=imports.store(file.file,file.filename,RUNS,stage)
    except imports.ImportError_ as e:return fail(e.status,str(e),e.fix)
    try:imports.check_readable(path,ext,stage)
    except imports.ImportError_ as e:
        path.unlink(missing_ok=True);(path.parent/f'{sha}.json').unlink(missing_ok=True)   # an unreadable file is not kept
        return fail(e.status,str(e),e.fix)
    try:
        stage,tool,params,also,changed=imports.plan(folder,stage,sha,ext,Path(file.filename).name[:120])
        chain,_=stages.changed_chain(stages.run_info(folder)['run']['chain'],stage,tool,params)
        if also:chain,_=also_chain(chain,stage,'',also)
    except imports.ImportError_ as e:return fail(e.status,str(e),e.fix)
    except ValueError as e:return fail(400,'The import could not be prepared: '+str(e),'Check that this run still has its files, then try again.')
    estimate,paid=estimate_stages(chain,stages.costs.clip_seconds(folder),rerun_stages(stage))
    refused=cost_gate(estimate,confirm_cost,legacy=False,folder=folder,what=f'Importing into the {stage} stage')
    if refused is not None:return refused
    try:child,chain_data,chain_changed=stages.branch(folder,stage,tool,params,runs_root=RUNS,also=also or None)
    except (ValueError,OSError) as e:return fail(400,'The branch could not be created: '+str(e),'Check that the parent run still has its files, then try again.')
    run=stages.load_run(child);run.update(changed=changed,imported=imports.imported_stages(chain_data),import_info={'stage':stage,'file':sha,'name':params['name'],'size':size,'chain_changed':chain_changed});stages.save_run(child,run)
    stages.runner.log(child,f'imported {params["name"]} ({size} bytes, sha256 {sha}) into the {stage} stage')
    return run_child(folder,child,chain_data,stage,changed,estimate,lead='Imported into a branch of ')

def resume_saved_generations():
    """Resume collection only: never requeue a paid prediction on restart."""
    from seedance_bridge import wait_and_finish
    for root in RUNS.iterdir():
        if not root.is_dir() or len(root.name)!=32:continue
        for folder,response_file,registry in [(root,'seedance-response.json',jobs),(root/'hd','response.json',hd_jobs)]:
            response=folder/response_file
            if not response.exists() or (folder/'final-preview.mp4').exists():continue
            try:request_id=json.loads(response.read_text()).get('requestId')
            except (ValueError,OSError):continue
            if not request_id:continue
            if stages.offline():   # never poll or touch the run's status.json while offline; the saved request stays resumable
                registry[root.name]={'id':root.name,'state':'error','status':'Saved request '+request_id+' is not being resumed in offline mode (PUPPETEER_OFFLINE=1).','fix':'Start the app without PUPPETEER_OFFLINE to collect it; nothing is resubmitted.'};continue
            registry[root.name]={'id':root.name,'state':'running','status':'Resuming saved request '+request_id}
            def collect_saved(folder=folder,ident=root.name,request_id=request_id,registry=registry):
                try:
                    wait_and_finish(folder,request_id,lambda message:registry[ident].update(status=message))
                    registry[ident].update(state='done',status='Final preview ready · original source audio')
                except Exception as e:registry[ident].update(state='error',status=str(e))
                write_status(folder,registry[ident])
            threading.Thread(target=collect_saved,daemon=True).start()

@app.get('/health')
def health():
    return {'status':'ok','service':'Puppeteer'}
