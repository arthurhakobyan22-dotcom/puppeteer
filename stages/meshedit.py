"""Face mesh track of the edit layer (Agent 3): mesh off on ranges, keyframed transform corrections, expression
offsets, the local renderer and the `mesh_edit` face tool (registered in stages/face.py). docs/TIMELINE-SPEC.md §5, §A3.

Layer value (`layer.mesh`), all optional:
  off:  [[a, b], …]                                   inclusive frame ranges drawn without a mesh (the base clip only)
  keys: {"<frame>": {dx, dy, scale, rot}}             transform corrections about the face centroid: dx / dy in normalized
                                                      frame units (1 = the full width / height), scale a factor, rot degrees
                                                      (positive = clockwise on screen)
  expr: {"<frame>": {jaw, smile, pucker, blink_l, blink_r, brow}}   per-frame expression offsets (ranges in RANGES)

`apply(landmarks, mesh, aspect)` is pure (no files, no network) and is what the tool, the tests and, with the same
formulas, the browser canvas (static/meshedit.js) use. Per frame, in pixel-aspect space (x · aspect, y), with the
frame's own unedited points: expressions first (all offsets computed from the unedited points and summed), then the
transform about the centroid of the unedited points 0–467.

Keyframes: a frame with a key uses that key; a frame strictly between two consecutive keys a, b blends them with the
ease-in-out curve e(t) = t²(3 − 2t), t = (f − a) / (b − a) (linear in dx, dy, scale and rot; e(½) = ½, endpoints
exact); a single key affects only its frame; frames before the first or after the last key get no correction.
Expressions apply only on the frames that carry them (a range sets every frame of it; no blending).

Expressions (H = |p152 − p10| face height, d = unit vector from p10 to p152 = "down" of the face, r = d turned to
the face's right on screen = (d.y, −d.x), m = mouth centre = mean of 61, 291, 13, 14):
  jaw 0…1      every point i not in UPPER_LIP moves along d by jaw · JAW_OPEN · H · wv · wl, where
               wv = clamp((v_i − v_c) / (v_14 − v_c), 0, 1) with v = (p − m)·d, v_c = mean v of the corners 61 / 291
               (the lower lip, chin and jaw below the mouth line move, the inner lower lip 14 and everything lower fully)
               and wl = clamp(2 − |(p_i − m)·r| / M, 0, 1), M = half the mouth width (full under the mouth, fading to
               nothing at twice the half-width, so the jaw angles near the ears barely move: a hinge).
               At jaw = 1 the chin (152) and the inner lower lip (14) drop by JAW_OPEN · H = 10 % of the face height.
  smile −1…1   points within SMILE_RADIUS · H of the nearer mouth corner (61 or 291) move by
               smile · H · w · (SMILE_OUT · side · r − SMILE_UP · d), w = (1 − dist / (SMILE_RADIUS · H))², side = the
               corner's side of m along r; at smile = 1 the corners go out by 6 % and up by 4 % of H (−1 = frown).
  pucker 0…1   the 40 lip points (LIPS) move by pucker · (−PUCKER_IN · ((p − m)·r) r + PUCKER_ROUND · ((p − m)·d) d):
               the mouth narrows by 40 % and rounds a little.
  blink_l/_r   0…1: each upper-lid point of the eye contour moves onto its lower-lid partner (EYELIDS):
               u' = u + blink · (l − u); blink = 1 closes the eye. blink_l = MediaPipe LEFT_EYE = the person's left eye
               (on the right of the picture); blink_r = RIGHT_EYE. Iris points 468–477 are not drawn and stay.
  brow −1…1    the 20 eyebrow points (BROWS) move by brow · BROW_UP · H against d (6 % of H at 1; −1 lowers them).

Rendering: `render(folder, landmarks, base_clip)` draws the mesh exactly like mesh_worker.py pass 2 (PIL, same
colours, widths and order from static/face-connections.json, dimmer on frames whose status is not 'tracked') over
`base_clip` → `composite-silent.mp4` + `preview.jpg`. Main venv, no MediaPipe, no network. Agent 4's face import can
call it with any landmarks dict in the face-landmarks.json schema.
"""
from pathlib import Path
from fractions import Fraction
import bisect,copy,json,math,os,re,shutil,uuid
from .editlayer import Track,register_track,EditError,layer_sha
from .base import Tool,register,fresh
from .composite import base_clip

ROOT=Path(__file__).resolve().parents[1]
CONNECTIONS=ROOT/'static'/'face-connections.json'
EXPR=('jaw','smile','pucker','blink_l','blink_r','brow')
RANGES={'jaw':(0.0,1.0),'smile':(-1.0,1.0),'pucker':(0.0,1.0),'blink_l':(0.0,1.0),'blink_r':(0.0,1.0),'brow':(-1.0,1.0)}
TKEYS=('dx','dy','scale','rot');IDENTITY={'dx':0.0,'dy':0.0,'scale':1.0,'rot':0.0}
SCALE=(0.2,5.0);SHIFT=2.0;ROT=180.0     # clamps for a key: scale factor, |dx|/|dy| in frame units, |rot| in degrees
JAW_OPEN=0.10;SMILE_OUT=0.06;SMILE_UP=0.04;SMILE_RADIUS=0.18;PUCKER_IN=0.4;PUCKER_ROUND=0.15;BROW_UP=0.06
FOREHEAD,CHIN=10,152;CORNERS=(61,291);LIP_TOP,LIP_BOTTOM=13,14   # LIP_TOP/LIP_BOTTOM = inner upper / lower lip centre
UPPER_LIP=(61,185,40,39,37,0,267,269,270,409,291,78,191,80,81,82,13,312,311,310,415,308)
LIPS=(61,146,91,181,84,17,314,405,321,375,291,185,40,39,37,0,267,269,270,409,78,95,88,178,87,14,317,402,318,324,308,191,80,81,82,13,312,311,310,415)
EYELIDS={'blink_r':((246,7),(161,163),(160,144),(159,145),(158,153),(157,154),(173,155)),     # (upper, lower) on MediaPipe RIGHT_EYE
         'blink_l':((466,249),(388,390),(387,373),(386,374),(385,380),(384,381),(398,382))}  # MediaPipe LEFT_EYE (the person's left)
BROWS=(46,53,52,65,55,70,63,105,66,107,276,283,282,295,285,300,293,334,296,336)
MESH=468   # points 0–467 are the mesh; 468–477 the irises
COLOURS={'tessellation':(50,170,205),'lips':(255,135,100),'left_eye':(130,255,150),'right_eye':(130,255,150)}   # as mesh_worker.py
DRAW=(('tessellation',1),('lips',2),('left_eye',2),('right_eye',2))   # mesh_worker.py order and widths
DIM=.45

def plural(n,word,many=None):return f'{n} {word if n==1 else (many or word+"s")}'
def clamp(v,lo,hi):return max(lo,min(hi,v))
def num(v,default=0.0):
    if isinstance(v,bool) or v is None or v=='':return default
    try:v=float(v)
    except (TypeError,ValueError):return default
    return v if math.isfinite(v) else default

# ---------------------------------------------------------------- the layer value

def as_int(v):
    """A whole number from an int, an integral float or a digit string; None otherwise (the JS port uses the same rule)."""
    if isinstance(v,bool):return None
    if isinstance(v,int):return v
    if isinstance(v,float):return int(v) if v.is_integer() else None
    if isinstance(v,str) and re.fullmatch(r'-?[0-9]+',v.strip()):return int(v.strip())
    return None

def merge_ranges(ranges):
    out=[]
    for a,b in sorted(ranges):
        if out and a<=out[-1][1]+1:out[-1][1]=max(out[-1][1],b)
        else:out.append([a,b])
    return out

def normalize(mesh):
    """(off ranges merged, keys {frame: {dx, dy, scale, rot}}, expr {frame: {name: value}}) with junk dropped and values clamped."""
    mesh=mesh if isinstance(mesh,dict) else {};ranges=[]
    for r in mesh.get('off') or []:
        if isinstance(r,(list,tuple)) and len(r)==2:
            a,b=as_int(r[0]),as_int(r[1])
            if a is None or b is None:continue
            ranges.append((max(0,min(a,b)),max(a,b)))
    keys={}
    for f,k in (mesh.get('keys') or {}).items() if isinstance(mesh.get('keys'),dict) else []:
        f=as_int(f)
        if f is None or f<0 or not isinstance(k,dict):continue
        keys[f]={'dx':clamp(num(k.get('dx')),-SHIFT,SHIFT),'dy':clamp(num(k.get('dy')),-SHIFT,SHIFT),'scale':clamp(num(k.get('scale'),1.0),*SCALE),'rot':clamp(num(k.get('rot')),-ROT,ROT)}
    expr={}
    for f,e in (mesh.get('expr') or {}).items() if isinstance(mesh.get('expr'),dict) else []:
        f=as_int(f)
        if f is None or f<0 or not isinstance(e,dict):continue
        values={n:clamp(num(e.get(n)),*RANGES[n]) for n in EXPR if num(e.get(n))}
        if values:expr[f]=values
    return merge_ranges(ranges),keys,expr

def off_frames(ranges):return {f for a,b in ranges for f in range(a,b+1)}

def transform_at(keys,frame):
    """The correction on `frame` (dict) or None: its key, the eased blend of the two keys around it, or nothing outside."""
    if not keys:return None
    if frame in keys:return dict(keys[frame])
    ks=sorted(keys)
    if frame<ks[0] or frame>ks[-1]:return None
    i=bisect.bisect_left(ks,frame);a,b=ks[i-1],ks[i];t=(frame-a)/(b-a);e=t*t*(3-2*t)
    return {k:keys[a][k]+(keys[b][k]-keys[a][k])*e for k in TKEYS}

def expr_runs(expr):
    """Consecutive frames with the same expression values count as one edit (a slider on a range = one edit)."""
    runs=[];last=None
    for f in sorted(expr):
        sig=json.dumps(expr[f],sort_keys=True)
        if runs and last==(f-1,sig):runs[-1][1]=f
        else:runs.append([f,f])
        last=(f,sig)
    return runs

def frames_text(ranges):return ', '.join(f'{a}' if a==b else f'{a}–{b}' for a,b in ranges)

# ---------------------------------------------------------------- the edit itself (pure)

def moves(key):return bool(key) and any(key.get(k,IDENTITY[k])!=IDENTITY[k] for k in TKEYS)

def edit_points(points,expr=None,key=None,aspect=1.0):
    """One face: [(x, y)] normalized → edited [(x, y)]. Expressions (from the unedited points) then the transform."""
    if not expr and not moves(key):return [(x,y) for x,y in points]
    A=float(aspect) or 1.0;P=[(x*A,y) for x,y in points];n=len(P)
    out=[list(p) for p in P];touched=set()
    if expr and n>max(BROWS+LIPS):
        f=P[FOREHEAD];c=P[CHIN];dx,dy=c[0]-f[0],c[1]-f[1];H=math.hypot(dx,dy) or 1e-9;d=(dx/H,dy/H);r=(d[1],-d[0])
        m=tuple(sum(P[i][k] for i in (CORNERS[0],CORNERS[1],LIP_TOP,LIP_BOTTOM))/4 for k in (0,1))
        dot=lambda p,u:(p[0]-m[0])*u[0]+(p[1]-m[1])*u[1]
        def move(i,ox,oy):out[i][0]+=ox;out[i][1]+=oy;touched.add(i)
        jaw=expr.get('jaw',0.0)
        if jaw:
            vc=(dot(P[CORNERS[0]],d)+dot(P[CORNERS[1]],d))/2;span=dot(P[LIP_BOTTOM],d)-vc
            if span<=0.02*H:span=0.02*H
            M=abs(dot(P[CORNERS[1]],r)-dot(P[CORNERS[0]],r))/2 or 1e-9;upper=set(UPPER_LIP)
            for i in range(min(n,MESH)):
                if i in upper:continue
                wv=clamp((dot(P[i],d)-vc)/span,0.0,1.0)
                if not wv:continue
                w=wv*clamp(2-abs(dot(P[i],r))/M,0.0,1.0)
                if w:move(i,jaw*JAW_OPEN*H*w*d[0],jaw*JAW_OPEN*H*w*d[1])
        smile=expr.get('smile',0.0)
        if smile:
            R=SMILE_RADIUS*H
            for i in range(min(n,MESH)):
                k=min(CORNERS,key=lambda j:math.hypot(P[i][0]-P[j][0],P[i][1]-P[j][1]));dist=math.hypot(P[i][0]-P[k][0],P[i][1]-P[k][1])
                if dist>=R:continue
                w=(1-dist/R)**2;side=1.0 if dot(P[k],r)>=0 else -1.0
                move(i,smile*H*w*(SMILE_OUT*side*r[0]-SMILE_UP*d[0]),smile*H*w*(SMILE_OUT*side*r[1]-SMILE_UP*d[1]))
        pucker=expr.get('pucker',0.0)
        if pucker:
            for i in LIPS:
                a=dot(P[i],r);b=dot(P[i],d)
                move(i,pucker*(-PUCKER_IN*a*r[0]+PUCKER_ROUND*b*d[0]),pucker*(-PUCKER_IN*a*r[1]+PUCKER_ROUND*b*d[1]))
        for name,pairs in EYELIDS.items():
            blink=expr.get(name,0.0)
            if blink:
                for u,l in pairs:move(u,blink*(P[l][0]-P[u][0]),blink*(P[l][1]-P[u][1]))
        brow=expr.get('brow',0.0)
        if brow:
            for i in BROWS:move(i,-brow*BROW_UP*H*d[0],-brow*BROW_UP*H*d[1])
    if moves(key):
        cx=sum(p[0] for p in P[:MESH])/min(n,MESH);cy=sum(p[1] for p in P[:MESH])/min(n,MESH)
        s=key.get('scale',1.0);a=math.radians(key.get('rot',0.0));cs,sn=math.cos(a)*s,math.sin(a)*s;tx,ty=key.get('dx',0.0)*A,key.get('dy',0.0)
        return [(x/A,y) for x,y in ([cx+cs*(x-cx)-sn*(y-cy)+tx,cy+sn*(x-cx)+cs*(y-cy)+ty] for x,y in out)]
    return [(out[i][0]/A,out[i][1]) if i in touched else (points[i][0],points[i][1]) for i in range(n)]   # untouched points keep their exact values

def apply(landmarks,mesh,aspect=1.0):
    """Edited landmarks: a face-landmarks.json dict (or its `frames` list) in, the same shape out (a new object; the input
    is not changed). Off frames lose their face (status 'off'); edited frames get `edited: true`; the rest are copied."""
    frames=landmarks.get('frames') if isinstance(landmarks,dict) else landmarks
    ranges,keys,expr=normalize(mesh);off=off_frames(ranges);out=[]
    for i,fr in enumerate(frames or []):
        fr=dict(fr);index=int(fr.get('frame',i))
        if index in off:
            fr.update(faces=[],status='off',edited='off');out.append(fr);continue
        key=transform_at(keys,index);e=expr.get(index)
        if fr.get('faces') and (moves(key) or e):
            face=fr['faces'][0];pts=edit_points([(p['x'],p['y']) for p in face],e,key,aspect)
            fr['faces']=[[{'x':x,'y':y} for x,y in pts]]+[f for f in fr['faces'][1:]];fr['edited']=True
        out.append(fr)
    if isinstance(landmarks,dict):
        data={k:copy.deepcopy(v) for k,v in landmarks.items() if k!='frames'};data['frames']=out;return data
    return out

def edited_section(landmarks,mesh,edited=None):
    """What changed, for face-tracking.json and the report: frame lists (off, keyed, transformed, expressions)."""
    ranges,keys,expr=normalize(mesh);frames=landmarks.get('frames') if isinstance(landmarks,dict) else landmarks;n=len(frames or [])
    moved=[i for i in range(n) if moves(transform_at(keys,i))]
    return {'off_frames':sorted(f for f in off_frames(ranges) if f<n),'off_ranges':ranges,'keyed_frames':sorted(keys),'transformed_frames':moved,
            'expression_frames':sorted(expr),'changed_frames':sorted(i for i,fr in enumerate((edited or {}).get('frames') or []) if fr.get('edited')) if edited else None}

def summary_lines(mesh):
    ranges,keys,expr=normalize(mesh);lines=[]
    if ranges:lines.append('mesh off on frame'+('s' if len(ranges)>1 or ranges[0][0]!=ranges[0][1] else '')+' '+frames_text(ranges))
    if keys:lines.append(plural(len(keys),'transform key')+' ('+('frame ' if len(keys)==1 else 'frames ')+', '.join(str(k) for k in sorted(keys))+')')
    if expr:
        runs=expr_runs(expr);names=sorted({n for e in expr.values() for n in e},key=EXPR.index)
        lines.append(', '.join(n.replace('_l',' left').replace('_r',' right') for n in names)+' on frame'+('s' if len(expr)>1 else '')+' '+frames_text(runs))
    return lines

# ---------------------------------------------------------------- local renderer (main venv, PIL; mirrors mesh_worker.py pass 2)

_connections=None
def connections():
    global _connections
    if _connections is None:
        try:_connections=json.loads(CONNECTIONS.read_text())
        except (OSError,ValueError):raise ValueError('static/face-connections.json is missing, so the mesh cannot be drawn. Restore it from the repository (or run .venv-face/bin/python face_connections.py).')
    return _connections

def colour(name,state):
    c=COLOURS[name];return c if state=='tracked' else tuple(int(v*DIM) for v in c)

def draw_face(im,points,state):
    """Draw one face on a PIL image exactly like mesh_worker.py (tessellation 1 px, lips and eyes 2 px)."""
    from PIL import ImageDraw
    d=ImageDraw.Draw(im);conn=connections();pts=[(round(x*im.width),round(y*im.height)) for x,y in points]
    for name,width in DRAW:
        for a,b in conn[name]:
            if a<len(pts) and b<len(pts):d.line([pts[a],pts[b]],fill=colour(name,state),width=width)

def render(folder,landmarks,base_clip,status=lambda s:None,out_name='composite-silent.mp4',preview_name='preview.jpg'):
    """Draw `landmarks` (face-landmarks.json shape) over every frame of `base_clip` into `folder/out_name` (libx264 crf 18,
    yuv420p, 24 fps like mesh_worker.py) and save `preview_name` (the first tracked frame from 30 on). Files are written
    under a temporary name and moved into place, so a hard link shared with another run is never written through.
    Returns {frames, drawn, preview_frame}."""
    import av
    folder=Path(folder);base_clip=Path(base_clip);frames=landmarks.get('frames') if isinstance(landmarks,dict) else landmarks;frames=frames or []
    fps=int(round(num((landmarks or {}).get('fps') if isinstance(landmarks,dict) else 24,24) or 24))
    if not base_clip.exists():raise ValueError(f'The base clip {base_clip.name} is missing, so there is nothing to draw the mesh on. Re-run from the composite stage.')
    statuses=[fr.get('status') for fr in frames]
    preview_frame=next((i for i in range(30,len(statuses)) if statuses[i]=='tracked'),next((i for i,s in enumerate(statuses) if s=='tracked'),0))
    tmp=folder/f'.{out_name}.{uuid.uuid4().hex[:6]}.mp4';drawn=0;count=0;preview=None
    try:
        with av.open(str(base_clip)) as inp,av.open(str(tmp),'w') as out:
            stream=inp.streams.video[0]
            vs=out.add_stream('libx264',rate=fps);vs.width=stream.width;vs.height=stream.height;vs.pix_fmt='yuv420p';vs.options={'crf':'18'}
            for i,f in enumerate(inp.decode(video=0)):
                im=f.to_image().convert('RGB')
                if i<len(frames) and frames[i].get('faces'):
                    draw_face(im,[(p['x'],p['y']) for p in frames[i]['faces'][0]],frames[i].get('status'));drawn+=1
                vf=av.VideoFrame.from_image(im);vf.pts=i;vf.time_base=Fraction(1,fps)
                for pkt in vs.encode(vf):out.mux(pkt)
                if i==preview_frame:preview=im.copy()
                count=i+1
                if i%48==0:status(f'Drawing the edited face mesh · frame {i+1}')
            for pkt in vs.encode():out.mux(pkt)
        fresh(folder/out_name);os.replace(tmp,folder/out_name)
    finally:
        if tmp.exists():tmp.unlink()
    if preview is not None:
        ptmp=folder/f'.{preview_name}.{uuid.uuid4().hex[:6]}.jpg';preview.save(ptmp,format='JPEG');fresh(folder/preview_name);os.replace(ptmp,folder/preview_name)
    return {'frames':count,'drawn':drawn,'preview_frame':preview_frame}

def clip_aspect(path):
    import av
    with av.open(str(path)) as c:s=c.streams.video[0];return (s.width/s.height) if s.height else 1.0

# ---------------------------------------------------------------- the save hook

class MeshTrack(Track):
    label='face';empty={}
    def parts(self,value):return normalize(value)
    def count(self,value):
        ranges,keys,expr=normalize(value);return len(ranges)+len(keys)+len(expr_runs(expr))
    def summary(self,value):return summary_lines(value)
    def check(self,value,session_dir):return None
    def change(self,value,parent_folder,session_dir):
        if not self.count(value):return None
        if not (Path(parent_folder)/'face-landmarks.json').exists():raise EditError('This run has no face mesh, so the face edits cannot be saved.','Discard the face edits, or edit a run made with a face-mesh preset.',track='mesh')
        ranges,keys,expr=normalize(value)
        return ('face','mesh_edit',{'layer_sha':layer_sha({'off':ranges,'keys':{str(k):v for k,v in keys.items()},'expr':{str(k):v for k,v in expr.items()}}),'base_run':Path(parent_folder).name})
    def materialize(self,value,child_folder,session_dir,parent_folder):
        ranges,keys,expr=normalize(value);dst=Path(child_folder)/'edit-layer';dst.mkdir(parents=True,exist_ok=True)
        layer={'off':ranges,'keys':{str(k):v for k,v in sorted(keys.items())},'expr':{str(k):v for k,v in sorted(expr.items())}}
        for name in ('mesh.json','face-landmarks-base.json','face-tracking-base.json'):fresh(dst/name)
        (dst/'mesh.json').write_text(json.dumps({'version':1,'base_run':Path(parent_folder).name,'layer_sha':layer_sha(layer),'summary':summary_lines(layer),'layer':layer},indent=1))
        shutil.copyfile(Path(parent_folder)/'face-landmarks.json',dst/'face-landmarks-base.json')
        if (Path(parent_folder)/'face-tracking.json').exists():shutil.copyfile(Path(parent_folder)/'face-tracking.json',dst/'face-tracking-base.json')

register_track('mesh',MeshTrack)

# ---------------------------------------------------------------- the `mesh_edit` face tool (registered here, after face.py's tools, so mediapipe_mesh stays first)

class MeshEdit(Tool):
    """The face mesh as edited on the timeline (mesh off on ranges, transform keys, expressions), saved with "Save edits".
    MeshTrack.materialize() writes `edit-layer/mesh.json` + `edit-layer/face-landmarks-base.json` into the child before it
    runs; this tool applies the layer, writes the edited face-landmarks.json / face-tracking.json and re-draws the mesh
    locally over the base clip (depth composite, or the original in Fast mode). Free, local, no MediaPipe, no network."""
    name='mesh_edit';stage='face';label='Timeline mesh edits (free)';paid=False
    description='Uses the face mesh you edited on the timeline (mesh off on ranges, moved / scaled / rotated keys, expressions) and re-draws it locally. Free; saved with "Save edits".'
    params={'layer_sha':{'type':'string','default':'','label':'Edit layer','hint':'sha256 of the saved mesh edits (filled in by Save edits).'},
            'base_run':{'type':'string','default':'','label':'Edited run','hint':'The run whose face landmarks were edited.'}}
    inputs=('original.mp4','depth-composite-silent.mp4','edit-layer/mesh.json','edit-layer/face-landmarks-base.json')
    outputs=('composite-silent.mp4','face-landmarks.json','face-tracking.json','preview.jpg')
    def run(self,inputs,params,folder,status):
        from .face import tracking_report
        folder=Path(folder);chain=inputs.get('chain') or {};base=base_clip(folder,chain);src=folder/'edit-layer'
        if base.name=='composite-silent.mp4':raise ValueError('This run has no clean depth composite (depth-composite-silent.mp4) to draw the edited mesh on. Re-run from the composite stage first.')
        if not base.exists():raise ValueError(f'The base clip {base.name} is missing, so the edited mesh has nothing to draw on. Re-run from the composite stage.')
        try:record=json.loads((src/'mesh.json').read_text());landmarks=json.loads((src/'face-landmarks-base.json').read_text())
        except (OSError,ValueError):raise ValueError('The timeline mesh edits are missing from this run (edit-layer/mesh.json, edit-layer/face-landmarks-base.json). Save the edits again from the run you edited.')
        layer=record.get('layer') or {}
        for name in self.outputs:fresh(folder/name)
        status('Face mesh · applying the timeline edits (local, free)')
        edited=apply(landmarks,layer,clip_aspect(base))
        section=edited_section(landmarks,layer,edited)
        (folder/'face-landmarks.json').write_text(json.dumps(edited))
        try:tracking=json.loads((src/'face-tracking-base.json').read_text())
        except (OSError,ValueError):
            from mesh_tracking import evaluate
            st=[fr.get('status') or 'missing' for fr in landmarks.get('frames') or []];depth=base.name!='original.mp4'
            tracking={**evaluate(st,int(landmarks.get('fps') or 24),strict=not depth),'fps':int(landmarks.get('fps') or 24),'missing_frames':[i for i,s in enumerate(st) if s=='missing'],'filled_frames':[i for i,s in enumerate(st) if s=='filled']}
        tracking['edited']={**section,'tool':self.name,'base_run':record.get('base_run') or params.get('base_run'),'layer_sha':params.get('layer_sha') or record.get('layer_sha'),'summary':record.get('summary') or summary_lines(layer),
                            'note':'Base tracking numbers above are unchanged; edited.off_frames are drawn without a mesh (the base clip only).'}
        (folder/'face-tracking.json').write_text(json.dumps(tracking,indent=1))
        drawn=render(folder,edited,base,status)
        result=tracking_report(folder);lines=record.get('summary') or summary_lines(layer)
        result['health']='Face mesh from the timeline edits ('+'; '.join(lines)+') drawn locally on '+plural(drawn['drawn'],'frame')+'. '+(result.get('health') or '')
        result.setdefault('data',{})['edited']=section
        return {'outputs':[n for n in self.outputs if (folder/n).exists()],**result}
    def partial_result(self,folder):
        from .face import tracking_report
        return tracking_report(folder)

register(MeshEdit)
