"""Export MediaPipe's face-mesh connection lists once to static/face-connections.json (run inside .venv-face):

    .venv-face/bin/python face_connections.py

The browser canvas (static/track-face.js) and the local renderer (stages/meshedit.py, main venv, no MediaPipe) draw
from this file, in MediaPipe's own order, so both match mesh_worker.py line for line."""
from pathlib import Path
import json,mediapipe as mp
C=mp.tasks.vision.FaceLandmarksConnections
NAMES={'tessellation':'FACE_LANDMARKS_TESSELATION','lips':'FACE_LANDMARKS_LIPS','left_eye':'FACE_LANDMARKS_LEFT_EYE','right_eye':'FACE_LANDMARKS_RIGHT_EYE',
       'left_eyebrow':'FACE_LANDMARKS_LEFT_EYEBROW','right_eyebrow':'FACE_LANDMARKS_RIGHT_EYEBROW','face_oval':'FACE_LANDMARKS_FACE_OVAL','left_iris':'FACE_LANDMARKS_LEFT_IRIS','right_iris':'FACE_LANDMARKS_RIGHT_IRIS'}
data={'source':'mediapipe '+mp.__version__+' tasks.vision.FaceLandmarksConnections','points':478,**{k:[[c.start,c.end] for c in getattr(C,v)] for k,v in NAMES.items()}}
out=Path(__file__).resolve().parent/'static'/'face-connections.json'
out.write_text('{'+','.join(json.dumps(k)+':'+json.dumps(v,separators=(',',':')) for k,v in data.items())+'}\n')
print(out,{k:len(v) for k,v in data.items() if isinstance(v,list)})
