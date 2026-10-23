"""External call log and the offline switch.

Every paid or network code path calls `record_call(...)` before any I/O. With `PUPPETEER_OFFLINE=1` that raises
`OfflineError` first, so nothing is sent. Otherwise one line is appended to `runs/<id>/calls.jsonl` and to the
global `runs/calls.log`: `{time, provider, endpoint, stage, tool, cost_usd, ok}`. `ok: true` means the request
was sent; a failure after that is in the run's `log.txt`. Costs are estimates from `stages/costs.py`.
"""
from pathlib import Path
from datetime import datetime,timezone
import json,os,threading
from config import ROOT

GLOBAL_LOG=ROOT/'runs'/'calls.log'
_lock=threading.Lock()
_context={}   # run folder (str) -> (stage, tool), set by the runner while a stage runs

class OfflineError(RuntimeError):
    """Raised before any network I/O when PUPPETEER_OFFLINE is set."""
    fix='Unset PUPPETEER_OFFLINE (or set it to 0) to allow paid and network calls, then run this step again.'

def offline():
    return os.getenv('PUPPETEER_OFFLINE','').strip().lower() in ('1','true','yes','on')

def is_run_folder(folder):
    try:folder=Path(folder)
    except TypeError:return False
    return folder.is_dir() and len(folder.name)==32 and all(c in '0123456789abcdef' for c in folder.name)

def set_context(folder,stage,tool):
    _context[str(Path(folder).resolve())]=(stage,tool)

def clear_context(folder):
    _context.pop(str(Path(folder).resolve()),None)

def current_context(folder):
    try:return _context.get(str(Path(folder).resolve()),(None,None))
    except (TypeError,OSError):return (None,None)

def run_folder_of(path):
    """The run folder a path belongs to (itself, its parent or the `hd/` parent), or None."""
    if path is None:return None
    path=Path(path)
    for candidate in [path,path.parent,path.parent.parent]:
        if is_run_folder(candidate):return candidate
    return None

def record_call(folder,provider,endpoint,stage=None,tool=None,cost_usd=None,ok=True):
    """Log one external call; raise OfflineError first when offline. `folder` may be a run folder, a file in it, or None."""
    label=f'{provider} {endpoint}'.strip()
    if offline():raise OfflineError(f'{label} is switched off in offline mode (PUPPETEER_OFFLINE=1); nothing was sent.')
    run=run_folder_of(folder)
    if stage is None or tool is None:
        context_stage,context_tool=current_context(run) if run else (None,None)
        stage=stage or context_stage;tool=tool or context_tool
    if cost_usd is None:
        from . import costs
        cost_usd=costs.call_cost(provider,endpoint,run)
    entry={'time':datetime.now(timezone.utc).isoformat(timespec='seconds'),'provider':provider,'endpoint':endpoint,'stage':stage,'tool':tool,'cost_usd':round(float(cost_usd or 0),4),'ok':bool(ok)}
    line=json.dumps(entry)
    with _lock:
        if run is not None:
            with (run/'calls.jsonl').open('a') as f:f.write(line+'\n')
        try:
            GLOBAL_LOG.parent.mkdir(parents=True,exist_ok=True)
            with GLOBAL_LOG.open('a') as f:f.write(json.dumps({**entry,'run':run.name if run else None})+'\n')
        except OSError:pass
    return entry

def read_calls(folder):
    path=Path(folder)/'calls.jsonl'
    if not path.exists():return []
    out=[]
    for line in path.read_text().splitlines():
        line=line.strip()
        if not line:continue
        try:out.append(json.loads(line))
        except ValueError:continue
    return out

def total_cost(folder):
    return round(sum(float(c.get('cost_usd') or 0) for c in read_calls(folder)),4)
