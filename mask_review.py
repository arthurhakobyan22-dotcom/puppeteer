"""Mandatory human/agent visual review, bound to the exact prepared assets."""
import hashlib,json
from pathlib import Path
from datetime import datetime,timezone

FILES=('original.mp4','depth.mp4','mask.mp4','composite-silent.mp4','seedance-input.mp4')
def mode_of(folder):
    """The mode saved in workflow-mode.json, or None (legacy depth runs did not write it)."""
    p=Path(folder)/'workflow-mode.json'
    try:return json.loads(p.read_text()).get('mode') if p.exists() else None
    except ValueError:return None

def is_mesh(folder):
    return mode_of(folder) in ['face_mesh','depth_mesh']

def fingerprint(folder):
    digest=hashlib.sha256()
    names=list(('workflow-mode.json','original.mp4','face-landmarks.json','composite-silent.mp4','seedance-input.mp4') if is_mesh(folder) else ('workflow-mode.json','original.mp4','composite-silent.mp4','seedance-input.mp4') if mode_of(folder)=='original' else FILES)
    if is_mesh(folder) and json.loads((Path(folder)/'workflow-mode.json').read_text()).get('mode')=='depth_mesh':names+=['depth.mp4','mask.mp4','depth-composite-silent.mp4']
    for name in names:
        path=Path(folder)/name
        if not path.exists():raise ValueError('Prepare the video and mask before review.')
        digest.update(name.encode())
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def state(folder,job=None):
    """The review state bound to the prepared files.

    `job` (optional) is the run's status dict (`{state, status, fix}`): while the preparation is still running the
    files are not there yet, so the state is `preparing` (not a review problem); when the preparation failed it is
    `failed` with the plain reason and its fix. Only when the job is neither does a missing file mean `unavailable`.
    `approved`, `status`, `note` and `fingerprint` keep their old meaning."""
    path=Path(folder)/'mask-review.json'
    saved=json.loads(path.read_text()) if path.exists() else {}
    try:current=fingerprint(folder)
    except ValueError:
        job=job or {}
        if job.get('state')=='running':return {'approved':False,'status':'preparing','note':'Preparing the clip. '+str(job.get('status') or '').strip(),'fix':None}
        if job.get('state')=='error':return {'approved':False,'status':'failed','note':'Preparation failed: '+(str(job.get('status') or '').strip() or 'no reason was saved'),'fix':job.get('fix') or 'Open the run in Studio and re-run the failed stage.'}
        return {'approved':False,'status':'unavailable','note':'Prepare the video first.','fix':'The prepared files are not in this run yet. Prepare the video, or re-run the stage that did not finish.'}
    if saved.get('fingerprint')!=current:return {'approved':False,'status':'pending','note':'Review the entire prepared input: mask coverage for depth mode; facial tracking and overlay alignment for fast mode.','fingerprint':current}
    return saved

def review(folder,approved,note,expected):
    current=fingerprint(folder)
    if current!=expected:raise ValueError('The mask changed. Reload and review the latest preview.')
    data={'approved':approved,'status':'approved' if approved else 'rejected','note':note,'fingerprint':current,'reviewed_at':datetime.now(timezone.utc).isoformat()}
    path=Path(folder)/'mask-review.json'
    try:
        if path.exists() and path.stat().st_nlink>1:path.unlink()   # a hard-linked copy must not write into the run it came from
    except OSError:pass
    path.write_text(json.dumps(data,indent=2))
    return data

def require_approved(folder):
    if not state(folder).get('approved'):raise ValueError('Input review required: inspect the whole prepared video and approve its current artifacts before submitting.')
