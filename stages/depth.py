"""Stage 3, depth: colored depth video from Depth Anything (`depth-raw.mp4`, copied to `depth.mp4`).

Tools wrap `pipeline.depth_replicate` (lucataco, chenxwh) and `pipeline.depth_hf` unchanged. `off` skips depth
(Fast mode); the composite stage then has to be `original`.
"""
from pathlib import Path
import shutil
from .base import Tool,register,allow_off,fresh

class DepthBase(Tool):
    stage='depth';paid=True;inputs=('original.mp4',);outputs=('depth-raw.mp4','depth.mp4')
    provider=''   # legacy `provider` form value this tool corresponds to
    def generate(self,folder,status):raise NotImplementedError
    def run(self,inputs,params,folder,status):
        folder=Path(folder);fresh(folder/'depth-raw.mp4');fresh(folder/'depth.mp4')
        status('Video Depth Anything · generating depth');self.generate(folder,status)
        if (folder/'depth-raw.mp4').exists():shutil.copyfile(folder/'depth-raw.mp4',folder/'depth.mp4')
        frames=None
        try:
            import av
            with av.open(str(folder/'depth.mp4')) as c:frames=c.streams.video[0].frames or None
        except Exception:pass
        return {'outputs':[n for n in self.outputs if (folder/n).exists()],'frames':{'covered':frames,'filled':0,'missing':0},'health':f'Depth generated with {self.label}'+(f' for {frames} frames.' if frames else '.')}

class DepthReplicate(DepthBase):
    name='depth_anything_replicate';label='Depth Anything on Replicate';provider='replicate';description='lucataco/depth-anything-video on Replicate; exact model colors kept.'
    model='lucataco/depth-anything-video'
    def generate(self,folder,status):
        import pipeline
        pipeline.depth_replicate(folder/'original.mp4',folder/'depth-raw.mp4',self.model)

class DepthReplicateChenxwh(DepthReplicate):
    name='depth_anything_replicate_chenxwh';label='Depth Any Video on Replicate (chenxwh)';provider='replicate-chenxwh';description='chenxwh/depth-any-video on Replicate, an alternative depth model.'
    model='chenxwh/depth-any-video'

class DepthHF(DepthBase):
    name='depth_anything_hf';label='Video Depth Anything on Hugging Face';provider='huggingface';paid=False;description='The public Hugging Face Space (free quota, availability varies).'
    def generate(self,folder,status):
        import pipeline
        pipeline.depth_hf(folder/'original.mp4',folder/'depth-raw.mp4')

register(DepthReplicate);register(DepthReplicateChenxwh);register(DepthHF);allow_off('depth')
BY_PROVIDER={'replicate':'depth_anything_replicate','replicate-chenxwh':'depth_anything_replicate_chenxwh','huggingface':'depth_anything_hf'}
PROVIDER_OF={v:k for k,v in BY_PROVIDER.items()}
