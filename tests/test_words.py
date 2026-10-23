"""Words track: worker output parsing (a fake worker run through the real subprocess path), the transcription cache,
words.json never overwritten, edits persisting across reloads, timing validation, save → child words.json +
mouth-guidance.json, dialogue beats, SRT export, the subtitle burn-in (only the bottom band changes, only during a
word; audio packets identical), the paid fal fallback (402 without confirm_cost, offline refusal before any I/O, a
mocked success) and, when `.venv-words` and the model exist, one real local transcription of the fixture's speech.
"""
import unittest,tempfile,json,os,re,sys,shutil,socket,time,urllib.request
from pathlib import Path
from fractions import Fraction
from unittest.mock import patch,Mock
import numpy as np
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parent))
import app as application
import stages
from stages import words as W,subtitles as S,editlayer
from test_mask_wand import synthetic_run,square_mask,tree_hashes,wait,HEX,N

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'runs'/'85e5dbe64df1464fa63825319ebfa104'

def write_av(path,frames,fps=24,seconds=None,tone=440):
    """An H.264 clip with an AAC sine tone (the run's audio)."""
    import av
    with av.open(str(path),'w') as c:
        v=c.add_stream('libx264',rate=fps);v.width=frames[0].shape[1];v.height=frames[0].shape[0];v.pix_fmt='yuv420p';v.options={'crf':'16','preset':'ultrafast'}
        a=c.add_stream('aac',rate=48000);a.layout='mono'
        for i,arr in enumerate(frames):
            f=av.VideoFrame.from_ndarray(arr,format='rgb24');f.pts=i;f.time_base=Fraction(1,fps)
            for p in v.encode(f):c.mux(p)
        total=int(48000*(seconds or len(frames)/fps));t=np.arange(total)/48000;pcm=(0.3*np.sin(2*np.pi*tone*t)).astype(np.float32)
        for k in range(0,total,1024):
            chunk=pcm[k:k+1024]
            fr=av.AudioFrame.from_ndarray(chunk.reshape(1,-1),format='fltp',layout='mono');fr.sample_rate=48000;fr.pts=k;fr.time_base=Fraction(1,48000)
            for p in a.encode(fr):c.mux(p)
        for s in (v,a):
            for p in s.encode():c.mux(p)

def words_parent(d,ident=HEX,tracking=True):
    """A synthetic prepared run with sound: original.mp4 (24 frames), upload.mp4 with an AAC tone, a face-tracking.json
    (face missing on 5–6, filled on 2), every prepared file, and a run.json."""
    folder=synthetic_run(Path(d)/'runs'/ident,mask_of=square_mask)
    frames=[np.full((192,320,3),40+i*4,np.uint8) for i in range(N)];write_av(folder/'upload.mp4',frames)
    if tracking:(folder/'face-tracking.json').write_text(json.dumps({'frames':N,'fps':24,'tracked':21,'filled':1,'missing':2,'missing_frames':[5,6],'filled_frames':[2],'gaps':[]}))
    for n in ('mask.mp4','composite.mp4','depth-composite-silent.mp4','composite-silent.mp4','seedance-input.mp4'):(folder/n).write_bytes(b'prepared:'+n.encode())
    (folder/'workflow-mode.json').write_text(json.dumps({'mode':'depth'}));(folder/'manifest.json').write_text(json.dumps({'frames':N}));(folder/'audio-manifest.json').write_text('{}')
    (folder/'status.json').write_text(json.dumps({'id':ident,'state':'done','status':'Complete'}))
    stages.reconstruct(folder,with_keys=True,write=True)
    return folder

FAKE_WORKER='''import sys,json,wave
args=sys.argv[1:];audio,out=args[0],args[1];singing='--singing' in args
with wave.open(audio) as w:assert w.getframerate()==16000 and w.getnchannels()==1;n=w.getnframes()
log=__import__('os').environ.get('FAKE_WORKER_LOG')
if log:open(log,'a').write('run\\n')
words=[{"word":" Hello,","start":0.04,"end":0.30,"probability":0.9},{"word":" there","start":0.33,"end":0.5,"probability":0.8},{"word":" friend.","start":0.62,"end":0.9,"probability":0.7}]
json.dump({"engine":"mlx-whisper:fake","model":"fake","language":"en","text":"Hello, there friend.","singing":singing,"seconds":0.01,
           "segments":[{"start":0.0,"end":0.9,"text":"Hello, there friend.","words":words}]},open(out,"w"))
'''

class FakeLocal:
    """Point the local engine at a fake worker (the main venv's python + a script that writes the worker's JSON)."""
    def __init__(self,d):
        self.d=Path(d);self.log=self.d/'worker.log';model=self.d/'models'/W.MODEL;model.mkdir(parents=True);(model/'config.json').write_text('{}');(model/'weights.safetensors').write_bytes(b'0')
        (self.d/'fake_worker.py').write_text(FAKE_WORKER)
    def __enter__(self):
        self.p=[patch.object(W,'VENV_PYTHON',Path(sys.executable)),patch.object(W,'WORKER',self.d/'fake_worker.py'),patch.object(W,'MODELS_DIR',self.d/'models'),patch.dict(os.environ,{'FAKE_WORKER_LOG':str(self.log)})]
        for p in self.p:p.start()
        return self
    def runs(self):return len(self.log.read_text().splitlines()) if self.log.exists() else 0
    def __exit__(self,*e):
        for p in self.p:p.stop()

class NoNetwork:
    def __init__(self):self.hits=[]
    def boom(self,*a,**k):self.hits.append(a[:2]);raise AssertionError('network contact')
    def __enter__(self):
        import requests
        self.p=[patch.object(socket.socket,'connect',self.boom),patch.object(socket,'create_connection',self.boom),patch.object(urllib.request,'urlopen',self.boom),patch.object(requests.Session,'request',self.boom)]
        for p in self.p:p.start()
        return self
    def __exit__(self,*e):
        for p in self.p:p.stop()

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=self.tmp.name;self.runs=Path(self.d)/'runs'
        self.rp=patch.object(application,'RUNS',self.runs);self.rp.start();self.parent=words_parent(self.d);self.client=TestClient(application.app);application.jobs.pop(HEX,None)
    def tearDown(self):self.rp.stop();self.tmp.cleanup()

# ---------------------------------------------------------------- pure helpers

class Helpers(unittest.TestCase):
    def test_parse_local_and_fal_and_clean(self):
        local={'segments':[{'words':[{'word':' Hi','start':0.1,'end':0.12},{'word':' there.','start':0.15,'end':0.5}]}]}
        self.assertEqual(W.parse(local),[{'text':' Hi','start':0.1,'end':0.12},{'text':' there.','start':0.15,'end':0.5}])
        fal={'words':[{'text':'Hi','start':0.1,'end':0.2,'type':'word'},{'text':' ','start':0.2,'end':0.3,'type':'spacing'},{'text':'(laughs)','start':0.3,'end':0.5,'type':'audio_event'},{'text':'you','start':0.5,'end':0.7,'type':'word'}]}
        self.assertEqual([w['text'] for w in W.parse(fal)],['Hi','you'])
        speech=W.clean(W.parse(local),False,8);self.assertEqual(speech,[{'text':'Hi','start':0.1,'end':0.15},{'text':'there.','start':0.15,'end':0.5}])   # stretched to the 0.06 s minimum, then trimmed to the next word
        sung=W.clean([{'text':'la','start':0.1,'end':0.15},{'text':'la','start':0.4,'end':0.5}],True,8)
        self.assertEqual(sung[0]['end'],0.4,'singing: held note closes the 0.1 s gap');self.assertGreaterEqual(sung[1]['end']-sung[1]['start'],0.2-1e-9)
        self.assertEqual(W.clean([{'text':'x','start':7.99,'end':9.0}],False,8.0)[0]['end'],8.0)

    def test_normalize_words_validates_layer_timing(self):
        got=W.normalize_words([{'text':' b ','start':0.5,'end':0.5},{'text':'a','start':0.0,'end':0.6},{'text':'','start':1,'end':2},{'text':'c','start':'x'},{'text':'d','start':9,'end':10},'junk'],24,8.125)
        self.assertEqual([w['text'] for w in got],['a','b','d'])
        self.assertEqual(got[0],{'text':'a','start':0.0,'end':0.5},'trimmed to the next word');self.assertAlmostEqual(got[1]['end']-got[1]['start'],1/24,places=3)
        self.assertLessEqual(got[2]['end'],8.125);self.assertGreaterEqual(got[2]['end']-got[2]['start'],1/24-1e-3)
        for a,b in zip(got,got[1:]):self.assertLessEqual(a['end'],b['start'])

    def test_beats_group_by_pauses(self):
        words=[{'text':'Hello','start':0,'end':0.4},{'text':'there.','start':0.45,'end':1.8},{'text':'How','start':2.4,'end':2.6},{'text':'are','start':2.62,'end':2.8},{'text':'"you"','start':2.85,'end':3.1}]
        self.assertEqual(W.beats(words),['0.0–1.8 s says: "Hello there."','2.4–3.1 s says: "How are \'you\'"'])
        self.assertTrue(W.beats_text(words).startswith('Dialogue beats'));self.assertEqual(W.beats_text([]),'')

    def test_srt_is_valid_and_phrases_are_short(self):
        words=[{'text':f'word{i}','start':i*0.3,'end':i*0.3+0.25} for i in range(40)]+[{'text':'late','start':20,'end':20.5}]
        cues=S.cues(words);text=S.srt(cues)
        blocks=text.split('\n\n')[:-1];self.assertEqual(len(blocks),len(cues));self.assertTrue(text.endswith('\n\n'))
        for k,b in enumerate(blocks):
            lines=b.split('\n');self.assertEqual(lines[0],str(k+1))
            m=re.fullmatch(r'(\d\d):(\d\d):(\d\d),(\d{3}) --> (\d\d):(\d\d):(\d\d),(\d{3})',lines[1]);self.assertIsNotNone(m,lines[1])
            t=[int(x) for x in m.groups()];a=t[0]*3600+t[1]*60+t[2]+t[3]/1000;z=t[4]*3600+t[5]*60+t[6]+t[7]/1000
            self.assertLess(a,z);self.assertLessEqual(len(lines[2]),42);self.assertLessEqual(z-a,5.0+1e-6)
        for x,y in zip(cues,cues[1:]):self.assertLessEqual(x['end'],y['start'])
        self.assertEqual(S.stamp(3725.5),'01:02:05,500')
        self.assertEqual(S.cues([{'text':'end','start':7.9,'end':8.0}],8.125)[0]['end'],8.125,'a cue never runs past the clip')

    def test_mouth_guidance_per_word_and_per_frame(self):
        with tempfile.TemporaryDirectory() as d:
            folder=words_parent(d)
            t=json.loads((folder/'face-tracking.json').read_text());t['edited']={'off_frames':[20]};(folder/'face-tracking.json').write_text(json.dumps(t))
            g=W.mouth_guidance([{'text':'hi','start':0.0,'end':0.125},{'text':'yo','start':0.2,'end':0.3}],folder)
            self.assertEqual(g['words'][0],{'text':'hi','start':0.0,'end':0.125,'start_frame':0,'end_frame':2});self.assertEqual((g['words'][1]['start_frame'],g['words'][1]['end_frame']),(4,7))
            self.assertEqual((g['frames'],len(g['per_frame'])),(N,N));self.assertEqual([p['word'] for p in g['per_frame'][:9]],[0,0,0,None,1,1,1,1,None])
            self.assertEqual(sorted(p['frame'] for p in g['per_frame'] if p['mouth_hidden']),[2,5,6,20])
            self.assertEqual(g['summary']['speech_frames_mouth_hidden'],3)
            (folder/'face-tracking.json').unlink();self.assertIsNone(W.mouth_guidance([{'text':'hi','start':0,'end':0.1}],folder)['per_frame'][0]['mouth_hidden'])

# ---------------------------------------------------------------- transcription through the routes

class Transcribe(Base):
    def test_fake_worker_writes_words_json_once_then_the_cache_answers(self):
        with FakeLocal(self.d) as fake,NoNetwork() as net:
            info=self.client.get(f'/jobs/{HEX}/words').json();local=next(e for e in info['engines'] if e['name']=='local')
            self.assertTrue(local['ready']);self.assertFalse(local['paid']);self.assertEqual(info['words'],[]);self.assertIsNone(info['source']);self.assertTrue(info['has_audio'])
            r=self.client.post(f'/jobs/{HEX}/words/transcribe',json={});self.assertEqual(r.status_code,200,r.text);body=r.json()
            self.assertEqual([w['text'] for w in body['words']],['Hello,','there','friend.']);self.assertTrue(body['written']);self.assertFalse(body['cached']);self.assertEqual(body['estimated_cost_usd'],0)
            self.assertEqual(fake.runs(),1);self.assertEqual(net.hits,[])
            data=json.loads((self.parent/'words.json').read_text());self.assertEqual((data['version'],data['engine'],data['language'],data['singing']),(1,'mlx-whisper:fake','en',False))
            self.assertEqual(data['audio']['source'],'upload.mp4');self.assertTrue((self.parent/'mouth-guidance.json').exists())
            cache=list((self.runs/'_cache'/'words').glob('*-local-speech.json'));self.assertEqual(len(cache),1);self.assertTrue(cache[0].name.startswith(data['audio']['sha256']))
            # again: the cache answers (no worker run), words.json is not rewritten
            (self.parent/'words.json').write_text(json.dumps({**data,'words':[{'text':'mine','start':0,'end':0.2}]}));before=tree_hashes(self.parent)
            r=self.client.post(f'/jobs/{HEX}/words/transcribe',data={'engine':'local'});body=r.json()
            self.assertTrue(body['cached']);self.assertFalse(body['written']);self.assertEqual(fake.runs(),1);self.assertEqual(tree_hashes(self.parent),before,'an existing words.json is never overwritten')
            # singing mode is its own cache entry and passes --singing to the worker
            r=self.client.post(f'/jobs/{HEX}/words/transcribe',json={'singing':True});self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['singing']);self.assertEqual(fake.runs(),2)
            self.assertEqual(len(list((self.runs/'_cache'/'words').glob('*-local-singing.json'))),1)
            self.assertEqual(self.client.get(f'/jobs/{HEX}/words').json()['source'],'words.json')

    def test_missing_install_and_no_audio_are_plain_errors(self):
        with patch.object(W,'VENV_PYTHON',Path(self.d)/'nope'/'python'):
            r=self.client.post(f'/jobs/{HEX}/words/transcribe',json={});self.assertEqual(r.status_code,400);self.assertIn('not installed',r.json()['message']);self.assertIn('setup-words.sh',r.json()['fix'])
        with FakeLocal(self.d),patch.object(W,'MODELS_DIR',Path(self.d)/'empty'),patch.dict(os.environ,{'PUPPETEER_OFFLINE':'1'}):
            r=self.client.post(f'/jobs/{HEX}/words/transcribe',json={});self.assertEqual(r.status_code,400);self.assertIn('not downloaded',r.json()['message']);self.assertIn('offline',r.json()['message']);self.assertIn('setup-words.sh',r.json()['fix'])
        (self.parent/'upload.mp4').unlink()
        r=self.client.post(f'/jobs/{HEX}/words/transcribe',json={});self.assertEqual(r.status_code,400);self.assertIn('no audio',r.json()['message'])
        self.assertEqual(self.client.post(f'/jobs/{HEX}/words/transcribe',json={'engine':'laser'}).status_code,400)

    def test_fal_fallback_is_gated_offline_safe_and_parsed(self):
        r=self.client.post(f'/jobs/{HEX}/words/transcribe',json={'engine':'fal'});self.assertEqual(r.status_code,402,r.text);self.assertEqual(r.json()['estimated_cost_usd'],0.03);self.assertTrue(r.json()['fix'])
        self.assertEqual(self.client.post(f'/jobs/{HEX}/words/transcribe',json={'engine':'fal','estimate_only':True}).json()['estimated_cost_usd'],0.03)
        self.assertFalse((self.parent/'calls.jsonl').exists());self.assertFalse((self.parent/'words.json').exists())
        with NoNetwork() as net,patch.dict(os.environ,{'PUPPETEER_OFFLINE':'1'}):
            import fal_client
            with patch.object(fal_client,'upload_file',side_effect=AssertionError('upload')),patch.object(fal_client,'submit',side_effect=AssertionError('submit')):
                r=self.client.post(f'/jobs/{HEX}/words/transcribe',json={'engine':'fal','confirm_cost':'true'})
            self.assertEqual(r.status_code,400,r.text);self.assertIn('offline',r.json()['message']);self.assertEqual(net.hits,[])
        self.assertFalse((self.parent/'calls.jsonl').exists());self.assertFalse((self.parent/'words.json').exists())
        result={'language_code':'eng','text':'hi you','words':[{'text':'hi','start':0.1,'end':0.3,'type':'word'},{'text':' ','start':0.3,'end':0.35,'type':'spacing'},{'text':'you','start':0.35,'end':0.6,'type':'word'}]}
        import fal_client,config
        handle=Mock();handle.get.return_value=result
        with patch.object(fal_client,'upload_file',return_value='https://fal.example/a.wav') as up,patch.object(fal_client,'submit',return_value=handle) as sub,patch.object(config,'credential',return_value='x'):
            r=self.client.post(f'/jobs/{HEX}/words/transcribe',json={'engine':'fal','confirm_cost':'true'})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual([w['text'] for w in r.json()['words']],['hi','you']);self.assertEqual(sub.call_args[0][0],'fal-ai/elevenlabs/speech-to-text')
        self.assertTrue(up.call_args[0][0].endswith('.wav'))
        calls=[json.loads(l) for l in (self.parent/'calls.jsonl').read_text().splitlines()];self.assertEqual(len(calls),1);self.assertEqual((calls[0]['provider'],calls[0]['endpoint'],calls[0]['cost_usd']),('fal','fal-ai/elevenlabs/speech-to-text',0.03))
        r=self.client.post(f'/jobs/{HEX}/words/transcribe',json={'engine':'fal'});self.assertEqual(r.status_code,200,'a cached fal result is free: no 402');self.assertTrue(r.json()['cached'])

# ---------------------------------------------------------------- edits, save, beats, srt

class EditsAndSave(Base):
    def test_edits_persist_and_save_writes_child_words_and_guidance(self):
        (self.parent/'words.json').write_text(json.dumps({'version':1,'engine':'mlx-whisper:x','language':'en','singing':False,'words':[{'text':'helo','start':0.0,'end':0.3},{'text':'there','start':0.4,'end':0.7}]}))
        before=tree_hashes(self.parent)
        layer={'words':[{'id':'f0','text':'hel','start':0.0,'end':0.125},{'id':'w9','text':'lo','start':0.125,'end':0.3},{'id':'f1','text':'there friend','start':0.25,'end':0.9}],'singing':False,'edited':['f0','w9','f1']}
        r=self.client.put(f'/jobs/{HEX}/edits',json={'rev':0,'label':'Split "helo"','track':'words','value':layer});self.assertEqual(r.status_code,200,r.text)
        again=TestClient(application.app).get(f'/jobs/{HEX}/edits').json();self.assertEqual(again['layer']['words'],layer);self.assertEqual(again['pending']['words'],3)   # a reload sees the same edits
        self.assertEqual(again['summary'],['words: 3 words edited'])
        self.assertEqual(self.client.get(f'/jobs/{HEX}/words').json()['source'],'edits')
        beats=self.client.get(f'/jobs/{HEX}/words/beats').json();self.assertEqual(beats['source'],'edits');self.assertEqual(beats['lines'],['0.0–0.9 s says: "hel lo there friend"'])
        srt=self.client.get(f'/jobs/{HEX}/subtitles.srt');self.assertEqual(srt.status_code,200);self.assertIn('attachment',srt.headers['content-disposition']);self.assertIn('.srt',srt.headers['content-disposition'])
        self.assertTrue(srt.text.startswith('1\n00:00:00,000 --> 00:00:00,900\nhel lo there friend\n\n'))
        r=self.client.post(f'/jobs/{HEX}/edits/save');self.assertEqual(r.status_code,200,r.text);job=wait(r.json()['id']);self.assertEqual(job['state'],'done',job);child=self.runs/r.json()['id']
        data=json.loads((child/'words.json').read_text());self.assertEqual([w['text'] for w in data['words']],['hel','lo','there friend']);self.assertEqual((data['words'][1]['end'],data['words'][2]['start']),(0.25,0.25),'overlap removed on save (the earlier word is trimmed)');self.assertEqual(data['engine'],'mlx-whisper:x')
        g=json.loads((child/'mouth-guidance.json').read_text());self.assertEqual(len(g['words']),3);self.assertEqual(len(g['per_frame']),N);self.assertTrue(g['per_frame'][2]['mouth_hidden'])
        self.assertEqual(tree_hashes(self.parent),before,'the parent is sha256-identical')

    def test_retranscription_in_the_layer_and_empty_states(self):
        self.assertEqual(self.client.get(f'/jobs/{HEX}/words/beats').status_code,404);self.assertEqual(self.client.get(f'/jobs/{HEX}/subtitles.srt').status_code,404)
        value={'words':[{'id':'a','text':'new','start':0,'end':0.2}],'singing':True,'edited':[],'replaced':{'engine':'mlx-whisper:t','language':'en'}}
        self.client.put(f'/jobs/{HEX}/edits',json={'rev':0,'label':'Transcribe again','track':'words','value':value})
        view=self.client.get(f'/jobs/{HEX}/edits').json();self.assertEqual(view['pending']['words'],1);self.assertEqual(view['summary'],['words: transcribed again (1 word, singing mode)'])
        r=self.client.post(f'/jobs/{HEX}/edits/save');job=wait(r.json()['id']);child=self.runs/r.json()['id']
        data=json.loads((child/'words.json').read_text());self.assertEqual((data['engine'],data['singing']),('mlx-whisper:t',True))

    def test_guidance_follows_a_branch_that_reruns_the_face_stage(self):
        (self.parent/'words.json').write_text(json.dumps({'version':1,'engine':'e','language':'en','singing':False,'words':[{'text':'hi','start':0.0,'end':0.5}]}))
        child=Path(self.d)/'runs'/('d'*32);child.mkdir()
        for n in ('words.json','original.mp4'):os.link(self.parent/n,child/n)
        (child/'face-tracking.json').write_text(json.dumps({'frames':N,'fps':24,'missing_frames':[0,1],'filled_frames':[],'edited':{'off_frames':[3]}}))
        self.assertTrue(W.refresh_guidance(child));g=json.loads((child/'mouth-guidance.json').read_text())
        self.assertEqual([p['frame'] for p in g['per_frame'] if p['mouth_hidden']],[0,1,3]);self.assertFalse((self.parent/'mouth-guidance.json').exists())
        self.assertFalse(W.refresh_guidance(child),'unchanged data is not rewritten')

# ---------------------------------------------------------------- burn-in

def frames_of(path):
    import av
    with av.open(str(path)) as c:return [f.to_ndarray(format='rgb24').astype(int) for f in c.decode(video=0)]
def audio_packets(path):
    import av
    with av.open(str(path)) as c:return [bytes(p) for p in c.demux(c.streams.audio[0]) if p.size]

class BurnIn(Base):
    def test_text_only_in_the_bottom_band_during_the_word_and_audio_identical(self):
        src=self.parent/'final-preview.mp4';frames=[np.full((192,320,3),(60,90,120),np.uint8) for _ in range(N)];write_av(src,frames)
        (self.parent/'words.json').write_text(json.dumps({'version':1,'engine':'e','language':'en','singing':False,'words':[{'text':'Hello','start':0.25,'end':0.75}]}))
        state=self.client.get(f'/jobs/{HEX}/subtitles').json();self.assertFalse(state['burn'],'off by default');self.assertEqual(state['cues'],1);self.assertFalse((self.parent/'final-preview-subtitled.mp4').exists())
        before=json.loads(json.dumps(tree_hashes(self.parent)))
        r=self.client.post(f'/jobs/{HEX}/subtitles',json={'burn':True});self.assertEqual(r.status_code,200,r.text);state=r.json()
        self.assertTrue(state['burn']);self.assertTrue(state['up_to_date']);out=self.parent/'final-preview-subtitled.mp4';self.assertTrue(out.exists())
        self.assertEqual(json.loads((self.parent/'subtitles.json').read_text())['files']['final-preview-subtitled.mp4'],{'frames':N,'frames_with_text':12})
        self.assertEqual({k:v for k,v in tree_hashes(self.parent).items() if k in before},before,'the untouched final and every other file stay as they were')
        a,b=frames_of(src),frames_of(out);self.assertEqual(len(a),len(b))
        band=int(192*0.6)
        for i,(x,y) in enumerate(zip(a,b)):
            top=np.abs(x[:band]-y[:band]).max();bottom=int((np.abs(x[band:]-y[band:]).max(2)>60).sum())
            self.assertLess(top,12,f'frame {i}: nothing changes above the bottom band')
            if 6<=i<18:self.assertGreater(bottom,40,f'frame {i}: text drawn while the word is spoken')
            else:self.assertEqual(bottom,0,f'frame {i}: no text outside the word')
        self.assertEqual(audio_packets(src),audio_packets(out),'audio packets copied unchanged')
        r=self.client.post(f'/jobs/{HEX}/subtitles',data={'burn':'false'});self.assertFalse(r.json()['burn']);self.assertTrue(out.exists())

    def test_burn_needs_words_and_a_final(self):
        r=self.client.post(f'/jobs/{HEX}/subtitles',json={'burn':True});self.assertEqual(r.status_code,400);self.assertIn('no transcript',r.json()['message'])
        (self.parent/'words.json').write_text(json.dumps({'version':1,'words':[{'text':'a','start':0,'end':0.2}]}))
        r=self.client.post(f'/jobs/{HEX}/subtitles',json={'burn':True});self.assertEqual(r.status_code,400);self.assertIn('no final preview',r.json()['message']);self.assertTrue(r.json()['fix'])

# ---------------------------------------------------------------- the real local engine (skipped without .venv-words + model)

@unittest.skipUnless(W.VENV_PYTHON.exists() and W.local_ready() is None and (FIXTURE/'upload.mp4').exists(),'needs bash setup-words.sh and the fixture run')
class RealLocal(unittest.TestCase):
    def test_fixture_speech_gives_timed_words(self):
        with tempfile.TemporaryDirectory() as d:
            runs=Path(d)/'runs';folder=runs/('e'*32);folder.mkdir(parents=True)
            for n in ('upload.mp4','original.mp4','face-tracking.json'):os.link(FIXTURE/n,folder/n)
            before=tree_hashes(FIXTURE)
            with NoNetwork() as net:result=W.transcribe(folder,runs,'local',False)
            words=result['data']['words'];self.assertGreaterEqual(len(words),5,words);self.assertEqual(net.hits,[])
            for a,b in zip(words,words[1:]):self.assertLessEqual(a['end'],b['start']+1e-6)
            self.assertTrue(all(0<=w['start']<w['end']<=8.2 for w in words))
            self.assertTrue(result['written']);self.assertTrue((folder/'mouth-guidance.json').exists());self.assertEqual(tree_hashes(FIXTURE),before)
            again=W.transcribe(folder,runs,'local',False);self.assertTrue(again['cached']);self.assertLess(again['seconds'],5)

if __name__=='__main__':unittest.main()
