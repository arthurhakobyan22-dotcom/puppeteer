"""Per-tool cost estimates in USD, with the source and date of each price.

Numbers follow docs/COSTS-RESEARCH.md (public list prices read on 2026-10-22). `verified` is true only for a
price read from the vendor's page as a per-unit rate; runtime-derived estimates (GPU seconds per frame) and
anything not public (Enhancor) stay `verified: false`. These are estimates shown before a paid step runs; the
real spend is on the provider's bill. Replicate bills public models per GPU second at the rates below.
"""
from pathlib import Path

DATE='2026-10-22'
RESEARCH='docs/COSTS-RESEARCH.md'
GPU_USD_PER_SECOND={'Nvidia T4':0.000225,'Nvidia L40S':0.000975,'Nvidia A100 (80GB)':0.0014,'Nvidia H100':0.001525}
FPS=24
# Unverified runtime constants (replace with measured values after the first paid runs).
SAM3_SECONDS_PER_FRAME=0.35     # SAM 3 tracking on an L40S (gener8-sam3 readme timing, same model family)

# tool name -> pricing model:
#   usd_flat                        a fixed estimate (Replicate's listed average per run, or 0 for free tools)
#   usd_per_clip_second             billed per second of the clip (fal Seedance output pricing)
#   usd_per_started_minute          billed per minute of audio, every started minute counted (speech-to-text)
#   gpu + usd_per_gpu_second + gpu_seconds_per_frame   billed per GPU second, runtime proportional to the frame count
PRICES={
    'depth_anything_replicate':{'provider':'replicate','endpoint':'lucataco/depth-anything-video','gpu':'Nvidia T4','usd_per_gpu_second':GPU_USD_PER_SECOND['Nvidia T4'],'usd_flat':0.04,
        'source':'replicate.com/lucataco/depth-anything-video: "approximately $0.040 to run" on Nvidia T4 (listed average; per-frame speed unverified)','date':DATE,'verified':False},
    'depth_anything_replicate_chenxwh':{'provider':'replicate','endpoint':'chenxwh/depth-any-video','gpu':'Nvidia A100 (80GB)','usd_per_gpu_second':GPU_USD_PER_SECOND['Nvidia A100 (80GB)'],'usd_flat':0.14,
        'source':'replicate.com/chenxwh/depth-any-video: "approximately $0.14 to run" on Nvidia A100 80GB (listed average)','date':DATE,'verified':False},
    'depth_anything_hf':{'provider':'huggingface','endpoint':'depth-anything/Video-Depth-Anything','usd_flat':0.0,
        'source':'Hugging Face ZeroGPU Space: free within the daily quota (2 min unauthenticated, 5 min free account); PRO overflow $1 per 10 GPU-minutes','date':DATE,'verified':True},
    'sam3_replicate':{'provider':'replicate','endpoint':'lucataco/sam3-video','gpu':'Nvidia L40S','usd_per_gpu_second':GPU_USD_PER_SECOND['Nvidia L40S'],'gpu_seconds_per_frame':SAM3_SECONDS_PER_FRAME,'per_term':True,
        'source':'replicate.com/lucataco/sam3-video on Nvidia L40S ($0.000975/s); about 0.35 GPU s per frame from the gener8-sam3 readme; one prediction per comma-separated term','date':DATE,'verified':False},
    'sam3_fallback_replicate':{'provider':'replicate','endpoint':'8digit/gener8-sam3','gpu':'Nvidia L40S','usd_per_gpu_second':GPU_USD_PER_SECOND['Nvidia L40S'],'gpu_seconds_per_frame':SAM3_SECONDS_PER_FRAME,
        'source':'replicate.com/8digit/gener8-sam3 readme: 576 frames = 200 GPU s on L40S without preview','date':DATE,'verified':False},
    'clean_dialogue':{'provider':'replicate','endpoint':'cjwbw/demucs','gpu':'Nvidia T4','usd_per_gpu_second':GPU_USD_PER_SECOND['Nvidia T4'],'usd_flat':0.015,
        'source':'replicate.com/cjwbw/demucs: "approximately $0.015 to run" on Nvidia T4 (listed average over longer inputs; a short clip costs less)','date':DATE,'verified':False},
    'fal':{'provider':'fal','endpoint':'bytedance/seedance-2.5/reference-to-video','usd_per_clip_second':round(0.6*0.2205*2,4),'resolution':'480p draft',
        'source':'fal.ai model page: 480p roughly $0.2205 per output second; with a video input the price is x0.6 and both input and output seconds are charged (the prepared clip is always a video input)','date':DATE,'verified':True},
    'fal_complete':{'provider':'fal','endpoint':'bytedance/seedance-2.5/draft/complete','usd_per_clip_second':round(0.6*1.164*2,4),'resolution':'1080p',
        'source':'fal.ai model page: 1080p roughly $1.164 per output second; x0.6 and input + output seconds charged when the draft used a video reference','date':DATE,'verified':True},
    'enhancor':{'provider':'enhancor','endpoint':'seedance2.5/v1/queue (is_draft)','usd_per_clip_second':0.30,'resolution':'1080p draft',
        'source':'Enhancor publishes no API price list; placeholder until the per-job price is read from app.enhancor.ai/api-dashboard','date':DATE,'verified':False},
    'enhancor_complete':{'provider':'enhancor','endpoint':'seedance2.5/v1/queue (draft_id)','usd_per_clip_second':0.30,'resolution':'1080p',
        'source':'Enhancor publishes no API price list; placeholder until the per-job price is read from app.enhancor.ai/api-dashboard','date':DATE,'verified':False},
    'sam3_points_fal':{'provider':'fal','endpoint':'fal-ai/sam-3/video-rle','usd_per_frame':round(0.005/16,6),
        'source':'fal.ai/models/fal-ai/sam-3/video-rle: $0.005 per 16 frames (docs/MASK-WAND.md); one call per click type (include, exclude)','date':DATE,'verified':True},
    'sam2_points_replicate':{'provider':'replicate','endpoint':'meta/sam-2-video','gpu':'Nvidia L40S','usd_per_gpu_second':GPU_USD_PER_SECOND['Nvidia L40S'],'usd_flat':0.029,
        'source':'replicate.com/meta/sam-2-video: "approximately $0.029 to run" on Nvidia L40S (listed average; docs/MASK-WAND.md); one prediction per click type','date':DATE,'verified':False},
    'words_fal':{'provider':'fal','endpoint':'fal-ai/elevenlabs/speech-to-text','usd_per_started_minute':0.03,
        'source':'fal.ai/models/fal-ai/elevenlabs/speech-to-text: "$0.03 per minutes" (read 2026-10-23); billing granularity not published, so the estimate counts every started minute (an 8 s clip shows $0.03). The paid fallback of the Words track; the default local Whisper is free','date':'2026-10-23','verified':True},
    'media_host':{'provider':'tmpfiles','endpoint':'upload','usd_flat':0.0,'source':'free host','date':DATE,'verified':True},
    'replicate_upload':{'provider':'replicate','endpoint':'files','usd_flat':0.0,'source':'Replicate file uploads are not billed','date':DATE,'verified':True},
}
NOTE='Estimates from public list prices (see docs/COSTS-RESEARCH.md); entries marked verified: false use listed averages or unmeasured runtimes. The real amount is on the provider bill.'
DEFAULT_SECONDS=10.0

def clip_seconds(folder):
    """Duration of the run's source clip in seconds (upload.mp4, else original.mp4), or None."""
    if folder is None:return None
    folder=Path(folder)
    for name in ['upload.mp4','original.mp4']:
        path=folder/name
        if not path.exists():continue
        try:
            import av
            with av.open(str(path)) as c:
                if c.duration:return float(c.duration/av.time_base)
                s=c.streams.video[0]
                if s.duration and s.time_base:return float(s.duration*s.time_base)
        except Exception:continue
    return None

def price_for(key,seconds=None,params=None):
    """USD estimate for one call of the priced entry `key` on a clip of `seconds` seconds."""
    entry=PRICES.get(key)
    if entry is None:return None
    seconds=float(seconds or DEFAULT_SECONDS)
    if 'usd_per_clip_second' in entry:return round(entry['usd_per_clip_second']*seconds,4)
    if 'usd_per_started_minute' in entry:
        import math
        return round(entry['usd_per_started_minute']*max(1,math.ceil(seconds/60-1e-9)),4)
    if 'usd_per_frame' in entry:return round(entry['usd_per_frame']*round(seconds*FPS),4)
    if 'gpu_seconds_per_frame' in entry:return round(entry['usd_per_gpu_second']*entry['gpu_seconds_per_frame']*round(seconds*FPS),4)
    return round(entry.get('usd_flat',0.0),4)

def estimate_tool(tool,seconds=None,params=None):
    """Estimate for a whole tool run (e.g. SAM 3 is one prediction per comma-separated term)."""
    params=params or {}
    if tool=='sam3_replicate':
        terms=[t for t in str(params.get('prompt','person')).split(',') if t.strip()] or ['person']
        return round((price_for('sam3_replicate',seconds) or 0)*len(terms),4)
    if tool in ('sam3_points_fal','sam2_points_replicate'):
        # one hosted call per click type present (include points, exclude points); no clicks yet counts as one call
        edits=params.get('edits') or []
        if isinstance(edits,str):
            import json
            try:edits=json.loads(edits) if edits.strip() else []
            except ValueError:edits=[]
        labels={1 if str((e or {}).get('label',1)).strip().lower() in ('1','true','include','+') else 0 for e in edits if isinstance(e,dict)} if isinstance(edits,list) else set()
        return round((price_for(tool,seconds) or 0)*max(1,len(labels)),4)
    if tool=='complete_draft':
        provider=params.get('provider') or 'fal'
        return price_for(provider+'_complete',seconds)
    return price_for(tool,seconds,params)

def call_cost(provider,endpoint,folder=None):
    """Estimate for a single logged call, by provider + endpoint (used when the caller does not know the price)."""
    seconds=clip_seconds(folder)
    for key,entry in PRICES.items():
        if entry['provider']==provider and entry['endpoint']==endpoint:
            return price_for(key,seconds) or 0.0
    return 0.0

def table():
    return {'note':NOTE,'date':DATE,'research':RESEARCH,'default_seconds':DEFAULT_SECONDS,'fps':FPS,'gpu_usd_per_second':GPU_USD_PER_SECOND,
            'tools':{key:{**entry,'estimate_usd_per_10s_clip':price_for(key,10.0)} for key,entry in PRICES.items()}}
