"""Generator capabilities: one shape for every adapter, plus plain-language limits for a set of slots.

Every `Provider.capabilities()` is passed through `normalize()` so the UI (`static/generator.js`) and the draft
panel can rely on the same keys (docs/WORLD-LOOK-EXPORT-SPEC.md §5, docs/GENERATORS.md). The legacy keys in
`providers.base.CAPABILITY_KEYS` stay untouched; this module only adds the generator keys and fills defaults.

`supports(caps, slots)` turns a slots object (docs/WORLD-LOOK-EXPORT-SPEC.md §3, plus optional `char2` /
`char1_video` / `seconds` facts about the run) into a list of `{slot, message, fix}` sentences: what the chosen
generator cannot do and the nearest option that works. An empty list means everything asked for is supported.
"""

GENERATOR_KEYS=('resolutions','draft','finalize','max_seconds','audio','tasks','ref_images_max','slots','control','fps')
SLOT_KEYS=('set_ref','look_ref','char2','identity_video')
CONTROLS=('video','pose')
TASKS=('auto','reference','editing','extension')
DEFAULTS={'resolutions':[],'draft':False,'finalize':None,'max_seconds':30,'audio':False,'tasks':[],'ref_images_max':1,
          'slots':{k:False for k in SLOT_KEYS},'control':'video','fps':24}

def normalize(caps):
    """Return a copy of `caps` with every generator key present (defaults filled, slots merged, lists copied)."""
    out=dict(caps or {})
    for key,default in DEFAULTS.items():
        if key=='slots':
            given=out.get('slots') if isinstance(out.get('slots'),dict) else {}
            slots={k:bool(given.get(k,default[k])) for k in SLOT_KEYS}
            if 'identity_video' not in given and 'video_identity_reference' in out:slots['identity_video']=bool(out['video_identity_reference'])
            if 'char2' not in given and int(out.get('ref_images_max') or 0)>=2:slots['char2']=True
            out['slots']=slots
        elif key not in out or out[key] is None:out[key]=list(default) if isinstance(default,list) else default
        elif isinstance(default,list):out[key]=[str(x) for x in out[key]]
    out['resolutions']=out['resolutions'] or ([out['draft_resolution'].split()[0]] if out.get('draft_resolution') else [])
    out['tasks']=[t for t in out['tasks'] if t in TASKS]
    out['ref_images_max']=max(0,int(out['ref_images_max'] or 0))
    if out['control'] not in CONTROLS:out['control']='video'
    out['max_seconds']=float(out['max_seconds']) if out['max_seconds'] is not None else DEFAULTS['max_seconds']
    out['fps']=int(out['fps'] or DEFAULTS['fps'])
    return out

def _label(caps):
    return str(caps.get('label') or caps.get('name') or 'This generator')

def _nearest(key,others,default='Seedance via fal'):
    """Label of the first other generator whose capability `key` (a slot name or 'tasks:<task>' / 'draft') holds."""
    for other in others or ():
        other=normalize(other)
        if key.startswith('tasks:') and key[6:] in other['tasks']:return other.get('label') or other['name']
        if key=='draft' and other['draft']:return other.get('label') or other['name']
        if key in SLOT_KEYS and other['slots'].get(key):return other.get('label') or other['name']
    return default

def supports(caps,slots,others=()):
    """Plain-language limits of `caps` for the requested `slots`; [] when everything is supported.

    `slots`: the §3 slots object (`set.mode`, `look.mode`, `generator.task` / `generator.resolution`), optionally with
    `char2` (truthy when a second character image is attached), `char1_video` (identity video as Character 1) and
    `seconds` (length of the prepared clip). `others`: the other generators' capabilities, used to name the nearest option.
    """
    caps=normalize(caps);slots=slots or {};name=_label(caps);out=[]
    def limit(slot,message,fix):out.append({'slot':slot,'message':message,'fix':fix})
    one_image=f'{name} takes one reference image' if caps['ref_images_max']<=1 else None
    set_mode=((slots.get('set') or {}).get('mode') or 'original') if isinstance(slots.get('set'),dict) else (slots.get('set_mode') or 'original')
    look_mode=((slots.get('look') or {}).get('mode') or 'follow') if isinstance(slots.get('look'),dict) else (slots.get('look_mode') or 'follow')
    generator=slots.get('generator') if isinstance(slots.get('generator'),dict) else {}
    task=generator.get('task');task=slots.get('task') if task in (None,'','auto') else task   # generator.task 'auto' means "the derived one", which the caller passes as slots['task']
    resolution=generator.get('resolution') or slots.get('resolution')
    if set_mode=='set_ref' and not caps['slots']['set_ref']:
        limit('set',(one_image or f'{name} has no set reference slot')+': the set image is ignored here.',f'Use {_nearest("set_ref",others)} for a set reference, or describe the set in the prompt.')
    if look_mode=='style_ref' and not caps['slots']['look_ref']:
        limit('look',(one_image or f'{name} has no style reference slot')+': the style image is ignored here.',f'Use {_nearest("look_ref",others)} for a style reference, or describe the look in words.')
    if slots.get('char2') and not caps['slots']['char2']:
        limit('char2',(one_image or f'{name} has no second character slot')+': Character 2 is not sent.',f'Use {_nearest("char2",others)} for two characters.')
    if slots.get('char1_video') and not caps['slots']['identity_video']:
        limit('char1',f'{name} needs an image for Character 1; an identity video is not accepted.',f'Pick one clear frame of the identity video as the Character 1 image, or use {_nearest("identity_video",others)} for a video identity.')
    if task and task!='auto' and task not in caps['tasks']:
        if caps['control']=='pose':limit('task',f'{name} has no "{task}" task; it always keeps the pose and timing of the prepared clip and sends no prompt.',f'Use {_nearest("tasks:"+task,others)} for the {task} task.')
        elif caps['tasks']:limit('task',f'{name} does not support the "{task}" task.',f'Use {_nearest("tasks:"+task,others)} for the {task} task.')
        else:limit('task',f'{name} has no task switch; the request is sent the same way whatever the set mode is.','Nothing to change: the set mode only affects the prompt text here.')
    if resolution and caps['resolutions'] and str(resolution) not in caps['resolutions']:
        limit('resolution',f'{name} cannot render at {resolution}; it offers {", ".join(caps["resolutions"])}.',f'Pick {caps["resolutions"][-1]} here, or use {_nearest("draft",others)} for {resolution}.')
    seconds=slots.get('seconds')
    if seconds and caps['max_seconds'] and float(seconds)>float(caps['max_seconds']):
        limit('length',f'{name} takes clips up to {caps["max_seconds"]:g} s; this one lasts {float(seconds):.1f} s.','Trim the clip in the timeline editor, or use a generator with a longer limit.')
    return out

def summary(caps):
    """One line for the UI: what the generator renders and what it cannot do."""
    caps=normalize(caps);parts=[]
    if caps['resolutions']:parts.append('/'.join(caps['resolutions']))
    parts.append('draft → final' if caps['draft'] and caps['finalize'] else ('one render, no draft/complete' if not caps['finalize'] else 'draft'))
    parts.append('generates audio' if caps['audio'] else 'no audio (original audio restored)')
    parts.append('pose-locked' if caps['control']=='pose' else 'video reference')
    parts.append(f"{caps['ref_images_max']} reference image" if caps['ref_images_max']==1 else f"up to {caps['ref_images_max']} reference images")
    return ' · '.join(parts)
