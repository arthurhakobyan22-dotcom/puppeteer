"""Edit layer: pending manual edits of a run, kept outside the run folder, saved as exactly one branch.

A session for run `<id>` lives in `RUNS/_sessions/<id>/` (never inside the run folder, so the parent is never
written): `session.json` (the layer + undo/redo, below), `log.txt` (one line per preview / apply / hands pass) and
`calls.jsonl` (external calls made while editing); tracks may add sub-folders (`mask/…`). `GET` never writes.

session.json: {version, run, rev, created, updated, base_fingerprint, layer: {mask, mesh, words}, undo: [{label, layer}],
redo: [...]} — newest last, `undo` capped at 200. The layer is plain JSON owned per track; the store only reads it
through the track hooks registered with `register_track(name, hooks)` (see `Track` and docs/TIMELINE-SPEC.md §2.3).

`save(parent, runs_root)` = one `branch()` at the earliest stage any track changes (a words-only session branches at
`prompt`: nothing re-runs), every track's `materialize()` into the child, `edit-layer.json` + `run.json.edits` in the
child, the session log / calls appended to the child's, and the session closed (moved to `saved-<child id>/`). The
caller (app.py) runs the child exactly like any other branch.
"""
from pathlib import Path
import copy,hashlib,json,os,shutil,threading,uuid
from .base import STAGES,fresh,unshare
from .report import now

UNDO_CAP=200
MAX_LAYER_BYTES=2_000_000   # the layer is small JSON; pixel results are files referenced by hash
SESSIONS='_sessions'
TRACKS={}
lock=threading.RLock()

class EditError(ValueError):
    """A plain refusal: `str(e)` is the sentence, `.fix` the suggestion, `.status` the HTTP code, `.extra` more fields."""
    def __init__(self,message,fix,status=400,**extra):
        super().__init__(message);self.fix=fix;self.status=status;self.extra=extra

class Track:
    """Hook interface (all optional; subclass and override). `label` names the track in `changed` ('face' for mesh)."""
    label=None
    empty={}   # the track's value in an empty layer
    def count(self,value):return 0
    def summary(self,value):return []
    def check(self,value,session_dir):return None   # a plain reason (str, or (message, fix)) the session cannot be saved yet
    def change(self,value,parent_folder,session_dir):return None   # None | (stage, tool, params)
    def materialize(self,value,child_folder,session_dir,parent_folder):return None   # write the files the tool reads into the child

def register_track(name,hooks):
    """Register (or replace) a track's server hooks. A later registration of the same name wins (Agents 2–4 replace the stubs)."""
    TRACKS[name]=hooks() if isinstance(hooks,type) else hooks
    return TRACKS[name]

def empty_layer():
    return {name:copy.deepcopy(getattr(hooks,'empty',{})) for name,hooks in TRACKS.items()}

def layer_sha(layer):
    return hashlib.sha256(json.dumps(layer,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()

def session_dir(runs_root,ident):
    return Path(runs_root)/SESSIONS/ident

def fingerprint(folder):
    import mask_review
    try:return mask_review.fingerprint(folder)
    except (ValueError,OSError):return None

def load(runs_root,ident):
    path=session_dir(runs_root,ident)/'session.json'
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):return None
    return data if isinstance(data,dict) and isinstance(data.get('layer'),dict) else None

def write(runs_root,ident,session):
    folder=session_dir(runs_root,ident);folder.mkdir(parents=True,exist_ok=True)
    tmp=folder/('session.json.'+uuid.uuid4().hex[:8]);tmp.write_text(json.dumps(session,ensure_ascii=False,default=str));os.replace(tmp,folder/'session.json')

def new_session(ident,folder):
    return {'version':1,'run':ident,'rev':0,'created':now(),'updated':now(),'base_fingerprint':fingerprint(folder),'layer':empty_layer(),'undo':[],'redo':[]}

def note(runs_root,ident,line):
    """One line in the session log (copied into the child's log.txt on save). Tracks call this for previews / applies / hands passes."""
    from datetime import datetime,timezone
    folder=session_dir(runs_root,ident);folder.mkdir(parents=True,exist_ok=True)
    with (folder/'log.txt').open('a') as f:f.write(datetime.now(timezone.utc).isoformat(timespec='seconds')+' '+str(line).rstrip()+'\n')

def track_value(layer,name):
    hooks=TRACKS[name];value=layer.get(name)
    return copy.deepcopy(getattr(hooks,'empty',{})) if value is None and getattr(hooks,'empty',{}) is not None else value

def counts(layer):
    pending={}
    for name,hooks in TRACKS.items():
        try:pending[name]=max(0,int(hooks.count(track_value(layer,name)) or 0))
        except Exception:pending[name]=0
    pending['total']=sum(pending.values());return pending

def label_of(name):
    return getattr(TRACKS[name],'label',None) or name

def summaries(layer,pending=None):
    """[(track, [lines])] for the tracks with pending edits."""
    pending=pending or counts(layer);out=[]
    for name,hooks in TRACKS.items():
        if not pending.get(name):continue
        try:lines=[str(l) for l in (hooks.summary(track_value(layer,name)) or []) if str(l).strip()]
        except Exception:lines=[]
        out.append((name,lines or [f'{pending[name]} edit'+('s' if pending[name]!=1 else '')]))
    return out

def changed_line(layer,pending=None):
    """'mask: 5 clicks on frames 12–40 applied · face: mesh off 50–52 · words: 3 words edited'"""
    return ' · '.join(f'{label_of(name)}: '+', '.join(lines) for name,lines in summaries(layer,pending))

def view(runs_root,ident,folder,session=None):
    """The GET shape. No session yet → an empty layer, rev 0; nothing is written."""
    session=session or load(runs_root,ident) or {'rev':0,'layer':empty_layer(),'undo':[],'redo':[],'base_fingerprint':None}
    layer={**empty_layer(),**session['layer']};pending=counts(layer)
    base=session.get('base_fingerprint');stale=False
    if base and session.get('rev'):
        current=fingerprint(folder);stale=bool(current and current!=base)
    undo,redo=session.get('undo') or [],session.get('redo') or []
    return {'run':ident,'rev':session.get('rev',0),'layer':layer,'can_undo':bool(undo),'can_redo':bool(redo),'undo_label':undo[-1].get('label') if undo else None,
            'redo_label':redo[-1].get('label') if redo else None,'pending':pending,'summary':[f'{label_of(n)}: '+', '.join(lines) for n,lines in summaries(layer,pending)],'stale':stale}

def check_rev(session,rev):
    if rev in (None,''):return
    try:rev=int(rev)
    except (TypeError,ValueError):raise EditError('The edit revision must be a whole number.','Reload the page and try again.')
    if rev!=session.get('rev',0):raise EditError('These edits changed in another tab or window.','Reload to see the latest edits, then make your change again.',status=409,rev=session.get('rev',0))

def put(runs_root,ident,folder,rev,label,layer=None,track=None,value=None):
    """Replace the whole layer (or only `layer[track]` with `value`); the old layer goes on the undo stack with `label`."""
    if rev in (None,''):raise EditError('The edit revision is missing.','Send rev with the number from GET /jobs/{id}/edits.')
    with lock:
        session=load(runs_root,ident) or new_session(ident,folder);check_rev(session,rev)
        current={**empty_layer(),**session['layer']}
        if track not in (None,''):
            if track not in TRACKS:raise EditError(f'Unknown track {track!r}.','Use one of: '+', '.join(TRACKS)+'.')
            new={**current,track:value}
        else:
            if not isinstance(layer,dict):raise EditError('The edit layer must be a JSON object.','Send layer as {"mask": {...}, "mesh": {...}, "words": null}.')
            unknown=[k for k in layer if k not in TRACKS]
            if unknown:raise EditError(f'Unknown track {unknown[0]!r}.','Use one of: '+', '.join(TRACKS)+'.')
            new={**empty_layer(),**layer}
        if len(json.dumps(new,default=str))>MAX_LAYER_BYTES:raise EditError('These edits are too large to keep.','Keep pixel data in files under the session folder and reference them by hash.',status=413)
        label=str(label or 'Edit').strip()[:200] or 'Edit'
        session['undo']=(session.get('undo') or [])+[{'label':label,'layer':current}];session['undo']=session['undo'][-UNDO_CAP:]
        session.update(layer=new,redo=[],rev=session.get('rev',0)+1,updated=now());write(runs_root,ident,session)
        return view(runs_root,ident,folder,session)

def step(runs_root,ident,folder,direction,rev=None):
    """Undo (`direction='undo'`) or redo the last edit, whatever track it was on (one shared stack)."""
    with lock:
        session=load(runs_root,ident)
        source,target=('undo','redo') if direction=='undo' else ('redo','undo')
        if not session or not session.get(source):raise EditError('There is nothing to undo.' if direction=='undo' else 'There is nothing to redo.','Make an edit first.' if direction=='undo' else 'Redo works right after an undo.')
        check_rev(session,rev)
        entry=session[source].pop();current={**empty_layer(),**session['layer']}
        session[target]=(session.get(target) or [])+[{'label':entry.get('label') or 'Edit','layer':current}];session[target]=session[target][-UNDO_CAP:]
        session.update(layer={**empty_layer(),**entry['layer']},rev=session.get('rev',0)+1,updated=now());write(runs_root,ident,session)
        return view(runs_root,ident,folder,session)

def discard(runs_root,ident):
    """Remove the live session (session.json, log, calls, track folders); records of earlier saves (`saved-*/`) stay."""
    with lock:
        folder=session_dir(runs_root,ident)
        if not folder.exists():return False
        for path in folder.iterdir():
            if path.name.startswith('saved-'):continue
            shutil.rmtree(path,ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
        try:folder.rmdir()
        except OSError:pass
        return True

def plan(parent_folder,runs_root):
    """What a save would do, without touching anything: {stage, tool, params, also, chain, changed, edits_changed, rev, pending}.
    Raises EditError (400) when nothing is pending or a track's check() refuses."""
    from .branch import parent_state,changed_chain,also_chain
    parent_folder=Path(parent_folder);ident=parent_folder.name;session=load(runs_root,ident)
    if not session:raise EditError('There are no edits to save.','Make an edit on the timeline first.')
    layer={**empty_layer(),**session['layer']};pending=counts(layer)
    if not pending['total']:raise EditError('There are no edits to save.','Make an edit on the timeline first, or undo back to one.')
    sdir=session_dir(runs_root,ident);changes=[]
    for name,hooks in TRACKS.items():
        if not pending.get(name):continue
        reason=hooks.check(track_value(layer,name),sdir)
        if reason:
            message,fix=(reason if isinstance(reason,(tuple,list)) else (reason,'Finish or remove those edits, then save again.'))
            raise EditError(str(message),str(fix),track=name)
        found=hooks.change(track_value(layer,name),parent_folder,sdir)
        if found:
            stage,tool,params=found
            if stage not in STAGES:raise EditError(f'The {name} track asked for an unknown stage {stage!r}.','This is a bug in the track; remove its edits to save the others.')
            if any(c[0]==stage for c in changes):raise EditError(f'Two tracks change the {stage} stage.','Save one track\'s edits first, then the other\'s in the new version.')
            changes.append((stage,tool,dict(params or {}),name))
    changes.sort(key=lambda c:STAGES.index(c[0]))
    if changes:stage,tool,params,_=changes[0];also={c[0]:{'tool':c[1],'params':c[2]} for c in changes[1:]}
    else:stage,tool,params,also='prompt',None,None,{}
    run,_=parent_state(parent_folder)
    chain,chain_changed=changed_chain(run['chain'],stage,tool,params)
    if also:chain,chain_changed=also_chain(chain,stage,chain_changed,also)
    return {'stage':stage,'tool':tool,'params':params,'also':also,'chain':chain,'chain_changed':chain_changed,'changed':changed_line(layer,pending),
            'rev':session.get('rev',0),'pending':pending,'tracks':[n for n in TRACKS if pending.get(n)]}

def append_file(source,target):
    """Append `source` to `target` (fresh() first, so a linked file is never written through)."""
    if not Path(source).exists() or not Path(source).stat().st_size:return
    target=Path(target);data=Path(source).read_bytes()
    old=target.read_bytes() if target.exists() else b''
    fresh(target);target.write_bytes(old+(b'' if not old or old.endswith(b'\n') else b'\n')+data)

def save(parent_folder,runs_root,planned=None,preset=None):
    """Create exactly one child for the whole session; returns (child_folder, chain, changed, stage). The child is not run here."""
    from .branch import branch as make_branch
    from .runner import load_run,save_run,log
    parent_folder=Path(parent_folder);ident=parent_folder.name
    with lock:
        current=plan(parent_folder,runs_root)
        if planned is not None and planned.get('rev')!=current['rev']:raise EditError('The edits changed while saving.','Look at the pending edits again, then save.',status=409,rev=current['rev'])
        session=load(runs_root,ident);layer={**empty_layer(),**session['layer']};sdir=session_dir(runs_root,ident)
        child,chain,chain_changed=make_branch(parent_folder,current['stage'],current['tool'],current['params'],runs_root=runs_root,preset=preset,also=current['also'] or None)
        try:
            unshare(child/'edit-layer')   # branch() may have linked the parent's saved edits (for a re-run edit-layer tool); a track writes its own over them
            for name in current['tracks']:TRACKS[name].materialize(track_value(layer,name),child,sdir,parent_folder)
            sha=layer_sha(layer);changed=current['changed'] or chain_changed
            record={'version':1,'run':ident,'child':child.name,'saved':now(),'rev':current['rev'],'layer_sha':sha,'summary':[f'{label_of(n)}: '+', '.join(l) for n,l in summaries(layer)],'changed':changed,
                    'stage':current['stage'],'chain_changed':chain_changed,'layer':layer}
            (child/'edit-layer.json').write_text(json.dumps(record,indent=1,ensure_ascii=False,default=str))
            run=load_run(child);run.update(changed=changed,edits={'summary':record['summary'],'layer_sha':sha,'stage':current['stage'],'chain_changed':chain_changed,'session_rev':current['rev']});save_run(child,run)
            append_file(sdir/'log.txt',child/'log.txt');append_file(sdir/'calls.jsonl',child/'calls.jsonl')
            log(child,f'edits saved from session {ident} rev {current["rev"]}: {changed}')
        except Exception:
            shutil.rmtree(child,ignore_errors=True);raise   # a half-made child is removed; the session stays for another try
        record_dir=sdir/('saved-'+child.name);record_dir.mkdir(parents=True,exist_ok=True)
        for path in list(sdir.iterdir()):
            if path.name.startswith('saved-'):continue
            shutil.move(str(path),str(record_dir/path.name))
        return child,chain,changed,current['stage']

# ---------------------------------------------------------------- built-in track stubs (replaced by Agents 2–4)
# The mask, mesh and words hooks are registered by stages/masktrack.py, stages/meshedit.py and stages/words.py.
