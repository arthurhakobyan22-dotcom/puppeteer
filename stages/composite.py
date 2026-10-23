"""Stage 5, composite: the silent base clip the face stage draws on.

`depth_cutout` wraps `pipeline.composite` unchanged (depth subject over the original background): `mask.mp4`,
`composite.mp4` and the cutout itself, kept as `depth-composite-silent.mp4`. `original` uses the untouched
frames (Fast mode). The face stage always produces the final `composite-silent.mp4` from this base, so a branch
that changes only the face tool re-links the base and never touches the parent's files.

Background (World stage, Agent 1): `depth_cutout` takes `background` = original (today's output, byte for byte) |
full_depth (the whole frame is depth.mp4) | plain (`plain_color` black or gray) | set_image (`set_image`, an asset name
from stages/plates.py, fitted with `set_fit`). Anything but `original` goes through `pipeline.composite_bg`; the plate is
copied into the run as `set-plate.<ext>`. `normalize_params` drops the new keys at their defaults, so a legacy chain's
params stay `{}` and its cache key is unchanged.
"""
from pathlib import Path
import os,shutil
from .base import Tool,register,fresh

BASE_OF={'depth_cutout':'depth-composite-silent.mp4','original':'original.mp4'}
BACKGROUNDS=('original','full_depth','plain','set_image')
BACKGROUND_LABELS={'original':'Original frames','full_depth':'Full depth','plain':'Plain colour','set_image':'Set image'}

class DepthCutout(Tool):
    name='depth_cutout';stage='composite';label='Depth subject over original';description='Keeps the depth colors inside the SAM mask; behind the person: the original frames, the full depth video, a plain colour or a set image.'
    params={'background':{'type':'choice','default':'original','choices':list(BACKGROUNDS),'label':'Background','hint':'What is behind the depth person: the original frames (default), the whole depth video, a plain colour, or a set image.'},
            'plain_color':{'type':'choice','default':'black','choices':['black','gray'],'label':'Plain colour','hint':'Used when the background is plain.'},
            'set_image':{'type':'string','default':'','label':'Set image','hint':'An asset name from the set-plate picker (runs/_assets); used when the background is a set image.'},
            'set_fit':{'type':'string','default':'','label':'Set image fit','hint':'JSON {"x":0,"y":0,"scale":1}: moves (frame fractions) and scales the plate after it is fitted to cover the frame.'}}
    inputs=('original.mp4','depth.mp4','clean-masks');outputs=('mask.mp4','composite.mp4','depth-composite-silent.mp4')
    def normalize_params(self,params):
        """Defaults are dropped (a legacy `{}` stays `{}`); plain_color / set_image / set_fit are kept only for the background that uses them."""
        from . import plates
        merged=super().normalize_params(params);background=merged.get('background') or 'original'
        if background=='original':
            for key in ('background','plain_color','set_image','set_fit'):merged.pop(key,None)
            return merged
        if background!='plain':merged.pop('plain_color',None)
        elif merged.get('plain_color')=='black':merged.pop('plain_color',None)
        if background!='set_image':merged.pop('set_image',None);merged.pop('set_fit',None)
        else:
            merged['set_image']=str(merged.get('set_image') or '')
            fit=plates.fit_text(merged.get('set_fit'))
            if fit:merged['set_fit']=fit
            else:merged.pop('set_fit',None)
        return merged
    def run(self,inputs,params,folder,status):
        import pipeline
        from . import plates
        folder=Path(folder);masks=folder/'clean-masks'
        if not masks.is_dir():masks=folder/'raw-masks'
        for name in self.outputs+('composite-silent.mp4',):fresh(folder/name)
        for old in folder.glob('set-plate.*'):fresh(old);old.unlink(missing_ok=True)
        background=(params or {}).get('background') or 'original';source=inputs.get('source') or folder/'upload.mp4';outputs=list(self.outputs);plate=None
        if background=='original':
            status('Compositing · depth subject over original background')
            frames=pipeline.composite(folder/'original.mp4',folder/'depth.mp4',masks,folder,source)
        else:
            if background=='set_image':
                name=str(params.get('set_image') or '')
                try:asset=plates.asset_path(name,folder.parent)
                except ValueError:asset=None
                if asset is None or not asset.exists():
                    exc=ValueError('The set image for the background is missing'+(f' ({name})' if name else '')+'; nothing was composited.');exc.fix='Upload or pick a set plate in the Background row of the composite card, then re-run from here.';raise exc
                plate=folder/('set-plate'+asset.suffix.lower());shutil.copy2(asset,plate);outputs.append(plate.name)
            status('Compositing · depth subject over '+BACKGROUND_LABELS.get(background,background).lower())
            frames=pipeline.composite_bg(folder/'original.mp4',folder/'depth.mp4',masks,folder,source,background=background,plate=plate,plain=params.get('plain_color') or 'black',fit=plates.parse_fit(params.get('set_fit')))
        silent=folder/'composite-silent.mp4'
        if silent.exists():os.replace(silent,folder/'depth-composite-silent.mp4')
        behind={'original':'the original background','full_depth':'the full depth video','plain':f'a plain {params.get("plain_color") or "black"} background','set_image':'the set image'}[background]
        return {'outputs':[n for n in outputs if (folder/n).exists()],'frames':{'covered':frames,'filled':0,'missing':0},'health':f'Subject cut out over {behind} on {frames} frames.' if frames else 'Composite written.','data':{'background':background}}

class OriginalFrames(Tool):
    name='original';stage='composite';label='Original frames';description='No cutout: the face stage draws on the original video (Fast mode). There is no depth person, so no background to choose.'
    inputs=('original.mp4',);outputs=()
    def run(self,inputs,params,folder,status):
        return {'outputs':[],'health':'Original frames used as the base; no depth or mask.'}

def base_clip(folder,chain):
    """The clip the face stage draws on, given the composite tool in `chain`."""
    folder=Path(folder);tool=(chain.get('composite') or {}).get('tool','original')
    base=folder/BASE_OF.get(tool,'original.mp4')
    if tool=='depth_cutout' and not base.exists() and (folder/'composite-silent.mp4').exists():base=folder/'composite-silent.mp4'
    return base

def background_of(chain):
    """(background, label) of a chain's composite stage; ('none', …) when the composite tool has no depth person."""
    entry=(chain or {}).get('composite') or {}
    if entry.get('tool')!='depth_cutout':return 'none','no cutout (original video)'
    background=(entry.get('params') or {}).get('background') or 'original'
    return background,BACKGROUND_LABELS.get(background,background)

register(DepthCutout);register(OriginalFrames)
