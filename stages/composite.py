"""Stage 5, composite: the silent base clip the face stage draws on.

`depth_cutout` wraps `pipeline.composite` unchanged (depth subject over the original background): `mask.mp4`,
`composite.mp4` and the cutout itself, kept as `depth-composite-silent.mp4`. `original` uses the untouched
frames (Fast mode). The face stage always produces the final `composite-silent.mp4` from this base, so a branch
that changes only the face tool re-links the base and never touches the parent's files.
"""
from pathlib import Path
import os,shutil
from .base import Tool,register,fresh

BASE_OF={'depth_cutout':'depth-composite-silent.mp4','original':'original.mp4'}

class DepthCutout(Tool):
    name='depth_cutout';stage='composite';label='Depth subject over original';description='Keeps the depth colors inside the SAM mask and the original frames outside it.'
    inputs=('original.mp4','depth.mp4','clean-masks');outputs=('mask.mp4','composite.mp4','depth-composite-silent.mp4')
    def run(self,inputs,params,folder,status):
        import pipeline
        folder=Path(folder);masks=folder/'clean-masks'
        if not masks.is_dir():masks=folder/'raw-masks'
        for name in self.outputs+('composite-silent.mp4',):fresh(folder/name)
        status('Compositing · depth subject over original background')
        frames=pipeline.composite(folder/'original.mp4',folder/'depth.mp4',masks,folder,inputs.get('source') or folder/'upload.mp4')
        silent=folder/'composite-silent.mp4'
        if silent.exists():os.replace(silent,folder/'depth-composite-silent.mp4')
        return {'outputs':[n for n in self.outputs if (folder/n).exists()],'frames':{'covered':frames,'filled':0,'missing':0},'health':f'Subject cut out over the original background on {frames} frames.' if frames else 'Composite written.'}

class OriginalFrames(Tool):
    name='original';stage='composite';label='Original frames';description='No cutout: the face stage draws on the original video (Fast mode).'
    inputs=('original.mp4',);outputs=()
    def run(self,inputs,params,folder,status):
        return {'outputs':[],'health':'Original frames used as the base; no depth or mask.'}

def base_clip(folder,chain):
    """The clip the face stage draws on, given the composite tool in `chain`."""
    folder=Path(folder);tool=(chain.get('composite') or {}).get('tool','original')
    base=folder/BASE_OF.get(tool,'original.mp4')
    if tool=='depth_cutout' and not base.exists() and (folder/'composite-silent.mp4').exists():base=folder/'composite-silent.mp4'
    return base

register(DepthCutout);register(OriginalFrames)
