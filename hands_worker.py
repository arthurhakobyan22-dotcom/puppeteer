"""Hand-landmark worker, run inside .venv-face: `python hands_worker.py VIDEO OUT_JSON FRAMES` (FRAMES = "12,13,40").

Used by the timeline's Grab hands (stages/masktrack.py): MediaPipe Hand Landmarker (IMAGE mode, up to 2 hands, low
confidence thresholds) on just the requested frames of the prepared clip. Writes
{"model": "hand_landmarker.task", "frames": {"12": [{"handedness": "Left", "score": 0.93, "points": [[x, y] × 21]}]}}
with x, y normalized to the frame. Free and local; the model is downloaded on first use from Google's
mediapipe-models bucket, like the face model in mesh_worker.py.
"""
from pathlib import Path
import av, mediapipe as mp, numpy as np, sys, json, urllib.request

video=Path(sys.argv[1]);out=Path(sys.argv[2]);wanted={int(f) for f in sys.argv[3].split(',') if f.strip()}
model=Path(__file__).resolve().parent/'models/hand_landmarker.task'
if not model.exists():
    model.parent.mkdir(exist_ok=True)
    temporary=model.with_suffix('.download')
    urllib.request.urlretrieve('https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task',str(temporary))
    temporary.replace(model)
V=mp.tasks.vision
options=V.HandLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),running_mode=V.RunningMode.IMAGE,num_hands=2,
                                min_hand_detection_confidence=0.3,min_hand_presence_confidence=0.3,min_tracking_confidence=0.3)
found={}
with V.HandLandmarker.create_from_options(options) as finder,av.open(str(video)) as inp:
    last=max(wanted) if wanted else -1
    for i,f in enumerate(inp.decode(video=0)):
        if i>last:break
        if i not in wanted:continue
        frame=np.ascontiguousarray(f.to_ndarray(format='rgb24'))
        result=finder.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=frame))
        hands=[]
        for k,landmarks in enumerate(result.hand_landmarks or []):
            side=result.handedness[k][0] if result.handedness and k<len(result.handedness) and result.handedness[k] else None
            hands.append({'handedness':side.category_name if side else None,'score':round(float(side.score),3) if side else None,'points':[[round(l.x,5),round(l.y,5)] for l in landmarks]})
        found[str(i)]=hands
out.write_text(json.dumps({'model':model.name,'frames':found}))
print({'frames':len(wanted),'with_hands':sum(1 for h in found.values() if h)},flush=True)
