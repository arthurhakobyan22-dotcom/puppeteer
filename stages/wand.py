"""Mask wand: the free local algorithms, the mask merge rules, the COCO RLE codec and the preview renderers.

Everything here is local and free. The tools in `stages/mask.py` call into this module; `app.py` uses
`preview_png` (what a click would select, no branch) and `frame_jpeg` (one frame with the mask outline).

Coordinates: every edit and stroke is normalized to the prepared clip (`original.mp4`): x and y in 0–1, frame
index from 0 in decode order (24 fps). Masks are 0/255 PNGs named `mask_<frame:05d>.png`, one per frame.

Merge rules (`merge_frame`): include regions are OR-ed into the base mask, exclude regions are subtracted, in
the order the edits were made; `base = replace` starts from an empty mask instead of the parent's.

Local propagation (`local_propagate`): on the clicked frame a region is grown from the click with a fixed-range
flood on the depth frame AND a fixed-range flood on the blurred RGB frame, bounded by a radius. The click point is
then tracked frame to frame with dense optical flow (OpenCV DIS; Farneback reports no motion inside flat regions,
DIS fills them) and the region is regrown around the tracked point in every frame, forward and backward, until the point's depth or colour drifts from the clicked pixel, the
region's area jumps, or `max_frames` is reached. Edges are rougher than SAM's; that is the documented trade-off.
"""
from pathlib import Path
import hashlib,json
import numpy as np

WORK_MAX_SIDE=480          # propagation runs at this resolution (longest side); regions are upscaled to the clip size
FARNEBACK=dict(pyr_scale=0.5,levels=3,winsize=21,iterations=3,poly_n=5,poly_sigma=1.2,flags=0)
DEFAULT_FPS=24

def dense_flow(a,b):
    """Dense flow from gray frame `a` to `b` (for each pixel of a: where it is in b). DIS (medium preset), Farneback when DIS is missing."""
    import cv2
    if hasattr(cv2,'DISOpticalFlow_create'):
        return cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM).calc(a,b,None)
    return cv2.calcOpticalFlowFarneback(a,b,None,**FARNEBACK)

# ---------------------------------------------------------------- COCO run-length encoding (pure numpy / python)

def rle_decode(rle,size=None):
    """Decode a COCO RLE `{counts, size: [h, w]}` (counts as a list of ints or the compressed string) to a bool array (h, w).

    Counts alternate 0-runs and 1-runs over the array flattened in column-major (Fortran) order, as pycocotools does.
    Raises ValueError with a plain reason for anything that does not fit."""
    if isinstance(rle,str):
        try:parsed=json.loads(rle)
        except ValueError:parsed=None
        if isinstance(parsed,dict):rle=parsed
        else:rle={'counts':rle,'size':size}
    if not isinstance(rle,dict):raise ValueError('The mask encoding is not a COCO RLE object ({counts, size}).')
    counts=rle.get('counts');shape=rle.get('size') or size
    if shape is None or len(shape)!=2:raise ValueError('The RLE has no size [height, width].')
    h,w=int(shape[0]),int(shape[1])
    if isinstance(counts,str):counts=rle_counts_from_string(counts)
    elif isinstance(counts,bytes):counts=rle_counts_from_string(counts.decode('ascii'))
    counts=[int(c) for c in (counts or [])]
    total=sum(counts)
    if total!=h*w:raise ValueError(f'The RLE covers {total} pixels but the mask is {w}×{h} = {h*w} pixels.')
    values=np.zeros(len(counts),np.uint8);values[1::2]=1
    flat=np.repeat(values,counts)
    return flat.reshape((w,h)).T.astype(bool)

def rle_encode(mask,compress=True):
    """Encode a bool array as a COCO RLE (`counts` compressed string, or the list of ints with compress=False)."""
    mask=np.asarray(mask).astype(bool);h,w=mask.shape
    flat=mask.T.reshape(-1).astype(np.int8)                       # column-major
    if flat.size==0:counts=[0]
    else:
        change=np.flatnonzero(np.diff(flat))+1
        starts=np.concatenate(([0],change));ends=np.concatenate((change,[flat.size]))
        runs=(ends-starts).tolist()
        counts=([0]+runs) if flat[0]==1 else runs              # counts always start with a 0-run
    return {'size':[h,w],'counts':rle_counts_to_string(counts) if compress else counts}

def rle_counts_to_string(counts):
    """pycocotools `rleToString`: LEB128-style 5-bit groups with delta coding from the second-last count on."""
    out=[]
    for i,count in enumerate(counts):
        x=int(count)
        if i>2:x-=int(counts[i-2])
        more=True
        while more:
            c=x&0x1f;x>>=5
            more=(x!=-1) if (c&0x10) else (x!=0)
            if more:c|=0x20
            out.append(chr(c+48))
    return ''.join(out)

def rle_counts_from_string(text):
    """pycocotools `rleFrString`."""
    counts=[];p=0;n=len(text)
    while p<n:
        x=0;k=0;more=True
        while more:
            if p>=n:raise ValueError('The compressed RLE string ends in the middle of a number.')
            c=ord(text[p])-48;x|=(c&0x1f)<<(5*k);more=bool(c&0x20);p+=1;k+=1
            if not more and (c&0x10):x|=-1<<(5*k)
        if len(counts)>2:x+=counts[-2]
        counts.append(x)
    return counts

# ---------------------------------------------------------------- video and mask I/O

def frame_shape(video):
    """(height, width, frames, fps) of a clip, read with PyAV."""
    import av
    with av.open(str(video)) as c:
        s=c.streams.video[0];rate=s.average_rate or s.guessed_rate or s.base_rate
        n=s.frames or sum(1 for _ in c.decode(video=0))
        return s.height,s.width,n,(float(rate) if rate else DEFAULT_FPS)

def work_scale(h,w):
    return min(1.0,WORK_MAX_SIDE/max(h,w))

def decode_video(video,scale=1.0,gray=False):
    """Every frame of `video` as an RGB (or gray) uint8 array, downscaled by `scale`."""
    import av,cv2
    out=[]
    with av.open(str(video)) as c:
        for f in c.decode(video=0):
            a=f.to_ndarray(format='rgb24')
            if scale<1.0:
                h,w=a.shape[:2];a=cv2.resize(a,(max(2,int(w*scale)),max(2,int(h*scale))),interpolation=cv2.INTER_AREA)
            out.append(cv2.cvtColor(a,cv2.COLOR_RGB2GRAY) if gray else a)
    return out

def decode_frame(video,index):
    """One RGB frame by index (seeks to the nearest keyframe first). Raises IndexError when the clip is shorter."""
    import av
    with av.open(str(video)) as c:
        s=c.streams.video[0];rate=s.average_rate or s.guessed_rate or DEFAULT_FPS
        if index>0 and s.time_base:
            try:c.seek(int(index/float(rate)/s.time_base),stream=s,backward=True,any_frame=False)
            except Exception:c.seek(0)
        for f in c.decode(video=0):
            i=int(round(float(f.time or 0)*float(rate))) if f.time is not None else None
            if i is None or i>=index:return f.to_ndarray(format='rgb24')
    raise IndexError(index)

def mask_dir(folder):
    """The folder of per-frame masks a run uses (clean-masks, else raw-masks), or None."""
    folder=Path(folder)
    for name in ('clean-masks','raw-masks'):
        if (folder/name).is_dir() and any((folder/name).glob('mask_*.png')):return folder/name
    return None

def read_mask(masks,index,shape):
    """Frame `index` of a mask folder as a bool array of `shape` (zeros when the file is missing or the folder is None)."""
    import cv2
    from PIL import Image
    if masks is None:return np.zeros(shape,bool)
    path=Path(masks)/f'mask_{index:05d}.png'
    if not path.exists():return np.zeros(shape,bool)
    a=np.asarray(Image.open(path).convert('L'))
    if a.shape!=tuple(shape):a=cv2.resize(a,(shape[1],shape[0]),interpolation=cv2.INTER_NEAREST)
    return a>127

def write_mask(mask,path):
    from PIL import Image
    Image.fromarray(np.asarray(mask,bool).astype(np.uint8)*255).save(path)

def upscale(region,shape):
    """A work-resolution region to the clip's size (linear then threshold, so edges stay smooth-ish)."""
    import cv2
    region=np.asarray(region)
    if region.shape==tuple(shape):return region.astype(bool)
    return cv2.resize(region.astype(np.float32),(shape[1],shape[0]),interpolation=cv2.INTER_LINEAR)>0.5

def merge_frame(base,regions):
    """Apply [(mode, region)] to `base` in order: include = OR, exclude = subtract. All bool arrays of one shape."""
    out=np.asarray(base,bool).copy()
    for mode,region in regions:
        region=np.asarray(region,bool)
        if mode=='exclude':out&=~region
        else:out|=region
    return out

def outline(mask):
    """Contours of a bool mask, for drawing."""
    import cv2
    contours,_=cv2.findContours(np.asarray(mask,bool).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    return contours

# ---------------------------------------------------------------- the free local algorithm

def _flood(img,px,py,tol):
    import cv2
    h,w=img.shape[:2];mask=np.zeros((h+2,w+2),np.uint8)
    flags=4|cv2.FLOODFILL_MASK_ONLY|cv2.FLOODFILL_FIXED_RANGE|(255<<8)
    cv2.floodFill(np.ascontiguousarray(img),mask,(int(px),int(py)),0,(tol,)*3,(tol,)*3,flags)
    return mask[1:-1,1:-1]>0

def seed_region(rgb,depth,x,y,depth_tol=24,color_tol=32,max_radius=0.35):
    """Region grown from a normalized click on one frame: depth flood AND colour flood, bounded by `max_radius` × height."""
    import cv2
    h,w=depth.shape[:2];px=min(w-1,max(0,int(round(x*w))));py=min(h-1,max(0,int(round(y*h))))
    d=_flood(depth,px,py,depth_tol);c=_flood(cv2.GaussianBlur(rgb,(5,5),0),px,py,color_tol)
    yy,xx=np.ogrid[:h,:w];r=max_radius*h;bound=((xx-px)**2+(yy-py)**2)<=r*r
    region=d&c&bound
    if region.sum()<30:region=d&bound
    if region.sum()<30:
        rr=max(3,int(0.02*h));region=((xx-px)**2+(yy-py)**2)<=rr*rr
    region=cv2.morphologyEx(region.astype(np.uint8),cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    region=cv2.morphologyEx(region,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))>0
    return region,(px,py)

def propagate(rgb,gray,depth,start,px,py,direction,max_frames,*,depth_tol=24,color_tol=32,depth_drift=30,color_drift=60,area_lo=0.3,area_hi=3.0):
    """Track the click point with dense flow and regrow the region in each frame in one direction.

    Returns ({frame: region}, reason) where reason says why it stopped: 'end' (clip start/end), 'max' (max_frames),
    'drift' (the tracked point's depth or colour left the clicked pixel's), 'area' (the region's area jumped)."""
    import cv2
    h,w=gray[0].shape[:2]
    region,_=seed_region(rgb[start],depth[start],px/w,py/h,depth_tol,color_tol)
    ref_d=float(depth[start][py,px]);ref_c=rgb[start][py,px].astype(np.float32);ref_area=max(1.0,float(region.sum()))
    out={};i=start;x,y=float(px),float(py);reason='end'
    while True:
        j=i+direction
        if j<0 or j>=len(gray):reason='end';break
        if abs(j-start)>max_frames:reason='max';break
        flow=dense_flow(gray[i],gray[j])   # for each pixel of frame i: where it is in frame j
        x0,y0=int(round(x)),int(round(y));win=flow[max(0,y0-3):y0+4,max(0,x0-3):x0+4].reshape(-1,2)
        dx,dy=np.median(win,axis=0) if len(win) else (0.0,0.0)
        x=min(w-1,max(0,x+float(dx)));y=min(h-1,max(0,y+float(dy)));qx,qy=int(round(x)),int(round(y))
        d=float(depth[j][qy,qx]);c=rgb[j][qy,qx].astype(np.float32)
        if abs(d-ref_d)>depth_drift or float(np.abs(c-ref_c).sum())>color_drift*3:reason='drift';break
        reg,_=seed_region(rgb[j],depth[j],x/w,y/h,depth_tol,color_tol);area=float(reg.sum())
        if area<area_lo*ref_area or area>area_hi*ref_area:reason='area';break
        out[j]=reg;i=j
    return region,out,reason

def local_propagate(folder,edits,*,max_frames=120,depth_tol=24,color_tol=32,status=lambda s:None):
    """Run every edit on the clip in `folder`: returns ({frame: [(mode, region at work resolution)]}, per-edit notes, (h, w), fps).

    `edits`: [{frame, x, y, label}] with label 1 = include, 0 = exclude, normalized coordinates."""
    import cv2
    folder=Path(folder);original=folder/'original.mp4';depth_video=folder/'depth.mp4'
    if not original.exists():raise ValueError('This run has no prepared clip (original.mp4), so there is nothing to select on.')
    if not depth_video.exists():raise ValueError('This run has no depth video, so the free local wand has nothing to follow. Use the Brush, or run the depth stage first.')
    h,w,n,fps=frame_shape(original);scale=work_scale(h,w)
    status('Mask wand · reading the clip')
    rgb=decode_video(original,scale);depth=decode_video(depth_video,scale,gray=True)
    if len(depth)!=len(rgb):raise ValueError(f'The depth video has {len(depth)} frames but the clip has {len(rgb)}; re-run the depth stage before editing the mask.')
    gray=[cv2.cvtColor(a,cv2.COLOR_RGB2GRAY) for a in rgb]
    wh,ww=gray[0].shape[:2];per_frame={};notes=[]
    for k,edit in enumerate(edits):
        frame=int(edit['frame']);mode='exclude' if int(edit.get('label',1))==0 else 'include'
        if frame<0 or frame>=len(gray):raise ValueError(f'Frame {frame} is outside the clip (0–{len(gray)-1}).')
        px=min(ww-1,max(0,int(round(float(edit['x'])*ww))));py=min(wh-1,max(0,int(round(float(edit['y'])*wh))))
        status(f'Mask wand · edit {k+1} of {len(edits)}: following the {mode} region from frame {frame}')
        region,fwd,why_f=propagate(rgb,gray,depth,frame,px,py,+1,max_frames,depth_tol=depth_tol,color_tol=color_tol)
        _,bwd,why_b=propagate(rgb,gray,depth,frame,px,py,-1,max_frames,depth_tol=depth_tol,color_tol=color_tol)
        regions={frame:region,**fwd,**bwd}
        for f,r in regions.items():per_frame.setdefault(f,[]).append((mode,r))
        first=min(regions);last=max(regions)
        notes.append({'edit':k,'frame':frame,'mode':mode,'first_frame':first,'last_frame':last,'frames':len(regions),'forward_stop':why_f,'backward_stop':why_b,
                      'seed_fraction':round(float(region.mean()),4)})
    return per_frame,notes,(h,w),fps

def stop_words(reason,backward=False):
    return {'end':'the start of the clip' if backward else 'the end of the clip','max':'the frame limit','drift':'where the region changed depth or colour','area':'where the region changed size'}.get(reason,reason)

# ---------------------------------------------------------------- brush

def rasterize_stroke(stroke,shape):
    """A normalized stroke {points: [[x, y], …], radius} as a bool array of `shape` (radius is a fraction of the height)."""
    import cv2
    h,w=shape;canvas=np.zeros((h,w),np.uint8)
    pts=[(int(round(float(x)*w)),int(round(float(y)*h))) for x,y in (stroke.get('points') or [])]
    radius=max(1,int(round(float(stroke.get('radius',0.02))*h)))
    if not pts:return canvas.astype(bool)
    if len(pts)==1:cv2.circle(canvas,pts[0],radius,255,-1)
    else:
        cv2.polylines(canvas,[np.array(pts,np.int32).reshape(-1,1,2)],False,255,thickness=max(1,2*radius),lineType=cv2.LINE_8)
        for p in (pts[0],pts[-1]):cv2.circle(canvas,p,radius,255,-1)
    return canvas>0

def brush_regions(strokes,shape,frames):
    """{frame: [(mode, region)]} for a list of strokes {frame_from, frame_to, mode: paint|erase, points, radius}."""
    per_frame={}
    for stroke in strokes:
        a=int(stroke.get('frame_from',0));b=int(stroke.get('frame_to',a));a,b=max(0,min(a,b)),min(frames-1,max(a,b))
        mode='exclude' if str(stroke.get('mode','paint')).lower() in ('erase','exclude') else 'include'
        region=rasterize_stroke(stroke,shape)
        for f in range(a,b+1):per_frame.setdefault(f,[]).append((mode,region))
    return per_frame

# ---------------------------------------------------------------- writing the result into a run folder

def write_edited_masks(folder,base_masks,per_frame,shape,frames,base='parent',status=lambda s:None):
    """Merge `per_frame` regions into the base masks and write raw-masks/ + clean-masks/ (identical, one PNG per frame).

    Returns {'changed': [frames whose mask changed], 'coverage': {frame: fraction}, 'covered': frames with any mask}."""
    from .base import fresh
    folder=Path(folder);raw=folder/'raw-masks';clean=folder/'clean-masks'
    for d in (raw,clean):fresh(d);d.mkdir(parents=True,exist_ok=True)
    changed=[];coverage={};covered=0
    for i in range(frames):
        before=read_mask(None if base=='replace' else base_masks,i,shape)
        regions=[(mode,upscale(region,shape)) for mode,region in per_frame.get(i,[])]
        after=merge_frame(before,regions) if regions else before
        if regions and not np.array_equal(before,after):changed.append(i);coverage[i]=round(float(after.mean()),4)
        if after.any():covered+=1
        name=f'mask_{i:05d}.png';write_mask(after,raw/name);write_mask(after,clean/name)
        if i%40==0:status(f'Mask wand · writing masks {i+1} of {frames}')
    return {'changed':changed,'coverage':coverage,'covered':covered}

def load_base(runs_root,base_run,folder):
    """The mask folder the edit starts from: the named base run, else the run's parent (run.json), else None."""
    from .runner import load_run
    candidates=[]
    if base_run:candidates.append(Path(runs_root)/str(base_run))
    run=load_run(folder) or {}
    if run.get('parent'):candidates.append(Path(runs_root)/run['parent'])
    for c in candidates:
        if c.is_dir():
            found=mask_dir(c)
            if found is not None:return found,c
    return None,(candidates[0] if candidates else None)

def history(base_folder):
    try:return json.loads((Path(base_folder)/'mask-edits.json').read_text()).get('history') or []
    except (OSError,ValueError,AttributeError,TypeError):return []

# ---------------------------------------------------------------- previews for the UI

def preview_png(folder,frame,edits,*,depth_tol=24,color_tol=32):
    """What the given clicks select on one frame, as a PNG under `<folder>/wand-preview/`; returns (relative name, info).

    The frame is drawn with the current mask outline (green), include selections tinted green and exclude selections
    tinted red. No propagation, no branch."""
    import cv2
    folder=Path(folder);original=folder/'original.mp4';depth_video=folder/'depth.mp4'
    if not original.exists():raise ValueError('This run has no prepared clip (original.mp4) to preview.')
    h,w,n,fps=frame_shape(original)
    if frame<0 or frame>=n:raise ValueError(f'Frame {frame} is outside the clip (0–{n-1}).')
    rgb=decode_frame(original,frame)
    scale=work_scale(h,w);wh,ww=max(2,int(h*scale)),max(2,int(w*scale))
    small=cv2.resize(rgb,(ww,wh),interpolation=cv2.INTER_AREA)
    depth=cv2.cvtColor(cv2.resize(decode_frame(depth_video,frame),(ww,wh),interpolation=cv2.INTER_AREA),cv2.COLOR_RGB2GRAY) if depth_video.exists() else cv2.cvtColor(small,cv2.COLOR_RGB2GRAY)
    base=read_mask(mask_dir(folder),frame,(h,w))
    canvas=rgb.copy().astype(np.float32);info=[]
    for edit in edits:
        if int(edit['frame'])!=frame:continue
        mode='exclude' if int(edit.get('label',1))==0 else 'include'
        region,_=seed_region(small,depth,float(edit['x']),float(edit['y']),depth_tol,color_tol);full=upscale(region,(h,w))
        tint=np.array([40,200,80],np.float32) if mode=='include' else np.array([230,60,50],np.float32)
        canvas[full]=canvas[full]*0.45+tint*0.55
        info.append({'mode':mode,'fraction':round(float(full.mean()),4),'already_in_mask':round(float((full&base).sum()/max(1,full.sum())),3)})
    canvas=canvas.astype(np.uint8)
    cv2.drawContours(canvas,outline(base),-1,(60,255,120),2)
    out=folder/'wand-preview';out.mkdir(exist_ok=True)
    digest=hashlib.sha1(json.dumps([frame,edits],sort_keys=True,default=str).encode()).hexdigest()[:10]
    name=f'preview-{frame:05d}-{digest}.png'
    cv2.imwrite(str(out/name),cv2.cvtColor(canvas,cv2.COLOR_RGB2BGR))
    return 'wand-preview/'+name,{'frame':frame,'frames':n,'fps':fps,'width':w,'height':h,'selections':info,'seconds':round(frame/fps,3)}

def frame_jpeg(folder,frame,quality=85):
    """One frame of the prepared clip with the current mask outline, as JPEG bytes; returns (bytes, info)."""
    import cv2
    folder=Path(folder);original=folder/'original.mp4'
    if not original.exists():raise ValueError('This run has no prepared clip (original.mp4) to show.')
    h,w,n,fps=frame_shape(original)
    if frame<0 or frame>=n:raise ValueError(f'Frame {frame} is outside the clip (0–{n-1}).')
    rgb=decode_frame(original,frame).copy();masks=mask_dir(folder);base=read_mask(masks,frame,(h,w))
    cv2.drawContours(rgb,outline(base),-1,(60,255,120),2)
    ok,buf=cv2.imencode('.jpg',cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR),[int(cv2.IMWRITE_JPEG_QUALITY),quality])
    if not ok:raise ValueError('The frame could not be encoded as JPEG.')
    return bytes(buf),{'frame':frame,'frames':n,'fps':fps,'width':w,'height':h,'has_masks':masks is not None,'mask_fraction':round(float(base.mean()),4),'seconds':round(frame/fps,3)}
