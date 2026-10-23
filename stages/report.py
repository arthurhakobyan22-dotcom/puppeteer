"""Stage reports: `runs/<id>/stages/<stage>/report.json` with a fixed set of keys.

Keys: tool, params, inputs (name -> sha256), outputs (name -> sha256), frames {covered, filled, missing},
gaps (list of {start_s, end_s, ...} ranges in seconds), warnings (plain sentences), health (one plain sentence
for the Studio card), seconds, cost_usd, cached_from (run id or null), started, finished.
Extra keys added by the runner: stage, key (cache key), state (done | cached | off | error), error {message, fix}.
"""
from pathlib import Path
from datetime import datetime,timezone
import json

REPORT_KEYS=('tool','params','inputs','outputs','frames','gaps','warnings','health','seconds','cost_usd','cached_from','started','finished')
EXTRA_KEYS=('stage','key','state','error')

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def new_report(stage,tool,params=None,**extra):
    report={'tool':tool,'params':params or {},'inputs':{},'outputs':{},'frames':{'covered':None,'filled':None,'missing':None},'gaps':[],'warnings':[],'health':'',
            'seconds':None,'cost_usd':0.0,'cached_from':None,'started':None,'finished':None,'stage':stage,'key':None,'state':'pending','error':None}
    report.update(extra)
    return report

def merge_result(report,result):
    """Fold a tool's return value into the report (only known keys; outputs may be a list of names or a dict)."""
    result=result or {}
    for key in ('frames','gaps','warnings','health','seconds','cost_usd','data'):
        if key in result and result[key] is not None:report[key]=result[key]
    outputs=result.get('outputs')
    if isinstance(outputs,(list,tuple)):report['outputs']={name:None for name in outputs}
    elif isinstance(outputs,dict):report['outputs']=dict(outputs)
    return report

def report_path(folder,stage):
    return Path(folder)/'stages'/stage/'report.json'

def write_report(folder,stage,report):
    path=report_path(folder,stage);path.parent.mkdir(parents=True,exist_ok=True)
    ordered={k:report.get(k) for k in REPORT_KEYS};ordered.update({k:report.get(k) for k in EXTRA_KEYS if k in report})
    for k,v in report.items():
        if k not in ordered:ordered[k]=v
    path.write_text(json.dumps(ordered,indent=1,ensure_ascii=False,default=str))
    return path

def read_report(folder,stage):
    path=report_path(folder,stage)
    if not path.exists():return None
    try:return json.loads(path.read_text())
    except ValueError:return None

def all_reports(folder):
    from .base import STAGES
    return {stage:report for stage in STAGES if (report:=read_report(folder,stage)) is not None}

def seconds_ranges(frame_list,fps):
    """Contiguous runs of frame indices as ranges in seconds, for `gaps`."""
    ranges=[];start=None;previous=None
    for i in sorted(int(f) for f in frame_list):
        if start is None:start=i
        elif i!=previous+1:ranges.append({'start_frame':start,'end_frame':previous,'frames':previous-start+1,'start_s':round(start/fps,2),'end_s':round((previous+1)/fps,2)});start=i
        previous=i
    if start is not None:ranges.append({'start_frame':start,'end_frame':previous,'frames':previous-start+1,'start_s':round(start/fps,2),'end_s':round((previous+1)/fps,2)})
    return ranges

def describe_ranges(ranges):
    return ', '.join(f"{r['start_s']}–{r['end_s']} s" for r in ranges)
