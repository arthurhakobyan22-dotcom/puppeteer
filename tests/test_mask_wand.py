"""Mask wand: RLE codec, merge rules, local propagation, brush, the three endpoints, branching, the paid gate and the offline switch.

Synthetic clip: a bright square moving over a dark background, 24 frames, with a depth video where the square is
near (bright) and the background far (dark). Everything is offline and free; the hosted tools are exercised with
`requests` and `fal_client` mocked to fail on contact, so `record_call` must come first.
"""
import unittest,tempfile,json,os,time,hashlib,sys
from pathlib import Path
from unittest.mock import patch,Mock
from fractions import Fraction
import numpy as np
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parent))
import app as application
import stages
from stages import wand
from stages.mask import parse_edits,parse_strokes,decode_fal_rle
from stages.calls import OfflineError

HEX='c'*32
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()
def tree_hashes(folder):return {p.relative_to(folder).as_posix():sha(p) for p in Path(folder).rglob('*') if p.is_file()}
def wait(ident):
    for _ in range(600):
        if application.jobs[ident]['state']!='running':return application.jobs[ident]
        time.sleep(.05)
    return application.jobs[ident]

def write_clip(path,frames,fps=24):
    import av
    with av.open(str(path),'w') as c:
        s=c.add_stream('libx264',rate=fps);s.width=frames[0].shape[1];s.height=frames[0].shape[0];s.pix_fmt='yuv420p';s.options={'crf':'16','preset':'ultrafast'}
        for i,a in enumerate(frames):
            f=av.VideoFrame.from_ndarray(a,format='rgb24');f.pts=i;f.time_base=Fraction(1,fps)
            for p in s.encode(f):c.mux(p)
        for p in s.encode():c.mux(p)

W,H,N=320,192,24
def square_box(i):
    x0=40+i*8;y0=60+(i%6)*2;return x0,y0,x0+56,y0+56

def synthetic_run(folder,with_masks=True,mask_of=None):
    """A depth run: original.mp4 (square moving right), depth.mp4 (square near), clean-masks (empty or as `mask_of` says)."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);rgb=[];dep=[]
    rng=np.random.default_rng(1)
    for i in range(N):
        a=np.full((H,W,3),28,np.uint8);a+=rng.integers(0,6,(H,W,3),dtype=np.uint8)   # a little texture for the flow
        x0,y0,x1,y1=square_box(i);a[y0:y1,x0:x1]=(220,200,60)
        d=np.full((H,W,3),30,np.uint8);d[y0:y1,x0:x1]=230
        rgb.append(a);dep.append(d)
    write_clip(folder/'original.mp4',rgb);write_clip(folder/'depth.mp4',dep);(folder/'upload.mp4').write_bytes((folder/'original.mp4').read_bytes())
    if with_masks:
        (folder/'clean-masks').mkdir(exist_ok=True)
        for i in range(N):
            m=np.zeros((H,W),bool)
            if mask_of:m=mask_of(i)
            wand.write_mask(m,folder/'clean-masks'/f'mask_{i:05d}.png')
    (folder/'sam-report.json').write_text(json.dumps({'prompt':'square','terms':['square'],'frames':N,'attempts':[],'method':'synthetic masks','source':'depth','model':'none'}))
    return folder

def masks_of(folder,name='clean-masks'):
    return [wand.read_mask(Path(folder)/name,i,(H,W)) for i in range(N)]

def square_mask(i,shape=(H,W)):
    m=np.zeros(shape,bool);x0,y0,x1,y1=square_box(i);m[y0:y1,x0:x1]=True;return m

# ---------------------------------------------------------------- RLE codec

class RleTests(unittest.TestCase):
    def test_round_trip_compressed_and_uncompressed(self):
        rng=np.random.default_rng(3)
        for shape in [(1,1),(7,5),(64,48),(30,97)]:
            for mask in [np.zeros(shape,bool),np.ones(shape,bool),rng.random(shape)>0.5,np.triu(np.ones(shape,bool))]:
                for compress in (True,False):
                    rle=wand.rle_encode(mask,compress=compress);self.assertEqual(rle['size'],list(shape))
                    back=wand.rle_decode(rle);self.assertTrue(np.array_equal(back,mask),(shape,compress))
                    self.assertTrue(np.array_equal(wand.rle_decode(json.dumps(rle)),mask))   # a JSON string of the same
        self.assertTrue(np.array_equal(wand.rle_decode(wand.rle_encode(mask,False)['counts'] and {'counts':wand.rle_encode(mask,False)['counts'],'size':[30,97]}),mask))
    def test_known_coco_example_and_column_major_order(self):
        # pycocotools: a 2x3 mask [[1,0,1],[0,1,0]] flattens column-major to 1 0 0 1 1 0 -> counts [0,1,2,2,1]
        mask=np.array([[1,0,1],[0,1,0]],bool)
        self.assertEqual(wand.rle_encode(mask,compress=False)['counts'],[0,1,2,2,1])
        self.assertTrue(np.array_equal(wand.rle_decode({'counts':[0,1,2,2,1],'size':[2,3]}),mask))
        self.assertEqual(wand.rle_counts_from_string(wand.rle_counts_to_string([0,1,2,2,1])),[0,1,2,2,1])
        self.assertEqual(wand.rle_counts_from_string(wand.rle_counts_to_string([5000,1,70000,3])),[5000,1,70000,3])   # multi-byte and delta coding
    def test_bad_rle_is_a_plain_error(self):
        with self.assertRaises(ValueError) as e:wand.rle_decode({'counts':[1,2],'size':[2,3]})
        self.assertIn('pixels',str(e.exception))
        with self.assertRaises(ValueError):wand.rle_decode('plain text with no size')
    def test_fal_result_shapes(self):
        masks=[square_mask(i,(10,12)) for i in range(3)];rles=[wand.rle_encode(m) for m in masks]
        for result in [{'rle':rles},{'rle':json.dumps(rles)},{'rle':[json.dumps(r) for r in rles]},{'rle':[r['counts'] for r in rles],'metadata':{'height':10,'width':12}},{'rle':{'url':'https://x/masks.json'}}]:
            got=decode_fal_rle(result,3,(10,12),download=lambda u:json.dumps(rles).encode())
            self.assertEqual(sorted(got),[0,1,2]);self.assertTrue(all(np.array_equal(got[i],masks[i]) for i in range(3)),result.keys())
        self.assertEqual(sorted(decode_fal_rle({'rle':rles[:1]},3,(10,12))),[0])
        with self.assertRaises(ValueError):decode_fal_rle({'rle':42},3,(10,12))

# ---------------------------------------------------------------- merge, brush, parsing

class MergeAndBrushTests(unittest.TestCase):
    def test_include_or_exclude_subtract_in_order(self):
        base=np.zeros((4,4),bool);base[0,:]=True;a=np.zeros((4,4),bool);a[1,:]=True;b=np.zeros((4,4),bool);b[:,0]=True
        out=wand.merge_frame(base,[('include',a),('exclude',b)])
        expect=base|a;expect[:,0]=False;self.assertTrue(np.array_equal(out,expect))
        self.assertTrue(np.array_equal(wand.merge_frame(base,[('exclude',b),('include',b)]),base|b))   # order matters
        self.assertTrue(np.array_equal(wand.merge_frame(base,[]),base));self.assertIsNot(wand.merge_frame(base,[]),base)
    def test_brush_rasterises_strokes_on_a_frame_range(self):
        per=wand.brush_regions([{'frame_from':2,'frame_to':4,'mode':'paint','points':[[0.1,0.5],[0.9,0.5]],'radius':0.05},{'frame_from':3,'frame_to':3,'mode':'erase','points':[[0.5,0.5]],'radius':0.1}],(100,200),10)
        self.assertEqual(sorted(per),[2,3,4]);self.assertEqual([m for m,_ in per[3]],['include','exclude'])
        line=per[2][0][1];self.assertTrue(line[50,100]);self.assertTrue(line[46,100]);self.assertFalse(line[20,100]);self.assertFalse(line[50,5])
        dot=per[3][1][1];self.assertTrue(dot[50,100]);self.assertTrue(dot[42,100]);self.assertFalse(dot[50,130])
        clamped=wand.brush_regions([{'frame_from':8,'frame_to':30,'mode':'paint','points':[[0.5,0.5]],'radius':0.02}],(100,200),10);self.assertEqual(sorted(clamped),[8,9])
    def test_parsers_give_plain_errors(self):
        self.assertEqual(parse_edits('[{"frame": 3, "x": 0.5, "y": 0.25, "label": 0}]'),[{'frame':3,'x':0.5,'y':0.25,'label':0,'object_id':'remove'}])
        self.assertEqual(parse_edits([{'frame':'1','x':'0.1','y':'0.9','label':'include'}])[0]['label'],1);self.assertEqual(parse_edits(''),[])
        for bad in ['{"frame": 1}','[{"frame": 1, "x": 2, "y": 0}]','[5]','[{"x": "a", "y": 0}]']:
            with self.assertRaises(ValueError,msg=bad) as e:parse_edits(bad)
            self.assertNotIn('Traceback',str(e.exception))
        self.assertEqual(parse_strokes([{'frame_from':5,'frame_to':2,'mode':'erase','points':[[0,0],[1,1]],'radius':9}])[0],{'frame_from':2,'frame_to':5,'mode':'erase','points':[[0.0,0.0],[1.0,1.0]],'radius':0.5})
        with self.assertRaises(ValueError):parse_strokes([{'points':[]}])
        with self.assertRaises(ValueError):parse_strokes([{'points':[[1.5,0]]}])

# ---------------------------------------------------------------- the free local algorithm on the synthetic clip

class LocalPropagateTests(unittest.TestCase):
    def test_include_click_masks_the_square_on_every_frame_and_exclude_removes_it(self):
        with tempfile.TemporaryDirectory() as d:
            folder=synthetic_run(Path(d)/'runs'/HEX)
            x0,y0,x1,y1=square_box(12);click={'frame':12,'x':(x0+x1)/2/W,'y':(y0+y1)/2/H,'label':1}
            per,notes,shape,fps=wand.local_propagate(folder,[click],max_frames=120)
            self.assertEqual(shape,(H,W));self.assertEqual(fps,24.0);self.assertEqual(sorted(per),list(range(N)),notes)
            self.assertEqual((notes[0]['first_frame'],notes[0]['last_frame'],notes[0]['frames']),(0,N-1,N));self.assertEqual((notes[0]['forward_stop'],notes[0]['backward_stop']),('end','end'))
            for i in range(N):
                region=wand.upscale(per[i][0][1],shape);truth=square_mask(i)
                inter=(region&truth).sum();union=(region|truth).sum();self.assertGreater(inter/union,0.8,f'frame {i}: IoU {inter/union:.2f}')
            # through the tool: include adds the square to the (empty) parent masks on all 24 frames
            tool=stages.get_tool('mask','local_propagate');params=tool.normalize_params({'edits':json.dumps([click]),'base_run':HEX})
            child=Path(d)/'runs'/('d'*32);child.mkdir();os.link(folder/'original.mp4',child/'original.mp4');os.link(folder/'depth.mp4',child/'depth.mp4')
            (child/'run.json').write_text(json.dumps({'id':child.name,'parent':HEX}))
            r=tool.run({'folder':child,'seconds':1.0},params,child,lambda s:None)
            self.assertEqual(r['frames']['covered'],N);self.assertEqual(len(r['data']['wand']['frames_changed']),N);self.assertRegex(r['health'],r'^Added a region from frame 12 forward to 1\.0 s \(the end of the clip\) and back to 0\.0 s \(the start of the clip\) on 24 frames\.$')
            self.assertEqual(set(r['outputs']),{'raw-masks','clean-masks','sam-report.json','mask-edits.json'})
            added=masks_of(child);self.assertTrue(all((added[i]&square_mask(i)).sum()/square_mask(i).sum()>0.8 for i in range(N)))
            self.assertTrue(np.array_equal(added[5],masks_of(child,'raw-masks')[5]))
            report=json.loads((child/'sam-report.json').read_text());self.assertEqual(report['wand']['tool'],'local_propagate');self.assertIn('mask wand',report['method']);self.assertEqual(report['prompt'],'square')
            history=json.loads((child/'mask-edits.json').read_text())['history'];self.assertEqual(len(history),1);self.assertEqual(history[0]['frames_changed'],N)
            # exclude: the same click with label 0 on a parent whose masks contain the square removes it everywhere
            full=synthetic_run(Path(d)/'runs'/('e'*32),mask_of=square_mask);grand=Path(d)/'runs'/('f'*32);grand.mkdir()
            for n in ('original.mp4','depth.mp4'):os.link(full/n,grand/n)
            (grand/'run.json').write_text(json.dumps({'id':grand.name,'parent':full.name}))
            r2=tool.run({'folder':grand,'seconds':1.0},tool.normalize_params({'edits':json.dumps([{**click,'label':0}]),'base_run':full.name}),grand,lambda s:None)
            self.assertTrue(r2['health'].startswith('Removed a region from frame 12'))
            left=masks_of(grand);self.assertTrue(all(left[i].sum()<0.2*square_mask(i).sum() for i in range(N)),[int(m.sum()) for m in left])
            # the second edit's history carries the first one along when branching from a wand child
            self.assertEqual(len(json.loads((grand/'mask-edits.json').read_text())['history']),1)
    def test_no_depth_or_no_clicks_is_a_plain_error(self):
        with tempfile.TemporaryDirectory() as d:
            folder=synthetic_run(Path(d)/HEX);(folder/'depth.mp4').unlink()
            with self.assertRaises(ValueError) as e:wand.local_propagate(folder,[{'frame':0,'x':.5,'y':.5,'label':1}])
            self.assertIn('depth video',str(e.exception))
            tool=stages.get_tool('mask','local_propagate')
            with self.assertRaises(ValueError) as e:tool.run({'folder':folder},tool.normalize_params({}),folder,lambda s:None)
            self.assertIn('No clicks',str(e.exception))

class BrushToolTests(unittest.TestCase):
    def test_brush_paints_five_frames_on_the_parent_masks(self):
        with tempfile.TemporaryDirectory() as d:
            parent=synthetic_run(Path(d)/'runs'/HEX,mask_of=square_mask);child=Path(d)/'runs'/('b'*32);child.mkdir();os.link(parent/'original.mp4',child/'original.mp4')
            (child/'run.json').write_text(json.dumps({'id':child.name,'parent':HEX}))
            tool=stages.get_tool('mask','brush');strokes=[{'frame_from':10,'frame_to':14,'mode':'paint','points':[[0.1,0.9],[0.3,0.9]],'radius':0.04}]
            r=tool.run({'folder':child},tool.normalize_params({'strokes':json.dumps(strokes),'base_run':HEX}),child,lambda s:None)
            self.assertEqual(r['data']['wand']['frames_changed'],[10,11,12,13,14]);self.assertIn('5 frames',r['health'])
            after=masks_of(child);self.assertTrue(after[12][int(0.9*H),int(0.2*W)]);self.assertFalse(after[9][int(0.9*H),int(0.2*W)]);self.assertTrue(np.array_equal(after[0],square_mask(0)))
            erase=[{'frame_from':0,'frame_to':0,'mode':'erase','points':[[(square_box(0)[0]+28)/W,(square_box(0)[1]+28)/H]],'radius':0.3}]
            r2=tool.run({'folder':child},tool.normalize_params({'strokes':json.dumps(erase),'base_run':HEX}),child,lambda s:None)
            self.assertEqual(r2['data']['wand']['frames_changed'],[0]);self.assertFalse(masks_of(child)[0].any())

# ---------------------------------------------------------------- endpoints, branching, approval, cost gate, offline

class EndpointTests(unittest.TestCase):
    def prepared_parent(self,d):
        """A synthetic depth run with every prepared artifact and a written run.json, as a wand parent."""
        folder=synthetic_run(Path(d)/'runs'/HEX,mask_of=square_mask)
        for n in ('mask.mp4','composite.mp4','depth-composite-silent.mp4','composite-silent.mp4','seedance-input.mp4'):(folder/n).write_bytes(b'prepared:'+n.encode())
        (folder/'workflow-mode.json').write_text(json.dumps({'mode':'depth'}));(folder/'manifest.json').write_text(json.dumps({'frames':N,'prompt':'square'}));(folder/'audio-manifest.json').write_text('{}')
        (folder/'status.json').write_text(json.dumps({'id':HEX,'state':'done','status':'Complete'}))
        stages.reconstruct(folder,with_keys=True,write=True)
        return folder
    def test_frame_preview_apply_and_the_child_run(self):
        from test_regression import FakeSteps,fake_face_root
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)/'runs'):
            parent=self.prepared_parent(d);client=TestClient(application.app);application.jobs.pop(HEX,None)
            import mask_review
            fp=mask_review.fingerprint(parent);mask_review.review(parent,True,'ok',fp);self.assertEqual(client.get(f'/jobs/{HEX}/mask-review').json()['status'],'approved')
            before=tree_hashes(parent)
            # frame
            r=client.get(f'/jobs/{HEX}/mask/frame?i=12');self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.headers['content-type'],'image/jpeg');self.assertEqual(r.content[:2],b'\xff\xd8')
            self.assertEqual((r.headers['x-frame'],r.headers['x-frames'],r.headers['x-width'],r.headers['x-height'],r.headers['x-has-masks']),('12',str(N),str(W),str(H),'1'))
            self.assertEqual(client.get(f'/jobs/{HEX}/mask/frame?t=0.5').headers['x-frame'],'12');self.assertEqual(client.get(f'/jobs/{HEX}/mask/frame?i=99').headers['x-frame'],str(N-1))
            self.assertEqual(client.get('/jobs/'+'0'*32+'/mask/frame?i=0').status_code,404)
            # preview
            x0,y0,x1,y1=square_box(12);click={'frame':12,'x':(x0+x1)/2/W,'y':(y0+y1)/2/H,'label':1}
            r=client.post(f'/jobs/{HEX}/mask/preview',json={'frame':12,'edits':[click]});self.assertEqual(r.status_code,200,r.text);body=r.json()
            self.assertTrue(body['url'].startswith(f'/runs/{HEX}/wand-preview/'));self.assertEqual(body['selections'][0]['mode'],'include');self.assertGreater(body['selections'][0]['fraction'],0.02)
            png=parent/body['url'].split(f'/runs/{HEX}/')[1];self.assertTrue(png.exists());self.assertEqual(png.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')   # served by the /runs mount (bound at import, so read from disk here)
            self.assertEqual(client.post(f'/jobs/{HEX}/mask/preview',data={'time':'0.5','edits':json.dumps([click])}).json()['frame'],12)
            r=client.post(f'/jobs/{HEX}/mask/preview',json={'frame':12,'edits':[{'frame':12,'x':3,'y':0}]});self.assertEqual(r.status_code,400);self.assertIn('fix',r.json())
            # apply with the free local tool: a branch at mask, composite + face re-run, parent untouched, review pending
            for bad,expect in [({'tool':'laser'},'Unknown mask wand tool'),({'tool':'local_propagate'},'No clicks'),({'tool':'brush'},'No brush strokes'),({'tool':'local_propagate','edits':[{'frame':99,'x':.5,'y':.5}]},'outside the clip')]:
                r=client.post(f'/jobs/{HEX}/mask/apply',json=bad);self.assertEqual(r.status_code,400,r.text);self.assertIn(expect,r.json()['message']);self.assertTrue(r.json()['fix'])
            steps=FakeSteps();patches=[patch('pipeline.composite',side_effect=steps.composite),patch('audio_workflow.prepare_seedance_video',side_effect=steps.prepare_seedance_video),patch('face_mesh.ROOT',fake_face_root(d))]
            for p in patches:p.start()
            try:
                with patch.dict(os.environ,{'PUPPETEER_OFFLINE':'1'}):
                    r=client.post(f'/jobs/{HEX}/mask/apply',json={'tool':'local_propagate','edits':[click]});self.assertEqual(r.status_code,200,r.text);cid=r.json()['id'];job=wait(cid)
            finally:
                for p in patches:p.stop()
            self.assertEqual(job['state'],'done',job);self.assertEqual(job['parent'],HEX);self.assertTrue(job['changed'].startswith('mask: sam3_replicate'));self.assertIn('local_propagate',job['changed']);self.assertEqual(job['estimated_cost_usd'],0)
            child=Path(d)/'runs'/cid;run=json.loads((child/'run.json').read_text());self.assertEqual(run['parent'],HEX);self.assertEqual(run['chain']['mask']['tool'],'local_propagate');self.assertEqual(run['chain']['mask']['params']['base_run'],HEX)
            self.assertEqual((child/'depth.mp4').stat().st_ino,(parent/'depth.mp4').stat().st_ino);self.assertEqual(sha(child/'depth.mp4'),sha(parent/'depth.mp4'))
            self.assertEqual(json.loads((child/'stages/depth/report.json').read_text())['cached_from'],HEX)
            self.assertEqual(steps.names(),['composite','prepare_seedance_video']);self.assertEqual(steps.first('composite')[3],'clean-masks')
            self.assertFalse((child/'calls.jsonl').exists());self.assertFalse((parent/'calls.jsonl').exists())
            self.assertEqual({k:v for k,v in tree_hashes(parent).items() if not k.startswith('wand-preview/')},before)   # parent files unchanged; the preview PNGs under wand-preview/ are the only addition (by design, no artifact)
            self.assertFalse((child/'mask-review.json').exists());self.assertEqual(client.get(f'/jobs/{cid}/mask-review').json()['status'],'pending')
            masks=masks_of(child);self.assertTrue(all(masks[i].any() for i in range(N)));self.assertEqual(json.loads((child/'sam-report.json').read_text())['wand']['tool'],'local_propagate')
            report=json.loads((child/'stages/mask/report.json').read_text());self.assertEqual(report['state'],'done');self.assertTrue(report['health'].startswith('Added a region from frame 12'));self.assertEqual(report['cost_usd'],0)
            # brush on the child: another branch
            r=client.post(f'/jobs/{cid}/mask/apply',data={'tool':'brush','strokes':json.dumps([{'frame_from':0,'frame_to':4,'mode':'paint','points':[[0.5,0.1],[0.6,0.1]],'radius':0.03}])})
            self.assertEqual(r.status_code,200,r.text)
            for p in patches:p.start()
            try:job2=wait(r.json()['id'])
            finally:
                for p in patches:p.stop()
            self.assertEqual(job2['state'],'done',job2);grand=Path(d)/'runs'/job2['id'];self.assertEqual(json.loads((grand/'run.json').read_text())['parent'],cid)
            self.assertEqual(len(json.loads((grand/'mask-edits.json').read_text())['history']),2);self.assertTrue(masks_of(grand)[2][int(0.1*H),int(0.55*W)])
            tree=client.get('/jobs/tree').json()['runs'];node=next(n for n in tree if n['id']==HEX);self.assertEqual(node['children'][0]['id'],cid);self.assertEqual(node['children'][0]['children'][0]['id'],job2['id'])
    def test_paid_tools_need_confirmation_and_stay_offline(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)/'runs'):
            parent=self.prepared_parent(d);client=TestClient(application.app);application.jobs.pop(HEX,None);before=tree_hashes(parent)
            click={'frame':3,'x':.5,'y':.5,'label':1};boom=Mock(side_effect=AssertionError('network call attempted'))
            for tool in ('sam3_points_fal','sam2_points_replicate'):
                r=client.post(f'/jobs/{HEX}/mask/apply',json={'tool':tool,'edits':[click]});self.assertEqual(r.status_code,402,r.text);body=r.json()
                self.assertGreater(body['estimated_cost_usd'],0);self.assertIn('costs about $',body['message']);self.assertIn('confirm_cost=true',body['fix'])
                r=client.post(f'/jobs/{HEX}/mask/apply',json={'tool':tool,'edits':[click,{**click,'label':0}]});self.assertEqual(r.json()['estimated_cost_usd'],round(body['estimated_cost_usd']*2,4))   # two click types: two calls
                est=client.post(f'/jobs/{HEX}/estimate',json={'stage':'mask','tool':tool,'params':{'edits':json.dumps([click])}}).json();self.assertEqual(est['paid'][0]['tool'],tool);self.assertEqual(est['stages_to_run'],['mask','composite','face'])
                with patch.dict(os.environ,{'PUPPETEER_OFFLINE':'1'}),patch('requests.post',boom),patch('requests.get',boom),patch('raw_masks.requests.post',boom),patch('raw_masks.requests.get',boom),patch('fal_client.upload_file',boom),patch('fal_client.submit',boom):
                    r=client.post(f'/jobs/{HEX}/mask/apply',json={'tool':tool,'edits':[click],'confirm_cost':'true'});self.assertEqual(r.status_code,200,r.text);job=wait(r.json()['id'])
                self.assertEqual(job['state'],'error',job);self.assertIn('switched off in offline mode',job['status']);self.assertIn('PUPPETEER_OFFLINE',job['fix']);self.assertNotIn('Traceback',job['status'])
                child=Path(d)/'runs'/job['id'];self.assertFalse((child/'calls.jsonl').exists());self.assertEqual(json.loads((child/'stages/mask/report.json').read_text())['state'],'error')
            self.assertEqual(tree_hashes(parent),before)
    def test_every_paid_wand_tool_records_the_call_before_any_network_io(self):
        """Online (not offline): with requests / fal_client failing on contact, the calls log must already hold the line."""
        with tempfile.TemporaryDirectory() as d,patch.object(stages.calls,'GLOBAL_LOG',Path(d)/'calls.log'):
            parent=synthetic_run(Path(d)/'runs'/HEX,mask_of=square_mask);child=Path(d)/'runs'/('a'*32);child.mkdir()
            for n in ('original.mp4','depth.mp4','upload.mp4'):os.link(parent/n,child/n)
            (child/'run.json').write_text(json.dumps({'id':child.name,'parent':HEX}))
            boom=Mock(side_effect=AssertionError('network call attempted'))
            with patch('requests.post',boom),patch('requests.get',boom),patch('raw_masks.requests.post',boom),patch('raw_masks.requests.get',boom),patch('fal_client.upload_file',boom),patch('fal_client.submit',boom),\
                 patch('raw_masks.setting',side_effect=lambda k,dflt='':{'REPLICATE_API_TOKEN':'tok'}.get(k,dflt)),patch('config.credential',return_value='k'),patch('config.load_env'):
                for tool_name in ('sam3_points_fal','sam2_points_replicate'):
                    (child/'calls.jsonl').unlink(missing_ok=True)
                    tool=stages.get_tool('mask',tool_name);params=tool.normalize_params({'edits':json.dumps([{'frame':3,'x':.5,'y':.5,'label':1}]),'base_run':HEX})
                    with self.assertRaises(AssertionError,msg=tool_name):tool.run({'folder':child,'seconds':1.0},params,child,lambda s:None)
                    logged=stages.read_calls(child);self.assertEqual(len(logged),1,tool_name);self.assertEqual(logged[0]['provider'],'fal' if tool_name=='sam3_points_fal' else 'replicate')
                    self.assertGreaterEqual(logged[0]['cost_usd'],0)
    def test_sam3_fal_result_is_merged_when_the_call_succeeds(self):
        """fal mocked end to end: the include object is OR-ed in, the exclude object subtracted, one call per click type, source auto = depth."""
        with tempfile.TemporaryDirectory() as d,patch.object(stages.calls,'GLOBAL_LOG',Path(d)/'calls.log'):
            parent=synthetic_run(Path(d)/'runs'/HEX,mask_of=square_mask);child=Path(d)/'runs'/('a'*32);child.mkdir()
            for n in ('original.mp4','depth.mp4','upload.mp4'):os.link(parent/n,child/n)
            (child/'run.json').write_text(json.dumps({'id':child.name,'parent':HEX}))
            include=[np.zeros((H,W),bool) for _ in range(N)];exclude=[np.zeros((H,W),bool) for _ in range(N)]
            for i in range(N):include[i][150:180,10:60]=True;exclude[i][:,:W//2]=True
            sent=[]
            def submit(endpoint,arguments):
                sent.append((endpoint,arguments));mode=arguments['point_prompts'][0]['object_id']
                return Mock(request_id='req-'+mode,get=lambda:{'rle':[wand.rle_encode(m) for m in (include if mode=='include' else exclude)]})
            with patch('fal_client.upload_file',return_value='https://fal/video') as up,patch('fal_client.submit',side_effect=submit),patch('config.credential',return_value='k'),patch('config.load_env'):
                tool=stages.get_tool('mask','sam3_points_fal')
                params=tool.normalize_params({'edits':json.dumps([{'frame':3,'x':.5,'y':.5,'label':1},{'frame':5,'x':.1,'y':.1,'label':0}]),'base_run':HEX})
                r=tool.run({'folder':child,'seconds':1.0},params,child,lambda s:None)
            self.assertEqual(up.call_args.args[0],str(child/'depth.mp4'));self.assertEqual([a['point_prompts'][0]['object_id'] for _,a in sent],['include','exclude'])
            self.assertEqual(sent[0][1]['point_prompts'][0],{'x':.5*W,'y':.5*H,'label':1,'frame_index':3,'object_id':'include'});self.assertNotIn('prompt',sent[0][1]);self.assertFalse(sent[0][1]['apply_mask'])
            masks=masks_of(child)
            for i in range(N):
                expect=(square_mask(i)|include[i])&~exclude[i];self.assertTrue(np.array_equal(masks[i],expect),i)
            self.assertEqual(len(stages.read_calls(child)),2);self.assertEqual(r['data']['wand']['source'],'depth');self.assertTrue((child/'wand-hosted.json').exists())
            self.assertEqual(json.loads((child/'wand-hosted.json').read_text())['calls']['include']['request_id'],'req-include')

if __name__=='__main__':unittest.main()
