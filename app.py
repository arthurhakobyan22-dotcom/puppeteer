from pathlib import Path
import threading,uuid,shutil,json
from fastapi import FastAPI,UploadFile,File,Form,HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pipeline import run
ROOT=Path(__file__).resolve().parent
RUNS=ROOT/'runs';RUNS.mkdir(exist_ok=True)
from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(_):
    resume_saved_generations();yield
app=FastAPI(lifespan=lifespan);jobs={}
@app.get('/')
def index():return FileResponse(ROOT/'static/index.html')
@app.post('/jobs')
def create(video:UploadFile=File(...),prompt:str=Form('person'),provider:str=Form('replicate'),mode:str=Form('depth'),clean_dialogue:str=Form('')):
    if mode not in ['depth','face_mesh','depth_mesh']:raise HTTPException(400,'Unknown workflow mode')
    clean=clean_dialogue.strip().lower() in ['1','true','on','yes']
    if provider not in ['huggingface','replicate','replicate-chenxwh']:raise HTTPException(400,'Unknown provider')
    ident=uuid.uuid4().hex;folder=RUNS/ident;folder.mkdir();src=folder/'upload.mp4'
    with src.open('wb') as out:shutil.copyfileobj(video.file,out)
    jobs[ident]={'state':'running','status':'Starting','id':ident}
    def work():
        try:
            if mode=='face_mesh':
                from face_mesh import run as run_mesh
                run_mesh(src,folder,lambda s:jobs[ident].update(status=s),clean)
            elif mode=='depth_mesh':
                from face_mesh import run_depth
                run_depth(src,folder,prompt,provider,lambda s:jobs[ident].update(status=s),clean)
            else:run(src,folder,prompt,provider,lambda s:jobs[ident].update(status=s),clean)
            jobs[ident].update(state='done',status='Preparation complete · input review required')
            (folder/'status.json').write_text(json.dumps(jobs[ident]))
        except Exception as e:
            jobs[ident].update(state='error',status=str(e))
            (folder/'status.json').write_text(json.dumps(jobs[ident]))
    threading.Thread(target=work,daemon=True).start();return jobs[ident]
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
    return {'id':ident,'mode':mode,'state':status.get('state','unknown'),'status':str(status.get('status',''))[:200],
            'created':datetime.datetime.fromtimestamp(stamp).astimezone().isoformat(timespec='minutes'),
            'reviewed':(folder/'mask-review.json').exists(),'draft':(folder/'final-preview.mp4').exists(),'final':(folder/'hd/final-preview.mp4').exists(),'request':(folder/'seedance-response.json').exists()}

@app.get('/jobs')
def list_jobs():
    runs=[run_summary(f) for f in RUNS.iterdir() if f.is_dir() and len(f.name)==32 and all(c in '0123456789abcdef' for c in f.name)]
    runs.sort(key=lambda r:r['created'],reverse=True)
    return {'runs':runs}

@app.get('/jobs/{ident}')
def get(ident:str):
    if ident not in jobs:
        if len(ident)==32 and all(c in '0123456789abcdef' for c in ident) and (RUNS/ident/'status.json').exists():return json.loads((RUNS/ident/'status.json').read_text())
        raise HTTPException(404)
    return jobs[ident]
@app.post('/jobs/{ident}/seedance')
def seedance(ident:str,prompt:str=Form(...),char1:UploadFile=File(...),char2:UploadFile|None=File(None),provider:str=Form('')):
    if len(ident)!=32 or not all(c in '0123456789abcdef' for c in ident):raise HTTPException(404)
    folder=RUNS/ident
    from providers import PROVIDERS
    provider=provider.strip().lower()
    if provider and provider not in PROVIDERS:raise HTTPException(400,'Unknown Seedance provider; choose one of: '+', '.join(PROVIDERS))
    if not (folder/'audio-manifest.json').exists():raise HTTPException(400,'Audio preparation must complete first.')
    from mask_review import require_approved
    try:require_approved(folder)
    except ValueError as e:raise HTTPException(409,str(e))
    paths=[]
    for name,upload in [('char1-reference',char1),('char2-reference',char2)]:
        if upload is None:
            paths.append(None)
            continue
        suffix=Path(upload.filename or '').suffix.lower()
        if suffix not in (['.png','.jpg','.jpeg','.webp','.mp4','.mov','.webm'] if name=='char1-reference' else ['.png','.jpg','.jpeg','.webp']):raise HTTPException(400,'Use an image, or an identity video for Character 1 only.')
        path=folder/(name+suffix)
        with path.open('wb') as f:shutil.copyfileobj(upload.file,f)
        paths.append(path)
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
        (folder/'status.json').write_text(json.dumps(jobs[ident]))
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
def create_hd(ident:str):
    folder=hd_folder(ident)
    with hd_lock:
        previous=get_hd(ident)
        if previous['state'] in ['running','done']:return previous
        if not (folder/'final-preview.mp4').exists():raise HTTPException(400,'Complete and review a draft first.')
        from seedance_bridge import provider_for
        from providers import get_provider
        caps=get_provider(provider_for(folder)).capabilities()
        hd=folder/'hd';hd.mkdir(exist_ok=True)
        hd_jobs[ident]={'state':'running','status':'Submitting approved draft for '+caps['final_resolution'],'id':ident,'provider':caps['name']}
        def save(): (hd/'status.json').write_text(json.dumps(hd_jobs[ident]))
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
    from mask_review import state
    return state(hd_folder(ident))

@app.post('/jobs/{ident}/mask-review')
def save_mask_review(ident:str,approved:bool=Form(...),fingerprint:str=Form(...),note:str=Form('')):
    from mask_review import review
    try:return review(hd_folder(ident),approved,note,fingerprint)
    except ValueError as e:raise HTTPException(409,str(e))

app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

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
            registry[root.name]={'id':root.name,'state':'running','status':'Resuming saved request '+request_id}
            def collect_saved(folder=folder,ident=root.name,request_id=request_id,registry=registry):
                try:
                    wait_and_finish(folder,request_id,lambda message:registry[ident].update(status=message))
                    registry[ident].update(state='done',status='Final preview ready · original source audio')
                except Exception as e:registry[ident].update(state='error',status=str(e))
                (folder/'status.json').write_text(json.dumps(registry[ident]))
            threading.Thread(target=collect_saved,daemon=True).start()

@app.get('/health')
def health():
    return {'status':'ok','service':'Puppeteer'}
