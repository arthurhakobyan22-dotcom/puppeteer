"""Per-stage cache keys and artifact hashing.

key = sha256(stage name, tool name, canonical JSON of the params, sha256 of each input artifact)

Same inputs + tool + params give the same key in any run, so a stage whose key matches an earlier run's can reuse
that run's outputs instead of running (and paying) again.
"""
from pathlib import Path
import hashlib,json

def sha256_file(path,chunk=1024*1024):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(chunk),b''):digest.update(block)
    return digest.hexdigest()

def sha256_tree(folder):
    """One digest for a folder: every file's relative name and sha256, in sorted order."""
    digest=hashlib.sha256();folder=Path(folder)
    for path in sorted(p for p in folder.rglob('*') if p.is_file()):
        digest.update(path.relative_to(folder).as_posix().encode());digest.update(b'\0');digest.update(sha256_file(path).encode());digest.update(b'\n')
    return digest.hexdigest()

def artifact_hash(path):
    """sha256 of a file or folder artifact, or None when it does not exist."""
    path=Path(path)
    if path.is_dir():return sha256_tree(path)
    if path.is_file():return sha256_file(path)
    return None

def hash_artifacts(folder,names):
    """{name: sha256} for the artifacts that exist in `folder` (missing ones are left out)."""
    out={}
    for name in names:
        digest=artifact_hash(Path(folder)/name)
        if digest is not None:out[name]=digest
    return out

def canonical(params):
    return json.dumps(params or {},sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str)

def cache_key(stage,tool,params,input_hashes):
    """input_hashes: {artifact name: sha256}. Order-independent; any change in any part changes the key."""
    material=json.dumps([stage,tool,canonical(params),sorted((input_hashes or {}).items())],separators=(',',':'))
    return hashlib.sha256(material.encode()).hexdigest()

def lookup(runs_root,stage,key,exclude=None):
    """Find a finished run whose `stage` has the same cache key and whose outputs are still intact; return (folder, report) or None."""
    runs_root=Path(runs_root)
    if not runs_root.is_dir():return None
    exclude=Path(exclude).name if exclude else None
    candidates=[]
    for folder in runs_root.iterdir():
        if not folder.is_dir() or len(folder.name)!=32 or folder.name==exclude:continue
        report_path=folder/'stages'/stage/'report.json'
        if not report_path.exists():continue
        try:report=json.loads(report_path.read_text())
        except ValueError:continue
        if report.get('key')!=key or report.get('state') not in ('done','cached'):continue
        candidates.append((report_path.stat().st_mtime,folder,report))
    for _,folder,report in sorted(candidates,key=lambda c:c[0],reverse=True):
        outputs=report.get('outputs') or {}
        if not outputs:continue
        if all(artifact_hash(folder/name)==digest for name,digest in outputs.items()):return folder,report
    return None
