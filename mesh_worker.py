"""Face-mesh worker, run inside .venv-face: `python mesh_worker.py RUN_FOLDER [--depth]`.

Pass 1 tracks the face with a face-first crop: the crop box follows the previous frame's landmarks (padded,
smoothed over a few frames) and falls back to a full-frame detection whenever tracking is lost.
Short gaps are filled by interpolation; pass 2 draws the mesh (dimmer on filled frames) over the original
frames, or over the depth composite with --depth. face-landmarks.json and face-tracking.json are written
before the run is judged, so the review screen can show the numbers even when the run fails.
"""
from pathlib import Path
from fractions import Fraction
import av, mediapipe as mp, numpy as np, sys, json, urllib.request
from PIL import ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mesh_tracking import face_box,smooth_box,fill_gaps,evaluate,map_landmarks,MAX_GAP,PAD

root=Path(sys.argv[1]).resolve();source=root/'original.mp4';FPS=24;depth='--depth' in sys.argv
# A zoomed tracking copy from the input doctor (small face): track on it, map every landmark back to the full frame.
zoom=None
if (root/'tracking-source.mp4').exists() and (root/'tracking-source.json').exists():
    try:zoom=json.loads((root/'tracking-source.json').read_text())
    except ValueError:zoom=None
    if zoom and not (zoom.get('crop') and zoom.get('original')):zoom=None
track_source=root/'tracking-source.mp4' if zoom else source
def option(name,default):
    """`--pad 2.0` / `--max-gap 8` overrides from the face stage; without them the worker behaves as it always did."""
    return type(default)(sys.argv[sys.argv.index(name)+1]) if name in sys.argv else default
PAD_USED=option('--pad',PAD);GAP_USED=option('--max-gap',MAX_GAP)
model=Path(__file__).resolve().parent/'models/face_landmarker.task'
if not model.exists():
    model.parent.mkdir(exist_ok=True)
    temporary=model.with_suffix('.download')
    urllib.request.urlretrieve('https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task',str(temporary))
    temporary.replace(model)
V=mp.tasks.vision
def options(mode):
    return V.FaceLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),running_mode=mode,num_faces=1,
                                   min_face_detection_confidence=0.15,min_face_presence_confidence=0.15,min_tracking_confidence=0.15)

def detect(detector,frame,box,timestamp=None):
    """Run the landmarker on `box` of `frame` (RGB ndarray); return landmarks normalized to the full frame, or None."""
    x0,y0,x1,y1=box;crop=np.ascontiguousarray(frame[y0:y1,x0:x1])
    image=mp.Image(image_format=mp.ImageFormat.SRGB,data=crop)
    result=detector.detect_for_video(image,timestamp) if timestamp is not None else detector.detect(image)
    if not result.face_landmarks:return None
    height,width=frame.shape[:2];w=x1-x0;h=y1-y0
    return [((x0+l.x*w)/width,(y0+l.y*h)/height) for l in result.face_landmarks[0]]

# Pass 1: track.
landmarks=[];sources=[];history=[];box=None;lost=0
with V.FaceLandmarker.create_from_options(options(V.RunningMode.VIDEO)) as tracker,V.FaceLandmarker.create_from_options(options(V.RunningMode.IMAGE)) as finder,av.open(str(track_source)) as inp:
    stream=inp.streams.video[0];W,H=stream.width,stream.height;full=(0,0,W,H)
    for i,f in enumerate(inp.decode(video=0)):
        frame=f.to_ndarray(format='rgb24');points=None;how=None
        if box is not None:
            points=detect(tracker,frame,box,round(i*1000/FPS));how='crop'
            if points is None:points=detect(finder,frame,box);how='crop-redetect'
        if points is None:
            points=detect(finder,frame,full);how='full'
        if points is None:
            lost+=1
            if lost>GAP_USED:box=None;history.clear()   # keep trying the last known box through a short loss
        else:
            lost=0;box=smooth_box(history,face_box(points,W,H,PAD_USED))
        landmarks.append(map_landmarks(points,zoom['crop'],zoom['original']) if (points and zoom) else points);sources.append(how if points else None)

# Fast mode is strict (no fallback for lost frames); Advanced + Face mesh keeps the depth composite where the face is lost.
# --strict / --lenient (from the face stage's `strict` param) override that default.
strict=not depth
if '--strict' in sys.argv:strict=True
if '--lenient' in sys.argv:strict=False
filled,status=fill_gaps(landmarks,GAP_USED);report=evaluate(status,FPS,max_gap=GAP_USED,strict=strict)

# Pass 2: draw.
connections=V.FaceLandmarksConnections
COLOURS={'tess':(50,170,205),'FACE_LANDMARKS_LIPS':(255,135,100),'FACE_LANDMARKS_LEFT_EYE':(130,255,150),'FACE_LANDMARKS_RIGHT_EYE':(130,255,150)}
def colour(name,state):
    c=COLOURS[name];return c if state=='tracked' else tuple(int(v*.45) for v in c)
preview_frame=next((i for i in range(30,len(status)) if status[i]=='tracked'),next((i for i,s in enumerate(status) if s=='tracked'),0))
background=av.open(str(root/'depth-composite-silent.mp4')) if depth else None
try:
    with av.open(str(source)) as inp,av.open(str(root/'composite-silent.mp4'),'w') as out:
        stream=inp.streams.video[0]
        if background is not None:
            bg_stream=background.streams.video[0]
            if bg_stream.frames!=stream.frames or (bg_stream.width,bg_stream.height)!=(stream.width,stream.height):
                raise ValueError('Depth and original frame count or dimensions differ; rebuild the depth composite before overlay.')
            bg_frames=background.decode(video=0)
        vs=out.add_stream('libx264',rate=FPS);vs.width=stream.width;vs.height=stream.height;vs.pix_fmt='yuv420p';vs.options={'crf':'18'}
        for i,f in enumerate(inp.decode(video=0)):
            im=(next(bg_frames) if background is not None else f).to_image().convert('RGB');d=ImageDraw.Draw(im)
            if i<len(filled) and filled[i]:
                pts=[(round(x*im.width),round(y*im.height)) for x,y in filled[i]];state=status[i]
                for c in connections.FACE_LANDMARKS_TESSELATION:d.line([pts[c.start],pts[c.end]],fill=colour('tess',state),width=1)
                for name in ['FACE_LANDMARKS_LIPS','FACE_LANDMARKS_LEFT_EYE','FACE_LANDMARKS_RIGHT_EYE']:
                    for c in getattr(connections,name):d.line([pts[c.start],pts[c.end]],fill=colour(name,state),width=2)
            vf=av.VideoFrame.from_image(im);vf.pts=i;vf.time_base=Fraction(1,FPS)
            for pkt in vs.encode(vf):out.mux(pkt)
            if i==preview_frame:im.save(root/'preview.jpg')
        for pkt in vs.encode():out.mux(pkt)
finally:
    if background is not None:background.close()

(root/'face-landmarks.json').write_text(json.dumps({'fps':FPS,'frames':[
    {'frame':i,'time':round(i/FPS,4),'status':status[i],'source':sources[i],'faces':[[{'x':x,'y':y} for x,y in filled[i]]] if filled[i] else []} for i in range(len(filled))],
    'summary':{k:report[k] for k in ['frames','tracked','filled','missing']}}))
(root/'face-tracking.json').write_text(json.dumps({**report,'fps':FPS,
    'missing_frames':[i for i,s in enumerate(status) if s=='missing'],'filled_frames':[i for i,s in enumerate(status) if s=='filled'],
    'crop':'face-first, padded %.1fx, smoothed; full-frame re-detection when lost'%PAD_USED,
    'tracking_source':'tracking-source.mp4 (zoomed copy from the input doctor, landmarks mapped back to the original frame)' if zoom else 'original.mp4'},indent=1))
print({k:report[k] for k in ['frames','tracked','filled','missing','ok','warning','message']},flush=True)
if not report['ok']:raise RuntimeError('Face tracking gaps: '+report['message'])
