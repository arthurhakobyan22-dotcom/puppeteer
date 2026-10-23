"""Mask track of the edit layer (server hooks). STUB by Agent 1: Agent 2 replaces it (batch wand, Apply to clip, the
`edit_layer` mask tool). Layer shape (docs/TIMELINE-SPEC.md §4): {points: [{id, frame, x, y, label}], strokes: [...],
applied: [{id, tool, quality, points, strokes, result}]}. Until the real track lands, pending mask edits refuse to
save (never dropped silently)."""
from .editlayer import Track,register_track

def frames_text(frames):
    frames=sorted(set(int(f) for f in frames))
    if not frames:return ''
    return f' on frame {frames[0]}' if len(frames)==1 else f' on frames {frames[0]}–{frames[-1]}'

class MaskTrack(Track):
    label='mask';empty={}
    def items(self,value):
        value=value if isinstance(value,dict) else {}
        return [x for x in value.get('points') or [] if isinstance(x,dict)],[x for x in value.get('strokes') or [] if isinstance(x,dict)],[x for x in value.get('applied') or [] if isinstance(x,dict)]
    def count(self,value):
        points,strokes,applied=self.items(value);return len(points)+len(strokes)+len(applied)
    def summary(self,value):
        points,strokes,applied=self.items(value);lines=[]
        if points:lines.append(f'{len(points)} click{"s" if len(points)!=1 else ""}{frames_text(p.get("frame",0) for p in points)} not applied')
        if strokes:lines.append(f'{len(strokes)} brush stroke{"s" if len(strokes)!=1 else ""} not applied')
        if applied:lines.append(f'{len(applied)} applied fix{"es" if len(applied)!=1 else ""}')
        return lines
    def check(self,value,session_dir):
        if self.count(value):return ('Mask edits cannot be saved yet: the mask track is not installed in this version.','Remove the mask edits (Undo or Discard), then save the others.')
        return None

register_track('mask',MaskTrack)
