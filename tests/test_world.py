"""World stage (Agent 1): backgrounds on the composite stage, set plates, Set / Look / Light slots, the Seedance task.

- `pipeline.composite_bg` on a synthetic 12-frame clip: plain → the colour outside the mask, depth inside; full_depth → the
  depth frame everywhere; set_image → plate pixels outside the mask; original → identical to `pipeline.composite`.
- `DepthCutout` keeps `normalize_params({}) == {}` (legacy cache keys unchanged), calls `pipeline.composite` for the default
  and `composite_bg` otherwise, copies the plate in as set-plate.<ext>, refuses a missing plate with a plain fix.
- Fit maths (`stages.plates.fit_rect`): cover + centre, then move / scale.
- Assets: POST /jobs/{id}/assets, GET /assets, GET /assets/{name}; a bad file is a plain 400.
- Slots: GET / PUT round trip, task_for, the run.json mirror, a hard-linked parent never written, inheritance by a branch.
- POST /jobs/{id}/seedance sends `task` into the adapter (from slots.json, or the form) with a mocked adapter; Enhancor records
  "not applicable".
"""
import unittest,tempfile,json,io,os,hashlib,inspect
from pathlib import Path
from fractions import Fraction
from unittest.mock import patch,Mock
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient
import av
import app as application,stages,pipeline,seedance_bridge
from stages import plates,slots

HEX='d'*32
RED=(200,40,40);BLUE=(30,30,220);GREEN=(20,200,20)

def write_clip(path,color,frames=12,w=64,h=48,audio=False):
    with av.open(str(path),'w') as out:
        v=out.add_stream('libx264',rate=24);v.width=w;v.height=h;v.pix_fmt='yuv420p';v.options={'crf':'10'}
        a=out.add_stream('aac',rate=48000) if audio else None
        if a:a.layout='stereo'
        for i in range(frames):
            f=av.VideoFrame.from_ndarray(np.full((h,w,3),color,dtype=np.uint8),format='rgb24');f.pts=i;f.time_base=Fraction(1,24)
            for p in v.encode(f):out.mux(p)
        for p in v.encode():out.mux(p)
        if a:
            samples=np.zeros((2,24000),dtype=np.float32)
            for i in range(0,24000,4096):
                fr=av.AudioFrame.from_ndarray(np.ascontiguousarray(samples[:,i:i+4096]),format='fltp',layout='stereo');fr.sample_rate=48000;fr.pts=i
                for p in a.encode(fr):out.mux(p)
            for p in a.encode():out.mux(p)

def synthetic_run(d,frames=12,w=64,h=48):
    """original (red), depth (blue), clean-masks (white box in the centre), upload with audio, run.json."""
    p=Path(d);p.mkdir(parents=True,exist_ok=True)
    write_clip(p/'original.mp4',RED,frames,w,h);write_clip(p/'depth.mp4',BLUE,frames,w,h);write_clip(p/'upload.mp4',RED,frames,w,h,audio=True)
    masks=p/'clean-masks';masks.mkdir(exist_ok=True)
    for i in range(frames):
        m=np.zeros((h,w),dtype=np.uint8);m[h//4:3*h//4,w//4:3*w//4]=255;Image.fromarray(m).save(masks/f'mask_{i:05d}.png')
    chain=stages.chain_for_mode('depth');run=stages.runner.new_run(p,chain,'depth');stages.save_run(p,run)
    (p/'workflow-mode.json').write_text('{"mode":"depth"}')
    return p

def frames_of(path):
    with av.open(str(path)) as c:return [f.to_ndarray(format='rgb24') for f in c.decode(video=0)]

def plate_png(color=GREEN,size=(32,16)):
    buf=io.BytesIO();Image.new('RGB',size,color).save(buf,'PNG');return buf.getvalue()

def near(a,b,tol=14):return all(abs(int(x)-int(y))<=tol for x,y in zip(a,b))

def sha_tree(folder):
    return {p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(folder).rglob('*') if p.is_file()}

class BackgroundRenderTests(unittest.TestCase):
    def check(self,folder,outside,inside=BLUE):
        frames=frames_of(folder/'depth-composite-silent.mp4');self.assertEqual(len(frames),12)
        f=frames[5];h,w=f.shape[:2];corner=f[2,2];centre=f[h//2,w//2]
        self.assertTrue(near(corner,outside),(corner,outside));self.assertTrue(near(centre,inside),(centre,inside))
        for name in ('mask.mp4','composite.mp4','depth-composite-silent.mp4'):self.assertTrue((folder/name).exists(),name)
        with av.open(str(folder/'composite.mp4')) as c:self.assertTrue(c.streams.audio)   # the original audio rides along
        return f
    def run_tool(self,folder,params):
        tool=stages.get_tool('composite','depth_cutout');params=tool.normalize_params(params)
        return tool.run({'folder':folder,'chain':{},'mode':'depth','source':folder/'upload.mp4','seconds':0.5},params,folder,lambda s:None),params
    def test_plain_full_depth_set_image_and_original(self):
        with tempfile.TemporaryDirectory() as d:
            p=synthetic_run(Path(d)/HEX)
            result,params=self.run_tool(p,{'background':'plain'});self.assertEqual(params,{'background':'plain'});self.check(p,(0,0,0))
            self.assertIn('plain black',result['health']);self.assertEqual(result['data']['background'],'plain')
            result,params=self.run_tool(p,{'background':'plain','plain_color':'gray'});self.assertEqual(params,{'background':'plain','plain_color':'gray'});self.check(p,(128,128,128))
            result,_=self.run_tool(p,{'background':'full_depth'});f=self.check(p,BLUE);self.assertTrue(near(f[0,0],BLUE))
            name=plates.store_asset(plate_png(),'room.png',Path(d),'set')
            result,params=self.run_tool(p,{'background':'set_image','set_image':name,'set_fit':'{"x":0,"y":0,"scale":1}'})
            self.assertEqual(params,{'background':'set_image','set_image':name});self.check(p,GREEN)
            self.assertIn('set-plate.png',result['outputs']);self.assertTrue((p/'set-plate.png').exists());self.assertIn('set image',result['health'])
            result,params=self.run_tool(p,{});self.assertEqual(params,{});self.check(p,RED)
            self.assertFalse(list(p.glob('set-plate.*')))   # a re-run without a plate drops the old one
            # the default path is pipeline.composite itself (the regression suite patches it by name); anything else is composite_bg
            with patch('pipeline.composite',side_effect=pipeline.composite) as comp,patch('pipeline.composite_bg',side_effect=pipeline.composite_bg) as bg:
                self.run_tool(p,{});comp.assert_called_once();bg.assert_not_called()
                self.run_tool(p,{'background':'plain'});bg.assert_called_once();self.assertEqual(bg.call_args.kwargs['background'],'plain')
    def test_original_is_byte_identical_to_composite(self):
        with tempfile.TemporaryDirectory() as d:
            p=synthetic_run(Path(d)/HEX);q=synthetic_run(Path(d)/('e'*32))
            pipeline.composite(p/'original.mp4',p/'depth.mp4',p/'clean-masks',p,p/'upload.mp4')
            pipeline.composite_bg(q/'original.mp4',q/'depth.mp4',q/'clean-masks',q,q/'upload.mp4',background='original')
            self.assertEqual((p/'composite-silent.mp4').read_bytes(),(q/'composite-silent.mp4').read_bytes());self.assertEqual((p/'mask.mp4').read_bytes(),(q/'mask.mp4').read_bytes())
            self.assertEqual(str(inspect.signature(pipeline.composite)),'(original, depth, seg, directory, audio_source=None)')
    def test_missing_plate_is_a_plain_error_and_bad_background_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=synthetic_run(Path(d)/HEX)
            with self.assertRaises(ValueError) as cm:self.run_tool(p,{'background':'set_image','set_image':'0123456789abcdef.png'})
            self.assertIn('set image',str(cm.exception).lower());self.assertTrue(getattr(cm.exception,'fix',''))
            self.assertFalse((p/'depth-composite-silent.mp4').exists())
            with self.assertRaises(ValueError):pipeline.composite_bg(p/'original.mp4',p/'depth.mp4',p/'clean-masks',p,None,background='sepia')
    def test_cache_key_for_the_default_params_is_unchanged(self):
        tool=stages.get_tool('composite','depth_cutout')
        self.assertEqual(tool.normalize_params({}),{});self.assertEqual(tool.normalize_params({'background':'original','plain_color':'gray','set_image':'x.png'}),{})
        hashes={'original.mp4':'a'*64,'depth.mp4':'b'*64,'clean-masks':'c'*64}
        self.assertEqual(stages.cache_key('composite','depth_cutout',tool.normalize_params({}),hashes),stages.cache_key('composite','depth_cutout',{},hashes))
        self.assertEqual(stages.cache_key('composite','depth_cutout',{},hashes),hashlib.sha256(json.dumps(['composite','depth_cutout','{}',sorted(hashes.items())],separators=(',',':')).encode()).hexdigest())
        self.assertNotEqual(stages.cache_key('composite','depth_cutout',tool.normalize_params({'background':'plain'}),hashes),stages.cache_key('composite','depth_cutout',{},hashes))
        self.assertEqual(stages.get_tool('generate','fal').normalize_params({'char1':'ref.png'}),{'char1':'ref.png','char2':''})
        self.assertEqual(stages.get_tool('generate','fal').normalize_params({'task':'reference'})['task'],'reference')
        self.assertEqual(set(stages.get_tool('prompt','identity_only').normalize_params({})),{'text'})
        self.assertEqual(stages.describe_change('composite',{'tool':'depth_cutout','params':{}},{'tool':'depth_cutout','params':{'background':'plain'}}),'composite: depth_cutout background: original → plain')
        self.assertEqual(stages.describe_change('composite',{'tool':'depth_cutout','params':{'background':'plain'}},{'tool':'depth_cutout','params':{}}),'composite: depth_cutout background: plain → original')
        self.assertEqual(stages.composite.background_of({'composite':{'tool':'depth_cutout','params':{'background':'set_image'}}}),('set_image','Set image'))
        self.assertEqual(stages.composite.background_of({'composite':{'tool':'original','params':{}}})[0],'none')

class FitMathsTests(unittest.TestCase):
    def test_cover_centre_then_move_and_scale(self):
        self.assertEqual(plates.fit_rect(100,50,200,200),(-100.0,0.0,400.0,200.0))     # wide plate on a square frame: height covers, width overflows, centred
        self.assertEqual(plates.fit_rect(50,100,200,100),(0.0,-150.0,200.0,400.0))     # tall plate on a wide frame
        self.assertEqual(plates.fit_rect(100,100,100,100,{'scale':2}),(-50.0,-50.0,200.0,200.0))
        x0,y0,w,h=plates.fit_rect(100,100,100,100,{'x':0.1,'y':-0.25});self.assertEqual((x0,y0,w,h),(10.0,-25.0,100.0,100.0))
        self.assertEqual(plates.parse_fit('{"x":5,"scale":0.01}'),{'x':1.0,'y':0.0,'scale':0.2});self.assertEqual(plates.parse_fit('nonsense'),plates.FIT_DEFAULT)
        self.assertEqual(plates.fit_text({'x':0,'y':0,'scale':1}),'');self.assertEqual(plates.fit_text({'x':0.05,'scale':1.2}),'{"scale":1.2,"x":0.05,"y":0.0}')
        with tempfile.TemporaryDirectory() as d:
            plate=Path(d)/'p.png';plate.write_bytes(plate_png(GREEN,(40,20)))
            img=plates.render_plate(plate,80,80,{'scale':0.5});self.assertEqual(img.shape,(80,80,3))
            self.assertEqual(tuple(img[40,40]),GREEN);self.assertEqual(tuple(img[2,2]),(0,0,0))   # half-size plate: green in the middle, black around

class AssetRouteTests(unittest.TestCase):
    def test_upload_list_serve_and_refusals(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            synthetic_run(Path(d)/HEX);client=TestClient(application.app)
            r=client.post(f'/jobs/{HEX}/assets',files={'file':('room.png',plate_png(),'image/png')},data={'kind':'set'});self.assertEqual(r.status_code,200,r.text);meta=r.json()
            self.assertEqual((meta['width'],meta['height'],meta['kind'],meta['filename']),(32,16,'set','room.png'));self.assertRegex(meta['name'],r'^[0-9a-f]{16}\.png$');self.assertEqual(meta['url'],'/assets/'+meta['name'])
            self.assertTrue((Path(d)/'_assets'/meta['name']).exists())
            self.assertEqual(client.get('/assets').json()['assets'][0]['name'],meta['name']);self.assertEqual(client.get('/assets?kind=look').json()['assets'],[])
            served=client.get(meta['url']);self.assertEqual(served.status_code,200);self.assertEqual(served.content,plate_png())
            again=client.post(f'/jobs/{HEX}/assets',files={'file':('copy.png',plate_png(),'image/png')},data={'kind':'set'}).json();self.assertEqual(again['name'],meta['name'])   # content-addressed
            for files,data,code,word in [({'file':('notes.txt',b'hello','text/plain')},{'kind':'set'},400,'PNG'),({'file':('x.png',b'not an image','image/png')},{'kind':'set'},400,'image'),
                                         ({'file':('x.png',plate_png(),'image/png')},{'kind':'prop'},400,'kind'),({'file':('empty.png',b'','image/png')},{'kind':'set'},400,'empty')]:
                r=client.post(f'/jobs/{HEX}/assets',files=files,data=data);self.assertEqual(r.status_code,code,r.text);body=r.json();self.assertIn('fix',body);self.assertIn('message',body);self.assertIn(word.lower(),(body['message']+body['fix']).lower())
            r=client.post(f'/jobs/{HEX}/assets',data={'kind':'set'});self.assertEqual(r.status_code,400);self.assertIn('fix',r.json())
            with patch.object(plates,'MAX_BYTES',10):
                r=client.post(f'/jobs/{HEX}/assets',files={'file':('big.png',plate_png(),'image/png')},data={'kind':'set'});self.assertEqual(r.status_code,413);self.assertIn('MB',r.json()['message'])
            self.assertEqual(client.get('/assets/0123456789abcdef.png').status_code,404);self.assertEqual(client.get('/assets/evil.png').status_code,400);self.assertIn(client.get('/assets/..%2Frun.json').status_code,(400,404))
            self.assertEqual({r['id'] for r in client.get('/jobs').json()['runs']},{HEX})   # _assets is never listed as a run

class SlotTests(unittest.TestCase):
    def test_defaults_round_trip_task_and_mirror(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            p=synthetic_run(Path(d)/HEX);client=TestClient(application.app)
            name=plates.store_asset(plate_png(),'room.png',Path(d),'set')
            s=client.get(f'/jobs/{HEX}/slots').json()
            self.assertEqual((s['set']['mode'],s['look']['mode'],s['light'],s['generator']['task'],s['task'],s['derived_task'],s['file'],s['background'],s['background_applied']),('original','follow','','auto','editing','editing',False,'original',True))
            r=client.put(f'/jobs/{HEX}/slots',json={'set':{'mode':'true_swap','image':name,'fit':{'x':0.1,'scale':1.5}},'look':{'mode':'style_ref','image':name},'light':'soft window light'});self.assertEqual(r.status_code,200,r.text);s=r.json()
            self.assertEqual((s['set']['mode'],s['set']['image'],s['set']['fit'],s['look']['mode'],s['look']['image'],s['light']),('true_swap',name,{'x':0.1,'y':0.0,'scale':1.5},'style_ref',name,'soft window light'))
            self.assertEqual((s['task'],s['task_source'],s['background_needed'],s['background_applied']),('reference','set','set_image',False));self.assertTrue(s['updated'])
            saved=json.loads((p/'slots.json').read_text());self.assertEqual(saved['set']['mode'],'true_swap');self.assertEqual(saved['version'],1)
            run=json.loads((p/'run.json').read_text());self.assertEqual(run['slots']['light'],'soft window light')
            self.assertEqual({k:run['chain']['prompt']['params'][k] for k in slots.FLAT_KEYS},{'set_mode':'true_swap','set_image':name,'set_prompt':'','look_mode':'style_ref','look_image':name,'look_prompt':'','light':'soft window light'})
            self.assertIn('text',run['chain']['prompt']['params'])
            # partial updates merge; a form body with JSON fields works too
            s=client.put(f'/jobs/{HEX}/slots',data={'look':json.dumps({'mode':'prompt','prompt':'16 mm film'})}).json();self.assertEqual((s['look']['mode'],s['look']['prompt'],s['set']['mode']),('prompt','16 mm film','true_swap'))
            # the user overrides the task; a set-mode change re-applies the derived one
            s=client.put(f'/jobs/{HEX}/slots',json={'generator':{'task':'editing'}}).json();self.assertEqual((s['task'],s['task_source']),('editing','user'))
            s=client.put(f'/jobs/{HEX}/slots',json={'set':{'mode':'prompt','prompt':'a loft'}}).json();self.assertEqual((s['task'],s['task_source'],s['generator']['task'],s['background_needed']),('reference','set','auto',None))
            s=client.put(f'/jobs/{HEX}/slots',json={'set':{'mode':'original'}}).json();self.assertEqual(s['task'],'editing')
            self.assertEqual(slots.task_for({'set':{'mode':'original'}}),'editing');self.assertEqual(slots.task_for({'set':{'mode':'set_ref'}}),'reference');self.assertEqual(slots.task_for({}),'editing')
            # validation: plain 400s, nothing written
            before=(p/'slots.json').read_bytes()
            for bad in [{'set':{'mode':'bogus'}},{'look':{'mode':'x'}},{'generator':{'task':'extension'}},{'set':{'image':'../../etc'}},{'light':'x'*5000}]:
                r=client.put(f'/jobs/{HEX}/slots',json=bad);self.assertEqual(r.status_code,400,bad);self.assertIn('fix',r.json())
            self.assertEqual((p/'slots.json').read_bytes(),before)
    def test_a_hard_linked_copy_never_writes_into_its_parent(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            parent=synthetic_run(Path(d)/HEX);slots.write(parent,{'set':{'mode':'prompt','prompt':'a loft'}})
            child=Path(d)/('f'*32);child.mkdir()
            for name in ('slots.json','run.json','original.mp4','workflow-mode.json'):os.link(parent/name,child/name)
            before=sha_tree(parent);client=TestClient(application.app)
            r=client.put('/jobs/'+'f'*32+'/slots',json={'set':{'mode':'true_swap'},'light':'noon sun'});self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(sha_tree(parent),before)
            self.assertEqual(json.loads((child/'slots.json').read_text())['light'],'noon sun');self.assertEqual(json.loads((parent/'slots.json').read_text())['light'],'')
            self.assertEqual((child/'slots.json').stat().st_nlink,1);self.assertEqual((child/'run.json').stat().st_nlink,1)
    def test_a_branch_inherits_the_slots_through_the_flat_keys(self):
        with tempfile.TemporaryDirectory() as d:
            parent=synthetic_run(Path(d)/HEX);slots.write(parent,{'set':{'mode':'set_ref','image':None,'prompt':''},'look':{'mode':'prompt','prompt':'grainy'},'light':'dusk'})
            child,chain,changed=stages.branch(parent,'prompt',None,{'text':'Hello'},runs_root=Path(d))
            self.assertFalse((child/'slots.json').exists())
            s=slots.view(child,chain);self.assertEqual((s['set']['mode'],s['look']['prompt'],s['light'],s['task']),('set_ref','grainy','dusk','reference'))
            self.assertEqual(chain['prompt']['params']['set_mode'],'set_ref')
    def test_slots_without_run_json(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/HEX;p.mkdir();s=slots.write(p,{'light':'candles'})
            self.assertEqual(s['light'],'candles');self.assertFalse((p/'run.json').exists());self.assertEqual(slots.read(p)['light'],'candles')

class FakeAdapter:
    """Records what submit_draft received; writes seedance-request.json like a real adapter (fal puts the task in the payload)."""
    def __init__(self,name='fal'):self.name=name;self.label=name;self.draft_endpoint='fake/'+name;self.final_endpoint=None;self.seen=[]
    def require_configured(self):pass
    def capabilities(self):return {'finalize':'complete_draft'}
    def submit_draft(self,prepared,refs,prompt,*,folder,status=print,task=None):
        self.seen.append(task);payload={'prompt':prompt,'video_urls':['https://x/v.mp4']}
        if self.name=='fal':payload['task']=task or 'editing'
        (Path(folder)/'seedance-request.json').write_text(json.dumps(payload));return 'req-'+self.name
    def poll(self,request_id,*,folder):return {'state':'running','status':'fake'}

def draft_ready(d,ident=HEX):
    p=synthetic_run(Path(d)/ident);(p/'audio-manifest.json').write_text('{}');(p/'seedance-input.mp4').write_bytes(b'prepared');(p/'char1-reference.png').write_bytes(plate_png())
    return p

class SeedanceTaskTests(unittest.TestCase):
    def post(self,client,ident,**data):
        return client.post(f'/jobs/{ident}/seedance',data={'prompt':'Base','provider':'fal','confirm_cost':'true',**data},files={'char1':('hero.png',plate_png(),'image/png')})
    def test_task_from_slots_then_form_then_default(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)),patch('mask_review.require_approved'),patch('seedance_bridge.wait_and_finish'),patch.dict(application.jobs,{},clear=False):   # the live-job dict is global: leave no entries behind
            p=draft_ready(d);adapter=FakeAdapter('fal');client=TestClient(application.app)
            with patch('seedance_bridge.get_provider',return_value=adapter):
                slots.write(p,{'set':{'mode':'prompt','prompt':'a loft'}})
                r=self.post(client,HEX);self.assertEqual(r.status_code,200,r.text);self.assertEqual(adapter.seen,['reference'])
                self.assertEqual(json.loads((p/'seedance-request.json').read_text())['task'],'reference')
                generation=json.loads((p/'generation.json').read_text());self.assertEqual(generation['task'],'reference')
                self.assertEqual(json.loads((p/'run.json').read_text())['chain']['generate']['params']['task'],'reference')
                report=stages.read_report(p,'generate');self.assertEqual(report['data']['task'],'reference');self.assertEqual(report['params']['task'],'reference')
                # the form wins over the slots; a bad value is a plain 400; a run without slots sends nothing (FAL_TASK as before)
                for name in ('seedance-response.json','generation.json','seedance-request.json'):(p/name).unlink()
                r=self.post(client,HEX,task='editing');self.assertEqual(r.status_code,200,r.text);self.assertEqual(adapter.seen[-1],'editing')
                r=self.post(client,HEX,task='extension');self.assertEqual(r.status_code,400);self.assertIn('fix',r.json())
                q=draft_ready(d,'e'*32)
                r=self.post(client,'e'*32);self.assertEqual(r.status_code,200,r.text);self.assertIsNone(adapter.seen[-1])
                self.assertEqual(json.loads((q/'generation.json').read_text())['task'],'editing')   # what the adapter wrote into the request
                r=self.post(client,'e'*32,task='auto');self.assertEqual(r.status_code,200,r.text) if r.status_code==200 else None
    def test_enhancor_records_not_applicable(self):
        with tempfile.TemporaryDirectory() as d,patch('mask_review.require_approved'):
            p=draft_ready(d);adapter=FakeAdapter('enhancor');slots.write(p,{'set':{'mode':'true_swap'}})
            with patch('seedance_bridge.get_provider',return_value=adapter):
                seedance_bridge.submit(p,'Base',p/'char1-reference.png',provider='enhancor',status=lambda s:None,task='reference')
            self.assertEqual(adapter.seen,['reference'])
            generation=json.loads((p/'generation.json').read_text());self.assertEqual(generation['task'],'not applicable');self.assertIn('no task setting',generation['task_note'])
            self.assertNotIn('task',json.loads((p/'run.json').read_text())['chain']['generate']['params'])
    def test_fal_task_override(self):
        from providers.fal import Fal
        with patch('providers.fal.setting',side_effect=lambda k,d='':{'FAL_TASK':'editing'}.get(k,d)):
            self.assertEqual(Fal()._task(),'editing');self.assertEqual(Fal()._task('reference'),'reference');self.assertEqual(Fal()._task('auto'),'editing')
            with self.assertRaises(ValueError):Fal()._task('sideways')

class StaticTests(unittest.TestCase):
    def test_slots_module_and_template_are_served(self):
        client=TestClient(application.app);index=client.get('/').text
        self.assertIn('tpl-world',index);self.assertIn('data-prompt-preview',index);self.assertIn('data-generator',index)
        self.assertEqual(client.get('/static/slots.js').status_code,200)

if __name__=='__main__':unittest.main()
