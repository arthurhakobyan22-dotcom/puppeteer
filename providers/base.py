"""Shared provider contract plus the prompt builder, local media checks and result download.

An adapter owns its request payload: `submit_draft` writes `<folder>/seedance-request.json` and
`finalize` writes `<folder>/hd/request.json` (both secret-free). The orchestrator in
`seedance_bridge.py` owns the response, generation and status files.
"""
from pathlib import Path
import json,requests

VIDEO_SUFFIXES=('.mp4','.mov','.webm')
CAPABILITY_KEYS=('name','label','draft_resolution','final_resolution','finalize','finalize_identical','finalize_label','needs_webhook','hosting','max_seconds','video_identity_reference')

class Provider:
    name=''
    label=''
    draft_endpoint=None   # recorded next to the draft request id so `poll` knows which app to query
    final_endpoint=None   # same for the finalize request
    def require_configured(self):
        """Raise ValueError when keys/callbacks are missing; never return or log their values."""
        raise NotImplementedError
    def submit_draft(self,prepared,refs,prompt,*,folder,status=print,task=None):
        """Submit the prepared clip plus `refs={'char1':Path,'char2':Path|None}`; return the provider request id.
        `task` (fal: reference | editing | …) overrides the adapter's default when given; adapters without a task setting ignore it."""
        raise NotImplementedError
    def poll(self,request_id,*,folder):
        """Return {'state': queued|running|done|error, 'status': str, 'result_url': str|None, ...}."""
        raise NotImplementedError
    def finalize(self,request_id,*,folder):
        """Complete the accepted draft at final resolution; return the new request id."""
        raise NotImplementedError
    def capabilities(self):
        raise NotImplementedError

def is_video(path):
    return Path(path).suffix.lower() in VIDEO_SUFFIXES

def build_prompt(prompt,folder,refs):
    """Return (full_prompt, mode); mode is 'multi_reference' when char1 is an identity video, else 'edit'."""
    folder=Path(folder)
    from mask_review import is_mesh
    char1=refs['char1'];char2=refs.get('char2')
    if is_video(char1):
        mode='multi_reference'
        full=prompt+'\n@Video1 is the source edit with the original dialogue embedded. @Video2 defines the primary character\'s visual identity only. Use only @Video1 audio for performance and lip synchronization.'
    else:
        mode='edit'
        full=prompt.replace('@Audio1','the audio embedded in @Video1')+'\n@Video1 is the colored-depth composite with the original dialogue embedded; use its embedded audio for performance and lip synchronization. '+("@Image2 defines the second character's identity only, under the same rules." if char2 else '@Image1 is the only character reference.')
    if is_mesh(folder):
        mesh_mode=json.loads((folder/'workflow-mode.json').read_text()).get('mode')
        description='depth composite with face mesh overlay' if mesh_mode=='depth_mesh' else 'original video with face mesh overlay'
        full=full.replace('colored-depth composite',description)+' Remove all face mesh lines and any depth colors from the output; use them only for expression and lip motion guidance. Replace the entire original identity including hair. Preserve the exact embedded dialogue and timing.'
    return full,mode

def probe_video(path):
    """Duration, size and frame rate of a local clip via PyAV; no network."""
    import av
    with av.open(str(path)) as source:
        stream=source.streams.video[0]
        seconds=float(source.duration/av.time_base) if source.duration else float((stream.duration or 0)*stream.time_base)
        rate=stream.average_rate or stream.guessed_rate or stream.base_rate
        return {'seconds':seconds,'width':stream.width,'height':stream.height,'fps':float(rate) if rate else 0.0}

def check_video_constraints(path):
    """Seedance 2.5 input limits: 1.8–30.2 s, ≤200 MB, 300–6000 px per side, aspect 0.4–2.5, 24–60 fps."""
    path=Path(path)
    if not path.exists():raise ValueError(f'Video not found: {path.name}')
    if path.stat().st_size>200_000_000:raise ValueError(f'{path.name} is larger than 200 MB.')
    info=probe_video(path)
    if not 1.8<=info['seconds']<=30.2:raise ValueError(f'{path.name} lasts {info["seconds"]:.1f} s; videos must be 1.8–30.2 s.')
    for side in (info['width'],info['height']):
        if not 300<=side<=6000:raise ValueError(f'{path.name} is {info["width"]}×{info["height"]}; each side must be 300–6000 px.')
    aspect=info['width']/info['height']
    if not 0.4<=aspect<=2.5:raise ValueError(f'{path.name} aspect ratio {aspect:.2f} is outside 0.4–2.5.')
    if not 24<=info['fps']<=60:raise ValueError(f'{path.name} runs at {info["fps"]:.1f} fps; videos must be 24–60 fps.')
    return info

def check_image_constraints(path):
    path=Path(path)
    if not path.exists():raise ValueError(f'Image not found: {path.name}')
    if path.stat().st_size>30_000_000:raise ValueError(f'{path.name} is larger than 30 MB.')

def download_result(url,folder,name='seedance-result.mp4'):
    """Fetch the generated clip over HTTPS into the run folder; returns the local path."""
    if not isinstance(url,str) or not url.startswith('https://'):raise ValueError('Seedance result URL missing.')
    r=requests.get(url,timeout=180);r.raise_for_status()
    target=Path(folder)/name;target.write_bytes(r.content)
    return target
