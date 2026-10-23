"""Regression suite for the Foundation phase: every line of the MUST KEEP list, mocks only, no network.

Written before the stage rack existed and kept green afterwards. Covers: the three preparation modes end to end
through POST /jobs (heavy steps mocked, call arguments asserted), fal and Enhancor draft -> finalize payloads,
original-audio restore on a real synthetic clip, the clean_dialogue path, the review-gate fingerprint for all
three modes, SAM multi-term / RGB retry / fallback / sam-attempts + sam-report, the face-tracking rules, the Runs
list, ?job= links and the job routes, doctor.py as a subprocess, and that every existing test module imports.
"""
import unittest,tempfile,json,time,io,zipfile,os,sys,subprocess,importlib.util
from pathlib import Path
from fractions import Fraction
from unittest.mock import patch,Mock
import numpy as np
from fastapi.testclient import TestClient
import app as application
import pipeline,face_mesh,mask_review,seedance_bridge,raw_masks,audio_workflow
from mesh_tracking import face_box,smooth_box,fill_gaps,evaluate,MAX_GAP

ROOT=Path(__file__).resolve().parents[1]
HEX='a'*32
NO_NET=lambda:[patch('requests.post',side_effect=AssertionError('network')),patch('requests.get',side_effect=AssertionError('network')),patch('requests.Session.request',side_effect=AssertionError('network'))]

# ---------------------------------------------------------------- helpers: fake heavy steps for the three modes

class FakeSteps:
    """Replacements for every heavy or paid step; each records its call and writes the files the next step expects."""
    def __init__(self):self.calls=[]
    def normalize(self,src,dst):
        self.calls.append(('normalize',Path(src).name,Path(dst).name));Path(dst).write_bytes(b'orig')
        return {'frames':3,'fps':24,'width':64,'height':64,'duration':.125}
    def depth_replicate(self,src,dst,model_name='lucataco/depth-anything-video'):
        self.calls.append(('depth_replicate',Path(src).name,Path(dst).name,model_name));Path(dst).write_bytes(b'depth')
    def depth_hf(self,src,dst):
        self.calls.append(('depth_hf',Path(src).name,Path(dst).name));Path(dst).write_bytes(b'depth-hf')
    def segment_raw(self,video,folder,prompt='person',rgb_video=None,status=print,frames=None):
        self.calls.append(('segment_raw',Path(video).name,prompt,Path(rgb_video).name if rgb_video else None))
        out=Path(folder)/'raw-masks';out.mkdir(exist_ok=True)
        (Path(folder)/'sam-report.json').write_text(json.dumps({'prompt':prompt,'terms':[t.strip() for t in prompt.split(',')],'method':'fake SAM on depth frames'}))
        (Path(folder)/'sam-attempts.json').write_text('[]');return out
    def clean_border_fragments(self,folder):
        self.calls.append(('clean_border_fragments',Path(folder).name));out=Path(folder).parent/'clean-masks';out.mkdir(exist_ok=True);return out
    def composite(self,original,depth,seg,directory,audio_source=None):
        self.calls.append(('composite',Path(original).name,Path(depth).name,Path(seg).name,Path(audio_source).name if audio_source else None))
        for n in ['mask.mp4','composite-silent.mp4','composite.mp4']:(Path(directory)/n).write_bytes(b'cutout:'+n.encode())
        return 3
    def separate(self,src,folder,status=print):
        self.calls.append(('separate',Path(src).name));folder=Path(folder)
        (folder/'vocals.wav').write_bytes(b'vocals');(folder/'music.wav').write_bytes(b'music')
        (folder/'audio-manifest.json').write_text(json.dumps({'prediction_id':'demucs-fake','stems':['vocals.wav','music.wav']}))
    def prepare_seedance_video(self,folder,clean_dialogue=False):
        self.calls.append(('prepare_seedance_video',bool(clean_dialogue)));target=Path(folder)/'seedance-input.mp4';target.write_bytes(b'prepared');return target
    def mesh_worker(self,folder,*args):
        self.calls.append(('mesh_worker',)+tuple(args));folder=Path(folder)
        (folder/'composite-silent.mp4').write_bytes(b'mesh-overlay'+(b'-depth' if '--depth' in args else b''))
        (folder/'face-landmarks.json').write_text('{"fps":24,"frames":[]}');(folder/'preview.jpg').write_bytes(b'jpg')
        (folder/'face-tracking.json').write_text(json.dumps({'frames':3,'tracked':3,'filled':0,'missing':0,'ok':True,'warning':'','message':'face tracked throughout','strict':'--depth' not in args}))
        return ''
    def names(self):return [c[0] for c in self.calls]
    def first(self,name):return next(c for c in self.calls if c[0]==name)
    def patches(self,face_root):
        return [patch('pipeline.normalize',side_effect=self.normalize),patch('pipeline.depth_replicate',side_effect=self.depth_replicate),patch('pipeline.depth_hf',side_effect=self.depth_hf),
                patch('raw_masks.segment_raw',side_effect=self.segment_raw),patch('raw_masks.clean_border_fragments',side_effect=self.clean_border_fragments),
                patch('pipeline.composite',side_effect=self.composite),patch('audio_workflow.separate',side_effect=self.separate),
                patch('audio_workflow.prepare_seedance_video',side_effect=self.prepare_seedance_video),patch('face_mesh.mesh_worker',side_effect=self.mesh_worker),
                patch('face_mesh.ROOT',face_root)]

def fake_face_root(d):
    """A ROOT whose .venv-face/bin/python exists, so the mesh modes pass their setup check without the real worker."""
    root=Path(d)/'fake-root';(root/'.venv-face/bin').mkdir(parents=True,exist_ok=True);(root/'.venv-face/bin/python').write_text('');return root

def post_job(client,data):
    data={'confirm_cost':'true',**data}   # paid modes need the cost confirmation the UI sends with every paying button
    r=client.post('/jobs',data=data,files={'video':('clip.mp4',b'video-bytes','video/mp4')})
    assert r.status_code==200,r.text
    ident=r.json()['id']
    for _ in range(200):
        if application.jobs[ident]['state']!='running':break
        time.sleep(.05)
    return ident,application.jobs[ident]

def before(names,a,b):return names.index(a)<names.index(b)

import contextlib

class PrepModesThroughPostJobsTests(unittest.TestCase):
    """All three preparation modes end to end through POST /jobs."""
    @contextlib.contextmanager
    def run_mode(self,mode,clean='',provider='replicate',prompt='person, hands'):
        with tempfile.TemporaryDirectory() as d:
            steps=FakeSteps();runs=Path(d)/'runs';runs.mkdir();patches=steps.patches(fake_face_root(d))
            with patch.object(application,'RUNS',runs):
                for p in patches:p.start()
                try:
                    data={'mode':mode,'prompt':prompt,'provider':provider}
                    if clean:data['clean_dialogue']=clean
                    ident,job=post_job(TestClient(application.app),data)
                finally:
                    for p in patches:p.stop()
                folder=runs/ident;status=json.loads((folder/'status.json').read_text())
                yield steps,folder,job,status
    def test_advanced_depth_sam(self):
        with self.run_mode('depth') as (steps,folder,job,status):
            self.assertEqual(job['state'],'done',job);self.assertEqual(status['state'],'done');self.assertIn('review required',status['status'])
            names=steps.names()
            self.assertEqual(names,['normalize','depth_replicate','segment_raw','clean_border_fragments','composite','prepare_seedance_video'])
            self.assertEqual(steps.first('normalize')[1:],('upload.mp4','original.mp4'))
            self.assertEqual(steps.first('depth_replicate')[1:],('original.mp4','depth-raw.mp4','lucataco/depth-anything-video'))
            self.assertEqual(steps.first('segment_raw')[1:],('depth.mp4','person, hands','original.mp4'))   # SAM runs on the depth video, RGB given for the retry
            self.assertEqual(steps.first('composite')[1:],('original.mp4','depth.mp4','clean-masks','upload.mp4'))
            self.assertEqual(steps.first('prepare_seedance_video')[1],False)
            self.assertEqual((folder/'depth.mp4').read_bytes(),b'depth')   # depth.mp4 is the exact copy of depth-raw.mp4
            for name in ['upload.mp4','original.mp4','depth-raw.mp4','depth.mp4','mask.mp4','composite-silent.mp4','composite.mp4','seedance-input.mp4','sam-report.json','manifest.json','status.json']:
                self.assertTrue((folder/name).exists(),name)
            manifest=json.loads((folder/'manifest.json').read_text())
            self.assertEqual((manifest['prompt'],manifest['depth_provider'],manifest['clean_dialogue'],manifest['frames']),('person, hands','replicate',False,3))
            self.assertEqual(manifest['mask_method'],'fake SAM on depth frames')
            self.assertFalse((folder/'face-tracking.json').exists());self.assertFalse(mask_review.is_mesh(folder))
    def test_advanced_depth_alternate_providers(self):
        with self.run_mode('depth',provider='replicate-chenxwh') as (steps,_,job,_):
            self.assertEqual(job['state'],'done');self.assertEqual(steps.first('depth_replicate')[3],'chenxwh/depth-any-video')
        with self.run_mode('depth',provider='huggingface') as (steps,_,job,_):
            self.assertEqual(job['state'],'done');self.assertIn('depth_hf',steps.names());self.assertNotIn('depth_replicate',steps.names())
    def test_advanced_with_clean_dialogue(self):
        with self.run_mode('depth',clean='on') as (steps,folder,job,_):
            self.assertEqual(job['state'],'done',job);names=steps.names()
            self.assertEqual(steps.first('separate')[1],'upload.mp4');self.assertTrue(before(names,'separate','prepare_seedance_video'))
            self.assertEqual(steps.first('prepare_seedance_video')[1],True)
            self.assertTrue(json.loads((folder/'manifest.json').read_text())['clean_dialogue'])
    def test_fast_face_mesh(self):
        with self.run_mode('face_mesh') as (steps,folder,job,status):
            self.assertEqual(job['state'],'done',job);names=steps.names()
            for absent in ['depth_replicate','depth_hf','segment_raw','composite','separate']:self.assertNotIn(absent,names)
            self.assertEqual(steps.first('mesh_worker'),('mesh_worker',))   # no --depth: strict rule
            self.assertTrue(before(names,'normalize','mesh_worker'));self.assertTrue(before(names,'mesh_worker','prepare_seedance_video'))
            self.assertEqual(json.loads((folder/'workflow-mode.json').read_text()),{'mode':'face_mesh'})
            manifest=json.loads((folder/'manifest.json').read_text());self.assertEqual((manifest['mode'],manifest['clean_dialogue']),('face_mesh',False))
            self.assertEqual((folder/'composite-silent.mp4').read_bytes(),b'mesh-overlay')
            for name in ['face-landmarks.json','face-tracking.json','seedance-input.mp4']:self.assertTrue((folder/name).exists(),name)
            self.assertTrue(mask_review.is_mesh(folder))
    def test_fast_face_mesh_with_clean_dialogue(self):
        with self.run_mode('face_mesh',clean='true') as (steps,folder,job,_):
            self.assertEqual(job['state'],'done',job);self.assertIn('separate',steps.names());self.assertEqual(steps.first('prepare_seedance_video')[1],True)
            self.assertTrue(json.loads((folder/'manifest.json').read_text())['clean_dialogue'])
    def test_advanced_plus_face_mesh_lenient(self):
        with self.run_mode('depth_mesh') as (steps,folder,job,_):
            self.assertEqual(job['state'],'done',job);names=steps.names()
            for required in ['normalize','depth_replicate','segment_raw','clean_border_fragments','composite','mesh_worker','prepare_seedance_video']:self.assertIn(required,names)
            self.assertEqual(steps.first('mesh_worker'),('mesh_worker','--depth'))   # --depth: lenient gap rule, mesh over the depth composite
            self.assertTrue(before(names,'composite','mesh_worker'));self.assertGreater(len(names)-1-names[::-1].index('prepare_seedance_video'),names.index('mesh_worker'))   # the clip is rebuilt after the mesh
            self.assertEqual(json.loads((folder/'workflow-mode.json').read_text()),{'mode':'depth_mesh'})
            self.assertEqual((folder/'depth-composite-silent.mp4').read_bytes(),b'cutout:composite-silent.mp4')   # the depth composite is kept
            self.assertEqual((folder/'composite-silent.mp4').read_bytes(),b'mesh-overlay-depth')             # and the mesh is drawn over it
            manifest=json.loads((folder/'manifest.json').read_text());self.assertEqual(manifest['prompt'],'person, hands');self.assertEqual(manifest['depth_provider'],'replicate')
            for name in ['depth.mp4','mask.mp4','face-landmarks.json','face-tracking.json','seedance-input.mp4']:self.assertTrue((folder/name).exists(),name)
    def test_unknown_mode_and_provider_rejected(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            client=TestClient(application.app)
            self.assertEqual(client.post('/jobs',data={'mode':'magic'},files={'video':('c.mp4',b'v','video/mp4')}).status_code,400)
            self.assertEqual(client.post('/jobs',data={'mode':'depth','provider':'runway'},files={'video':('c.mp4',b'v','video/mp4')}).status_code,400)
            self.assertEqual(list(Path(d).iterdir()),[])
    def test_failure_is_recorded_in_status(self):
        with tempfile.TemporaryDirectory() as d:
            runs=Path(d)/'runs';runs.mkdir()
            with patch.object(application,'RUNS',runs),patch('pipeline.normalize',side_effect=ValueError('Use a clip of 30 seconds or less for this hosted workflow.')),patch('audio_workflow.separate'):
                ident,job=post_job(TestClient(application.app),{'mode':'depth'})
            self.assertEqual(job['state'],'error');self.assertIn('30 seconds',job['status'])
            self.assertEqual(json.loads((runs/ident/'status.json').read_text())['state'],'error')

# ---------------------------------------------------------------- providers: draft -> finalize

def provider_folder(d,mesh=None):
    p=Path(d);(p/'audio-manifest.json').write_text('{}');(p/'seedance-input.mp4').write_bytes(b'prepared');(p/'upload.mp4').write_bytes(b'src')
    (p/'char1-reference.png').write_bytes(b'png');(p/'char2-reference.png').write_bytes(b'png');(p/'char1-reference.mp4').write_bytes(b'identity')
    if mesh:(p/'workflow-mode.json').write_text(json.dumps({'mode':mesh}))
    return p

FAL_SETTINGS=lambda k,d='':{'FAL_KEY':'fal-secret-key','FAL_TASK':'editing'}.get(k,d)
ENH_SETTINGS=lambda k,d='':{'ENHANCOR_WEBHOOK_URL':'https://example.org/callback','ENHANCOR_BASE_URL':'https://enhancor.test/v1'}.get(k,d)

class ProviderDraftFinalizeTests(unittest.TestCase):
    def test_fal_draft_then_complete_at_1080p(self):
        import fal_client
        from providers import fal as falmod
        with tempfile.TemporaryDirectory() as d,NO_NET()[0],NO_NET()[1],NO_NET()[2]:
            p=provider_folder(d);submit=Mock(return_value=Mock(request_id='fal-req'))
            common=[patch('mask_review.require_approved'),patch('providers.fal.setting',side_effect=FAL_SETTINGS),patch('providers.fal.credential',return_value='fal-secret-key'),patch('providers.fal.load_env'),
                    patch('providers.fal.check_video_constraints'),patch('providers.fal.check_image_constraints'),patch('audio_workflow.prepare_seedance_video',return_value=p/'seedance-input.mp4'),
                    patch('providers.fal.fal_client.upload_file',side_effect=lambda f,**k:'https://v3.fal.media/files/'+Path(f).name)]
            for c in common:c.start()
            try:
                with patch('providers.fal.fal_client.submit',submit):
                    ident=seedance_bridge.submit(p,'Base',p/'char1-reference.png',p/'char2-reference.png',provider='fal',status=lambda s:None)
                self.assertEqual(ident,'fal-req')
                payload=submit.call_args.kwargs['arguments'];self.assertEqual(submit.call_args.args,('bytedance/seedance-2.5/reference-to-video',))
                self.assertEqual(payload['video_urls'],['https://v3.fal.media/files/seedance-input.mp4']);self.assertEqual(payload['image_urls'],['https://v3.fal.media/files/char1-reference.png','https://v3.fal.media/files/char2-reference.png'])
                self.assertEqual((payload['task'],payload['draft'],payload['resolution'],payload['generate_audio']),('editing',True,'480p',True))
                self.assertIn('@Image2 defines the second character',payload['prompt'])
                self.assertEqual(json.loads((p/'seedance-request.json').read_text()),payload);self.assertNotIn('fal-secret-key',(p/'seedance-request.json').read_text())
                self.assertEqual(json.loads((p/'seedance-response.json').read_text()),{'requestId':'fal-req','provider':'fal','endpoint':falmod.DRAFT_APP})
                generation=json.loads((p/'generation.json').read_text());self.assertEqual((generation['provider'],generation['mode'],generation['video']),('fal','edit','seedance-result.mp4'))
                media=Mock();media.content=b'video'
                with patch('providers.fal.fal_client.status',return_value=fal_client.Completed(logs=[],metrics={})),patch('providers.fal.fal_client.result',return_value={'video':{'url':'https://v3.fal.media/out.mp4'},'draft_id':'draft-abc'}),patch('providers.base.requests.get',return_value=media),patch('seedance_bridge.finish_preview') as restore:
                    seedance_bridge.wait_and_finish(p,'fal-req',status=lambda s:None)
                restore.assert_called_once_with(p/'seedance-result.mp4',p);self.assertEqual(json.loads((p/'generation.json').read_text())['draft_id'],'draft-abc')
                (p/'final-preview.mp4').write_bytes(b'preview');hd_submit=Mock(return_value=Mock(request_id='fal-hd'))
                with patch('providers.fal.fal_client.submit',hd_submit):self.assertEqual(seedance_bridge.submit_hd(p),'fal-hd')
                self.assertEqual(hd_submit.call_args.args,('bytedance/seedance-2.5/draft/complete',));self.assertEqual(hd_submit.call_args.kwargs,{'arguments':{'draft_id':'draft-abc','resolution':'1080p'}})
                self.assertEqual(json.loads((p/'hd/request.json').read_text()),{'draft_id':'draft-abc','resolution':'1080p'})
                self.assertEqual(json.loads((p/'hd/response.json').read_text()),{'requestId':'fal-hd','provider':'fal','endpoint':falmod.COMPLETE_APP});self.assertTrue((p/'hd/upload.mp4').exists())
                with self.assertRaises(ValueError):seedance_bridge.submit_hd(p)   # never resubmits an HD request
                with self.assertRaises(ValueError):seedance_bridge.submit(p,'Base',p/'char1-reference.png',provider='fal')   # never duplicates a draft
            finally:
                for c in common:c.stop()
    def test_enhancor_draft_then_complete(self):
        from providers import enhancor as enh
        with tempfile.TemporaryDirectory() as d:
            p=provider_folder(d);response=Mock(ok=True);response.json.return_value={'requestId':'enh-1'}
            with patch('mask_review.require_approved'),patch('providers.enhancor.credential',return_value='secret'),patch('providers.enhancor.setting',side_effect=ENH_SETTINGS),patch('providers.enhancor.upload',side_effect=lambda f:'https://tmpfiles.org/dl/'+Path(f).name),patch('providers.enhancor.requests.post',return_value=response) as post:
                self.assertEqual(seedance_bridge.submit(p,'Base',p/'char1-reference.png',provider='enhancor',status=lambda s:None),'enh-1')
            self.assertEqual(post.call_args.args[0],'https://enhancor.test/v1/queue');self.assertEqual(post.call_args.kwargs['headers'],{'x-api-key':'secret'})
            payload=post.call_args.kwargs['json']
            self.assertEqual((payload['mode'],payload['is_draft'],payload['resolution'],payload['aspect_ratio']),('edit',True,'1080p','adaptive'))
            self.assertEqual(payload['videos'],['https://tmpfiles.org/dl/seedance-input.mp4']);self.assertEqual(payload['images'],['https://tmpfiles.org/dl/char1-reference.png']);self.assertEqual(payload['audios'],[])
            self.assertEqual(payload['webhook_url'],'https://example.org/callback');self.assertNotIn('secret',json.dumps(payload))
            self.assertEqual(json.loads((p/'seedance-response.json').read_text()),{'requestId':'enh-1','provider':'enhancor'})
            (p/'final-preview.mp4').write_bytes(b'preview');hd=Mock();hd.json.return_value={'requestId':'hd-1'}
            with patch('providers.enhancor.credential',return_value='secret'),patch('providers.enhancor.setting',side_effect=ENH_SETTINGS),patch('providers.enhancor.requests.post',return_value=hd) as post:
                self.assertEqual(seedance_bridge.submit_hd(p),'hd-1')
            self.assertEqual(post.call_args.kwargs['json'],{'draft_id':'enh-1','webhook_url':'https://example.org/callback'})
            self.assertEqual(json.loads((p/'hd/response.json').read_text()),{'requestId':'hd-1','provider':'enhancor'})
    def test_enhancor_identity_video_uses_multi_reference(self):
        from providers import enhancor as enh
        with tempfile.TemporaryDirectory() as d:
            p=provider_folder(d);response=Mock(ok=True);response.json.return_value={'requestId':'enh-2'}
            with patch('providers.enhancor.credential',return_value='secret'),patch('providers.enhancor.setting',side_effect=ENH_SETTINGS),patch('providers.enhancor.upload',side_effect=lambda f:'https://h/'+Path(f).name),patch('providers.enhancor.probe_video',return_value={'seconds':5.4,'width':1920,'height':1080,'fps':24.0}),patch('providers.enhancor.requests.post',return_value=response) as post:
                enh.Enhancor().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.mp4','char2':None},'Base',folder=p,status=lambda s:None)
            payload=post.call_args.kwargs['json']
            self.assertEqual((payload['mode'],payload['duration'],payload['aspect_ratio']),('multi_reference','5','16:9'));self.assertEqual(payload['videos'],['https://h/seedance-input.mp4','https://h/char1-reference.mp4'])
    def test_mesh_mode_prompt_text_reaches_the_provider(self):
        with tempfile.TemporaryDirectory() as d:
            p=provider_folder(d,'depth_mesh');response=Mock(ok=True);response.json.return_value={'requestId':'enh-3'}
            with patch('mask_review.require_approved'),patch('providers.enhancor.credential',return_value='secret'),patch('providers.enhancor.setting',side_effect=ENH_SETTINGS),patch('providers.enhancor.upload',return_value='https://h/x'),patch('audio_workflow.prepare_seedance_video') as prepare,patch('providers.enhancor.requests.post',return_value=response) as post:
                seedance_bridge.submit(p,'Base',p/'char1-reference.png',provider='enhancor',status=lambda s:None);prepare.assert_not_called()
            prompt=post.call_args.kwargs['json']['prompt']
            self.assertIn('depth composite with face mesh overlay',prompt);self.assertIn('Remove all face mesh lines',prompt);self.assertIn('Preserve the exact embedded dialogue and timing',prompt)

# ---------------------------------------------------------------- audio: original restore and clean dialogue

def write_upload(path,samples,frames=24,codec='aac'):
    with av_module().open(str(path),'w') as out:
        v=out.add_stream('libx264',rate=24);v.width=64;v.height=64;v.pix_fmt='yuv420p';a=out.add_stream(codec,rate=audio_workflow.RATE);a.layout='stereo'
        for i in range(frames):
            f=av_module().VideoFrame.from_ndarray(np.full((64,64,3),40,dtype=np.uint8),format='rgb24');f.pts=i;f.time_base=Fraction(1,24)
            for packet in v.encode(f):out.mux(packet)
        for packet in v.encode():out.mux(packet)
        for i in range(0,samples.shape[1],4096):
            f=av_module().AudioFrame.from_ndarray(np.ascontiguousarray(samples[:,i:i+4096]),format='fltp',layout='stereo');f.sample_rate=audio_workflow.RATE;f.pts=i
            for packet in a.encode(f):out.mux(packet)
        for packet in a.encode():out.mux(packet)

def av_module():
    import av;return av

def sine(seconds=1,hz=440):
    n=int(audio_workflow.RATE*seconds);return np.tile((np.sin(np.arange(n)*2*np.pi*hz/audio_workflow.RATE)*.1).astype(np.float32),(2,1))

def silent_video(path,frames=24,value=150):
    c,s=pipeline.writer(path,64,64)
    for i in range(frames):pipeline.put(c,s,np.full((64,64,3),value,dtype=np.uint8),i)
    pipeline.finish(c,s)

def audio_packets(path):
    with av_module().open(str(path)) as c:return [bytes(x) for x in c.demux(audio=0) if x.dts is not None]

class OriginalAudioTests(unittest.TestCase):
    def test_finish_preview_restores_the_entire_original_track(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);write_upload(p/'upload.mp4',sine());silent_video(p/'generated.mp4')
            result=audio_workflow.finish_preview(p/'generated.mp4',p)
            self.assertEqual(result,p/'final-preview.mp4');self.assertEqual(audio_packets(p/'upload.mp4'),audio_packets(result))
            with av_module().open(str(result)) as c:self.assertEqual(sum(1 for _ in c.decode(video=0)),24)
    def test_finish_preview_refuses_to_stretch_audio(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);write_upload(p/'upload.mp4',sine(2),frames=48);silent_video(p/'generated.mp4',frames=24)
            with self.assertRaisesRegex(ValueError,'refusing'):audio_workflow.finish_preview(p/'generated.mp4',p)
    def test_prepared_clip_carries_original_audio_packet_for_packet(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);write_upload(p/'upload.mp4',sine());silent_video(p/'composite-silent.mp4')
            audio_workflow.prepare_seedance_video(p,clean_dialogue=False)
            self.assertEqual(audio_packets(p/'upload.mp4'),audio_packets(p/'seedance-input.mp4'))
            manifest=json.loads((p/'audio-manifest.json').read_text())
            self.assertEqual((manifest['clean_dialogue'],manifest['audio_remux'],manifest['embedded_audio'],manifest['final_audio'],manifest['discard_seedance_audio']),(False,'copy','entire original source audio','entire original source audio',True))

class CleanDialogueTests(unittest.TestCase):
    def test_separate_calls_demucs_and_writes_stems(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);write_upload(p/'upload.mp4',sine(hz=220))
            stems={};tmp=p/'stems';tmp.mkdir()
            for name,hz in [('vocals',880),('other',110)]:audio_workflow.write_audio(tmp/(name+'.wav'),sine(hz=hz));stems['https://d/'+name+'.wav']=(tmp/(name+'.wav')).read_bytes()
            posted=[]
            def post(url,**kw):
                r=Mock();posted.append((url,kw))
                if url.endswith('/files'):r.json.return_value={'urls':{'get':'https://api.replicate.com/v1/files/a1'}}
                else:r.json.return_value={'id':'demucs-1','status':'succeeded','output':{'vocals':'https://d/vocals.wav','other':'https://d/other.wav','drums':None},'urls':{'get':'https://api.replicate.com/v1/predictions/demucs-1'}}
                return r
            def get(url,**kw):r=Mock();r.content=stems[url];return r
            with patch.dict(os.environ,{'REPLICATE_API_TOKEN':'tok-test'}),patch('audio_workflow.requests.post',side_effect=post),patch('audio_workflow.requests.get',side_effect=get):
                audio_workflow.separate(p/'upload.mp4',p,status=lambda s:None)
            body=next(kw['json'] for url,kw in posted if url.endswith('/predictions'))
            self.assertEqual(body['input'],{'audio':'https://api.replicate.com/v1/files/a1','model_name':'htdemucs','output_format':'wav'});self.assertEqual(body['version'],'25a173108cff36ef9f80f854c162d01df9e6528be175794b81158fa03836d953')
            for name in ['original-audio.wav','vocals.wav','music.wav','audio-prediction.json','audio-manifest.json']:self.assertTrue((p/name).exists(),name)
            manifest=json.loads((p/'audio-manifest.json').read_text());self.assertEqual(manifest['prediction_id'],'demucs-1');self.assertEqual(manifest['stems'],['vocals.wav','music.wav'])
            with patch('audio_workflow.requests.post',side_effect=AssertionError('no second call')):audio_workflow.separate(p/'upload.mp4',p,status=lambda s:None)   # stems present: never re-billed
    def test_prepared_clip_embeds_isolated_vocals(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);write_upload(p/'upload.mp4',sine(hz=220));silent_video(p/'composite-silent.mp4');audio_workflow.write_audio(p/'vocals.wav',sine(hz=880))
            audio_workflow.prepare_seedance_video(p,clean_dialogue=True)
            embedded=audio_workflow.read_audio(p/'seedance-input.mp4');spectrum=np.abs(np.fft.rfft(embedded[0,:audio_workflow.RATE]))
            self.assertEqual(int(np.argmax(spectrum)),880)
            manifest=json.loads((p/'audio-manifest.json').read_text());self.assertTrue(manifest['clean_dialogue']);self.assertEqual(manifest['embedded_audio'],'vocals.wav (Demucs)');self.assertEqual(manifest['final_audio'],'entire original source audio')
    def test_clean_dialogue_without_vocals_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);write_upload(p/'upload.mp4',sine());silent_video(p/'composite-silent.mp4')
            with self.assertRaisesRegex(ValueError,'vocals.wav'):audio_workflow.prepare_seedance_video(p,clean_dialogue=True)

# ---------------------------------------------------------------- review gate

def gate_fixture(root,mode):
    p=Path(root)/HEX;p.mkdir()
    names=list(mask_review.FILES) if mode=='depth' else ['original.mp4','face-landmarks.json','composite-silent.mp4','seedance-input.mp4']
    if mode!='depth':(p/'workflow-mode.json').write_text(json.dumps({'mode':mode}))
    if mode=='depth_mesh':names+=['depth.mp4','mask.mp4','depth-composite-silent.mp4']
    for n in names:(p/n).write_bytes(b'artifact:'+n.encode())
    (p/'upload.mp4').write_bytes(b'upload');(p/'audio-manifest.json').write_text('{"clean_dialogue": false}');(p/'status.json').write_text(json.dumps({'id':HEX,'state':'done','status':'ready'}))
    return p,names

class ReviewGateTests(unittest.TestCase):
    def check(self,mode):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            p,names=gate_fixture(d,mode);client=TestClient(application.app);files={'char1':('ref.png',b'\x89PNG\r\n\x1a\n'+b'\x00'*8,'image/png')};data={'prompt':'x','provider':'fal'}
            review=client.get(f'/jobs/{HEX}/mask-review').json();self.assertFalse(review['approved']);self.assertEqual(review['status'],'pending');self.assertIn('Review the entire prepared input',review['note'])
            with patch.object(seedance_bridge,'submit') as submit:self.assertEqual(client.post(f'/jobs/{HEX}/seedance',data=data,files=files).status_code,409);submit.assert_not_called()
            self.assertEqual(client.post(f'/jobs/{HEX}/mask-review',data={'approved':'true','fingerprint':review['fingerprint'],'note':'full clip'}).status_code,200)
            self.assertTrue(client.get(f'/jobs/{HEX}/mask-review').json()['approved']);mask_review.require_approved(p)
            for tampered in names:   # every fingerprinted artifact clears approval when it changes
                original=(p/tampered).read_bytes();(p/tampered).write_bytes(original+b'!')
                after=client.get(f'/jobs/{HEX}/mask-review').json();self.assertFalse(after['approved'],tampered);self.assertNotEqual(after['fingerprint'],review['fingerprint'],tampered)
                with self.assertRaises(ValueError):mask_review.require_approved(p)
                with patch.object(seedance_bridge,'submit') as submit:self.assertEqual(client.post(f'/jobs/{HEX}/seedance',data=data,files=files).status_code,409);submit.assert_not_called()
                self.assertEqual(client.post(f'/jobs/{HEX}/mask-review',data={'approved':'true','fingerprint':review['fingerprint'],'note':'stale'}).status_code,409)
                (p/tampered).write_bytes(original);self.assertTrue(client.get(f'/jobs/{HEX}/mask-review').json()['approved'],tampered)   # restoring the bytes restores the approval
            missing=p/names[0];missing.unlink()
            self.assertEqual(client.get(f'/jobs/{HEX}/mask-review').json()['status'],'unavailable')
    def test_depth_mode(self):self.check('depth')
    def test_face_mesh_mode(self):self.check('face_mesh')
    def test_depth_mesh_mode(self):self.check('depth_mesh')
    def test_rejection_is_recorded_and_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            p,_=gate_fixture(d,'depth');fp=mask_review.fingerprint(p)
            saved=mask_review.review(p,False,'spill on the left hand',fp);self.assertEqual(saved['status'],'rejected')
            with self.assertRaises(ValueError):mask_review.require_approved(p)

# ---------------------------------------------------------------- SAM: multi-term, RGB retry, fallback, reports

def png_bytes(mask):
    from PIL import Image
    b=io.BytesIO();Image.fromarray((np.array(mask,dtype=np.uint8)*255)).save(b,format='PNG');return b.getvalue()
def zip_masks(masks,start=0):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        for i,m in enumerate(masks):z.writestr(f'output_masks/mask_{start+i:05d}.png',png_bytes(m))
    return b.getvalue()
def empty_zip():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('overlay.mp4',b'\x00'*16)
    return b.getvalue()
def box(y0,y1,x0,x1,h=8,w=8):
    m=np.zeros((h,w),bool);m[y0:y1,x0:x1]=True;return m
def masks_in(folder):
    from PIL import Image
    return [np.asarray(Image.open(p))>127 for p in sorted(Path(folder).glob('mask_*.png'))]

class FakeReplicate:
    """Routes raw_masks' requests by URL. `outputs` maps term -> zip bytes for the primary model; `fallback` for SAM_FALLBACK_MODEL."""
    def __init__(self,outputs,fallback=None,fail_submit=None,after_first=None):
        self.outputs=outputs;self.fallback=fallback;self.fail_submit=fail_submit;self.after_first=after_first;self.predictions=[];self.uploads=0;self.blobs={}
    def post(self,url,**kw):
        r=Mock(ok=True,status_code=201)
        if url.endswith('/files'):r.json.return_value={'urls':{'get':f'https://api.replicate.com/v1/files/x{self.uploads}'}};self.uploads+=1;return r
        body=kw['json'];self.predictions.append(body)
        if self.after_first and len(self.predictions)==2:self.outputs=self.after_first
        if self.fail_submit:
            code,detail=self.fail_submit;r.ok=False;r.status_code=code;r.json.return_value={'detail':detail};r.text=detail;return r
        record=self.outputs.get(body['input']['prompt']) if body['version']==raw_masks.PRIMARY_VERSION else self.fallback
        ident='pred-%d'%len(self.predictions)
        if isinstance(record,dict):j={'id':ident,'status':record.get('status','failed'),'error':record.get('error'),'logs':record.get('logs',''),'urls':{'get':'u'},'input':body['input']}
        else:j={'id':ident,'status':'succeeded','output':f'https://replicate.delivery/{ident}/output.zip','urls':{'get':'u'},'input':body['input'],'metrics':{'predict_time':1},'logs':'ok'};self.blobs[j['output']]=record
        r.json.return_value=j;return r
    def get(self,url,**kw):r=Mock(ok=True,status_code=200);r.content=self.blobs[url];return r
    def __enter__(self):
        fallback='8digit/gener8-sam3' if self.fallback is not None else ''
        self.patches=[patch('raw_masks.requests.post',side_effect=self.post),patch('raw_masks.requests.get',side_effect=self.get),patch('raw_masks.setting',side_effect=lambda k,d='':{'REPLICATE_API_TOKEN':'tok','SAM_FALLBACK_MODEL':fallback}.get(k,d)),patch('raw_masks.load_env'),patch('raw_masks.time.sleep'),patch('raw_masks._model_version',return_value='v-fallback')]
        for p in self.patches:p.start()
        return self
    def __exit__(self,*a):
        for p in self.patches:p.stop()

class SamTests(unittest.TestCase):
    def test_multi_term_prompt_runs_each_term_and_unions(self):
        with tempfile.TemporaryDirectory() as d,FakeReplicate({'person':zip_masks([box(0,4,0,8)]*3),'hands':zip_masks([box(4,8,0,4)]*3)}) as fake:
            Path(d,'depth.mp4').write_bytes(b'v');out=raw_masks.segment_raw(Path(d,'depth.mp4'),d,'person, hands',frames=3,status=lambda s:None)
            self.assertEqual([p['input']['prompt'] for p in fake.predictions],['person','hands']);self.assertTrue(all(p['input']['mask_only'] and p['input']['return_zip'] for p in fake.predictions))
            m=masks_in(out);self.assertEqual(len(m),3);self.assertTrue(m[0][0,0] and m[0][5,0] and not m[0][5,5])
            report=json.loads(Path(d,'sam-report.json').read_text());self.assertEqual(report['terms'],['person','hands']);self.assertEqual(report['source'],'depth');self.assertEqual(report['model'],raw_masks.PRIMARY_MODEL)
            self.assertEqual([a['frames_with_mask'] for a in report['attempts']],[3,3]);self.assertIn("terms matched: ['person', 'hands']",report['method'])
            attempts=json.loads(Path(d,'sam-attempts.json').read_text());self.assertEqual(len(attempts),2);self.assertEqual({a['status'] for a in attempts},{'succeeded'});self.assertTrue(all('logs_tail' in a and 'metrics' in a for a in attempts))
    def test_empty_depth_result_retries_on_rgb(self):
        notes=[]
        with tempfile.TemporaryDirectory() as d,FakeReplicate({'person':empty_zip()},after_first={'person':zip_masks([box(0,2,0,2)]*3)}) as fake:
            Path(d,'depth.mp4').write_bytes(b'v');Path(d,'original.mp4').write_bytes(b'o')
            out=raw_masks.segment_raw(Path(d,'depth.mp4'),d,'person',rgb_video=Path(d,'original.mp4'),frames=3,status=notes.append)
            self.assertEqual(len(masks_in(out)),3);self.assertEqual(len(fake.predictions),2);self.assertEqual(fake.uploads,2)
            report=json.loads(Path(d,'sam-report.json').read_text());self.assertEqual(report['source'],'rgb');self.assertEqual([a['source'] for a in report['attempts']],['depth','rgb'])
            self.assertTrue(any('retrying on the original RGB' in n for n in notes))
    def test_fallback_model_is_used_when_primary_finds_nothing(self):
        with tempfile.TemporaryDirectory() as d,FakeReplicate({'person':empty_zip()},fallback=zip_masks([box(1,3,1,3)]*3)) as fake:
            Path(d,'depth.mp4').write_bytes(b'v');Path(d,'original.mp4').write_bytes(b'o')
            out=raw_masks.segment_raw(Path(d,'depth.mp4'),d,'person',rgb_video=Path(d,'original.mp4'),frames=3,status=lambda s:None)
            self.assertEqual(len(masks_in(out)),3);self.assertEqual(fake.predictions[-1]['version'],'v-fallback');self.assertEqual(fake.predictions[-1]['input'],{'video':'https://api.replicate.com/v1/files/x1','prompt':'person'})
            report=json.loads(Path(d,'sam-report.json').read_text());self.assertEqual(report['model'],'8digit/gener8-sam3');self.assertIn('fallback 8digit/gener8-sam3 on rgb',report['method'])
    def test_everything_empty_reports_the_real_reason(self):
        with tempfile.TemporaryDirectory() as d,FakeReplicate({'person':empty_zip(),'hands':empty_zip()},fallback=empty_zip()) as fake:
            Path(d,'depth.mp4').write_bytes(b'v');Path(d,'original.mp4').write_bytes(b'o')
            with self.assertRaises(raw_masks.SamError) as caught:raw_masks.segment_raw(Path(d,'depth.mp4'),d,'person, hands',rgb_video=Path(d,'original.mp4'),frames=3,status=lambda s:None)
            self.assertEqual(caught.exception.kind,'empty');self.assertIn('every prediction succeeded',str(caught.exception));self.assertEqual(len(fake.predictions),5)
            self.assertIsNone(json.loads(Path(d,'sam-report.json').read_text())['method']);self.assertEqual(len(json.loads(Path(d,'sam-attempts.json').read_text())),5)
    def test_billing_error_stops_immediately(self):
        with tempfile.TemporaryDirectory() as d,FakeReplicate({},fail_submit=(402,'Insufficient credit')) as fake:
            Path(d,'depth.mp4').write_bytes(b'v');Path(d,'original.mp4').write_bytes(b'o')
            with self.assertRaises(raw_masks.SamError) as caught:raw_masks.segment_raw(Path(d,'depth.mp4'),d,'person',rgb_video=Path(d,'original.mp4'),frames=3,status=lambda s:None)
            self.assertEqual(caught.exception.kind,'quota');self.assertEqual(len(fake.predictions),1)
    def test_border_fragment_cleanup_keeps_large_subjects(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            raw=Path(d)/'raw-masks';raw.mkdir();m=np.zeros((40,40),bool);m[5:35,10:30]=True;m[18:22,0:2]=True   # subject plus a 2-px sliver on the left edge
            Image.fromarray(m.astype(np.uint8)*255).save(raw/'mask_00000.png')
            out=raw_masks.clean_border_fragments(raw);cleaned=np.asarray(Image.open(out/'mask_00000.png'))>127
            self.assertTrue(cleaned[20,20]);self.assertFalse(cleaned[20,0]);self.assertEqual(out.name,'clean-masks')
            report=json.loads((Path(d)/'mask-cleanup-report.json').read_text());self.assertEqual(report[0]['removed_border_pixels'],8)

# ---------------------------------------------------------------- face tracking rules

def face(x,y,size=0.1):return [(x,y),(x+size,y),(x,y+size),(x+size,y+size)]

class FaceTrackingRuleTests(unittest.TestCase):
    def test_face_first_crop_follows_and_pads_the_face(self):
        self.assertEqual(face_box(face(.4,.4,.2),1000,1000),(320,320,680,680))   # 1.8x padded square around the face
        x0,y0,x1,y1=face_box(face(.9,.9,.08),960,540);self.assertTrue(0<=x0<x1<=960 and 0<=y0<y1<=540)   # off-centre face: clamped, never centred by force
        history=[];smooth_box(history,(0,0,100,100));self.assertEqual(smooth_box(history,(10,10,110,110)),(5,5,105,105))
    def test_gap_fill_up_to_six_frames(self):
        self.assertEqual(MAX_GAP,6)
        _,status=fill_gaps([face(0,0)]+[None]*6+[face(1,1)]);self.assertEqual(status.count('filled'),6);self.assertNotIn('missing',status)
        _,status=fill_gaps([face(0,0)]+[None]*7+[face(1,1)]);self.assertEqual(status.count('missing'),7)
    def test_strict_in_fast_lenient_in_advanced_mesh(self):
        frames=[face(0,0)]*10+[None]*7+[face(0,0)]*33+[None]*12+[face(0,0)]*133
        _,status=fill_gaps(frames);strict=evaluate(status,24);lenient=evaluate(status,24,strict=False)
        self.assertFalse(strict['ok']);self.assertIn('lost face 0.42–0.71 s, 2.08–2.58 s',strict['message'])
        self.assertTrue(lenient['ok']);self.assertIn('lost face 0.42–0.71 s, 2.08–2.58 s',lenient['warning']);self.assertIn('depth composite only',lenient['warning'])
        self.assertEqual((lenient['tracked'],lenient['filled'],lenient['missing']),(176,0,19))
        source=(ROOT/'mesh_worker.py').read_text()
        self.assertIn("'--depth' in sys.argv",source);self.assertIn('strict=not depth',source)   # the worker derives the rule from --depth
    def test_tracking_summary_line(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'face-tracking.json').write_text(json.dumps({'frames':195,'tracked':163,'filled':13,'missing':19}))
            self.assertEqual(face_mesh.tracking_summary(d),'tracked 163 / filled 13 / missing 19 of 195 frames');self.assertEqual(face_mesh.tracking_summary(Path(d)/'nope'),'')
    def test_worker_error_is_surfaced_as_one_line(self):
        with patch('face_mesh.subprocess.run',return_value=Mock(returncode=1,stderr='Traceback\nRuntimeError: Face tracking gaps: lost face 1.0–2.0 s\n',stdout='')):
            with self.assertRaises(ValueError) as caught:face_mesh.mesh_worker('/tmp/x')
        self.assertEqual(str(caught.exception),'Face mesh worker failed: Face tracking gaps: lost face 1.0–2.0 s')

# ---------------------------------------------------------------- Runs list, ?job= links, job routes

class RunsAndRoutesTests(unittest.TestCase):
    def test_runs_list_and_job_links(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            p,_=gate_fixture(d,'depth');(p/'mask-review.json').write_text('{}');(p/'final-preview.mp4').write_bytes(b'd');(p/'seedance-response.json').write_text('{}')
            q=Path(d)/('b'*32);q.mkdir();(q/'workflow-mode.json').write_text('{"mode":"face_mesh"}');(q/'upload.mp4').write_bytes(b'u');(q/'status.json').write_text(json.dumps({'id':'b'*32,'state':'error','status':'Face mesh worker failed: lost face 1.0–2.0 s'}))
            r=Path(d)/('c'*32);r.mkdir();(r/'face-tracking.json').write_text('{}');(r/'depth.mp4').write_bytes(b'd');(r/'upload.mp4').write_bytes(b'u')
            (Path(d)/'notarun').mkdir();client=TestClient(application.app);application.jobs.pop(HEX,None)   # other suites may have left an in-memory entry
            runs=client.get('/jobs').json()['runs'];self.assertEqual({x['id'] for x in runs},{HEX,'b'*32,'c'*32})
            depth=next(x for x in runs if x['id']==HEX);self.assertEqual((depth['mode'],depth['state'],depth['reviewed'],depth['draft'],depth['final'],depth['request']),('depth','done',True,True,False,True))
            mesh=next(x for x in runs if x['id']=='b'*32);self.assertEqual((mesh['mode'],mesh['state']),('face_mesh','error'));self.assertIn('lost face',mesh['status'])
            legacy=next(x for x in runs if x['id']=='c'*32);self.assertEqual((legacy['mode'],legacy['state']),('depth_mesh','unknown'))
            for x in runs:self.assertRegex(x['created'],r'^\d{4}-\d{2}-\d{2}T')
            index=client.get('/');self.assertEqual(index.status_code,200);self.assertIn("'/?job='",index.text);self.assertIn('name="mode"',index.text);self.assertIn('id="runs"',index.text)
            self.assertEqual(client.get('/jobs/'+HEX).json(),{'id':HEX,'state':'done','status':'ready'})   # saved status served after a restart
            self.assertEqual(client.get('/jobs/'+'d'*32).status_code,404);self.assertEqual(client.get('/jobs/notarun').status_code,404)
            listed=client.get(f'/jobs/{HEX}/files').json()['files'];self.assertIn('mask.mp4',listed);self.assertIn('seedance-input.mp4',listed);self.assertEqual(client.get('/jobs/'+'d'*32+'/files').status_code,404)
            self.assertEqual(client.get(f'/jobs/{HEX}/hd').json()['state'],'idle');self.assertEqual(client.get('/health').json(),{'status':'ok','service':'Puppeteer'})
            providers=client.get('/providers').json();self.assertEqual(set(providers['providers']),{'enhancor','fal','wan'});self.assertNotIn('FAL_KEY',json.dumps(providers))

# ---------------------------------------------------------------- doctor.py and the existing test modules

FAKE_KEYS={'FAL_KEY':'fake-fal-key-0001','ENHANCOR_API_KEY':'fake-enhancor-key-0002','REPLICATE_API_TOKEN':'fake-replicate-token-0003','HF_TOKEN':'fake-hf-token-0004'}

def run_doctor(env,*args):
    base={k:v for k,v in os.environ.items() if k not in FAKE_KEYS and not k.startswith(('ENHANCOR_','SEEDANCE_','MEDIA_HOST','FAL_','CATBOX'))}
    base.update({'ENHANCOR_WEBHOOK_URL':'https://example.test/callback','SEEDANCE_PROVIDER':'fal','MEDIA_HOST':'tmpfiles','MEDIA_HOST_FALLBACKS':'','FAL_TASK':'editing','CATBOX_USERHASH':''})
    base.update(env)
    return subprocess.run([sys.executable,str(ROOT/'doctor.py'),*args],cwd=ROOT,env=base,capture_output=True,text=True,timeout=120)

class DoctorTests(unittest.TestCase):
    def test_doctor_reports_keys_without_printing_them(self):
        result=run_doctor(FAKE_KEYS);out=result.stdout
        self.assertEqual(result.returncode,0,result.stderr[-500:])
        for line in ['Python:','av: OK','fastapi: OK','fal_client: OK','FAL_KEY: configured (not verified remotely)','ENHANCOR_API_KEY: configured (not verified remotely)','REPLICATE_API_TOKEN: configured (not verified remotely)','fal: READY','enhancor: READY','LOCAL SETUP READY (fal, enhancor)']:self.assertIn(line,out,line)
        for value in FAKE_KEYS.values():self.assertNotIn(value,out+result.stderr,'doctor printed a key value')
    def test_doctor_without_keys_blocks_generation_only(self):
        empty={k:'' for k in FAKE_KEYS};result=run_doctor(empty);self.assertEqual(result.returncode,0);self.assertIn('LOCAL UI READY; GENERATION BLOCKED',result.stdout);self.assertIn('FAL_KEY: MISSING',result.stdout)
        self.assertEqual(run_doctor(empty,'--require-keys').returncode,2)
    def test_every_existing_test_module_imports(self):
        for path in sorted((ROOT/'tests').glob('test_*.py')):
            if path.name==Path(__file__).name:continue
            spec=importlib.util.spec_from_file_location('regression_import_'+path.stem,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertTrue(any(isinstance(v,type) and issubclass(v,unittest.TestCase) for v in vars(module).values()),path.name)

if __name__=='__main__':unittest.main()
