"""Face-mesh tracking rules shared by mesh_worker.py (runs in .venv-face) and the tests (main venv).

Pure Python, no MediaPipe import. Landmarks are lists of (x, y) pairs normalized to the full frame.
"""
MAX_GAP=6            # longest run of untracked frames that may be filled by interpolation
MAX_UNTRACKED=0.15   # fraction of frames still missing after gap filling above which the run fails; the same share of filled frames only warns
PAD=1.8              # crop box size relative to the detected face
SMOOTH=5             # moving-average window for the crop box, in frames
MIN_BOX=96           # smallest crop side in pixels

def clamp_box(box,width,height):
    x0,y0,x1,y1=box
    x0=max(0,min(x0,width-2));y0=max(0,min(y0,height-2))
    x1=max(x0+2,min(x1,width));y1=max(y0+2,min(y1,height))
    return (int(round(x0)),int(round(y0)),int(round(x1)),int(round(y1)))

def face_box(points,width,height,pad=PAD):
    """Square crop around the landmarks, `pad` times the face size, clamped to the frame."""
    xs=[p[0]*width for p in points];ys=[p[1]*height for p in points]
    cx=(min(xs)+max(xs))/2;cy=(min(ys)+max(ys))/2
    size=max(max(xs)-min(xs),max(ys)-min(ys))*pad
    size=max(size,MIN_BOX)
    return clamp_box((cx-size/2,cy-size/2,cx+size/2,cy+size/2),width,height)

def smooth_box(history,box,window=SMOOTH):
    """Append `box` to `history` (kept to `window` entries) and return the average box."""
    history.append(tuple(box));del history[:-window]
    n=len(history)
    return tuple(int(round(sum(b[k] for b in history)/n)) for k in range(4))

def fill_gaps(frames,max_gap=MAX_GAP):
    """Fill short runs of missing landmarks.

    `frames` is a list with a landmark list or None per frame. Runs of at most `max_gap` missing frames are
    filled: interior runs by linear interpolation between the neighbouring tracked frames, runs at the
    start or end of the clip by holding the nearest tracked frame. Longer runs stay missing.
    Returns (frames, status) with status[i] in {'tracked', 'filled', 'missing'}.
    """
    n=len(frames);out=list(frames);status=['tracked' if f else 'missing' for f in frames]
    i=0
    while i<n:
        if frames[i]:i+=1;continue
        j=i
        while j<n and not frames[j]:j+=1
        length=j-i
        if length<=max_gap:
            before=frames[i-1] if i>0 else None;after=frames[j] if j<n else None
            if before and after:
                for k in range(i,j):
                    t=(k-i+1)/(length+1)
                    out[k]=[(a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t) for a,b in zip(before,after)];status[k]='filled'
            elif before or after:
                source=before or after
                for k in range(i,j):out[k]=[tuple(p) for p in source];status[k]='filled'
        i=j
    return out,status

def ranges(status,fps,kind='missing'):
    """Contiguous runs of `kind` as frame and second ranges (end_s is exclusive, i.e. the end of the last frame)."""
    result=[];start=None
    for i,s in enumerate(list(status)+[None]):
        if s==kind and start is None:start=i
        if s!=kind and start is not None:
            result.append({'start_frame':start,'end_frame':i-1,'frames':i-start,'start_s':round(start/fps,2),'end_s':round(i/fps,2)});start=None
    return result

def evaluate(status,fps,max_gap=MAX_GAP,max_untracked=MAX_UNTRACKED):
    """Warn, don't block: fail only for a gap longer than `max_gap` frames or too many untracked frames."""
    n=len(status);tracked=status.count('tracked');filled=status.count('filled');missing=status.count('missing')
    gaps=ranges(status,fps,'missing');long_gaps=[g for g in gaps if g['frames']>max_gap]
    problems=[]
    if not n:problems.append('no frames decoded')
    if long_gaps:problems.append('lost face '+', '.join(f"{g['start_s']}–{g['end_s']} s" for g in long_gaps))
    missing_ratio=missing/n if n else 1;untracked=(filled+missing)/n if n else 1
    if n and missing_ratio>max_untracked:problems.append(f'{round(missing_ratio*100)}% of frames missing (limit {round(max_untracked*100)}%)')
    warning=f'{round(untracked*100)}% of frames were not detected directly ({filled} interpolated); check lip motion closely' if n and not problems and untracked>max_untracked else ''
    return {'frames':n,'tracked':tracked,'filled':filled,'missing':missing,'gaps':gaps,'filled_ranges':ranges(status,fps,'filled'),
            'max_gap_frames':max_gap,'max_missing_ratio':max_untracked,'ok':not problems,'warning':warning,'message':'; '.join(problems) if problems else 'face tracked throughout'}
