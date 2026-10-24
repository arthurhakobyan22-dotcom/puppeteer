"""Prompt builder with fences (World stage, Agent 2): the creative prompt assembled from the run's references, the Set / Look /
Light slots and the dialogue beats, with one job and one fence sentence per attached reference.

`assemble(folder, slots=None, refs=None, words=None, runs_root=None)` -> {'text', 'refs', 'beats', 'sections', 'warnings'}

References are attached, numbered and fenced **in attachment order**: `char1` (image -> @Image1; an identity video -> @Video2),
`char2` (@Image2 when char1 is an image, else @Image1), the set image (`slots.set.mode == 'set_ref'`), the look image
(`slots.look.mode == 'style_ref'`). @Video1 is always the prepared clip. The adapters upload in the same order
(`providers/fal.py`, `providers/enhancor.py`), so the numbers in the text are the numbers Seedance sees.

Sections, in order, each present only when its slot says so: CHARACTER (the identity fences + the @Video1 line), SET
(`set.prompt`, the set fence for `set_ref`, the depth sentence for `original_depth`, the plate sentence for `true_swap`; nothing
for `original`), LOOK (`look.prompt` or the style fence), the dialogue-beats block exactly as `GET /jobs/{id}/words/beats`
renders it (pending word edits first, else words.json), LIGHT, then exactly one closing constraints line whose mesh / depth
clauses appear only when the run has a mesh / depth.

`fences_ok(text, refs)` lists the problems a hand-edited prompt can have (a ref mentioned without its job sentence, a ref with
two job sentences, numbering gaps); the UI shows them as warnings and the tests assert the assembled text has none.
Nothing here touches the network and nothing is written into the run folder.
"""
from pathlib import Path
import re

REF_EXT=('png','jpg','jpeg','webp','mp4','mov','webm')   # the lookup order static/draft.js savedReference uses
IMAGE_EXT=('png','jpg','jpeg','webp')
VIDEO_EXT=('mp4','mov','webm')
SLOT_ORDER=('char1','char2','set','look')
IDENTITY_DETAIL='(face, hair, outfit, proportions); do not copy its pose, expression, props, background or lighting.'
FENCES={
    'char1':"{token} defines the character's identity only "+IDENTITY_DETAIL,
    'char2':"{token} defines the second character's identity only "+IDENTITY_DETAIL,
    'set':'{token} defines the set only (walls, floor, furniture, depth of the room); do not use its people or lighting.',
    'look':'{token} defines the rendering style only (palette, grain, contrast, brushwork); do not copy its content, people or layout.',
}
JOBS={'char1':'identity','char2':'identity','set':'set','look':'style'}
JOB_LINES={'char1':'Character 1 · identity only (face, hair, outfit, proportions)','char2':'Character 2 · identity only (face, hair, outfit, proportions)',
           'set':'Set · walls, floor, furniture and depth only','look':'Look · rendering style only (palette, grain, contrast, brushwork)'}
VIDEO1_LINE='Pose, motion, timing and lip-sync come from @Video1.'
DEPTH_LINE='The depth of @Video1 defines the layout of the room only (walls, floor, furniture, distances); regenerate its look and materials.'
PLATE_LINE='The set behind the person in @Video1 is the real set: keep its walls, floor, furniture and depth exactly as they are.'
CLOSING_BASE='Keep the camera, crop, timing and every word of the embedded dialogue'
SECTION_NAMES=('CHARACTER','SET','LOOK','DIALOGUE BEATS','LIGHT','CONSTRAINTS')

# ---------------------------------------------------------------- references

def is_video(path):return str(path).lower().rsplit('.',1)[-1] in VIDEO_EXT

def saved_reference(folder,slot):
    """`<slot>-reference.<ext>` saved with the run, in the same extension order as the draft panel (images, then videos for char1); None when absent."""
    folder=Path(folder)
    for ext in (REF_EXT if slot=='char1' else IMAGE_EXT):
        p=folder/f'{slot}-reference.{ext}'
        if p.exists():return p
    return None

def asset_file(name,runs_root):
    """The stored set / look asset for an asset name, or None when the name is not valid or the file is gone."""
    from .plates import asset_path
    try:p=asset_path(name,runs_root)
    except ValueError:return None
    return p if p.exists() else None

def extra_refs(slots,runs_root):
    """{'set': Path|None, 'look': Path|None}: the set image when the Set slot is `set_ref`, the look image when the Look slot is `style_ref`."""
    s=(slots or {}).get('set') or {};l=(slots or {}).get('look') or {};out={'set':None,'look':None}
    if s.get('mode')=='set_ref' and s.get('image'):out['set']=asset_file(s['image'],runs_root)
    if l.get('mode')=='style_ref' and l.get('image'):out['look']=asset_file(l['image'],runs_root)
    return out

def number_refs(items):
    """[(slot, path)] in attachment order -> the numbered ref list: images @Image1.., an identity video @Video2 (it takes no image number)."""
    out=[];n=0
    for slot,path in items:
        if path is None:continue
        path=Path(path)
        if slot=='char1' and is_video(path):token='@Video2';kind='video'
        else:n+=1;token=f'@Image{n}';kind='image'
        out.append({'n':int(token[6:]) if kind=='image' else 2,'token':token,'slot':slot,'kind':kind,'file':path.name,'path':str(path),'job':JOBS[slot],'job_line':JOB_LINES[slot],'fence':FENCES[slot].format(token=token)})
    return out

def collect_refs(folder,slots,refs=None,runs_root=None):
    """The ref list from whatever the caller has: a numbered list (kept, renumbered), a provider-style dict {'char1','char2','set','look'},
    or nothing (the run folder's saved references + the slots' assets)."""
    folder=Path(folder);runs_root=Path(runs_root) if runs_root else folder.parent
    if isinstance(refs,dict):items=[(slot,refs.get(slot)) for slot in SLOT_ORDER]
    elif isinstance(refs,list):
        by_slot={str(r.get('slot')):r.get('path') or (folder/r['file'] if r.get('file') else None) for r in refs if isinstance(r,dict) and r.get('slot') in SLOT_ORDER}
        items=[(slot,by_slot.get(slot)) for slot in SLOT_ORDER]
    else:
        extra=extra_refs(slots,runs_root)
        items=[('char1',saved_reference(folder,'char1')),('char2',saved_reference(folder,'char2')),('set',extra['set']),('look',extra['look'])]
    return number_refs(items)

# ---------------------------------------------------------------- the text

def run_has(folder):
    """{'mesh': bool, 'depth': bool} from the run's mode (workflow-mode.json) and files, for the closing line."""
    from mask_review import mode_of
    folder=Path(folder);mode=mode_of(folder)
    mesh=mode in ('face_mesh','depth_mesh') or (folder/'face-landmarks.json').exists()
    depth=mode in ('depth','depth_mesh') or (mode is None and (folder/'depth.mp4').exists())
    return {'mesh':mesh,'depth':depth}

def closing_line(has):
    parts=[CLOSING_BASE]
    if has.get('mesh'):parts.append('replace the whole identity including hair')
    remove=(['mesh lines'] if has.get('mesh') else [])+(['depth colours'] if has.get('depth') else [])
    if remove:parts.append('remove any '+' or '.join(remove)+' from the output')
    return '; '.join(parts)+'.'

def beats_block(folder,words=None,runs_root=None):
    """The exact `Dialogue beats` block the beats route renders ('' when the run has no words). Pending word edits first, else words.json."""
    from . import words as W
    folder=Path(folder)
    if words is None:
        try:words,_,_=W.current(folder,runs_root or folder.parent)
        except Exception:words=[]
    return W.beats_text(words) if words else ''

def assemble(folder,slots=None,refs=None,words=None,runs_root=None):
    """The assembled prompt for this run. `slots` None -> stages.slots.read(folder); `refs` None -> the run's saved references and the slots'
    assets (or pass the numbered list / the provider dict); `words` None -> the run's current words. Returns
    {'text', 'refs', 'beats', 'sections': [{'name', 'text'}], 'warnings': [str], 'closing', 'has'}."""
    from . import slots as S
    folder=Path(folder);runs_root=Path(runs_root) if runs_root else folder.parent
    slots=S.merge(S.defaults(),slots) if isinstance(slots,dict) else S.read(folder)
    ref_list=collect_refs(folder,slots,refs,runs_root);by_slot={r['slot']:r for r in ref_list}
    s=slots.get('set') or {};l=slots.get('look') or {};warnings=[];sections=[]
    # CHARACTER
    lines=[by_slot[k]['fence'] for k in ('char1','char2') if k in by_slot]+[VIDEO1_LINE]
    if 'char1' not in by_slot:warnings.append('No Character 1 reference is saved with this run yet; choose one in step 03 so @Image1 has something to point at.')
    sections.append({'name':'CHARACTER','text':' '.join(lines)})
    # SET
    mode=s.get('mode') or 'original';set_lines=[]
    if mode=='set_ref':
        if 'set' in by_slot:set_lines.append(by_slot['set']['fence'])
        else:warnings.append('The Set slot says "set reference" but no set image is attached; pick one in the Set images list.')
    elif mode=='original_depth':set_lines.append(DEPTH_LINE)
    elif mode=='true_swap':set_lines.append(PLATE_LINE)
    if (s.get('prompt') or '').strip():set_lines.append(s['prompt'].strip())
    elif mode=='prompt':warnings.append('The Set slot says "described" but the set description is empty.')
    if set_lines:sections.append({'name':'SET','text':' '.join(set_lines)})
    # LOOK
    lmode=l.get('mode') or 'follow';look_lines=[]
    if lmode=='style_ref':
        if 'look' in by_slot:look_lines.append(by_slot['look']['fence'])
        else:warnings.append('The Look slot says "style image" but no style image is attached; pick one in the Style images list.')
    if (l.get('prompt') or '').strip():look_lines.append(l['prompt'].strip())
    elif lmode=='prompt':warnings.append('The Look slot says "described" but the look description is empty.')
    if look_lines:sections.append({'name':'LOOK','text':' '.join(look_lines)})
    # DIALOGUE BEATS
    beats=beats_block(folder,words,runs_root)
    if beats:sections.append({'name':'DIALOGUE BEATS','text':beats})
    # LIGHT
    if (slots.get('light') or '').strip():sections.append({'name':'LIGHT','text':slots['light'].strip()})
    # closing constraints
    has=run_has(folder);closing=closing_line(has);sections.append({'name':'CONSTRAINTS','text':closing})
    text='\n\n'.join(sec['text'] if sec['name'] in ('DIALOGUE BEATS','CONSTRAINTS') else f'{sec["name"]}: {sec["text"]}' for sec in sections)
    warnings+=fences_ok(text,ref_list)
    return {'text':text,'refs':ref_list,'beats':beats,'sections':sections,'warnings':warnings,'closing':closing,'has':has}

# ---------------------------------------------------------------- checks

SENTENCE=re.compile(r'(?<=[.!?])\s+|\n+')
JOB=re.compile(r'\bdefines\b.*\bonly\b')

def fences_ok(text,refs):
    """Problems with the fences in `text` for the attached `refs` (plain sentences; [] when everything is right): a ref that is
    mentioned without its job sentence or never mentioned, a ref with two job sentences, an @ImageN / @VideoN that is not attached."""
    problems=[];text=text or '';sentences=[s for s in SENTENCE.split(text) if s.strip()]
    for r in refs or []:
        token=r['token'];jobs=[s for s in sentences if token in s and JOB.search(s)]
        if token not in text:problems.append(f'{token} ({r["slot"]}) is attached but the prompt never mentions it.')
        elif not jobs:problems.append(f'{token} ({r["slot"]}) is mentioned without its job sentence ("{token} defines … only").')
        elif len(jobs)>1:problems.append(f'{token} ({r["slot"]}) has {len(jobs)} job sentences; it should have exactly one.')
    images=sorted({int(n) for n in re.findall(r'@Image(\d+)',text)});attached={r['n'] for r in refs or [] if r['kind']=='image'}
    for n in images:
        if n not in attached:problems.append(f'@Image{n} is mentioned but only {len(attached)} image reference{"" if len(attached)==1 else "s"} {"is" if len(attached)==1 else "are"} attached.')
    has_video2=any(r['kind']=='video' for r in refs or [])
    for n in sorted({int(n) for n in re.findall(r'@Video(\d+)',text)}):
        if n==2 and not has_video2:problems.append('@Video2 is mentioned but Character 1 is an image, so there is no second video.')
        elif n>2:problems.append(f'@Video{n} is mentioned but only {"two videos" if has_video2 else "one video"} go with the request.')
    return problems
