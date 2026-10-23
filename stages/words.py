"""Words track of the edit layer (server hooks). Minimal version by Agent 1; Agent 4 extends it (transcription,
mouth guidance, subtitles). Layer: `words = {words: [{id, text, start, end}], singing, edited?: [word ids]}` or
null. On save the child gets `words.json` ({version, engine, language, singing, words: [{text, start, end}]});
nothing re-runs for a words-only session (the branch is at `prompt`)."""
import json
from pathlib import Path
from .base import fresh
from .editlayer import Track,register_track

def word_list(value):
    value=value if isinstance(value,dict) else {}
    return [w for w in value.get('words') or [] if isinstance(w,dict) and str(w.get('text','')).strip()]

class WordsTrack(Track):
    label='words';empty=None
    def count(self,value):
        if not isinstance(value,dict):return 0
        edited=value.get('edited')
        return len(set(map(str,edited))) if isinstance(edited,list) and edited else len(word_list(value)) or (1 if 'words' in value else 0)
    def summary(self,value):
        n=self.count(value);words=word_list(value)
        if isinstance((value or {}).get('edited'),list) and value['edited']:return [f'{n} word{"s" if n!=1 else ""} edited']
        return [f'transcript of {len(words)} word{"s" if len(words)!=1 else ""} edited' if words else 'transcript cleared']
    def materialize(self,value,child_folder,session_dir,parent_folder):
        if not isinstance(value,dict):return
        base={}
        try:base=json.loads((Path(parent_folder)/'words.json').read_text())
        except (OSError,ValueError):pass
        words=sorted(({'text':str(w['text']).strip(),'start':round(float(w.get('start') or 0),3),'end':round(float(w.get('end') or w.get('start') or 0),3)} for w in word_list(value)),key=lambda w:w['start'])
        data={'version':1,'engine':base.get('engine') or 'manual','language':base.get('language') or '','singing':bool(value.get('singing',base.get('singing',False))),'edited':True,'words':words}
        path=Path(child_folder)/'words.json';fresh(path);path.write_text(json.dumps(data,indent=1,ensure_ascii=False))

register_track('words',WordsTrack)
