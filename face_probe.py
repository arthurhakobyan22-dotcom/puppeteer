"""Face-size probe for the input doctor, run inside .venv-face: `python face_probe.py VIDEO i,j,k…`.

Prints one JSON line: {"frames": [{"frame": i, "box": [x0, y0, x1, y1] | null, "zoomed": bool}], "detector": "mediapipe"}.
Boxes are normalized to the full frame. When the full frame shows no face, overlapping tiles are searched at
2x (`zoomed: true`): a face found only that way is small. Free and local; the same MediaPipe model the face
stage tracks with, so "the tracker can find this face" is measured by the tracker itself.
"""
from pathlib import Path
import sys,json,av,numpy as np
import mediapipe as mp
from PIL import Image

model=Path(__file__).resolve().parent/'models/face_landmarker.task'
V=mp.tasks.vision

def detect(detector,rgb):
    r=detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(rgb)))
    if not r.face_landmarks:return None
    xs=[l.x for l in r.face_landmarks[0]];ys=[l.y for l in r.face_landmarks[0]]
    return [min(xs),min(ys),max(xs),max(ys)]

def tiles(h,w):
    """3x3 overlapping tiles, each half the frame."""
    th,tw=h//2,w//2
    for fy in (0,0.5,1):
        for fx in (0,0.5,1):
            y0=int((h-th)*fy);x0=int((w-tw)*fx);yield x0,y0,tw,th

def zoomed(detector,rgb):
    h,w=rgb.shape[:2]
    for x0,y0,tw,th in tiles(h,w):
        crop=Image.fromarray(rgb[y0:y0+th,x0:x0+tw]).resize((tw*2,th*2),Image.Resampling.LANCZOS)
        box=detect(detector,np.asarray(crop))
        if box:return [(x0+box[0]*tw)/w,(y0+box[1]*th)/h,(x0+box[2]*tw)/w,(y0+box[3]*th)/h]
    return None

def main():
    video=sys.argv[1];wanted=sorted({int(i) for i in sys.argv[2].split(',') if i.strip()}) if len(sys.argv)>2 else [0]
    if not model.exists():print(json.dumps({'frames':[],'detector':'mediapipe','error':'models/face_landmarker.task is missing; run bash setup-face-mesh.sh'}));return
    options=V.FaceLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),running_mode=V.RunningMode.IMAGE,num_faces=1,
                                    min_face_detection_confidence=0.15,min_face_presence_confidence=0.15)
    out=[]
    with V.FaceLandmarker.create_from_options(options) as detector,av.open(video) as c:
        remaining=set(wanted)
        for i,f in enumerate(c.decode(video=0)):
            if i not in remaining:
                if i>max(wanted):break
                continue
            rgb=f.to_ndarray(format='rgb24');box=detect(detector,rgb);z=False
            if box is None:box=zoomed(detector,rgb);z=box is not None
            out.append({'frame':i,'box':[round(v,4) for v in box] if box else None,'zoomed':z});remaining.discard(i)
            if not remaining:break
    print(json.dumps({'frames':out,'detector':'mediapipe'}))

if __name__=='__main__':main()
