"""Generator capabilities (normalize / supports) and the Wan 2.2 Animate adapter with `fal_client` mocked; no network."""
import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch,Mock
import fal_client
import providers
import providers.capabilities as capmod
from providers import wan as wanmod
from providers.base import CAPABILITY_KEYS

NO_NET=[patch('requests.post',side_effect=AssertionError('network')),patch('requests.get',side_effect=AssertionError('network')),patch('requests.Session.request',side_effect=AssertionError('network'))]

def no_network(test):
    def wrapper(self):
        with NO_NET[0],NO_NET[1],NO_NET[2]:return test(self)
    return wrapper

def run_folder(d):
    p=Path(d)/('a'*32);p.mkdir()   # a run-shaped folder so record_call writes calls.jsonl into it
    (p/'audio-manifest.json').write_text('{}');(p/'seedance-input.mp4').write_bytes(b'prepared')
    (p/'char1-reference.png').write_bytes(b'png');(p/'char2-reference.png').write_bytes(b'png');(p/'char1-reference.mp4').write_bytes(b'identity')
    return p

def wan_settings(key,default=''):
    return {'FAL_KEY':'fal-secret-key'}.get(key,default)

def wan_patches(uploads=None):
    """Patch settings, constraints and fal_client for the Wan adapter; returns (patches, submit mock, upload mock)."""
    submit=Mock(return_value=Mock(request_id='wan-req'))
    upload=Mock(side_effect=uploads or (lambda f,**k:'https://v3.fal.media/files/'+Path(f).name))
    patches=[patch('providers.wan.setting',side_effect=wan_settings),patch('providers.wan.credential',return_value='fal-secret-key'),patch('providers.wan.load_env'),
             patch('providers.wan.check_video_constraints'),patch('providers.wan.check_image_constraints'),patch('providers.wan.fal_client.upload_file',upload),patch('providers.wan.fal_client.submit',submit)]
    return patches,submit,upload

class Patched:
    def __init__(self,patches):self.patches=patches
    def __enter__(self):
        for p in self.patches:p.start()
    def __exit__(self,*exc):
        for p in self.patches:p.stop()

FAL_CAPS={'name':'fal','label':'fal · Seedance 2.5','resolutions':['480p','720p','1080p'],'draft':True,'finalize':'complete_draft','audio':True,'tasks':['auto','reference','editing','extension'],'ref_images_max':30,
          'slots':{'set_ref':True,'look_ref':True,'char2':True,'identity_video':True},'control':'video','fps':24}

class CapabilityShapeTests(unittest.TestCase):
    def test_normalize_fills_every_key_with_defaults(self):
        caps=capmod.normalize({'name':'x','label':'X'})
        for key in capmod.GENERATOR_KEYS:self.assertIn(key,caps)
        self.assertEqual(caps['resolutions'],[]);self.assertFalse(caps['draft']);self.assertIsNone(caps['finalize']);self.assertEqual(caps['max_seconds'],30)
        self.assertFalse(caps['audio']);self.assertEqual(caps['tasks'],[]);self.assertEqual(caps['ref_images_max'],1);self.assertEqual(caps['control'],'video');self.assertEqual(caps['fps'],24)
        self.assertEqual(caps['slots'],{'set_ref':False,'look_ref':False,'char2':False,'identity_video':False})
        self.assertEqual(caps['name'],'x')   # existing keys stay
    def test_normalize_derives_slots_from_legacy_keys_and_keeps_given_ones(self):
        caps=capmod.normalize({'video_identity_reference':True,'ref_images_max':2,'draft_resolution':'1080p draft'})
        self.assertTrue(caps['slots']['identity_video']);self.assertTrue(caps['slots']['char2']);self.assertEqual(caps['resolutions'],['1080p'])
        caps=capmod.normalize({'slots':{'set_ref':True},'control':'bogus','tasks':['editing','remix']})
        self.assertEqual(caps['slots'],{'set_ref':True,'look_ref':False,'char2':False,'identity_video':False});self.assertEqual(caps['control'],'video');self.assertEqual(caps['tasks'],['editing'])
        self.assertIsNot(capmod.normalize(FAL_CAPS)['resolutions'],FAL_CAPS['resolutions'])
    def test_registered_adapters_share_the_shape(self):
        for name in providers.GENERATORS:
            caps=providers.normalized_capabilities(name)
            for key in capmod.GENERATOR_KEYS+CAPABILITY_KEYS:self.assertIn(key,caps,name)
            self.assertEqual(caps['name'],name);self.assertEqual(set(caps['slots']),set(capmod.SLOT_KEYS));self.assertIn(caps['control'],capmod.CONTROLS)
            self.assertNotIn('fal-secret-key',json.dumps(caps))
        fal=providers.normalized_capabilities('fal');enh=providers.normalized_capabilities('enhancor');wan=providers.normalized_capabilities('wan')
        self.assertEqual(fal['resolutions'],['480p','720p','1080p']);self.assertTrue(fal['draft']);self.assertTrue(fal['audio']);self.assertEqual(fal['tasks'],['auto','reference','editing','extension'])
        self.assertEqual(fal['ref_images_max'],30);self.assertTrue(all(fal['slots'].values()));self.assertEqual(fal['control'],'video');self.assertEqual(fal['fps'],24)
        self.assertEqual(enh['resolutions'],['1080p']);self.assertEqual(enh['tasks'],[]);self.assertTrue(all(enh['slots'].values()));self.assertEqual(enh['finalize'],'complete_draft')
        self.assertEqual(wan['resolutions'],['480p','580p','720p']);self.assertFalse(wan['draft']);self.assertIsNone(wan['finalize']);self.assertFalse(wan['finalize_identical']);self.assertFalse(wan['audio'])
        self.assertEqual(wan['tasks'],[]);self.assertEqual(wan['ref_images_max'],1);self.assertFalse(any(wan['slots'].values()));self.assertEqual(wan['control'],'pose');self.assertEqual(wan['endpoint'],wanmod.APP)
        # the legacy registry is unchanged: /providers and default_provider still see the Seedance pair only
        self.assertEqual(providers.PROVIDERS,('enhancor','fal'));self.assertEqual(providers.GENERATORS,('enhancor','fal','wan'));self.assertEqual(providers.KEYS['wan'],'FAL_KEY')
        with patch('providers.setting',side_effect=lambda k,d='':{'FAL_KEY':'k'}.get(k,d)):self.assertTrue(providers.configured('wan'));self.assertEqual(providers.default_provider(),'fal')

class SupportsTests(unittest.TestCase):
    def wan(self):return providers.normalized_capabilities('wan')
    def test_everything_supported_is_silent(self):
        self.assertEqual(capmod.supports(FAL_CAPS,{'set':{'mode':'set_ref'},'look':{'mode':'style_ref'},'generator':{'task':'reference','resolution':'720p'},'char2':True,'char1_video':True}),[])
        self.assertEqual(capmod.supports(self.wan(),{'set':{'mode':'original'},'look':{'mode':'follow'},'generator':{'task':'auto'}}),[])
        self.assertEqual(capmod.supports(self.wan(),{}),[])
    def test_wan_limits_name_the_nearest_option(self):
        slots={'set':{'mode':'set_ref'},'look':{'mode':'style_ref'},'generator':{'task':'reference','resolution':'1080p'},'char2':True,'char1_video':True,'seconds':12}
        limits=capmod.supports(self.wan(),slots,others=[providers.normalized_capabilities('enhancor'),FAL_CAPS])
        by_slot={l['slot']:l for l in limits}
        self.assertEqual(set(by_slot),{'set','look','char2','char1','task','resolution'})
        self.assertIn('one reference image',by_slot['set']['message']);self.assertIn('set image is ignored',by_slot['set']['message']);self.assertIn('Enhancor',by_slot['set']['fix'])
        self.assertIn('style image is ignored',by_slot['look']['message']);self.assertIn('Character 2 is not sent',by_slot['char2']['message'])
        self.assertIn('identity video is not accepted',by_slot['char1']['message']);self.assertIn('one clear frame',by_slot['char1']['fix'])
        self.assertIn('keeps the pose and timing',by_slot['task']['message']);self.assertIn('fal · Seedance 2.5',by_slot['task']['fix'])   # Enhancor has no tasks, fal does
        self.assertIn('480p, 580p, 720p',by_slot['resolution']['message']);self.assertIn('720p',by_slot['resolution']['fix'])
        for l in limits:
            self.assertTrue(l['message'].endswith('.'),l);self.assertTrue(l['fix'].endswith('.'),l);self.assertNotIn('Traceback',l['message'])
    def test_default_nearest_is_seedance_via_fal_and_flat_keys_work(self):
        limits=capmod.supports(self.wan(),{'set_mode':'set_ref','look_mode':'follow'})
        self.assertEqual([l['slot'] for l in limits],['set']);self.assertIn('Seedance via fal',limits[0]['fix'])
    def test_enhancor_without_tasks_explains_the_switch(self):
        limits=capmod.supports(providers.normalized_capabilities('enhancor'),{'set':{'mode':'set_ref'},'generator':{'task':'reference'}})
        self.assertEqual([l['slot'] for l in limits],['task']);self.assertIn('no task switch',limits[0]['message'])
    def test_too_long_clip(self):
        limits=capmod.supports({'name':'x','label':'X','max_seconds':10},{'seconds':12.4})
        self.assertEqual(limits[0]['slot'],'length');self.assertIn('12.4 s',limits[0]['message'])
    def test_summary_line(self):
        self.assertEqual(capmod.summary(self.wan()),'480p/580p/720p · one render, no draft/complete · no audio (original audio restored) · pose-locked · 1 reference image')
        self.assertIn('draft → final',capmod.summary(FAL_CAPS));self.assertIn('up to 30 reference images',capmod.summary(FAL_CAPS))

class WanAdapterTests(unittest.TestCase):
    @no_network
    def test_submit_payload_exact_and_upload_order(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d);patches,submit,upload=wan_patches();seen=[]
            with Patched(patches):
                ident=wanmod.Wan().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base prompt',folder=p,status=seen.append,task='reference')
            self.assertEqual(ident,'wan-req')
            self.assertEqual([Path(c.args[0]).name for c in upload.call_args_list],['seedance-input.mp4','char1-reference.png'])   # video first, then the image
            expected={'video_url':'https://v3.fal.media/files/seedance-input.mp4','image_url':'https://v3.fal.media/files/char1-reference.png','resolution':'480p'}
            self.assertEqual(submit.call_args.args,(wanmod.APP,));self.assertEqual(submit.call_args.kwargs,{'arguments':expected})
            self.assertEqual(json.loads((p/'wan-request.json').read_text()),expected);self.assertEqual(json.loads((p/'seedance-request.json').read_text()),expected)
            self.assertNotIn('prompt',expected);self.assertNotIn('task',expected);self.assertNotIn('fal-secret-key',(p/'seedance-request.json').read_text())
            self.assertTrue(any('Uploading' in s for s in seen));self.assertTrue(any('480p' in s for s in seen))
            calls=[json.loads(l) for l in (p/'calls.jsonl').read_text().splitlines()]
            self.assertEqual((calls[-1]['provider'],calls[-1]['endpoint']),('fal',wanmod.APP))
    @no_network
    def test_resolution_from_options_file_env_and_argument(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d);patches,submit,_=wan_patches()
            (p/'wan-options.json').write_text(json.dumps({'resolution':'720p'}))
            with Patched(patches):wanmod.Wan().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None)
            self.assertEqual(submit.call_args.kwargs['arguments']['resolution'],'720p')
            with Patched(patches):wanmod.Wan(resolution='580p').submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None)
            self.assertEqual(submit.call_args.kwargs['arguments']['resolution'],'580p')
            (p/'wan-options.json').unlink()
            with patch('providers.wan.setting',side_effect=lambda k,d='':{'FAL_KEY':'x','WAN_RESOLUTION':'720p'}.get(k,d)),Patched(patches[1:]):
                wanmod.Wan().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None)
            self.assertEqual(submit.call_args.kwargs['arguments']['resolution'],'720p')
            with Patched(patches):
                with self.assertRaises(ValueError) as caught:wanmod.Wan(resolution='1080p').submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None)
            self.assertIn('480p, 580p, 720p',str(caught.exception))
    @no_network
    def test_video_char1_and_char2_are_refused_before_any_upload(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d);patches,submit,upload=wan_patches()
            with Patched(patches):
                with self.assertRaises(ValueError) as video:wanmod.Wan().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.mp4','char2':None},'Base',folder=p,status=lambda s:None)
                with self.assertRaises(ValueError) as second:wanmod.Wan().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':p/'char2-reference.png'},'Base',folder=p,status=lambda s:None)
            self.assertIn('identity video',str(video.exception));self.assertIn('Seedance via fal',str(video.exception))
            self.assertIn('one reference image',str(second.exception));self.assertIn('Character 2',str(second.exception));self.assertIn('Seedance via fal',str(second.exception))
            upload.assert_not_called();submit.assert_not_called();self.assertFalse((p/'seedance-request.json').exists());self.assertFalse((p/'calls.jsonl').exists())
    @no_network
    def test_missing_key_blocks_before_any_fal_call(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d)
            with patch('providers.wan.setting',side_effect=lambda k,d='':d),patch('providers.wan.credential',side_effect=ValueError('Set FAL_KEY in this project’s .env file.')),patch('providers.wan.load_env'),patch('providers.wan.fal_client.upload_file') as up,patch('providers.wan.fal_client.submit') as submit:
                with self.assertRaises(ValueError) as caught:wanmod.Wan().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None)
            self.assertIn('FAL_KEY',str(caught.exception));up.assert_not_called();submit.assert_not_called()
    @no_network
    def test_offline_refuses_before_upload(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d);patches,submit,upload=wan_patches()
            from stages.calls import OfflineError
            with Patched(patches),patch.dict('os.environ',{'PUPPETEER_OFFLINE':'1'}):
                with self.assertRaises(OfflineError):wanmod.Wan().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None)
            upload.assert_not_called();submit.assert_not_called()
    @no_network
    def test_errors_are_wrapped_without_the_key(self):
        with tempfile.TemporaryDirectory() as d:
            p=run_folder(d);patches,_,_=wan_patches()
            with Patched(patches[:-1]),patch('providers.wan.fal_client.submit',side_effect=fal_client.FalClientError('denied for fal-secret-key')):
                with self.assertRaises(RuntimeError) as caught:wanmod.Wan().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None)
            self.assertNotIn('fal-secret-key',str(caught.exception));self.assertIn('[FAL_KEY]',str(caught.exception));self.assertIn('FalClientError',str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
    @no_network
    def test_poll_state_mapping(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);result={'video':{'url':'https://v3.fal.media/out.mp4'},'seed':11,'prompt':'auto prompt'}
            cases=[(fal_client.Queued(position=2),'queued'),(fal_client.InProgress(logs=[]),'running'),(fal_client.Completed(logs=[],metrics={}),'done'),(fal_client.Completed(logs=[],metrics={},error='quota for fal-secret-key'),'error')]
            for current,state in cases:
                with patch('providers.wan.setting',side_effect=wan_settings),patch('providers.wan.credential',return_value='fal-secret-key'),patch('providers.wan.load_env'),patch('providers.wan.fal_client.status',return_value=current) as st,patch('providers.wan.fal_client.result',return_value=result) as res:
                    out=wanmod.Wan().poll('wan-req',folder=p)
                self.assertEqual(out['state'],state,current);self.assertEqual(st.call_args.args,(wanmod.APP,'wan-req'));self.assertEqual(st.call_args.kwargs,{'with_logs':False});self.assertEqual(out['endpoint'],wanmod.APP)
                if state=='queued':self.assertIn('position 2',out['status']);res.assert_not_called()
                if state=='done':
                    self.assertEqual(out['result_url'],'https://v3.fal.media/out.mp4');self.assertIsNone(out['draft_id']);self.assertEqual(out['seed'],11);self.assertEqual(out['auto_prompt'],'auto prompt')
                    self.assertEqual(json.loads((p/'wan-result.json').read_text()),result)
                if state=='error':self.assertIn('quota',out['status']);self.assertNotIn('fal-secret-key',out['status']);res.assert_not_called()
    @no_network
    def test_poll_without_video_url_raises_plainly(self):
        with tempfile.TemporaryDirectory() as d:
            with patch('providers.wan.setting',side_effect=wan_settings),patch('providers.wan.credential',return_value='fal-secret-key'),patch('providers.wan.load_env'),patch('providers.wan.fal_client.status',return_value=fal_client.Completed(logs=[],metrics={})),patch('providers.wan.fal_client.result',return_value={'seed':1}):
                with self.assertRaises(ValueError) as caught:wanmod.Wan().poll('wan-req',folder=d)
            self.assertIn('video URL missing',str(caught.exception))
    @no_network
    def test_finalize_is_refused_with_the_nearest_option(self):
        with tempfile.TemporaryDirectory() as d:
            with patch('providers.wan.fal_client.submit') as submit:
                with self.assertRaises(ValueError) as caught:wanmod.Wan().finalize('wan-req',folder=d)
            text=str(caught.exception);self.assertIn('no draft to complete',text);self.assertIn('720p',text);self.assertIn('Seedance via fal',text);submit.assert_not_called()
            self.assertFalse((Path(d)/'hd').exists());self.assertEqual(wanmod.Wan().capabilities()['finalize_hint'],text)

class CostTests(unittest.TestCase):
    def test_wan_prices_follow_the_fal_frame_rule(self):
        from stages import costs
        self.assertEqual(costs.PRICES['wan']['usd_per_clip_second'],0.06);self.assertEqual(costs.PRICES['wan_720p']['usd_per_clip_second'],0.12);self.assertEqual(costs.PRICES['wan_580p']['usd_per_clip_second'],0.09)
        self.assertEqual(costs.PRICES['wan']['endpoint'],wanmod.APP);self.assertEqual(costs.PRICES['wan']['provider'],'fal');self.assertNotIn('wan_complete',costs.PRICES)
        for key in ('wan','wan_580p','wan_720p'):self.assertIn('2026-10-24',costs.PRICES[key]['source']);self.assertTrue(costs.PRICES[key]['verified'])
        self.assertEqual(costs.price_for('wan',10),0.6);self.assertEqual(costs.estimate_tool('wan',10,{'resolution':'720p'}),1.2);self.assertEqual(costs.estimate_tool('wan_fal',10,{}),0.6)
        self.assertEqual(costs.estimate_tool('wan_fal',10,{'resolution':'580p'}),0.9);self.assertIsNone(costs.estimate_tool('complete_draft',10,{'provider':'wan'}))
        self.assertEqual(costs.call_cost('fal',wanmod.APP,None),0.6)
        # the existing Seedance entries are untouched
        self.assertEqual(costs.PRICES['fal']['usd_per_clip_second'],round(0.6*0.2205*2,4));self.assertEqual(costs.estimate_tool('complete_draft',10,{'provider':'fal'}),costs.price_for('fal_complete',10))

class EndpointTests(unittest.TestCase):
    def test_providers_route_still_lists_the_seedance_pair_with_old_and_new_keys(self):
        from fastapi.testclient import TestClient
        import app as application
        with patch('providers.setting',side_effect=lambda k,d='':d):
            data=TestClient(application.app).get('/providers').json()
        self.assertEqual(data['default'],'enhancor');self.assertEqual(set(data['providers']),{'enhancor','fal','wan'});self.assertEqual(data['generators'],['enhancor','fal','wan'])
        for name,caps in data['providers'].items():
            self.assertFalse(caps['configured'],name)
            for key in CAPABILITY_KEYS:self.assertIn(key,caps)
            for key in capmod.GENERATOR_KEYS:self.assertIn(key,caps)
        self.assertEqual(data['providers']['fal']['resolutions'],['480p','720p','1080p']);self.assertEqual(data['providers']['enhancor']['tasks'],[])
        self.assertNotIn('FAL_KEY',json.dumps(data))

if __name__=='__main__':unittest.main()

# ---------------------------------------------------------------- Phase B: the wan_fal tool, the routes, the generator slot data

import test_world as world
from fastapi.testclient import TestClient
import app as application
import seedance_bridge,stages

def wan_fal_patches():
    submit=Mock(return_value=Mock(request_id='wan-req'))
    return [patch('mask_review.require_approved'),patch('providers.wan.setting',side_effect=wan_settings),patch('providers.wan.credential',return_value='fal-secret-key'),patch('providers.wan.load_env'),
            patch('providers.wan.check_video_constraints'),patch('providers.wan.check_image_constraints'),patch('providers.wan.fal_client.upload_file',side_effect=lambda f,**k:'https://v3.fal.media/files/'+Path(f).name),
            patch('providers.wan.fal_client.submit',submit),patch('audio_workflow.prepare_seedance_video',side_effect=lambda folder,clean:Path(folder)/'seedance-input.mp4')],submit

class WanToolTests(unittest.TestCase):
    @no_network
    def test_submit_through_the_orchestrator_records_wan(self):
        with tempfile.TemporaryDirectory() as d:
            p=world.draft_ready(d);patches,submit=wan_fal_patches()
            stages.slots.write(p,{'generator':{'name':'wan','resolution':'720p'},'set':{'mode':'set_ref'}})
            stages.generate.write_wan_options(p)
            with Patched(patches):ident=seedance_bridge.submit(p,'Base',p/'char1-reference.png',provider='wan',status=lambda s:None,task='reference')
            self.assertEqual(ident,'wan-req');self.assertEqual(json.loads((p/'wan-options.json').read_text()),{'resolution':'720p'})
            payload=submit.call_args.kwargs['arguments'];self.assertEqual(payload['resolution'],'720p');self.assertNotIn('task',payload);self.assertNotIn('prompt',payload)
            self.assertEqual(json.loads((p/'seedance-request.json').read_text()),payload);self.assertEqual(json.loads((p/'wan-request.json').read_text()),payload)
            self.assertEqual(json.loads((p/'seedance-response.json').read_text()),{'requestId':'wan-req','provider':'wan','endpoint':wanmod.APP})
            generation=json.loads((p/'generation.json').read_text());self.assertEqual(generation['provider'],'wan');self.assertEqual(generation['task'],'not applicable');self.assertIn('no task setting',generation['task_note'])
            self.assertEqual(seedance_bridge.provider_for(p),'wan')
            report=stages.read_report(p,'generate');self.assertEqual(report['tool'],'wan_fal');self.assertEqual(report['params']['provider'],'wan');self.assertEqual(report['state'],'running')
            self.assertNotIn('task',json.loads((p/'run.json').read_text())['chain'].get('generate',{}).get('params',{}))
            # the HD step is refused plainly for a wan run
            (p/'final-preview.mp4').write_bytes(b'x')
            with self.assertRaises(ValueError) as caught:seedance_bridge.submit_hd(p)
            self.assertIn('cannot complete drafts',str(caught.exception));self.assertFalse((p/'hd/response.json').exists())
    def test_wan_fal_tool_writes_options_and_calls_the_orchestrator(self):
        with tempfile.TemporaryDirectory() as d:
            p=world.draft_ready(d);tool=stages.get_tool('generate','wan_fal')
            self.assertTrue(tool.paid);self.assertEqual(tool.provider,'wan');self.assertEqual(tool.params['resolution']['choices'],['480p','580p','720p']);self.assertNotIn('task',tool.params);self.assertNotIn('char2',tool.params)
            self.assertEqual(tool.estimate_cost({'seconds':10},{'resolution':'720p'}),1.2);self.assertEqual(tool.estimate_cost({'seconds':10},{}),0.6)
            with patch('seedance_bridge.submit',return_value='wan-req') as submit,patch('seedance_bridge.wait_and_finish') as wait:
                out=tool.run({'chain':{'prompt':{'params':{'text':'Prompt text'}}},'seconds':0.5},{'resolution':'580p'},p,lambda s:None)
            self.assertEqual(json.loads((p/'wan-options.json').read_text()),{'resolution':'580p'})
            self.assertEqual(submit.call_args.args,(p,'Prompt text',p/'char1-reference.png',None));self.assertEqual(submit.call_args.kwargs['provider'],'wan');wait.assert_called_once()
            self.assertIn('first render is the final',out['health']);self.assertIn('wan-options.json',out['outputs'])
            with self.assertRaises(ValueError):tool.run({'chain':{}},{'char1':'missing.png'},p,lambda s:None)
    def test_write_wan_options_falls_back_to_slots_then_480p(self):
        with tempfile.TemporaryDirectory() as d:
            p=world.draft_ready(d)
            self.assertEqual(stages.generate.write_wan_options(p),'480p')
            stages.slots.write(p,{'generator':{'resolution':'720p'}});self.assertEqual(stages.generate.write_wan_options(p),'720p')
            self.assertEqual(stages.generate.write_wan_options(p,'1080p'),'480p');self.assertEqual(json.loads((p/'wan-options.json').read_text()),{'resolution':'480p'})

class RouteTests(unittest.TestCase):
    def post(self,client,ident,**data):
        return client.post(f'/jobs/{ident}/seedance',data={'prompt':'Base','provider':'wan',**data},files={'char1':('hero.png',world.plate_png(),'image/png')})
    def test_seedance_route_with_wan_needs_confirmation_then_submits_at_the_slots_resolution(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)),patch('seedance_bridge.wait_and_finish'),patch.dict(application.jobs,{},clear=False):
            p=world.draft_ready(d);patches,submit=wan_fal_patches();client=TestClient(application.app)
            stages.slots.write(p,{'generator':{'name':'wan','resolution':'720p'}})
            with Patched(patches):
                r=self.post(client,world.HEX);self.assertEqual(r.status_code,402,r.text);body=r.json();self.assertIn('fix',body);self.assertAlmostEqual(body['estimated_cost_usd'],0.12*0.5,places=3)   # 0.5 s clip at 720p
                submit.assert_not_called();self.assertFalse((p/'seedance-response.json').exists())
                r=self.post(client,world.HEX,confirm_cost='true');self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['request_id'],'wan-req')
            self.assertEqual(submit.call_args.kwargs['arguments']['resolution'],'720p');self.assertEqual(json.loads((p/'wan-options.json').read_text()),{'resolution':'720p'})
            self.assertEqual(json.loads((p/'generation.json').read_text())['provider'],'wan')
            r=client.post(f'/jobs/{world.HEX}/seedance',data={'prompt':'Base','provider':'kling','confirm_cost':'true'},files={'char1':('hero.png',world.plate_png(),'image/png')});self.assertEqual(r.status_code,400)
    def test_hd_route_refuses_a_wan_run_plainly(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)),patch.dict(application.hd_jobs,{},clear=False):
            p=world.draft_ready(d);(p/'final-preview.mp4').write_bytes(b'x');(p/'generation.json').write_text(json.dumps({'request_id':'wan-req','provider':'wan'}))
            (p/'seedance-response.json').write_text(json.dumps({'requestId':'wan-req','provider':'wan','endpoint':wanmod.APP}))
            r=TestClient(application.app).post(f'/jobs/{world.HEX}/hd',data={'confirm_cost':'true'})
            self.assertEqual(r.status_code,400,r.text);body=r.json();self.assertIn('no draft to complete',body['message']);self.assertIn('fix',body);self.assertFalse((p/'hd').exists())
            self.assertEqual(TestClient(application.app).get(f'/jobs/{world.HEX}/hd').json()['state'],'idle')
    def test_generators_route_lists_limits_estimates_and_keys(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)),patch('providers.setting',side_effect=lambda k,d='':{'FAL_KEY':'fal-secret-value-xyz'}.get(k,d)):
            p=world.draft_ready(d);(p/'char2-reference.png').write_bytes(b'png');client=TestClient(application.app)
            stages.slots.write(p,{'set':{'mode':'set_ref'},'generator':{'name':'wan','resolution':'720p'}})
            data=client.get(f'/jobs/{world.HEX}/generators').json()
            self.assertEqual([g['name'] for g in data['generators']],['enhancor','fal','wan']);self.assertEqual(data['chosen'],'wan');self.assertEqual(data['resolution'],'720p');self.assertEqual(data['task'],'reference')
            by={g['name']:g for g in data['generators']}
            self.assertFalse(by['enhancor']['configured']);self.assertEqual(by['enhancor']['key'],'ENHANCOR_API_KEY');self.assertTrue(by['fal']['configured']);self.assertTrue(by['wan']['configured']);self.assertEqual(by['wan']['key'],'FAL_KEY')
            self.assertEqual([l['slot'] for l in by['wan']['limits']],['set','char2','task']);self.assertIn('set image is ignored',by['wan']['limits'][0]['message']);self.assertIn('fal · Seedance 2.5',by['wan']['limits'][0]['fix'])
            self.assertEqual(by['fal']['limits'],[]);self.assertEqual([l['slot'] for l in by['enhancor']['limits']],['task'])
            self.assertEqual(set(by['wan']['estimates']),{'480p','580p','720p'});self.assertAlmostEqual(by['wan']['estimate_usd'],0.06,places=3);self.assertAlmostEqual(by['wan']['estimates']['480p'],0.03,places=3)
            self.assertAlmostEqual(by['fal']['estimate_usd'],stages.costs.price_for('fal',0.5),places=4);self.assertIn('summary',by['wan'])
            self.assertNotIn('fal-secret-value-xyz',json.dumps(data))
            # an identity video chosen in the form (not saved yet) counts through the query string
            data=client.get(f'/jobs/{world.HEX}/generators?char1_video=1').json();self.assertIn('char1',[l['slot'] for l in next(g for g in data['generators'] if g['name']=='wan')['limits']])
            self.assertEqual(client.get('/jobs/'+'f'*32+'/generators').status_code,404)
            run=client.get(f'/jobs/{world.HEX}/run').json();self.assertAlmostEqual(run['estimates']['draft']['wan'],0.06,places=3);self.assertIsNone(run['estimates']['complete']['wan'])
    def test_index_serves_the_generator_module(self):
        client=TestClient(application.app)
        self.assertEqual(client.get('/static/generator.js').status_code,200);self.assertIn('data-slot="generator"',client.get('/').text)
