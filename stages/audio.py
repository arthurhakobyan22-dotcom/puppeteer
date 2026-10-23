"""Stage 2, audio: which track the prepared clip carries.

`original` (default): the source track, copied packet for packet at the end of preparation (nothing to run here).
`clean_dialogue`: Demucs on Replicate (`audio_workflow.separate`) isolates the vocals; the prepared clip embeds
them instead. The final export always restores the entire original track either way.
"""
from pathlib import Path
from .base import Tool,register,fresh

class Original(Tool):
    name='original';stage='audio';label='Original audio';description='The prepared clip carries the entire source audio, copied packet for packet.'
    inputs=('upload.mp4',);outputs=()
    def run(self,inputs,params,folder,status):
        folder=Path(folder);warnings=[]
        source=inputs.get('source') or folder/'upload.mp4'
        try:
            import av
            with av.open(str(source)) as c:has_audio=bool(c.streams.audio)
        except Exception:has_audio=None
        if has_audio is False:warnings.append('The source has no audio track; the prepared clip will be silent.')
        return {'outputs':[],'warnings':warnings,'health':'Original audio kept, copied packet for packet.'}

class CleanDialogue(Tool):
    name='clean_dialogue';stage='audio';label='Clean dialogue (Demucs)';paid=True;description='Isolates the vocals with Demucs on Replicate and embeds them instead of the full mix; the final export still restores the original track.'
    inputs=('upload.mp4',);outputs=('original-audio.wav','vocals.wav','music.wav','audio-prediction.json','audio-manifest.json')
    def run(self,inputs,params,folder,status):
        import audio_workflow
        folder=Path(folder);source=inputs.get('source') or folder/'upload.mp4'
        for name in self.outputs:fresh(folder/name)
        audio_workflow.separate(source,folder,status)
        present=[n for n in ('vocals.wav','music.wav') if (folder/n).exists()]
        return {'outputs':[n for n in self.outputs if (folder/n).exists()],'health':'Vocals isolated with Demucs; the prepared clip carries only the voice.' if 'vocals.wav' in present else 'Separation finished without a vocals stem.',
                'warnings':[] if 'vocals.wav' in present else ['No vocals stem came back; the prepared clip falls back to the original audio.']}

register(Original);register(CleanDialogue)
