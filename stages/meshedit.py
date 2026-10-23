"""Face mesh track of the edit layer (server hooks). STUB by Agent 1: Agent 3 replaces it (range off, transform keys,
expressions, the `mesh_edit` face tool, `apply(landmarks, mesh_layer)`). Layer shape (docs/TIMELINE-SPEC.md §5):
{off: [[a, b], …], keys: {"<frame>": {dx, dy, scale, rot}}, expr: {"<frame>": {...}}}. Until the real track lands,
pending mesh edits refuse to save (never dropped silently)."""
from .editlayer import Track,register_track

class MeshTrack(Track):
    label='face';empty={}
    def parts(self,value):
        value=value if isinstance(value,dict) else {}
        return [r for r in value.get('off') or [] if isinstance(r,(list,tuple)) and len(r)==2],dict(value.get('keys') or {}),dict(value.get('expr') or {})
    def count(self,value):
        off,keys,expr=self.parts(value);return len(off)+len(keys)+len(expr)
    def summary(self,value):
        off,keys,expr=self.parts(value);lines=[]
        if off:lines.append('mesh off '+', '.join(f'{int(a)}–{int(b)}' for a,b in off))
        if keys:lines.append(f'{len(keys)} transform key{"s" if len(keys)!=1 else ""}')
        if expr:lines.append(f'{len(expr)} expression key{"s" if len(expr)!=1 else ""}')
        return lines
    def check(self,value,session_dir):
        if self.count(value):return ('Face mesh edits cannot be saved yet: the face track is not installed in this version.','Remove the face edits (Undo or Discard), then save the others.')
        return None

register_track('mesh',MeshTrack)
