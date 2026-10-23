"""Stage rack: registry, cache keys, branching, offline switch, calls log, cost gate, presets, migration, tree."""
import unittest,tempfile,json,os,time,hashlib,sys
from pathlib import Path
from unittest.mock import patch,Mock
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_regression import FakeSteps,fake_face_root,write_upload,sine,silent_video
import app as application
import stages
from stages import base,cache,calls,presets,runner,branch,migrate,costs
from stages.calls import OfflineError

HEX='a'*32
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()
def tree_hashes(folder):
    return {p.relative_to(folder).as_posix():sha(p) for p in Path(folder).rglob('*') if p.is_file()}
def wait(ident):
    for _ in range(400):
        if application.jobs[ident]['state']!='running':return application.jobs[ident]
        time.sleep(.05)
    return application.jobs[ident]

def fake_run(d,mode='depth_mesh',ident=HEX,prompt='person, hands',clean=False):
    """A complete run made through the rack with every heavy step faked; returns (folder, steps)."""
    steps=FakeSteps();folder=Path(d)/'runs'/ident;folder.mkdir(parents=True,exist_ok=True);(folder/'upload.mp4').write_bytes(b'upload-bytes')
    patches=steps.patches(fake_face_root(d))
    for p in patches:p.start()
    try:stages.run_mode(mode,folder/'upload.mp4',folder,lambda s:None,prompt=prompt,clean_dialogue=clean)
    finally:
        for p in patches:p.stop()
    return folder,steps

# ---------------------------------------------------------------- registry

class RegistryTests(unittest.TestCase):
    def test_stage_order_and_tools(self):
        self.assertEqual(stages.STAGES,['input_doctor','audio','depth','mask','composite','face','prompt','generate','finish'])
        for stage in stages.STAGES:self.assertGreaterEqual(len(stages.tools_for(stage)),1,stage)
        for stage in ['depth','mask','face']:self.assertEqual(stages.get_tool(stage,'off').name,'off',stage)
        for stage in ['input_doctor','audio','composite','prompt','generate','finish']:
            with self.assertRaises(ValueError):stages.get_tool(stage,'off')
        first={'input_doctor':'probe','audio':'original','depth':'depth_anything_replicate','mask':'sam3_replicate','composite':'depth_cutout','face':'mediapipe_mesh','prompt':'identity_only','generate':'fal','finish':'restore_original_audio'}
        for stage,name in first.items():self.assertEqual(stages.tools_for(stage)[0].name,name)
        self.assertEqual({t.name for t in stages.tools_for('generate')},{'fal','enhancor'})
        paid={(t.stage,t.name) for s in stages.STAGES for t in stages.tools_for(s) if t.paid}
        self.assertEqual(paid,{('audio','clean_dialogue'),('depth','depth_anything_replicate'),('depth','depth_anything_replicate_chenxwh'),('mask','sam3_replicate'),('mask','sam3_points_fal'),('mask','sam2_points_replicate'),('generate','fal'),('generate','enhancor'),('finish','complete_draft')})
        with self.assertRaises(ValueError):stages.get_tool('face','nope')
        with self.assertRaises(ValueError):stages.tools_for('render')
    def test_params_schema_and_coercion(self):
        mesh=stages.get_tool('face','mediapipe_mesh')
        for name,spec in mesh.params.items():
            self.assertIn(spec['type'],('bool','number','string','choice'));self.assertIn('default',spec);self.assertIn('label',spec)
        self.assertEqual(mesh.normalize_params({}),{'strict':True,'pad':1.8,'max_gap':6})
        self.assertEqual(mesh.normalize_params({'strict':'false','pad':'2.2','max_gap':'8'}),{'strict':False,'pad':2.2,'max_gap':8})
        self.assertEqual(stages.get_tool('mask','sam3_replicate').normalize_params({'prompt':'man'}),{'prompt':'man'})
        self.assertEqual(stages.get_tool('generate','fal').normalize_params({'char1':'ref.png'}),{'char1':'ref.png','char2':''})
    def test_registry_listing_for_the_ui(self):
        listing=stages.registry();names=[s['name'] for s in listing['stages']];self.assertEqual(names,stages.STAGES)
        face=next(s for s in listing['stages'] if s['name']=='face');tool=next(t for t in face['tools'] if t['name']=='mediapipe_mesh')
        self.assertEqual(tool['params']['strict']['default'],True);self.assertFalse(tool['paid']);self.assertIn('off',[t['name'] for t in face['tools']])
        self.assertTrue(all('label' in t and 'experimental' in t and 'paid' in t for s in listing['stages'] for t in s['tools']))
        client=TestClient(application.app);self.assertEqual(client.get('/stages').json()['stages'][0]['name'],'input_doctor')
    def test_modes_map_to_chains_and_back(self):
        for mode,depth,mask,comp,face,strict in [('depth','depth_anything_replicate','sam3_replicate','depth_cutout','off',None),('face_mesh','off','off','original','mediapipe_mesh',True),('depth_mesh','depth_anything_replicate','sam3_replicate','depth_cutout','mediapipe_mesh',False)]:
            chain=stages.chain_for_mode(mode,'man','replicate',True)
            self.assertEqual((chain['depth']['tool'],chain['mask']['tool'],chain['composite']['tool'],chain['face']['tool']),(depth,mask,comp,face),mode)
            self.assertEqual(chain['audio']['tool'],'clean_dialogue')
            if strict is not None:self.assertEqual(chain['face']['params']['strict'],strict)
            if mask!='off':self.assertEqual(chain['mask']['params']['prompt'],'man')
            self.assertEqual(stages.mode_for_chain(chain),mode)
        self.assertEqual(stages.chain_for_mode('depth',provider='replicate-chenxwh')['depth']['tool'],'depth_anything_replicate_chenxwh')
        self.assertEqual(stages.chain_for_mode('depth',provider='huggingface')['depth']['tool'],'depth_anything_hf')
        self.assertEqual(stages.mode_for_chain({'depth':{'tool':'off'},'face':{'tool':'off'},'composite':{'tool':'original'}}),'original')

# ---------------------------------------------------------------- cache keys

class CacheKeyTests(unittest.TestCase):
    def test_same_inputs_same_key_any_change_new_key(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a';b=Path(d)/'b';a.mkdir();b.mkdir()
            for folder in (a,b):(folder/'original.mp4').write_bytes(b'same video')
            key=lambda folder,tool='mediapipe_mesh',params=None:cache.cache_key('face',tool,params or {'strict':True,'pad':1.8},cache.hash_artifacts(folder,('original.mp4','depth-composite-silent.mp4')))
            self.assertEqual(key(a),key(b))                                        # stable across runs
            self.assertEqual(key(a,params={'pad':1.8,'strict':True}),key(a))       # canonical params: order does not matter
            self.assertNotEqual(key(a,params={'strict':False,'pad':1.8}),key(a))   # a param change
            self.assertNotEqual(key(a,tool='off'),key(a))                          # a tool change
            (b/'original.mp4').write_bytes(b'other video');self.assertNotEqual(key(a),key(b))   # an input change
            (b/'original.mp4').write_bytes(b'same video');(b/'depth-composite-silent.mp4').write_bytes(b'x');self.assertNotEqual(key(a),key(b))   # an extra input
            self.assertNotEqual(cache.cache_key('mask','sam3_replicate',{},{}),cache.cache_key('depth','sam3_replicate',{},{}))   # the stage name counts
            self.assertEqual(len(key(a)),64)
    def test_folder_artifacts_hash_their_contents(self):
        with tempfile.TemporaryDirectory() as d:
            masks=Path(d)/'clean-masks';masks.mkdir();(masks/'mask_00000.png').write_bytes(b'a');(masks/'mask_00001.png').write_bytes(b'b')
            first=cache.artifact_hash(masks);(masks/'mask_00001.png').write_bytes(b'c');self.assertNotEqual(first,cache.artifact_hash(masks))
            self.assertIsNone(cache.artifact_hash(Path(d)/'missing'))
    def test_runs_record_keys_and_reuse_paid_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            first,steps=fake_run(d,'depth',ident='1'*32)
            run=json.loads((first/'run.json').read_text())
            for stage in stages.PREP_STAGES:
                self.assertRegex(run['chain'][stage]['key'],r'^[0-9a-f]{64}$',stage);self.assertEqual(json.loads((first/'stages'/stage/'report.json').read_text())['key'],run['chain'][stage]['key'])
            second,steps2=fake_run(d,'depth',ident='2'*32)   # same upload, same chain: the paid depth and mask stages are reused
            self.assertNotIn('depth_replicate',steps2.names());self.assertNotIn('segment_raw',steps2.names());self.assertIn('composite',steps2.names())
            run2=json.loads((second/'run.json').read_text())
            self.assertEqual(run2['chain']['depth']['cached_from'],'1'*32);self.assertEqual(run2['chain']['mask']['cached_from'],'1'*32);self.assertIsNone(run2['chain']['composite']['cached_from'])
            depth=json.loads((second/'stages/depth/report.json').read_text());self.assertEqual(depth['state'],'cached');self.assertIn('nothing re-billed',depth['health'])
            self.assertEqual((second/'depth.mp4').read_bytes(),b'depth');self.assertEqual((second/'depth.mp4').stat().st_ino,(first/'depth.mp4').stat().st_ino)
            (first/'depth.mp4').write_bytes(b'tampered')   # a changed source output is not reused
            third,steps3=fake_run(d,'depth',ident='3'*32);self.assertIn('depth_replicate',steps3.names())

# ---------------------------------------------------------------- reports and run.json

class ReportTests(unittest.TestCase):
    def test_every_stage_has_a_report_with_the_fixed_keys(self):
        with tempfile.TemporaryDirectory() as d:
            folder,_=fake_run(d,'depth_mesh')
            for stage in stages.PREP_STAGES:
                report=json.loads((folder/'stages'/stage/'report.json').read_text())
                for key in ('tool','params','inputs','outputs','frames','gaps','warnings','health','seconds','cost_usd','cached_from','started','finished'):self.assertIn(key,report,(stage,key))
                self.assertEqual(set(report['frames']),{'covered','filled','missing'});self.assertIsInstance(report['health'],str);self.assertTrue(report['health'])
            self.assertEqual(json.loads((folder/'stages/depth/report.json').read_text())['outputs'].keys(),{'depth-raw.mp4','depth.mp4'})
            face=json.loads((folder/'stages/face/report.json').read_text());self.assertIn('seedance-input.mp4',face['outputs']);self.assertEqual(face['params'],{'strict':False,'pad':1.8,'max_gap':6})
            run=json.loads((folder/'run.json').read_text())
            self.assertEqual(set(run)>= {'id','parent','created','preset','changed','chain','cost_usd_total','mode'},True);self.assertEqual(run['mode'],'depth_mesh');self.assertIsNone(run['parent']);self.assertEqual(run['state'],'done')
            self.assertEqual(set(run['chain']),set(stages.STAGES));self.assertEqual(run['chain']['mask']['params'],{'prompt':'person, hands'})
            self.assertIn('face: running mediapipe_mesh',(folder/'log.txt').read_text())
            self.assertEqual(json.loads((folder/'workflow-mode.json').read_text()),{'mode':'depth_mesh'})
    def test_off_stages_write_off_reports(self):
        with tempfile.TemporaryDirectory() as d:
            folder,_=fake_run(d,'face_mesh')
            for stage in ['depth','mask']:
                report=json.loads((folder/'stages'/stage/'report.json').read_text());self.assertEqual((report['tool'],report['state']),('off','off'))
            self.assertEqual(json.loads((folder/'stages/face/report.json').read_text())['params']['strict'],True)
    def test_failure_writes_an_error_report_and_plain_error(self):
        with tempfile.TemporaryDirectory() as d:
            steps=FakeSteps();folder=Path(d)/'runs'/HEX;folder.mkdir(parents=True);(folder/'upload.mp4').write_bytes(b'u')
            def lost(folder,*args):steps.mesh_worker(folder,*args);raise ValueError('Face mesh worker failed: Face tracking gaps: lost face 1.0–2.0 s')
            patches=steps.patches(fake_face_root(d));patches[-2]=patch('face_mesh.mesh_worker',side_effect=lost)
            for p in patches:p.start()
            try:
                with self.assertRaises(ValueError):stages.run_mode('face_mesh',folder/'upload.mp4',folder,lambda s:None)
            finally:
                for p in patches:p.stop()
            report=json.loads((folder/'stages/face/report.json').read_text());self.assertEqual(report['state'],'error');self.assertIn('lost face',report['error']['message']);self.assertIn('Expressive',report['error']['fix'])
            self.assertEqual(report['frames']['covered'],3)   # the worker's numbers survive the failure
            run=json.loads((folder/'run.json').read_text());self.assertEqual(run['state'],'error');self.assertIn('lost face',run['error']['message'])
            self.assertIn('Traceback',(folder/'log.txt').read_text());self.assertFalse((folder/'seedance-input.mp4').exists())

# ---------------------------------------------------------------- branching

class BranchTests(unittest.TestCase):
    def branch(self,d,parent,stage,tool,params,steps):
        patches=steps.patches(fake_face_root(d))
        for p in patches:p.start()
        try:
            child,chain,changed=stages.branch(parent,stage,tool,params)
            stages.run_branch(child,chain,stage,lambda s:None)
        finally:
            for p in patches:p.stop()
        return child,changed
    def test_face_change_reruns_only_face_and_links_the_rest(self):
        with tempfile.TemporaryDirectory() as d:
            parent,_=fake_run(d,'depth_mesh');before=tree_hashes(parent);steps=FakeSteps()
            child,changed=self.branch(d,parent,'face','off',None,steps)
            self.assertEqual(steps.names(),['prepare_seedance_video'])   # nothing before the face stage ran; the face tool `off` is a local copy
            self.assertEqual(changed,'face: mediapipe_mesh (strict: false, pad: 1.8, max_gap: 6) → off')
            run=json.loads((child/'run.json').read_text());self.assertEqual(run['parent'],parent.name);self.assertEqual(run['changed'],changed);self.assertEqual(run['mode'],'depth');self.assertEqual(run['state'],'done')
            self.assertEqual(len(child.name),32);self.assertNotEqual(child.name,parent.name);self.assertEqual(child.parent,parent.parent)
            for name in ['upload.mp4','original.mp4','depth.mp4','depth-raw.mp4','mask.mp4','depth-composite-silent.mp4','clean-masks','sam-report.json']:
                self.assertTrue((child/name).exists(),name)
                if (child/name).is_file():self.assertEqual((child/name).stat().st_ino,(parent/name).stat().st_ino,name)   # hard-linked, not copied
            self.assertEqual((child/'composite-silent.mp4').read_bytes(),b'cutout:composite-silent.mp4')   # face off: the depth cutout is the composite again
            self.assertNotEqual((child/'composite-silent.mp4').stat().st_ino,(parent/'composite-silent.mp4').stat().st_ino)
            self.assertFalse((child/'face-tracking.json').exists());self.assertTrue((child/'seedance-input.mp4').exists())
            for stage in ['input_doctor','audio','depth','mask','composite']:
                report=json.loads((child/'stages'/stage/'report.json').read_text());self.assertEqual(report['cached_from'],parent.name,stage);self.assertEqual(run['chain'][stage]['cached_from'],parent.name)
            face=json.loads((child/'stages/face/report.json').read_text());self.assertEqual((face['tool'],face['state'],face['cached_from']),('off','off',None))
            self.assertEqual(tree_hashes(parent),before)   # the parent is untouched
            self.assertEqual(json.loads((parent/'run.json').read_text())['changed'],None)
    def test_mask_change_reruns_mask_and_everything_after(self):
        with tempfile.TemporaryDirectory() as d:
            parent,_=fake_run(d,'depth_mesh');before=tree_hashes(parent);steps=FakeSteps()
            child,changed=self.branch(d,parent,'mask','sam3_replicate',{'prompt':'man in a suit'},steps)
            self.assertEqual(steps.names(),['segment_raw','clean_border_fragments','composite','mesh_worker','prepare_seedance_video'])
            self.assertEqual(steps.first('segment_raw')[2],'man in a suit');self.assertEqual(changed,'mask: sam3_replicate prompt: person, hands → man in a suit')
            self.assertEqual((child/'depth.mp4').stat().st_ino,(parent/'depth.mp4').stat().st_ino)
            self.assertNotEqual((child/'mask.mp4').stat().st_ino,(parent/'mask.mp4').stat().st_ino)
            self.assertEqual(json.loads((child/'manifest.json').read_text())['prompt'],'man in a suit')
            self.assertEqual(tree_hashes(parent),before)
            self.assertIn('man in a suit',json.loads((child/'sam-report.json').read_text())['prompt']);self.assertEqual(json.loads((parent/'sam-report.json').read_text())['prompt'],'person, hands')
    def test_branch_of_a_branch_and_tree(self):
        with tempfile.TemporaryDirectory() as d:
            parent,_=fake_run(d,'face_mesh');steps=FakeSteps()
            child,_=self.branch(d,parent,'face','mediapipe_mesh',{'pad':2.0},steps)
            grandchild,changed=self.branch(d,child,'face','mediapipe_mesh',{'strict':False},FakeSteps())
            self.assertEqual(changed,'face: mediapipe_mesh strict: true → false')
            self.assertEqual(json.loads((grandchild/'run.json').read_text())['chain']['face']['params'],{'strict':False,'pad':2.0,'max_gap':6})   # inherits the branch's pad
            forest=stages.tree(parent.parent);self.assertEqual([n['id'] for n in forest],[parent.name])
            self.assertEqual(forest[0]['children'][0]['id'],child.name);self.assertEqual(forest[0]['children'][0]['children'][0]['id'],grandchild.name)
            self.assertEqual(forest[0]['children'][0]['children'][0]['changed'],changed)
    def test_generation_stage_branch_keeps_everything_prepared(self):
        with tempfile.TemporaryDirectory() as d:
            parent,_=fake_run(d,'depth');before=tree_hashes(parent)
            child,chain,changed=stages.branch(parent,'generate','enhancor',None)
            run=stages.run_branch(child,chain,'generate',lambda s:None)
            self.assertEqual(changed,'generate: fal (char1: char1-reference.png) → enhancor (char1: char1-reference.png)');self.assertEqual(run['state'],'done')
            self.assertEqual((child/'seedance-input.mp4').stat().st_ino,(parent/'seedance-input.mp4').stat().st_ino)
            self.assertFalse((child/'seedance-response.json').exists());self.assertEqual(tree_hashes(parent),before)
    def test_fresh_breaks_shared_links_before_writing(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a.bin';a.write_bytes(b'parent');b=Path(d)/'b.bin';os.link(a,b)
            base.fresh(b);self.assertFalse(b.exists());self.assertEqual(a.read_bytes(),b'parent')
            c=Path(d)/'only.bin';c.write_bytes(b'x');base.fresh(c);self.assertTrue(c.exists())

# ---------------------------------------------------------------- offline switch and calls log

class NoNet:
    """Any HTTP or fal_client call fails the test."""
    def __enter__(self):
        boom=Mock(side_effect=AssertionError('network call attempted'))
        self.patches=[patch('requests.post',boom),patch('requests.get',boom),patch('requests.Session.request',boom),patch('pipeline.requests.post',boom),patch('pipeline.requests.get',boom),
                      patch('raw_masks.requests.post',boom),patch('raw_masks.requests.get',boom),patch('audio_workflow.requests.post',boom),patch('audio_workflow.requests.get',boom),
                      patch('media_host.requests.post',boom),patch('media_host.requests.get',boom),patch('providers.enhancor.requests.post',boom),
                      patch('providers.fal.fal_client.upload_file',boom),patch('providers.fal.fal_client.submit',boom),patch('providers.fal.fal_client.status',boom),patch('pipeline.Client',boom)]
        for p in self.patches:p.start()
        return self
    def __exit__(self,*a):
        for p in self.patches:p.stop()

class OfflineTests(unittest.TestCase):
    def test_every_paid_tool_raises_before_any_network_io(self):
        import pipeline,raw_masks,audio_workflow,media_host
        from providers import fal as falmod,enhancor as enh
        with tempfile.TemporaryDirectory() as d,NoNet(),patch.dict(os.environ,{'PUPPETEER_OFFLINE':'1','REPLICATE_API_TOKEN':'tok'}):
            p=Path(d)/HEX;p.mkdir();(p/'original.mp4').write_bytes(b'v');(p/'upload.mp4').write_bytes(b'u');(p/'seedance-input.mp4').write_bytes(b's');(p/'char1-reference.png').write_bytes(b'png')
            (p/'audio-manifest.json').write_text('{}');(p/'seedance-request.json').write_text(json.dumps({'is_draft':True,'webhook_url':''}));(p/'fal-result.json').write_text(json.dumps({'draft_id':'draft-1'}))
            cases={'depth_replicate':lambda:pipeline.depth_replicate(p/'original.mp4',p/'depth-raw.mp4'),
                   'depth_hf':lambda:pipeline.depth_hf(p/'original.mp4',p/'depth-raw.mp4'),
                   'segment_raw':lambda:raw_masks.segment_raw(p/'original.mp4',p,'person',frames=3,status=lambda s:None),
                   'separate':lambda:audio_workflow.separate(p/'upload.mp4',p,status=lambda s:None),
                   'fal.submit_draft':lambda:falmod.Fal().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None),
                   'fal.finalize':lambda:falmod.Fal().finalize('fal-req',folder=p),
                   'enhancor.submit_draft':lambda:enh.Enhancor().submit_draft(p/'seedance-input.mp4',{'char1':p/'char1-reference.png','char2':None},'Base',folder=p,status=lambda s:None),
                   'enhancor.finalize':lambda:enh.Enhancor().finalize('enh-1',folder=p),
                   'media_host.upload':lambda:media_host.upload(p/'seedance-input.mp4')}
            with patch('raw_masks.setting',side_effect=lambda k,dflt='':{'REPLICATE_API_TOKEN':'tok'}.get(k,dflt)),patch('providers.fal.setting',side_effect=lambda k,dflt='':{'FAL_KEY':'k','FAL_TASK':'editing'}.get(k,dflt)),patch('providers.fal.credential',return_value='k'),patch('providers.fal.load_env'),patch('providers.fal.check_video_constraints'),patch('providers.fal.check_image_constraints'),patch('providers.enhancor.credential',return_value='k'),patch('providers.enhancor.setting',side_effect=lambda k,dflt='':{'ENHANCOR_WEBHOOK_URL':'https://x/cb'}.get(k,dflt)),patch('media_host.setting',side_effect=lambda k,dflt='':dflt):
                for name,call in cases.items():
                    with self.assertRaises(OfflineError,msg=name) as caught:call()
                    self.assertIn('switched off in offline mode',str(caught.exception),name);self.assertTrue(caught.exception.fix)
            self.assertFalse((p/'calls.jsonl').exists());self.assertFalse((p/'sam-raw-request.json').exists());self.assertFalse((p/'hd').exists())
    def test_offline_blocks_polling_and_the_whole_paid_chain(self):
        import seedance_bridge
        with tempfile.TemporaryDirectory() as d,NoNet(),patch.dict(os.environ,{'PUPPETEER_OFFLINE':'1'}):
            p=Path(d)/HEX;p.mkdir();(p/'seedance-response.json').write_text(json.dumps({'requestId':'r','provider':'fal'}))
            with self.assertRaises(OfflineError):seedance_bridge.wait_and_finish(p,'r',status=lambda s:None)
            folder=Path(d)/'runs'/('b'*32);folder.mkdir(parents=True);(folder/'upload.mp4').write_bytes(b'u')
            with patch('pipeline.normalize',return_value={'frames':1}),patch.dict(os.environ,{'REPLICATE_API_TOKEN':'tok'}):
                with self.assertRaises(OfflineError):stages.run_mode('depth',folder/'upload.mp4',folder,lambda s:None)
            run=json.loads((folder/'run.json').read_text());self.assertEqual(run['state'],'error');self.assertIn('offline',run['error']['message']);self.assertIn('PUPPETEER_OFFLINE',run['error']['fix'])
            self.assertEqual(json.loads((folder/'stages/depth/report.json').read_text())['state'],'error');self.assertFalse((folder/'calls.jsonl').exists())
    def test_free_tools_run_offline(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'PUPPETEER_OFFLINE':'1'}):
            folder,steps=fake_run(d,'face_mesh');self.assertEqual(json.loads((folder/'run.json').read_text())['state'],'done');self.assertIn('mesh_worker',steps.names())

class CallsLogTests(unittest.TestCase):
    def test_record_call_appends_to_the_run_and_the_global_log(self):
        with tempfile.TemporaryDirectory() as d,patch.object(calls,'GLOBAL_LOG',Path(d)/'calls.log'):
            p=Path(d)/HEX;p.mkdir();(p/'upload.mp4').write_bytes(b'u')
            entry=calls.record_call(p,'replicate','lucataco/sam3-video',stage='mask',tool='sam3_replicate')
            calls.record_call(p/'upload.mp4','replicate','files')   # a file inside the run folder resolves to the run
            lines=[json.loads(l) for l in (p/'calls.jsonl').read_text().splitlines()]
            self.assertEqual(len(lines),2);self.assertEqual(set(lines[0]),{'time','provider','endpoint','stage','tool','cost_usd','ok'});self.assertTrue(lines[0]['ok']);self.assertGreater(lines[0]['cost_usd'],0)
            self.assertEqual(lines[1]['cost_usd'],0);self.assertEqual(json.loads((Path(d)/'calls.log').read_text().splitlines()[0])['run'],HEX)
            self.assertEqual(calls.total_cost(p),round(lines[0]['cost_usd']+lines[1]['cost_usd'],4))
            calls.record_call(None,'tmpfiles','upload');self.assertEqual(len((Path(d)/'calls.log').read_text().splitlines()),3)   # no run folder: global log only
    def test_runner_attributes_calls_to_the_stage_and_sums_the_total(self):
        with tempfile.TemporaryDirectory() as d:
            steps=FakeSteps();folder=Path(d)/'runs'/HEX;folder.mkdir(parents=True);(folder/'upload.mp4').write_bytes(b'u')
            def depth(src,dst,model='lucataco/depth-anything-video'):calls.record_call(Path(dst).parent,'replicate',model);steps.depth_replicate(src,dst,model)
            patches=steps.patches(fake_face_root(d));patches[1]=patch('pipeline.depth_replicate',side_effect=depth)
            for p in patches:p.start()
            try:stages.run_mode('depth',folder/'upload.mp4',folder,lambda s:None)
            finally:
                for p in patches:p.stop()
            logged=calls.read_calls(folder);self.assertEqual((logged[0]['stage'],logged[0]['tool']),('depth','depth_anything_replicate'))
            run=json.loads((folder/'run.json').read_text());self.assertEqual(run['cost_usd_total'],logged[0]['cost_usd']);self.assertGreater(run['cost_usd_total'],0)
            self.assertEqual(json.loads((folder/'stages/depth/report.json').read_text())['cost_usd'],logged[0]['cost_usd'])

# ---------------------------------------------------------------- cost gate and the new endpoints

def upload():return {'video':('clip.mp4',b'video','video/mp4')}

class CostGateTests(unittest.TestCase):
    def test_preset_without_confirmation_is_refused_with_the_estimate(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            client=TestClient(application.app)
            r=client.post('/jobs',data={'preset':'Full body','prompt':'person'},files=upload());self.assertEqual(r.status_code,402,r.text)
            body=r.json();self.assertGreater(body['estimated_cost_usd'],0);self.assertIn('costs about $',body['message']);self.assertIn('confirm_cost=true',body['fix']);self.assertEqual(body['detail'],body['message'])
            self.assertEqual(list(Path(d).iterdir()),[])   # nothing was created
            r=client.post('/jobs',data={'preset':'Full body','confirm_cost':'false'},files=upload());self.assertEqual(r.status_code,402)
    def test_confirmed_preset_runs_and_free_preset_needs_no_confirmation(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)),patch.object(stages,'run_chain') as run_chain:
            client=TestClient(application.app)
            r=client.post('/jobs',data={'preset':'Full body','prompt':'man','provider':'replicate-chenxwh','confirm_cost':'true'},files=upload());self.assertEqual(r.status_code,200,r.text)
            job=wait(r.json()['id']);self.assertEqual(job['state'],'done');self.assertEqual(job['preset'],'Full body');self.assertGreater(job['estimated_cost_usd'],0)
            chain=run_chain.call_args.args[1];self.assertEqual(chain['mask']['params']['prompt'],'man');self.assertEqual(chain['depth']['tool'],'depth_anything_replicate_chenxwh');self.assertEqual(run_chain.call_args.kwargs['preset'],'Full body')
            r=client.post('/jobs',data={'preset':'Talking head'},files=upload());self.assertEqual(r.status_code,200,r.text);self.assertEqual(wait(r.json()['id'])['estimated_cost_usd'],0)
            self.assertEqual(run_chain.call_args.args[1]['face']['tool'],'mediapipe_mesh')
            r=client.post('/jobs',data={'preset':'Nope'},files=upload());self.assertEqual(r.status_code,400);self.assertIn('fix',r.json())
    def test_explicit_chain_json(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)),patch.object(stages,'run_chain') as run_chain:
            client=TestClient(application.app);chain=json.dumps({'depth':{'tool':'off'},'mask':{'tool':'off'},'composite':{'tool':'original'},'face':{'tool':'mediapipe_mesh','params':{'strict':False}}})
            r=client.post('/jobs',data={'chain':chain},files=upload());self.assertEqual(r.status_code,200,r.text);wait(r.json()['id'])
            self.assertEqual(run_chain.call_args.args[1]['face']['params'],{'strict':False,'pad':1.8,'max_gap':6})
            self.assertEqual(client.post('/jobs',data={'chain':'not json'},files=upload()).status_code,400)
    def test_legacy_mode_needs_confirmation_too(self):
        """No paid call without confirmation: a legacy `mode` request without confirm_cost is refused with the estimate; with it, it runs."""
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)),patch.object(application,'run') as run:
            client=TestClient(application.app)
            r=client.post('/jobs',data={'mode':'depth'},files=upload());self.assertEqual(r.status_code,402,r.text);self.assertIn('estimated_cost_usd',r.json());self.assertEqual(list(Path(d).iterdir()),[]);run.assert_not_called()
            self.assertEqual(client.post('/jobs',data={'mode':'depth','confirm_cost':'false'},files=upload()).status_code,402)
            r=client.post('/jobs',data={'mode':'depth','confirm_cost':'true'},files=upload());self.assertEqual(r.status_code,200,r.text);wait(r.json()['id']);run.assert_called_once()
    def test_draft_and_hd_gates(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            p=Path(d)/HEX;p.mkdir();(p/'audio-manifest.json').write_text('{}');(p/'upload.mp4').write_bytes(b'u');(p/'final-preview.mp4').write_bytes(b'f');(p/'generation.json').write_text(json.dumps({'request_id':'r','provider':'fal'}))
            client=TestClient(application.app);files={'char1':('ref.png',b'png','image/png')}
            with patch('mask_review.require_approved'):
                r=client.post(f'/jobs/{HEX}/seedance',data={'prompt':'x','provider':'fal','confirm_cost':'false'},files=files);self.assertEqual(r.status_code,402);self.assertIn('estimated_cost_usd',r.json())
                with patch('seedance_bridge.submit',return_value='req'),patch('seedance_bridge.wait_and_finish'):
                    self.assertEqual(client.post(f'/jobs/{HEX}/seedance',data={'prompt':'x','provider':'fal','confirm_cost':'true'},files=files).status_code,200)
            application.hd_jobs.pop(HEX,None)
            r=client.post(f'/jobs/{HEX}/hd',data={'confirm_cost':'false'});self.assertEqual(r.status_code,402);self.assertNotIn(HEX,application.hd_jobs)
            self.assertEqual(client.post(f'/jobs/{HEX}/hd',json={'confirm_cost':'no'}).status_code,402)

class EndpointTests(unittest.TestCase):
    def test_tree_run_calls_estimate_and_branch(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)/'runs'):
            parent,_=fake_run(d,'depth_mesh');client=TestClient(application.app);application.jobs.pop(HEX,None)
            listed=client.get('/jobs').json()['runs'][0];self.assertEqual((listed['parent'],listed['changed'],listed['preset'],listed['cost_usd_total']),(None,None,None,0))
            info=client.get(f'/jobs/{HEX}/run').json();self.assertFalse(info['migrated']);self.assertEqual(set(info['reports']),set(stages.PREP_STAGES));self.assertEqual(info['run']['mode'],'depth_mesh');self.assertEqual(info['calls'],[])
            self.assertEqual(client.get(f'/jobs/{HEX}/calls').json()['cost_usd_total'],0)
            est=client.post(f'/jobs/{HEX}/estimate',json={'stage':'face','tool':'off'}).json();self.assertEqual((est['estimated_cost_usd'],est['stages_to_run'],est['free']),(0,['face'],True));self.assertTrue(est['changed'].startswith('face: mediapipe_mesh'))
            est=client.post(f'/jobs/{HEX}/estimate',data={'stage':'mask','params':json.dumps({'prompt':'person, hands, hat'})}).json();self.assertGreater(est['estimated_cost_usd'],0);self.assertEqual(est['stages_to_run'],['mask','composite','face']);self.assertEqual(est['paid'][0]['stage'],'mask')
            self.assertEqual(client.post(f'/jobs/{HEX}/estimate',json={'stage':'render'}).status_code,400);self.assertEqual(client.post(f'/jobs/{HEX}/branch',json={'stage':'face','tool':'laser'}).status_code,400)
            r=client.post(f'/jobs/{HEX}/branch',json={'stage':'mask','params':{'prompt':'hat'}});self.assertEqual(r.status_code,402);self.assertIn('mask stage',r.json()['message'])
            steps=FakeSteps();patches=steps.patches(fake_face_root(d))
            for p in patches:p.start()
            try:
                r=client.post(f'/jobs/{HEX}/branch',data={'stage':'face','tool':'off'});self.assertEqual(r.status_code,200,r.text);cid=r.json()['id'];job=wait(cid)
            finally:
                for p in patches:p.stop()
            self.assertEqual(job['state'],'done',job);self.assertEqual(job['parent'],HEX);self.assertTrue(job['changed'].startswith('face: mediapipe_mesh'));self.assertEqual(job['estimated_cost_usd'],0)
            self.assertEqual(json.loads((Path(d)/'runs'/cid/'status.json').read_text())['state'],'done')
            tree=client.get('/jobs/tree').json()['runs'];self.assertEqual(len(tree),1);self.assertEqual(tree[0]['id'],HEX);self.assertEqual(tree[0]['children'][0]['id'],cid);self.assertEqual(tree[0]['children'][0]['changed'],job['changed'])
            runs=client.get('/jobs').json()['runs'];child=next(r for r in runs if r['id']==cid);self.assertEqual(child['parent'],HEX);self.assertEqual(child['mode'],'depth')
            self.assertEqual(client.get('/jobs/'+'f'*32+'/run').status_code,404)
    def test_costs_presets_and_stages_endpoints(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)/'runs'),patch.object(presets,'PRESETS_FILE',Path(d)/'presets.json'):
            client=TestClient(application.app);table=client.get('/costs').json()
            self.assertIn('lucataco/sam3-video',json.dumps(table));self.assertTrue(all('source' in t and 'date' in t and 'verified' in t for t in table['tools'].values()));self.assertFalse(table['tools']['sam3_replicate']['verified'])
            self.assertEqual(table['tools']['sam3_replicate']['gpu'],'Nvidia L40S');self.assertTrue(table['tools']['fal']['verified']);self.assertEqual(table['tools']['clean_dialogue']['endpoint'],'cjwbw/demucs')
            listed=client.get('/presets').json()['presets'];self.assertEqual([p['name'] for p in listed],['Talking head','Full body','Expressive','Profile-heavy'])
            by={p['name']:p for p in listed};self.assertEqual(by['Talking head']['mode'],'face_mesh');self.assertEqual(by['Expressive']['chain']['face']['params']['strict'],False);self.assertEqual(by['Profile-heavy']['chain']['face']['tool'],'off');self.assertTrue(all(p['builtin'] for p in listed))
            parent,_=fake_run(d,'depth_mesh',prompt='man, hands')
            r=client.post('/presets',data={'name':'Hands study','description':'depth mesh with hands','job':HEX});self.assertEqual(r.status_code,200,r.text);saved=r.json()['preset']
            self.assertEqual(saved['chain']['mask']['params']['prompt'],'man, hands');self.assertEqual(saved['source_run'],HEX);self.assertFalse(saved['builtin'])
            names=[p['name'] for p in client.get('/presets').json()['presets']];self.assertEqual(names[-1],'Hands study');self.assertTrue((Path(d)/'presets.json').exists())
            self.assertEqual(client.post('/presets',json={'name':'Full body','job':HEX}).status_code,400);self.assertEqual(client.post('/presets',json={'name':'x','job':'0'*32}).status_code,404);self.assertEqual(client.post('/presets',json={'job':HEX}).status_code,400)
            with patch.object(stages,'run_chain') as run_chain:
                r=client.post('/jobs',data={'preset':'hands study','confirm_cost':'true'},files=upload());self.assertEqual(r.status_code,200,r.text);wait(r.json()['id'])
                self.assertEqual(run_chain.call_args.args[1]['mask']['params']['prompt'],'person')   # the form's subject applies to a saved preset too
            self.assertEqual(stages.get_tool('face','mediapipe_mesh').describe()['params']['pad']['default'],1.8)

# ---------------------------------------------------------------- legacy migration

def legacy_folder(d,ident=HEX):
    """A depth_mesh run made before the rack existed (no run.json, no stages/)."""
    p=Path(d)/'runs'/ident;p.mkdir(parents=True)
    for name in ['upload.mp4','original.mp4','depth-raw.mp4','depth.mp4','mask.mp4','composite.mp4','depth-composite-silent.mp4','composite-silent.mp4','seedance-input.mp4','preview.jpg','sam-attempts.json','sam-raw-request.json','mask-cleanup-report.json']:(p/name).write_bytes(b'legacy:'+name.encode())
    (p/'clean-masks').mkdir();(p/'clean-masks/mask_00000.png').write_bytes(b'm');(p/'raw-masks').mkdir();(p/'raw-masks/mask_00000.png').write_bytes(b'm')
    (p/'workflow-mode.json').write_text(json.dumps({'mode':'depth_mesh'}))
    (p/'manifest.json').write_text(json.dumps({'frames':195,'fps':24,'prompt':'person, hands','depth_provider':'replicate','clean_dialogue':False,'mask_method':'SAM 3 (lucataco/sam3-video) on depth frames'}))
    (p/'sam-report.json').write_text(json.dumps({'prompt':'person, hands','terms':['person','hands'],'frames':195,'attempts':[{'model':'lucataco/sam3-video','source':'depth','term':'person','frames_with_mask':195},{'model':'lucataco/sam3-video','source':'depth','term':'hands','frames_with_mask':40}],'method':'SAM 3 (lucataco/sam3-video) on depth frames','source':'depth','model':'lucataco/sam3-video'}))
    (p/'face-tracking.json').write_text(json.dumps({'frames':195,'tracked':163,'filled':13,'missing':19,'gaps':[{'start_frame':10,'end_frame':16,'frames':7,'start_s':0.42,'end_s':0.71},{'start_frame':50,'end_frame':61,'frames':12,'start_s':2.08,'end_s':2.58}],'strict':False,'ok':True,'warning':'lost face 0.42–0.71 s, 2.08–2.58 s · depth composite only on those frames (no mesh)','message':'face tracked throughout','max_gap_frames':6}))
    (p/'face-landmarks.json').write_text('{}');(p/'audio-manifest.json').write_text(json.dumps({'clean_dialogue':False,'audio_remux':'copy'}))
    (p/'status.json').write_text(json.dumps({'id':ident,'state':'done','status':'Depth + face mesh ready'}))
    return p

class MigrationTests(unittest.TestCase):
    def test_reconstruct_in_memory_never_writes(self):
        with tempfile.TemporaryDirectory() as d:
            p=legacy_folder(d);before=tree_hashes(p)
            run,reports=stages.reconstruct(p)
            self.assertTrue(run['migrated']);self.assertEqual(run['mode'],'depth_mesh');self.assertEqual(run['state'],'done');self.assertIsNone(run['parent'])
            chain=run['chain'];self.assertEqual((chain['depth']['tool'],chain['mask']['tool'],chain['composite']['tool'],chain['face']['tool'],chain['audio']['tool']),('depth_anything_replicate','sam3_replicate','depth_cutout','mediapipe_mesh','original'))
            self.assertEqual(chain['mask']['params'],{'prompt':'person, hands'});self.assertEqual(chain['face']['params'],{'strict':False,'pad':1.8,'max_gap':6})
            self.assertEqual(reports['mask']['frames'],{'covered':195,'filled':0,'missing':0});self.assertIn('terms matched: person, hands',reports['mask']['health'])
            self.assertEqual(reports['face']['frames'],{'covered':163,'filled':13,'missing':19});self.assertEqual(len(reports['face']['gaps']),2);self.assertIn('lost 0.42–0.71 s, 2.08–2.58 s',reports['face']['health']);self.assertEqual(reports['face']['state'],'done')
            self.assertEqual(set(reports['composite']['outputs']),{'mask.mp4','composite.mp4','depth-composite-silent.mp4'});self.assertEqual(set(reports['face']['outputs']),{'composite-silent.mp4','face-landmarks.json','face-tracking.json','preview.jpg','seedance-input.mp4'})
            self.assertEqual(reports['generate']['state'],'missing');self.assertEqual(reports['audio']['health'],'Original audio kept, copied packet for packet.')
            self.assertEqual(tree_hashes(p),before);self.assertFalse((p/'run.json').exists())
            run2,_=stages.reconstruct(p,with_keys=True,write=True);self.assertTrue((p/'run.json').exists());self.assertRegex(run2['chain']['face']['key'],r'^[0-9a-f]{64}$')
    def test_legacy_depth_run_and_failed_run(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'runs'/('b'*32);p.mkdir(parents=True)
            for name in ['upload.mp4','original.mp4','depth.mp4','mask.mp4','composite-silent.mp4','seedance-input.mp4']:(p/name).write_bytes(b'x')
            (p/'manifest.json').write_text(json.dumps({'prompt':'person','depth_provider':'huggingface','clean_dialogue':True}));(p/'vocals.wav').write_bytes(b'v')
            run,reports=stages.reconstruct(p);self.assertEqual(run['mode'],'depth');self.assertEqual(run['chain']['depth']['tool'],'depth_anything_hf');self.assertEqual(run['chain']['audio']['tool'],'clean_dialogue');self.assertEqual(run['chain']['face']['tool'],'off')
            self.assertIn('composite-silent.mp4',reports['face']['outputs']);self.assertEqual(reports['face']['state'],'off')
            q=Path(d)/'runs'/('c'*32);q.mkdir();(q/'upload.mp4').write_bytes(b'u');(q/'original.mp4').write_bytes(b'o');(q/'face-landmarks.json').write_text('{}');(q/'face-tracking.json').write_text(json.dumps({'frames':10,'tracked':2,'filled':0,'missing':8,'strict':True,'ok':False,'message':'lost face 0.0–0.33 s'}))
            (q/'workflow-mode.json').write_text('{"mode":"face_mesh"}');(q/'status.json').write_text(json.dumps({'state':'error','status':'Face mesh worker failed: lost face 0.0–0.33 s'}))
            run,reports=stages.reconstruct(q);self.assertEqual(run['state'],'error');self.assertEqual(reports['face']['state'],'error');self.assertIn('lost face',reports['face']['error']['message']);self.assertEqual(reports['face']['frames']['missing'],8)
    def test_run_endpoint_and_branch_from_a_legacy_run(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)/'runs'):
            p=legacy_folder(d);before=tree_hashes(p);client=TestClient(application.app)
            info=client.get(f'/jobs/{HEX}/run').json();self.assertTrue(info['migrated']);self.assertEqual(info['run']['chain']['face']['tool'],'mediapipe_mesh');self.assertIn('lost 0.42',info['reports']['face']['health']);self.assertEqual(tree_hashes(p),before)
            steps=FakeSteps();patches=steps.patches(fake_face_root(d))
            for x in patches:x.start()
            try:
                child,chain,changed=stages.branch(p,'face','mediapipe_mesh',{'strict':True});stages.run_branch(child,chain,'face',lambda s:None)
            finally:
                for x in patches:x.stop()
            self.assertEqual(changed,'face: mediapipe_mesh strict: false → true');self.assertEqual(steps.names(),['mesh_worker','prepare_seedance_video']);self.assertEqual(steps.first('mesh_worker'),('mesh_worker','--depth','--strict'))
            self.assertEqual((child/'depth.mp4').stat().st_ino,(p/'depth.mp4').stat().st_ino);self.assertEqual((child/'depth-composite-silent.mp4').stat().st_ino,(p/'depth-composite-silent.mp4').stat().st_ino)
            self.assertEqual((child/'composite-silent.mp4').read_bytes(),b'mesh-overlay-depth');self.assertEqual(tree_hashes(p),before);self.assertFalse((p/'run.json').exists())
            self.assertEqual(json.loads((child/'stages/mask/report.json').read_text())['cached_from'],HEX);self.assertEqual(json.loads((child/'run.json').read_text())['parent'],HEX)
            tree=client.get('/jobs/tree').json()['runs'];self.assertEqual(tree[0]['id'],HEX);self.assertEqual(tree[0]['children'][0]['id'],child.name)

if __name__=='__main__':unittest.main()
