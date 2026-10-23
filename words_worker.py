"""Local word-level transcription for the Words track. Runs inside .venv-words (Python 3.12, mlx-whisper on Apple Silicon).

usage: words_worker.py <audio.wav> <out.json> --model <model folder> [--singing] [--language xx]

The WAV is 16 kHz mono 16-bit (written by stages/words.py). Word timestamps come from Whisper's cross-attention
alignment (`word_timestamps=True`, dynamic time warping over the attention heads). Singing mode does not condition on
the previous text (lyrics repeat, which sends Whisper into loops) and accepts less certain segments; the main app then
gives sung words a longer minimum length and closes short gaps (docs/WORDS.md).
Writes {engine, model, language, text, segments: [{start, end, text, words: [{word, start, end, probability}]}], seconds}.
"""
import argparse,json,os,sys,time,wave
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('audio');p.add_argument('out');p.add_argument('--model',required=True)
    p.add_argument('--singing',action='store_true');p.add_argument('--language',default=None)
    a=p.parse_args()
    import numpy as np
    with wave.open(a.audio,'rb') as w:
        if w.getframerate()!=16000 or w.getnchannels()!=1 or w.getsampwidth()!=2:raise SystemExit('error: the audio must be 16 kHz mono 16-bit PCM')
        audio=np.frombuffer(w.readframes(w.getnframes()),'<i2').astype(np.float32)/32768.0
    if not Path(a.model,'config.json').exists():raise SystemExit(f'error: the model folder {a.model} has no config.json; run bash setup-words.sh')
    import mlx_whisper
    clock=time.time()
    options=dict(path_or_hf_repo=a.model,word_timestamps=True,verbose=None,language=a.language or None,temperature=(0.0,0.2,0.4,0.6,0.8,1.0))
    if a.singing:options.update(condition_on_previous_text=False,no_speech_threshold=0.8,logprob_threshold=-1.5,compression_ratio_threshold=2.8)
    else:options.update(condition_on_previous_text=True,hallucination_silence_threshold=2.0)
    result=mlx_whisper.transcribe(audio,**options)
    segments=[{'start':round(float(s.get('start',0)),3),'end':round(float(s.get('end',0)),3),'text':s.get('text','').strip(),
               'words':[{'word':w.get('word','').strip(),'start':round(float(w.get('start',0)),3),'end':round(float(w.get('end',0)),3),'probability':round(float(w.get('probability',0)),3)} for w in s.get('words') or []]}
              for s in result.get('segments') or []]
    out={'engine':'mlx-whisper:'+Path(a.model).name,'model':Path(a.model).name,'language':result.get('language') or a.language or '','text':(result.get('text') or '').strip(),
         'segments':segments,'singing':a.singing,'seconds':round(time.time()-clock,2)}
    tmp=a.out+'.tmp';Path(tmp).write_text(json.dumps(out,ensure_ascii=False));os.replace(tmp,a.out)

if __name__=='__main__':
    try:main()
    except SystemExit:raise
    except Exception as e:
        print(f'error: {type(e).__name__}: {e}',file=sys.stderr);sys.exit(1)
