"""Provider adapters with mocked HTTP and mocked fal_client: exact payloads, state mapping, finalize, no network."""
import unittest,tempfile,json
from pathlib import Path
from fractions import Fraction
from unittest.mock import patch,Mock
import fal_client
import providers,seedance_bridge
from providers import enhancor as enh,fal as falmod
from providers.base import CAPABILITY_KEYS,build_prompt,check_video_constraints

NO_NET=[patch('requests.post',side_effect=AssertionError('network')),patch('requests.get',side_effect=AssertionError('network')),patch('requests.Session.request',side_effect=AssertionError('network'))]

def no_network(test):
    """Fail if anything reaches `requests` while the adapters run."""
    def wrapper(self):
        with NO_NET[0],NO_NET[1],NO_NET[2]:return test(self)
    return wrapper

def write_clip(path,width=320,height=320,frames=48,rate=24):
    import av,numpy as np
    with av.open(str(path),'w') as out:
        v=out.add_stream('libx264',rate=rate);v.width=width;v.height=height;v.pix_fmt='yuv420p'
        for i in range(frames):
            f=av.VideoFrame.from_ndarray(np.full((height,width,3),90,dtype=np.uint8),format='rgb24');f.pts=i;f.time_base=Fraction(1,rate)
            for packet in v.encode(f):out.mux(packet)
        for packet in v.encode():out.mux(packet)

def run_folder(d,mesh=None):
    p=Path(d);(p/'audio-manifest.json').write_text('{}');(p/'seedance-input.mp4').write_bytes(b'prepared')
    (p/'char1-reference.png').write_bytes(b'png');(p/'char2-reference.png').write_bytes(b'png');(p/'char1-reference.mp4').write_bytes(b'identity')
    if mesh:(p/'workflow-mode.json').write_text(json.dumps({'mode':mesh}))
    return p

def enhancor_settings(key,default=''):
    return {'ENHANCOR_WEBHOOK_URL':'https://example.org/callback','ENHANCOR_BASE_URL':'https://enhancor.test/v1'}.get(key,default)

def fal_settings(key,default=''):
    return {'FAL_KEY':'fal-secret-key','FAL_TASK':'editing'}.get(key,default)

EDIT_TAIL="\n@Video1 is the colored-depth composite with the original dialogue embedded; use its embedded audio for performance and lip synchronization. @Image1 is the only character reference."

class PromptTests(unittest.TestCase):
    def test_edit_single_reference(self):
        with tempfile.TemporaryDirectory() as d:
            full,mode=build_prompt('Base @Audio1',d,{'char1':Path('a.png'),'char2':None})
            self.assertEqual(mode,'edit');self.assertEqual(full,'Base the audio embedded in @Video1'+EDIT_TAIL)
    def test_second_image_and_video_identity(self):
        with tempfile.TemporaryDirectory() as d:
            full,_=build_prompt('Base',d,{'char1':Path('a.png'),'char2':Path('b.png')})
            self.assertIn("@Image2 defines the second character's identity only, under the same rules.",full)
            full,mode=build_prompt('Base',d,{'char1':Path('a.mp4'),'char2':None})
            self.assertEqual(mode,'multi_reference');self.assertIn('@Video2 defines the primary character',full)
    def test_mesh_substitution(self):
        with tempfile.TemporaryDirectory() as d:
            run_folder(d,'face_mesh');full,_=build_prompt('Base',d,{'char1':Path('a.png'),'char2':None})
            self.assertIn('original video with face mesh overlay',full);self.assertNotIn('colored-depth',full);self.assertIn('Remove all face mesh lines',full)

class EnhancorTests(unittest.TestCase):
    @no_network
    def test_edit_payload_exact(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d);response=Mock(ok=True);response.json.return_value={'requestId':'enh-1'}
            with patch('providers.enhancor.credential',return_value='secret'),patch('providers.enhancor.setting',side_effect=enhancor_settings),patch('providers.enhancor.upload',side_effect=lambda f:'https://tmpfiles.org/dl/'+Path(f).name),patch('providers.enhancor.requests.post',return_value=response) as post:
                ident=enh.Enhancor().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':p/'char2-reference.png'},'Base',folder=p,status=lambda s:None)
            self.assertEqual(ident,'enh-1')
            self.assertEqual(post.call_args.args[0],'https://enhancor.test/v1/queue');self.assertEqual(post.call_args.kwargs['headers'],{'x-api-key':'secret'})
            expected={'resolution':'1080p','output_format':'mp4','pass_faces':True,'webhook_url':'https://example.org/callback','mode':'edit','is_draft':True,'aspect_ratio':'adaptive',
                      'videos':['https://tmpfiles.org/dl/seedance-input.mp4'],'audios':[],'images':['https://tmpfiles.org/dl/char1-reference.png','https://tmpfiles.org/dl/char2-reference.png'],
                      'prompt':"Base\n@Video1 is the colored-depth composite with the original dialogue embedded; use its embedded audio for performance and lip synchronization. @Image2 defines the second character's identity only, under the same rules."}
            self.assertEqual(post.call_args.kwargs['json'],expected)
            self.assertEqual(json.loads((p/'seedance-request.json').read_text()),expected)
    @no_network
    def test_multi_reference_when_char1_is_video(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d);response=Mock(ok=True);response.json.return_value={'requestId':'enh-2'}
            with patch('providers.enhancor.credential',return_value='secret'),patch('providers.enhancor.setting',side_effect=enhancor_settings),patch('providers.enhancor.upload',side_effect=lambda f:'https://h/'+Path(f).name),patch('providers.enhancor.probe_video',return_value={'seconds':5.4,'width':1920,'height':1080,'fps':24.0}),patch('providers.enhancor.requests.post',return_value=response) as post:
                enh.Enhancor().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.mp4','char2':None},'Base',folder=p,status=lambda s:None)
            payload=post.call_args.kwargs['json']
            self.assertEqual(payload['mode'],'multi_reference');self.assertEqual(payload['duration'],'5');self.assertEqual(payload['aspect_ratio'],'16:9')
            self.assertEqual(payload['videos'],['https://h/seedance-input.mp4','https://h/char1-reference.mp4']);self.assertEqual(payload['images'],[])
            self.assertIn('@Video2 defines the primary character',payload['prompt'])
    @no_network
    def test_missing_webhook_blocks_before_upload(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d)
            with patch('providers.enhancor.credential',return_value='secret'),patch('providers.enhancor.setting',side_effect=lambda k,d='':d),patch('providers.enhancor.upload') as up:
                with self.assertRaises(ValueError):enh.Enhancor().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None)
            up.assert_not_called()
    @no_network
    def test_poll_state_mapping(self):
        with tempfile.TemporaryDirectory() as d:
            for raw,state in [({'status':'COMPLETED','result':'https://cdn/x.mp4'},'done'),({'status':'FAILED','error':'boom'},'error'),({'status':'CANCELED'},'error'),({'status':'PROCESSING'},'running'),({'status':'QUEUED'},'running')]:
                response=Mock();response.json.return_value=raw
                with patch('providers.enhancor.credential',return_value='secret'),patch('providers.enhancor.setting',side_effect=enhancor_settings),patch('providers.enhancor.requests.post',return_value=response) as post:
                    result=enh.Enhancor().poll('enh-1',folder=d)
                self.assertEqual(result['state'],state,raw);self.assertEqual(post.call_args.kwargs['json'],{'request_id':'enh-1'})
                if state=='done':self.assertEqual(result['result_url'],'https://cdn/x.mp4')
                if raw.get('error'):self.assertIn('boom',result['status'])
    @no_network
    def test_finalize_reuses_draft_payload(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'seedance-request.json').write_text(json.dumps({'is_draft':True,'webhook_url':'https://example.org/callback'}))
            response=Mock();response.json.return_value={'requestId':'hd-1'}
            with patch('providers.enhancor.credential',return_value='secret'),patch('providers.enhancor.setting',side_effect=enhancor_settings),patch('providers.enhancor.requests.post',return_value=response) as post:
                self.assertEqual(enh.Enhancor().finalize('enh-1',folder=p),'hd-1')
            self.assertEqual(post.call_args.kwargs['json'],{'draft_id':'enh-1','webhook_url':'https://example.org/callback'})
            self.assertEqual(json.loads((p/'hd/request.json').read_text()),{'draft_id':'enh-1','webhook_url':'https://example.org/callback'})

class FalTests(unittest.TestCase):
    def fal_patches(self,**extra):
        submit=Mock(return_value=Mock(request_id='fal-req'))
        return [patch('providers.fal.setting',side_effect=fal_settings),patch('providers.fal.credential',return_value='fal-secret-key'),patch('providers.fal.load_env'),
                patch('providers.fal.check_video_constraints'),patch('providers.fal.check_image_constraints'),
                patch('providers.fal.fal_client.upload_file',side_effect=lambda f,**k:'https://v3.fal.media/files/'+Path(f).name),patch('providers.fal.fal_client.submit',submit)],submit
    @no_network
    def test_draft_payload_exact(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d);patches,submit=self.fal_patches()
            with patches[0],patches[1],patches[2],patches[3],patches[4],patches[5],patches[6]:
                ident=falmod.Fal().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':p/'char2-reference.png'},'Base',folder=p,status=lambda s:None)
            self.assertEqual(ident,'fal-req')
            expected={'prompt':"Base\n@Video1 is the colored-depth composite with the original dialogue embedded; use its embedded audio for performance and lip synchronization. @Image2 defines the second character's identity only, under the same rules.",
                      'video_urls':['https://v3.fal.media/files/seedance-input.mp4'],'image_urls':['https://v3.fal.media/files/char1-reference.png','https://v3.fal.media/files/char2-reference.png'],
                      'task':'editing','draft':True,'resolution':'480p','generate_audio':True}
            self.assertEqual(submit.call_args.args,('bytedance/seedance-2.5/reference-to-video',));self.assertEqual(submit.call_args.kwargs,{'arguments':expected})
            self.assertEqual(json.loads((p/'seedance-request.json').read_text()),expected)
            self.assertNotIn('fal-secret-key',(p/'seedance-request.json').read_text())
    @no_network
    def test_video_identity_goes_to_video_urls_and_images_omitted(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d);patches,submit=self.fal_patches()
            with patches[0],patches[1],patches[2],patches[3],patches[4],patches[5],patches[6]:
                falmod.Fal().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.mp4','char2':None},'Base',folder=p,status=lambda s:None)
            payload=submit.call_args.kwargs['arguments']
            self.assertEqual(payload['video_urls'],['https://v3.fal.media/files/seedance-input.mp4','https://v3.fal.media/files/char1-reference.mp4'])
            self.assertNotIn('image_urls',payload);self.assertNotIn('duration',payload);self.assertNotIn('aspect_ratio',payload)
            self.assertIn('@Video2 defines the primary character',payload['prompt'])
    @no_network
    def test_missing_key_raises_before_any_fal_call(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d)
            with patch('providers.fal.setting',side_effect=lambda k,d='':d),patch('providers.fal.credential',side_effect=ValueError('Set FAL_KEY in this project’s .env file.')),patch('providers.fal.load_env'),patch('providers.fal.fal_client.upload_file') as up,patch('providers.fal.fal_client.submit') as submit:
                with self.assertRaises(ValueError) as caught:falmod.Fal().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None)
            self.assertIn('FAL_KEY',str(caught.exception));up.assert_not_called();submit.assert_not_called()
    @no_network
    def test_invalid_task_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d)
            with patch('providers.fal.setting',side_effect=lambda k,d='':{'FAL_KEY':'x','FAL_TASK':'remix'}.get(k,d)),patch('providers.fal.load_env'),patch('providers.fal.fal_client.submit') as submit:
                with self.assertRaises(ValueError):falmod.Fal().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None)
            submit.assert_not_called()
    @no_network
    def test_errors_are_wrapped_without_the_key(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d);patches,_=self.fal_patches()
            with patches[0],patches[1],patches[2],patches[3],patches[4],patches[5],patch('providers.fal.fal_client.submit',side_effect=fal_client.FalClientError('denied for fal-secret-key')):
                with self.assertRaises(RuntimeError) as caught:falmod.Fal().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None)
            self.assertNotIn('fal-secret-key',str(caught.exception));self.assertIn('FalClientError',str(caught.exception))
    @no_network
    def test_poll_state_mapping(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'seedance-response.json').write_text(json.dumps({'requestId':'fal-req','provider':'fal','endpoint':falmod.DRAFT_APP}))
            result={'video':{'url':'https://v3.fal.media/out.mp4'},'seed':7,'draft_id':'draft-abc'}
            cases=[(fal_client.Queued(position=3),'queued'),(fal_client.InProgress(logs=[]),'running'),(fal_client.Completed(logs=[],metrics={}),'done'),(fal_client.Completed(logs=[],metrics={},error='out of credits'),'error')]
            for current,state in cases:
                with patch('providers.fal.setting',side_effect=fal_settings),patch('providers.fal.credential',return_value='fal-secret-key'),patch('providers.fal.load_env'),patch('providers.fal.fal_client.status',return_value=current) as st,patch('providers.fal.fal_client.result',return_value=result) as res:
                    out=falmod.Fal().poll('fal-req',folder=p)
                self.assertEqual(out['state'],state,current);self.assertEqual(st.call_args.args,(falmod.DRAFT_APP,'fal-req'));self.assertEqual(st.call_args.kwargs,{'with_logs':False})
                if state=='queued':self.assertIn('position 3',out['status']);res.assert_not_called()
                if state=='done':
                    self.assertEqual(out['result_url'],'https://v3.fal.media/out.mp4');self.assertEqual(out['draft_id'],'draft-abc')
                    self.assertEqual(json.loads((p/'fal-result.json').read_text()),result)
                if state=='error':self.assertIn('out of credits',out['status']);res.assert_not_called()
    @no_network
    def test_finalize_completes_saved_draft(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'fal-result.json').write_text(json.dumps({'video':{'url':'https://x/y.mp4'},'draft_id':'draft-abc'}))
            submit=Mock(return_value=Mock(request_id='fal-hd'))
            with patch('providers.fal.setting',side_effect=fal_settings),patch('providers.fal.credential',return_value='fal-secret-key'),patch('providers.fal.load_env'),patch('providers.fal.fal_client.submit',submit):
                self.assertEqual(falmod.Fal().finalize('fal-req',folder=p),'fal-hd')
            self.assertEqual(submit.call_args.args,('bytedance/seedance-2.5/draft/complete',));self.assertEqual(submit.call_args.kwargs,{'arguments':{'draft_id':'draft-abc','resolution':'1080p'}})
            self.assertEqual(json.loads((p/'hd/request.json').read_text()),{'draft_id':'draft-abc','resolution':'1080p'})
    @no_network
    def test_finalize_without_draft_id_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'fal-result.json').write_text(json.dumps({'video':{'url':'https://x/y.mp4'},'draft_id':None}));(p/'generation.json').write_text(json.dumps({'request_id':'fal-req','provider':'fal'}))
            with patch('providers.fal.setting',side_effect=fal_settings),patch('providers.fal.credential',return_value='fal-secret-key'),patch('providers.fal.load_env'),patch('providers.fal.fal_client.submit') as submit:
                with self.assertRaises(ValueError) as caught:falmod.Fal().finalize('fal-req',folder=p)
            self.assertIn('draft_id',str(caught.exception));submit.assert_not_called();self.assertFalse((p/'hd/request.json').exists())
    @no_network
    def test_hd_poll_uses_complete_endpoint(self):
        with tempfile.TemporaryDirectory() as d:
            hd=Path(d)/'hd';hd.mkdir();(hd/'response.json').write_text(json.dumps({'requestId':'fal-hd','provider':'fal','endpoint':falmod.COMPLETE_APP}))
            with patch('providers.fal.setting',side_effect=fal_settings),patch('providers.fal.credential',return_value='fal-secret-key'),patch('providers.fal.load_env'),patch('providers.fal.fal_client.status',return_value=fal_client.InProgress(logs=[])) as st:
                self.assertEqual(falmod.Fal().poll('fal-hd',folder=hd)['state'],'running')
            self.assertEqual(st.call_args.args,(falmod.COMPLETE_APP,'fal-hd'))

class ConstraintTests(unittest.TestCase):
    def test_video_constraints(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);write_clip(p/'ok.mp4');info=check_video_constraints(p/'ok.mp4')
            self.assertEqual((info['width'],info['height']),(320,320));self.assertAlmostEqual(info['fps'],24.0);self.assertAlmostEqual(info['seconds'],2.0,delta=.1)
            write_clip(p/'small.mp4',width=64,height=64)
            with self.assertRaises(ValueError) as caught:check_video_constraints(p/'small.mp4')
            self.assertIn('300',str(caught.exception))
            write_clip(p/'short.mp4',frames=12)
            with self.assertRaises(ValueError):check_video_constraints(p/'short.mp4')

class RegistryTests(unittest.TestCase):
    def test_capabilities_keys(self):
        for name in providers.PROVIDERS:
            caps=providers.get_provider(name).capabilities()
            for key in CAPABILITY_KEYS:self.assertIn(key,caps,name)
            self.assertEqual(caps['name'],name);self.assertEqual(caps['finalize'],'complete_draft');self.assertTrue(caps['finalize_identical'])
        self.assertFalse(providers.get_provider('fal').capabilities()['needs_webhook']);self.assertEqual(providers.get_provider('fal').capabilities()['hosting'],'fal_storage')
        self.assertTrue(providers.get_provider('enhancor').capabilities()['needs_webhook']);self.assertEqual(providers.get_provider('enhancor').capabilities()['hosting'],'tmpfiles')
    def test_unknown_provider(self):
        with self.assertRaises(ValueError):providers.get_provider('runway')
    def test_default_provider(self):
        for env,expected in [({},'enhancor'),({'FAL_KEY':'k'},'fal'),({'ENHANCOR_API_KEY':'k','FAL_KEY':'k'},'enhancor'),({'SEEDANCE_PROVIDER':'fal','ENHANCOR_API_KEY':'k'},'fal'),({'SEEDANCE_PROVIDER':'bogus','FAL_KEY':'k'},'fal')]:
            with patch('providers.setting',side_effect=lambda k,d='',env=env:env.get(k,d)):self.assertEqual(providers.default_provider(),expected,env)

class OrchestratorTests(unittest.TestCase):
    @no_network
    def test_fal_round_trip_persists_provider_and_draft_id(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d);(p/'upload.mp4').write_bytes(b'src')
            submit=Mock(return_value=Mock(request_id='fal-req'))
            with patch('mask_review.require_approved'),patch('providers.fal.setting',side_effect=fal_settings),patch('providers.fal.credential',return_value='fal-secret-key'),patch('providers.fal.load_env'),patch('providers.fal.check_video_constraints'),patch('providers.fal.check_image_constraints'),patch('audio_workflow.prepare_seedance_video',return_value=p/'seedance-input.mp4'),patch('providers.fal.fal_client.upload_file',return_value='https://v3.fal.media/f'),patch('providers.fal.fal_client.submit',submit):
                self.assertEqual(seedance_bridge.submit(p,'Base',p/'char1-reference.png',provider='fal',status=lambda s:None),'fal-req')
            self.assertEqual(json.loads((p/'seedance-response.json').read_text()),{'requestId':'fal-req','provider':'fal','endpoint':falmod.DRAFT_APP})
            generation=json.loads((p/'generation.json').read_text());self.assertEqual(generation['provider'],'fal');self.assertEqual(generation['mode'],'edit');self.assertEqual(generation['video'],'seedance-result.mp4')
            self.assertEqual(seedance_bridge.provider_for(p),'fal')
            media=Mock();media.content=b'video'
            with patch('providers.fal.setting',side_effect=fal_settings),patch('providers.fal.credential',return_value='fal-secret-key'),patch('providers.fal.load_env'),patch('providers.fal.fal_client.status',return_value=fal_client.Completed(logs=[],metrics={})),patch('providers.fal.fal_client.result',return_value={'video':{'url':'https://v3.fal.media/out.mp4'},'draft_id':'draft-abc'}),patch('providers.base.requests.get',return_value=media) as get,patch('seedance_bridge.finish_preview') as restore:
                seedance_bridge.wait_and_finish(p,'fal-req',status=lambda s:None)
            self.assertEqual(get.call_args.args[0],'https://v3.fal.media/out.mp4');self.assertEqual((p/'seedance-result.mp4').read_bytes(),b'video');restore.assert_called_once()
            self.assertEqual(json.loads((p/'generation.json').read_text())['draft_id'],'draft-abc');self.assertEqual(json.loads((p/'provider-status.json').read_text())['state'],'done')
            (p/'final-preview.mp4').write_bytes(b'preview');submit=Mock(return_value=Mock(request_id='fal-hd'))
            with patch('providers.fal.setting',side_effect=fal_settings),patch('providers.fal.credential',return_value='fal-secret-key'),patch('providers.fal.load_env'),patch('providers.fal.fal_client.submit',submit):
                self.assertEqual(seedance_bridge.submit_hd(p),'fal-hd')
            self.assertEqual(submit.call_args.kwargs,{'arguments':{'draft_id':'draft-abc','resolution':'1080p'}})
            self.assertEqual(json.loads((p/'hd/response.json').read_text()),{'requestId':'fal-hd','provider':'fal','endpoint':falmod.COMPLETE_APP});self.assertTrue((p/'hd/upload.mp4').exists())
            self.assertEqual(seedance_bridge.provider_for(p/'hd'),'fal')
            with patch('providers.fal.setting',side_effect=fal_settings),patch('providers.fal.credential',return_value='fal-secret-key'),patch('providers.fal.load_env'),patch('providers.fal.fal_client.status',return_value=fal_client.Completed(logs=[],metrics={})) as st,patch('providers.fal.fal_client.result',return_value={'video':{'url':'https://v3.fal.media/hd.mp4'},'draft_id':None}),patch('providers.base.requests.get',return_value=media),patch('seedance_bridge.finish_preview'):
                seedance_bridge.wait_and_finish(p/'hd','fal-hd',status=lambda s:None)
            self.assertEqual(st.call_args.args,(falmod.COMPLETE_APP,'fal-hd'))
            with self.assertRaises(ValueError):seedance_bridge.submit_hd(p)
    @no_network
    def test_missing_key_blocks_before_audio_preparation(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d)
            with patch('mask_review.require_approved'),patch('providers.fal.setting',side_effect=lambda k,d='':d),patch('providers.fal.load_env'),patch('audio_workflow.prepare_seedance_video') as prepare:
                with self.assertRaises(ValueError):seedance_bridge.submit(p,'Base',p/'char1-reference.png',provider='fal',status=lambda s:None)
            prepare.assert_not_called();self.assertFalse((p/'seedance-response.json').exists())
    def test_unknown_provider_name_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d)
            with patch('mask_review.require_approved'):
                with self.assertRaises(ValueError):seedance_bridge.submit(p,'Base',p/'char1-reference.png',provider='runway')
    @no_network
    def test_failed_poll_raises_and_timeout_does_not_resubmit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'seedance-response.json').write_text(json.dumps({'requestId':'enh-1','provider':'enhancor'}))
            failed=Mock();failed.json.return_value={'status':'FAILED','error':'bad input'}
            with patch('providers.enhancor.credential',return_value='secret'),patch('providers.enhancor.setting',side_effect=enhancor_settings),patch('providers.enhancor.requests.post',return_value=failed):
                with self.assertRaises(RuntimeError) as caught:seedance_bridge.wait_and_finish(p,'enh-1',status=lambda s:None)
            self.assertIn('bad input',str(caught.exception))
            pending=Mock();pending.json.return_value={'status':'PROCESSING'}
            with patch('providers.enhancor.credential',return_value='secret'),patch('providers.enhancor.setting',side_effect=enhancor_settings),patch('providers.enhancor.requests.post',return_value=pending) as post,patch('seedance_bridge.time.sleep'):
                with self.assertRaises(TimeoutError):seedance_bridge.wait_and_finish(p,'enh-1',status=lambda s:None)
            self.assertEqual(post.call_count,360);self.assertTrue(all(c.args[0].endswith('/status') for c in post.call_args_list))

class EndpointTests(unittest.TestCase):
    def test_providers_endpoint_lists_both_unconfigured(self):
        from fastapi.testclient import TestClient
        import app as application
        with patch('providers.setting',side_effect=lambda k,d='':d):
            data=TestClient(application.app).get('/providers').json()
        self.assertEqual(data['default'],'enhancor');self.assertEqual(set(data['providers']),{'enhancor','fal','wan'})
        for name,caps in data['providers'].items():
            self.assertFalse(caps['configured'],name)
            for key in CAPABILITY_KEYS:self.assertIn(key,caps)
        self.assertNotIn('FAL_KEY',json.dumps(data))
    def test_seedance_route_rejects_unknown_provider(self):
        from fastapi.testclient import TestClient
        import app as application
        with tempfile.TemporaryDirectory() as d:
            ident='a'*32;folder=Path(d)/ident;folder.mkdir();(folder/'audio-manifest.json').write_text('{}')
            with patch.object(application,'RUNS',Path(d)),patch('mask_review.require_approved'):
                r=TestClient(application.app).post('/jobs/'+ident+'/seedance',data={'prompt':'Base','provider':'runway'},files={'char1':('c.png',b'png','image/png')})
        self.assertEqual(r.status_code,400);self.assertIn('provider',r.json()['detail'].lower())

if __name__=='__main__':unittest.main()
