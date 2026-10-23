"""Export targets: what each tool downstream expects, as data. `stages/export.py` reads this; docs/EXPORT.md explains it.

ITEMS is the ordered list of things an export can contain (the tick boxes). PRESETS picks the default items and the
per-item formats for one target; `custom` is whatever is ticked, in the plain formats. Formats per item kind:
  video  (composite_silent, depth, mask):  mp4 (H.264 copy) | prores422 (.mov, yuv422p10le) | png (frame_%05d.png)
  rgba   (mesh_alpha, alpha):              prores (ProRes 4444 .mov, yuva444p10le) | png (RGBA frame_%05d.png)
  audio  (audio_original):                 wav (48 kHz PCM) | m4a (AAC copy, for the Seedance web upload box)
"""

VIDEO_FORMATS=('mp4','prores422','png')
RGBA_FORMATS=('prores','png')
AUDIO_FORMATS=('wav','m4a')

# key, label, one line of what it is, kind (video | rgba | audio | file), the file name(s) written (per format)
ITEMS=[
 ('composite_audio','Prepared clip with audio','The clip you reviewed: composite with the mesh / depth person and the entire original audio (H.264 + AAC). This is what Seedance and Kling take as the control video.','file',{'default':'composite.mp4'}),
 ('composite_silent','Silent composite','The same picture without sound.','video',{'mp4':'composite-silent.mp4','prores422':'composite-silent.mov','png':'composite-silent/frame_%05d.png'}),
 ('depth','Depth video','Depth Anything colours, as the depth stage made them.','video',{'mp4':'depth.mp4','prores422':'depth.mov','png':'depth/frame_%05d.png'}),
 ('mesh_alpha','Face mesh alone on transparent','Only the mesh lines (with your timeline edits), alpha 0 everywhere else. Lay it over any plate.','rgba',{'prores':'face-mesh-alpha.mov','png':'face-mesh/frame_%05d.png'}),
 ('mask','Mask (black / white)','White where the person is, black elsewhere; one frame per clip frame.','video',{'mp4':'mask.mp4','prores422':'mask.mov','png':'mask/frame_%05d.png'}),
 ('alpha','Person with alpha','The composite colours with the mask as the alpha channel: the person cut out, ready to key.','rgba',{'prores':'person-alpha.mov','png':'person-alpha/frame_%05d.png'}),
 ('audio_original','Original audio','The untouched source soundtrack.','audio',{'wav':'audio-original.wav','m4a':'audio-original.m4a'}),
 ('audio_vocals','Isolated vocals','vocals.wav from the Clean dialogue step.','file',{'default':'vocals.wav'}),
 ('audio_music','Music without vocals','music.wav from the Clean dialogue step.','file',{'default':'music.wav'}),
 ('landmarks','Face landmarks (JSON)','face-landmarks.json with the timeline mesh edits applied: {fps, frames: [{frame, status, faces: [[{x, y} × 478]]}]}, x / y as fractions of the frame.','file',{'default':'face-landmarks.json'}),
 ('words','Words (SRT + JSON)','The transcript as words.srt (subtitle phrases) and words.json (word timings); pending word edits first.','file',{'default':'words.srt, words.json'}),
 ('prompt','Prompt (text)','The final generation prompt with the timed dialogue beats and the reference list, as prompt.txt.','file',{'default':'prompt.txt'}),
 ('refs','Reference images','The saved character / set / look references, numbered in attachment order (ref-01-char1.png …).','file',{'default':'ref-NN-<slot>.<ext>'}),
 ('run','Run record','run.json (the whole chain: tool + params + cache key per stage) and slots.json when the run has one.','file',{'default':'run.json, slots.json'}),
]
ITEM_KEYS=[i[0] for i in ITEMS]
ITEM_BY_KEY={i[0]:{'key':i[0],'label':i[1],'what':i[2],'kind':i[3],'names':i[4]} for i in ITEMS}

PRESETS={
 'seedance_web':{'label':'Seedance web (Dreamina / fal playground)','items':['composite_audio','prompt','refs'],
   'formats':{'audio_original':'m4a'},
   'what':'composite.mp4 (H.264 + AAC, source fps, ≤1080p) to upload as the video, prompt.txt to paste, the reference images numbered in the order you attach them.',
   'why':['The web upload box takes one H.264 mp4 with AAC audio and up to 1080p; the prepared clip already is one, so the picture is copied byte for byte and the audio is copied when it is AAC (re-encoded only when it is not).',
          'The prompt mentions @Image1, @Image2 … by position, so the references are numbered in that order; the clip itself is @Video1.']},
 'kling':{'label':'Kling (video + mask)','items':['composite_audio','mask','prompt'],
   'formats':{'mask':'mp4'},
   'what':'composite.mp4 (control video), mask.mp4 (black / white, same frame count and fps) and prompt.txt.',
   'why':['Kling takes a control video and a mask video of the same length; both stay at the source fps so the frames line up one to one.',
          'The mask is H.264 (lossless enough for a hard black / white matte at crf 18); PNG sequences are not accepted there.']},
 'comfyui':{'label':'ComfyUI (PNG sequences)','items':['depth','mask','composite_silent','landmarks','words','run'],
   'formats':{'depth':'png','mask':'png','composite_silent':'png'},
   'what':'depth/, mask/ and composite-silent/ as frame_%05d.png, face-landmarks.json, words.json / words.srt, run.json, and frames.json {fps, frames, width, height} for the loader.',
   'why':['Load Image (sequence) nodes read numbered PNGs with no codec step, and ControlNet / depth / mask nodes want exact frames, not decoded video.',
          'The fps is not in a PNG, so frames.json and the README carry it (set the same value on the video combine node).']},
 'after_effects':{'label':'After Effects / Nuke (ProRes 4444)','items':['mesh_alpha','alpha','composite_silent','audio_original','words'],
   'formats':{'mesh_alpha':'prores','alpha':'prores','composite_silent':'prores422','audio_original':'wav'},
   'what':'face-mesh-alpha.mov and person-alpha.mov (ProRes 4444 with a real alpha channel), composite-silent.mov (ProRes 422 HQ), audio-original.wav (48 kHz) and words.srt.',
   'why':['ProRes 4444 is the alpha codec every NLE and compositor imports natively with straight alpha; H.264 cannot carry alpha.',
          'ProRes 422 HQ for the flat composite keeps 10-bit 4:2:2 colour for grading; the wav is 48 kHz PCM because that is the timeline default (no resampling on import).']},
 'custom':{'label':'Custom (whatever is ticked)','items':[],
   'formats':{},
   'what':'Exactly the items you tick, in the plain formats: mp4 for video, ProRes 4444 or PNG sequence for the alpha items, wav for audio.',
   'why':['Nothing is chosen for you; tick what the next tool needs.',
          'The alpha items take the format picked below (ProRes 4444 .mov, or an RGBA PNG sequence).']},
}
PRESET_ORDER=['seedance_web','kling','comfyui','after_effects','custom']

def preset(name):
    """The preset dict for `name`; ValueError with a plain sentence when it does not exist."""
    if name not in PRESETS:raise ValueError(f'There is no export preset called {name!r}. Use one of: '+', '.join(PRESET_ORDER)+'.')
    return PRESETS[name]

def formats_for(name,mesh_format='prores',alpha_format='prores'):
    """Per-item format for `name`, with the user's choice for the two alpha items (custom and the two formats always honour them)."""
    out={'composite_silent':'mp4','depth':'mp4','mask':'mp4','mesh_alpha':'prores','alpha':'prores','audio_original':'wav'}
    out.update(preset(name).get('formats') or {})
    if mesh_format in RGBA_FORMATS:out['mesh_alpha']=mesh_format
    if alpha_format in RGBA_FORMATS:out['alpha']=alpha_format
    return out

def listing():
    """What the UI shows: every preset with its default items, what is in it and the reasoning."""
    return [{'name':n,'label':PRESETS[n]['label'],'items':list(PRESETS[n]['items']),'formats':dict(PRESETS[n]['formats']),'what':PRESETS[n]['what'],'why':list(PRESETS[n]['why'])} for n in PRESET_ORDER]
