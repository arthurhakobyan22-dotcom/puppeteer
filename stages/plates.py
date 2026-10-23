"""Set plates and style images: the shared asset store under `runs/_assets/` plus the plate-fit maths.

`store_asset(data, filename, runs_root, kind)` keeps an uploaded image content-addressed as `runs/_assets/<sha256[:16]>.<ext>`
(png / jpg / jpeg / webp, at most 30 MB, decoded with PIL so it really is an image) with a small `<sha16>.json` next to it
(original name, kind, size) and returns the asset `name` (`<sha16>.<ext>`). The composite tool copies a plate into the run
as `set-plate.<ext>` so the run folder stays self-contained; the asset store itself is never a tool output.

Fit maths (`fit_rect`): the plate covers the frame (scaled to fill, centred), then `set_fit` `{x, y, scale}` moves it by
frame fractions and scales it around its own centre. `static/slots.js: fitRect()` is the same formula for the preview canvas.
"""
from pathlib import Path
import hashlib,io,json,re
import numpy as np
from PIL import Image

ASSETS='_assets'
MAX_BYTES=30_000_000
EXT={'.png':'PNG','.jpg':'JPEG','.jpeg':'JPEG','.webp':'WEBP'}
KINDS=('set','look')
NAME=re.compile(r'^[0-9a-f]{16}\.(png|jpg|jpeg|webp)$')
FIT_DEFAULT={'x':0.0,'y':0.0,'scale':1.0}
SCALE_RANGE=(0.2,5.0)

class AssetError(ValueError):
    """A plain refusal for the upload route: str(e) is the sentence, .fix the suggestion, .status the HTTP code."""
    def __init__(self,message,fix,status=400):super().__init__(message);self.fix=fix;self.status=status

def assets_dir(runs_root):return Path(runs_root)/ASSETS

def store_asset(data,filename,runs_root,kind='set'):
    """Save an uploaded image into runs/_assets; returns the asset name. `data` is bytes (or a file object)."""
    if hasattr(data,'read'):data=data.read()
    ext=Path(filename or '').suffix.lower()
    if kind not in KINDS:raise AssetError(f'An asset is a set plate or a look image, not {kind!r}.','Send kind=set or kind=look.')
    if ext not in EXT:raise AssetError(f'A {ext or "file without an extension"} cannot be used as a {"set plate" if kind=="set" else "look image"}.','Use a PNG, JPEG or WebP image.')
    if not data:raise AssetError('The file is empty.','Choose the image again and upload it.')
    if len(data)>MAX_BYTES:raise AssetError(f'This image is larger than {MAX_BYTES//1_000_000} MB.','Export a smaller copy (a 1920 px wide JPEG is plenty) and upload that.',status=413)
    try:
        with Image.open(io.BytesIO(data)) as im:im.verify()
        with Image.open(io.BytesIO(data)) as im:width,height=im.size
    except Exception:raise AssetError('This file could not be read as an image.','Use a PNG, JPEG or WebP that opens in an image viewer.')
    sha=hashlib.sha256(data).hexdigest()[:16];name=f'{sha}{ext}';folder=assets_dir(runs_root);folder.mkdir(parents=True,exist_ok=True)
    path=folder/name
    if not path.exists():path.write_bytes(data)
    meta=folder/f'{sha}.json'
    if not meta.exists():meta.write_text(json.dumps({'name':name,'filename':Path(filename).name[:120],'kind':kind,'width':width,'height':height,'size':len(data)}))
    return name

def asset_path(name,runs_root):
    """The stored file for an asset name; ValueError (plain) for anything that is not an asset name."""
    if not NAME.match(str(name or '')):raise ValueError(f'{name!r} is not an asset name (it looks like <16 hex>.<png|jpg|jpeg|webp>).')
    return assets_dir(runs_root)/name

def asset_info(path):
    """{width, height} of an image file."""
    with Image.open(path) as im:return {'width':im.size[0],'height':im.size[1]}

def asset_meta(name,runs_root):
    path=asset_path(name,runs_root)
    try:meta=json.loads((path.parent/(path.stem+'.json')).read_text())
    except (OSError,ValueError):meta={}
    info=asset_info(path) if path.exists() else {}
    return {'name':name,'filename':meta.get('filename') or name,'kind':meta.get('kind') or 'set','size':meta.get('size'),**info,'url':'/assets/'+name}

def list_assets(runs_root,kind=None):
    """Every stored asset (newest first), optionally one kind only."""
    folder=assets_dir(runs_root)
    if not folder.is_dir():return []
    out=[]
    for path in folder.iterdir():
        if not NAME.match(path.name):continue
        try:meta=asset_meta(path.name,runs_root)
        except (OSError,ValueError):continue
        if kind and meta['kind']!=kind:continue
        out.append((path.stat().st_mtime,meta))
    return [m for _,m in sorted(out,key=lambda t:t[0],reverse=True)]

# ---------------------------------------------------------------- fit maths (ported to static/slots.js as fitRect)

def parse_fit(value):
    """`set_fit` as {x, y, scale} with the defaults filled and the numbers clamped; accepts a dict, a JSON string or nothing."""
    data=value
    if isinstance(value,str):
        try:data=json.loads(value) if value.strip() else {}
        except ValueError:data={}
    if not isinstance(data,dict):data={}
    out=dict(FIT_DEFAULT)
    for key in ('x','y','scale'):
        try:out[key]=float(data.get(key,out[key]))
        except (TypeError,ValueError):pass
    out['x']=max(-1.0,min(1.0,out['x']));out['y']=max(-1.0,min(1.0,out['y']));out['scale']=max(SCALE_RANGE[0],min(SCALE_RANGE[1],out['scale']))
    return out

def fit_is_default(fit):
    fit=parse_fit(fit);return all(abs(fit[k]-FIT_DEFAULT[k])<1e-9 for k in FIT_DEFAULT)

def fit_text(fit):
    """Canonical JSON for the `set_fit` param ('' when it is the default), so cache keys are stable."""
    fit=parse_fit(fit)
    return '' if fit_is_default(fit) else json.dumps({k:round(fit[k],4) for k in ('x','y','scale')},separators=(',',':'),sort_keys=True)

def fit_rect(plate_w,plate_h,frame_w,frame_h,fit=None):
    """Where the plate is drawn, in frame pixels: (x0, y0, width, height). Cover the frame (scale to fill, centred), then
    `fit.scale` around the centre and `fit.x` / `fit.y` as fractions of the frame size."""
    fit=parse_fit(fit)
    s=max(frame_w/plate_w,frame_h/plate_h)*fit['scale'];w=plate_w*s;h=plate_h*s
    return ((frame_w-w)/2+fit['x']*frame_w,(frame_h-h)/2+fit['y']*frame_h,w,h)

def render_plate(path,frame_w,frame_h,fit=None):
    """The plate fitted to a frame_h × frame_w RGB canvas (black where the plate does not reach), as a uint8 array."""
    with Image.open(path) as im:plate=im.convert('RGB')
    x0,y0,w,h=fit_rect(plate.size[0],plate.size[1],frame_w,frame_h,fit)
    canvas=Image.new('RGB',(frame_w,frame_h),(0,0,0))
    resized=plate.resize((max(1,int(round(w))),max(1,int(round(h)))),Image.Resampling.LANCZOS)
    canvas.paste(resized,(int(round(x0)),int(round(y0))))
    return np.asarray(canvas,dtype=np.uint8)
