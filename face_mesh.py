"""Optional local face-mesh preparation; no depth or segmentation calls."""
from pathlib import Path
import json,subprocess,sys,shutil
ROOT=Path(__file__).resolve().parent

def tracking_summary(folder):
    """Short 'tracked / filled / missing' line from face-tracking.json, or '' when absent."""
    path=Path(folder)/'face-tracking.json'
    if not path.exists():return ''
    try:t=json.loads(path.read_text())
    except ValueError:return ''
    return f"tracked {t.get('tracked')} / filled {t.get('filled')} / missing {t.get('missing')} of {t.get('frames')} frames"

def mesh_worker(folder,*args):
    """Run the isolated MediaPipe worker; surface its own error line instead of a raw CalledProcessError."""
    python=ROOT/'.venv-face/bin/python'
    result=subprocess.run([str(python),str(ROOT/'mesh_worker.py'),str(folder),*args],capture_output=True,text=True)
    if result.returncode!=0:
        lines=[l for l in (result.stderr or result.stdout).splitlines() if l.strip()]
        message=lines[-1] if lines else 'worker exited with code '+str(result.returncode)
        raise ValueError('Face mesh worker failed: '+message.split(': ',1)[-1][:300])
    return result.stdout

def run(src,folder,status=print,clean_dialogue=False):
    """Fast mode as the `face_mesh` chain: the same artifacts as before, plus run.json and stage reports."""
    from stages.runner import run_mode
    folder=Path(folder)
    python=ROOT/'.venv-face/bin/python'
    if not python.exists():raise ValueError('Fast face mesh needs setup: bash setup-face-mesh.sh (Python 3.12).')
    run_mode('face_mesh',src,folder,status,clean_dialogue=clean_dialogue)
    status('Face mesh ready · '+tracking_summary(folder)+' · review tracking and embedded audio')


def run_depth(src,folder,prompt='person',provider='replicate',status=print,clean_dialogue=False):
    """Advanced + Face mesh as the `depth_mesh` chain (lenient gap rule, mesh over the depth composite)."""
    from stages.runner import run_mode
    folder=Path(folder)
    python=ROOT/'.venv-face/bin/python'
    if not python.exists():raise ValueError('Install face mesh first: bash setup-face-mesh.sh')
    run_mode('depth_mesh',src,folder,status,prompt=prompt,provider=provider,clean_dialogue=clean_dialogue)
    status('Depth + face mesh ready · '+tracking_summary(folder)+' · full mask and facial tracking review required')
