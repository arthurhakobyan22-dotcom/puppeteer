"""Optional local face-mesh preparation; no depth or segmentation calls."""
from pathlib import Path
import json,subprocess,sys,shutil
ROOT=Path(__file__).resolve().parent

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
    from pipeline import normalize
    from audio_workflow import separate,prepare_seedance_video
    folder=Path(folder)
    python=ROOT/'.venv-face/bin/python'
    if not python.exists():raise ValueError('Fast face mesh needs setup: bash setup-face-mesh.sh (Python 3.12).')
    folder.mkdir(parents=True,exist_ok=True)
    status('Normalizing video');normalize(src,folder/'original.mp4')
    status('Tracking face mesh locally · no depth or SAM')
    mesh_worker(folder)
    (folder/'workflow-mode.json').write_text(json.dumps({'mode':'face_mesh'}))
    if clean_dialogue:separate(src,folder,status)
    prepare_seedance_video(folder,clean_dialogue)
    (folder/'manifest.json').write_text(json.dumps({'mode':'face_mesh','clean_dialogue':bool(clean_dialogue)},indent=2))
    status('Face mesh ready · review tracking and embedded audio')


def run_depth(src,folder,prompt='person',provider='replicate',status=print,clean_dialogue=False):
    from pipeline import run as run_advanced
    from audio_workflow import prepare_seedance_video
    folder=Path(folder)
    python=ROOT/'.venv-face/bin/python'
    if not python.exists():raise ValueError('Install face mesh first: bash setup-face-mesh.sh')
    folder.mkdir(parents=True,exist_ok=True)
    run_advanced(src,folder,prompt,provider,status,clean_dialogue)
    shutil.copy2(folder/'composite-silent.mp4',folder/'depth-composite-silent.mp4')
    status('Adding face mesh from original video onto depth composite')
    mesh_worker(folder,'--depth')
    (folder/'workflow-mode.json').write_text(json.dumps({'mode':'depth_mesh'}))
    prepare_seedance_video(folder,clean_dialogue)
    status('Depth + face mesh ready · full mask and facial tracking review required')
