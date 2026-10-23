"""Stage 6, face: the MediaPipe face mesh drawn over the base clip (`face_mesh.mesh_worker`, local and free).

`mediapipe_mesh` writes the final `composite-silent.mp4` (mesh over the original frames in Fast mode, over the
depth composite otherwise), `face-landmarks.json`, `face-tracking.json` and `preview.jpg`. `strict` is the gap
rule: true fails on a gap longer than `max_gap` frames (Fast mode, no fallback), false only warns (the depth
composite stands in where the face is lost). Default flags reproduce today's worker invocation exactly.
`off` copies the base clip to `composite-silent.mp4`. `mesh_edit` (timeline mesh edits, free, local) lives in
stages/meshedit.py and registers itself after these two, so `mediapipe_mesh` stays the default.
"""
from pathlib import Path
import json,shutil
from .base import Tool,register,fresh
from .composite import base_clip
from .report import describe_ranges

def tracking_report(folder):
    """frames / gaps / warnings / health from face-tracking.json (used after a run, on failure and by the legacy migration)."""
    folder=Path(folder)
    try:t=json.loads((folder/'face-tracking.json').read_text())
    except (OSError,ValueError):return {}
    tracked,filled,missing,total=t.get('tracked'),t.get('filled'),t.get('missing'),t.get('frames')
    gaps=t.get('gaps') or [];warnings=[]
    if t.get('warning'):warnings.append(str(t['warning']))
    health=f'Face tracked on {tracked} of {total} frames'+(f', {filled} filled by interpolation' if filled else '')
    if gaps:health+=f'; lost {describe_ranges(gaps)}'+(' (depth composite shown there)' if t.get('strict') is False else '')
    health+='.' if t.get('ok',True) else f". {t.get('message','')}".rstrip('.')+'.'
    return {'frames':{'covered':tracked,'filled':filled,'missing':missing},'gaps':gaps,'warnings':warnings,'health':health,'data':{'strict':t.get('strict'),'ok':t.get('ok'),'message':t.get('message'),'crop':t.get('crop')}}

class MediaPipeMesh(Tool):
    name='mediapipe_mesh';stage='face';label='MediaPipe face mesh';description='Tracks one face locally (face-first crop, gaps up to max_gap frames interpolated) and draws the mesh over the base clip.'
    params={'strict':{'type':'bool','default':True,'label':'Strict gap rule','hint':'On: a gap longer than max_gap frames fails the run (Fast mode). Off: it only warns and the depth composite stands in (Advanced + mesh).'},
            'pad':{'type':'number','default':1.8,'label':'Crop padding','hint':'Crop box size relative to the detected face.'},
            'max_gap':{'type':'number','default':6,'label':'Max gap (frames)','hint':'Longest run of lost frames filled by interpolation.'}}
    inputs=('original.mp4','depth-composite-silent.mp4','tracking-source.mp4','tracking-source.json');outputs=('composite-silent.mp4','face-landmarks.json','face-tracking.json','preview.jpg')
    def run(self,inputs,params,folder,status):
        import face_mesh
        folder=Path(folder);chain=inputs.get('chain') or {};base=base_clip(folder,chain);depth=base.name!='original.mp4'
        if not (Path(face_mesh.ROOT)/'.venv-face/bin/python').exists():raise ValueError('Install face mesh first: bash setup-face-mesh.sh' if depth else 'Fast face mesh needs setup: bash setup-face-mesh.sh (Python 3.12).')
        if depth and base.name=='composite-silent.mp4':   # legacy depth run: keep the clean cutout under its own name before drawing over it
            fresh(folder/'depth-composite-silent.mp4');shutil.copy2(base,folder/'depth-composite-silent.mp4');base=folder/'depth-composite-silent.mp4'
        if depth and not base.exists():raise ValueError('The depth composite is missing, so the face mesh has nothing to draw on. Re-run from the composite stage.')
        for name in self.outputs:fresh(folder/name)
        args=['--depth'] if depth else []
        strict=bool(params.get('strict',True))
        if strict!=(not depth):args.append('--strict' if strict else '--lenient')
        if float(params.get('pad',1.8))!=1.8:args+=['--pad',str(params['pad'])]
        if int(params.get('max_gap',6))!=6:args+=['--max-gap',str(int(params['max_gap']))]
        zoomed=(folder/'tracking-source.mp4').exists() and (folder/'tracking-source.json').exists()
        status(('Adding face mesh from original video onto depth composite' if depth else 'Tracking face mesh locally · no depth or SAM')+(' · tracking on the zoomed copy from the input doctor' if zoomed else ''))
        face_mesh.mesh_worker(folder,*args)
        result=tracking_report(folder)
        return {'outputs':[n for n in self.outputs if (folder/n).exists()],**result}
    def partial_result(self,folder):
        """What the worker wrote before failing (the numbers are still useful on the review screen)."""
        return tracking_report(folder)

class FaceOff(Tool):
    name='off';stage='face';label='Off';description='No face mesh: the composite is used as it is.'
    inputs=('original.mp4','depth-composite-silent.mp4');outputs=('composite-silent.mp4',)
    def run(self,inputs,params,folder,status):
        folder=Path(folder);base=base_clip(folder,inputs.get('chain') or {});target=folder/'composite-silent.mp4'
        if base.exists() and base.resolve()!=target.resolve():fresh(target);shutil.copy2(base,target)
        elif not base.exists():return {'outputs':[],'warnings':['No base clip was found for the composite; the prepared clip cannot be built until the composite stage succeeds.'],'health':'Face mesh off; no composite to pass on.'}
        return {'outputs':['composite-silent.mp4'],'health':'Face mesh off; the composite is used as it is.'}

register(MediaPipeMesh);register(FaceOff)
