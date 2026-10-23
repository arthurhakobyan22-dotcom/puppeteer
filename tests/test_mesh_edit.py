"""Face mesh track of the edit layer: the pure edit (`meshedit.apply`: mesh off, eased keys, expressions) against fixed
expectations shared with the JS port (tests/fixtures/mesh-edit-cases.json, also run under node), the local renderer
(pixel compares on a small synthetic clip), the routes (undo / redo across mask and mesh edits), saving (mesh only →
one child at face with `mesh_edit`; mask + mesh → one child at mask with also face; a later branch re-runs mesh_edit),
the parent never written, and zero external calls (sockets, requests and urllib patched to fail on contact).
"""
import unittest,tempfile,json,os,math,time,sys,shutil,socket,subprocess,urllib.request
from pathlib import Path
from unittest.mock import patch
import numpy as np
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parent))
import app as application
import stages
from stages import meshedit,editlayer,wand
from test_mask_wand import synthetic_run,square_mask,square_box,write_clip,tree_hashes,wait,HEX,W,H,N

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=json.loads((ROOT/'tests'/'fixtures'/'mesh-edit-cases.json').read_text())
FACE=[tuple(p) for p in FIXTURE['face']];ASPECT=W/H

def runs_in(root):return sorted(p.name for p in Path(root).iterdir() if p.is_dir() and len(p.name)==32)
def frames_of(path):
    import av
    with av.open(str(path)) as c:return [f.to_ndarray(format='rgb24').astype(int) for f in c.decode(video=0)]
def axes(points,aspect=ASPECT):
    P=[(x*aspect,y) for x,y in points];f,c=P[meshedit.FOREHEAD],P[meshedit.CHIN];h=math.hypot(c[0]-f[0],c[1]-f[1]);d=((c[0]-f[0])/h,(c[1]-f[1])/h)
    return P,h,d
def big(a,b):return int((np.abs(a-b).max(2)>40).sum())   # pixels that differ by more than codec noise (re-encoding stays under ~10)
def moved(a,b,i,aspect=ASPECT):return ((b[i][0]-a[i][0])*aspect,b[i][1]-a[i][1])
def landmarks(n=N,missing=(20,21),filled=(3,)):
    """A synthetic face-landmarks.json: the fixture face drifting right, tracked except `filled` / `missing` frames."""
    frames=[]
    for i in range(n):
        status='missing' if i in missing else 'filled' if i in filled else 'tracked'
        faces=[] if status=='missing' else [[{'x':x+0.004*i,'y':y} for x,y in FACE]]
        frames.append({'frame':i,'time':round(i/24,4),'status':status,'source':'crop' if status=='tracked' else None,'faces':faces})
    return {'fps':24,'frames':frames,'summary':{'frames':n,'tracked':n-len(missing)-len(filled),'filled':len(filled),'missing':len(missing)}}
def depth_composite(i):
    a=np.zeros((H,W,3),np.uint8);a[:,:,0]=np.linspace(40,200,W,dtype=np.uint8)[None,:];a[:,:,1]=90+i*2;a[:,:,2]=np.linspace(180,60,H,dtype=np.uint8)[:,None];return a

def mesh_parent(d,ident=HEX):
    """A synthetic Advanced + mesh run: original/depth/masks (test_mask_wand), a real depth composite, landmarks, the mesh drawn over it."""
    folder=synthetic_run(Path(d)/'runs'/ident,mask_of=square_mask)
    write_clip(folder/'depth-composite-silent.mp4',[depth_composite(i) for i in range(N)])
    lm=landmarks();(folder/'face-landmarks.json').write_text(json.dumps(lm))
    from mesh_tracking import evaluate
    st=[f['status'] for f in lm['frames']]
    (folder/'face-tracking.json').write_text(json.dumps({**evaluate(st,24,strict=False),'fps':24,'missing_frames':[i for i,s in enumerate(st) if s=='missing'],'filled_frames':[i for i,s in enumerate(st) if s=='filled']}))
    meshedit.render(folder,lm,folder/'depth-composite-silent.mp4')
    for n in ('mask.mp4','composite.mp4','seedance-input.mp4'):(folder/n).write_bytes(b'prepared:'+n.encode())
    (folder/'workflow-mode.json').write_text(json.dumps({'mode':'depth_mesh'}));(folder/'manifest.json').write_text(json.dumps({'frames':N,'prompt':'square'}));(folder/'audio-manifest.json').write_text('{}')
    (folder/'status.json').write_text(json.dumps({'id':ident,'state':'done','status':'Complete'}))
    stages.reconstruct(folder,with_keys=True,write=True)
    return folder

class NoNetwork:
    """Every way out of the process fails loudly: sockets, requests, urllib (and fal_client's HTTP goes through them)."""
    def __init__(self):self.hits=[]
    def boom(self,*a,**k):
        self.hits.append(a[:2]);raise AssertionError('an external call was attempted during a mesh edit')
    def __enter__(self):
        import requests
        self.patches=[patch.object(socket.socket,'connect',self.boom),patch.object(socket,'create_connection',self.boom),patch.object(urllib.request,'urlopen',self.boom),
                      patch.object(requests.Session,'request',self.boom),patch.object(stages.calls,'record_call',self.boom)]
        for p in self.patches:p.start()
        return self
    def __exit__(self,*exc):
        for p in self.patches:p.stop()

# ---------------------------------------------------------------- the formulas (shared fixture with the JS port)

class Formulas(unittest.TestCase):
    def test_python_matches_the_fixture(self):
        for case in FIXTURE['cases']:
            got=meshedit.edit_points(FACE,case['expr'],case['key'],FIXTURE['aspect'])
            self.assertEqual(len(got),478,case['name'])
            worst=max(max(abs(a[0]-b[0]),abs(a[1]-b[1])) for a,b in zip(got,case['expected']));self.assertLess(worst,1e-9,case['name'])
        keys=meshedit.normalize({'keys':FIXTURE['blend']['keys']})[1]
        for f,expect in FIXTURE['blend']['frames'].items():
            got=meshedit.transform_at(keys,int(f));self.assertEqual(got is None,expect is None,f)
            if got:self.assertLess(max(abs(got[k]-expect[k]) for k in expect),1e-12,f)
        for case in FIXTURE['normalize']:
            off,k,e=meshedit.normalize(case['in']);self.assertEqual({'off':off,'keys':{str(a):b for a,b in k.items()},'expr':{str(a):b for a,b in e.items()}},case['out'])
    def test_js_port_matches_the_fixture(self):
        node=shutil.which('node')
        if not node:self.skipTest('node is not installed')
        script="""import fs from 'fs';const M=await import('data:text/javascript,'+encodeURIComponent(fs.readFileSync('static/meshedit.js','utf8')));
const fx=JSON.parse(fs.readFileSync('tests/fixtures/mesh-edit-cases.json','utf8'));let worst=0;
for(const c of fx.cases){M.editPoints(fx.face,c.expr,c.key,fx.aspect).forEach((p,i)=>{worst=Math.max(worst,Math.abs(p[0]-c.expected[i][0]),Math.abs(p[1]-c.expected[i][1]));});}
const n=M.normalize({keys:fx.blend.keys});let blend=true;
for(const [f,e] of Object.entries(fx.blend.frames)){const g=M.transformAt(n.keys,Number(f));if(!!g!==!!e)blend=false;else if(g)for(const k in e)worst=Math.max(worst,Math.abs(g[k]-e[k]));}
const norms=fx.normalize.map(c=>{const g=M.normalize(c.in);return JSON.stringify({off:g.off,keys:Object.fromEntries([...g.keys].map(([a,b])=>[String(a),b])),expr:Object.fromEntries([...g.expr].map(([a,b])=>[String(a),b]))})===JSON.stringify(c.out);});
const fr={status:'tracked',faces:[fx.face.map(([x,y])=>({x,y}))]};const off=M.editFrame(fr,5,M.normalize({off:[[4,6]]}),fx.aspect);const same=M.editFrame(fr,9,M.normalize({off:[[4,6]]}),fx.aspect);
console.log(JSON.stringify({worst,blend,norms,off:[off.faces.length,off.status],same:same.edited}));"""
        r=subprocess.run([node,'--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=60);self.assertEqual(r.returncode,0,r.stderr)
        out=json.loads(r.stdout.strip().splitlines()[-1])
        self.assertLess(out['worst'],1e-9);self.assertTrue(out['blend']);self.assertEqual(out['norms'],[True]*len(FIXTURE['normalize']));self.assertEqual(out['off'],[0,'off']);self.assertFalse(out['same'])
    def test_jaw_moves_lower_lip_and_chin_down_by_the_documented_amount(self):
        P,h,d=axes(FACE);out=meshedit.edit_points(FACE,{'jaw':0.8},None,ASPECT)
        for i in (meshedit.CHIN,meshedit.LIP_BOTTOM,17,18,200):   # chin, inner lower lip, outer lower lip, below the lip
            dx,dy=moved(FACE,out,i);self.assertAlmostEqual(dx,0.8*meshedit.JAW_OPEN*h*d[0],12,i);self.assertAlmostEqual(dy,0.8*meshedit.JAW_OPEN*h*d[1],12,i)
            self.assertGreater(dy,0.07*h,f'{i} moves down the picture')
        for i in meshedit.UPPER_LIP+(meshedit.FOREHEAD,1,4,33,133,263,362,159,386,105,334):self.assertEqual(out[i],FACE[i],f'{i} stays (upper lip, nose, eyes, brows)')
        chin=math.hypot(*moved(FACE,out,152))
        for i in (172,58,132,397,288,361):self.assertLess(math.hypot(*moved(FACE,out,i)),0.75*chin,f'jaw angle {i} moves less than the chin (hinge)')
    def test_blink_smile_pucker_brow(self):
        out=meshedit.edit_points(FACE,{'blink_l':1.0,'blink_r':0.5},None,ASPECT)
        for u,l in meshedit.EYELIDS['blink_l']:self.assertAlmostEqual(out[u][0],FACE[l][0],12);self.assertAlmostEqual(out[u][1],FACE[l][1],12)   # closed: upper lid on the lower
        for u,l in meshedit.EYELIDS['blink_r']:self.assertAlmostEqual(out[u][1],(FACE[u][1]+FACE[l][1])/2,12)
        for u,l in meshedit.EYELIDS['blink_l']:self.assertEqual(out[l],FACE[l])
        P,h,d=axes(FACE);r=(d[1],-d[0])
        out=meshedit.edit_points(FACE,{'smile':1.0},None,ASPECT);left,right=moved(FACE,out,61),moved(FACE,out,291)
        side=lambda v:v[0]*r[0]+v[1]*r[1];up=lambda v:-(v[0]*d[0]+v[1]*d[1])
        self.assertAlmostEqual(side(right),meshedit.SMILE_OUT*h,12);self.assertAlmostEqual(side(left),-meshedit.SMILE_OUT*h,12);self.assertAlmostEqual(up(left),meshedit.SMILE_UP*h,12)
        out=meshedit.edit_points(FACE,{'pucker':1.0},None,ASPECT);width=lambda pts:abs(pts[291][0]-pts[61][0])
        self.assertAlmostEqual(width(out),(1-meshedit.PUCKER_IN)*width(FACE),3)
        out=meshedit.edit_points(FACE,{'brow':1.0},None,ASPECT)
        for i in meshedit.BROWS:self.assertAlmostEqual(up(moved(FACE,out,i)),meshedit.BROW_UP*h,12)
        self.assertEqual(meshedit.edit_points(FACE,None,{'dx':0,'dy':0,'scale':1,'rot':0},ASPECT),FACE,'an identity key changes nothing (no float round trip)')
    def test_keys_on_40_and_52_ease_across_41_to_51(self):
        lm=landmarks(70,missing=(),filled=())
        layer={'keys':{'40':{'dx':0.02,'dy':0.0,'scale':1.0,'rot':0.0},'52':{'dx':0.08,'dy':-0.04,'scale':1.0,'rot':0.0}}}
        out=meshedit.apply(lm,layer,ASPECT)
        shift=lambda f,k:out['frames'][f]['faces'][0][1][k]-lm['frames'][f]['faces'][0][1][k]
        dx=[shift(f,'x') for f in range(40,53)];dy=[shift(f,'y') for f in range(40,53)]
        self.assertAlmostEqual(dx[0],0.02,12);self.assertAlmostEqual(dx[-1],0.08,12);self.assertAlmostEqual(dy[0],0.0,12);self.assertAlmostEqual(dy[-1],-0.04,12)   # endpoints exact
        self.assertAlmostEqual(dx[6],0.05,12);self.assertAlmostEqual(dy[6],-0.02,12)   # frame 46 = half way (ease symmetry)
        steps=[b-a for a,b in zip(dx,dx[1:])];self.assertTrue(all(s>0 for s in steps),'monotonic')
        for a,b in zip(steps,reversed(steps)):self.assertAlmostEqual(a,b,12)   # symmetric ease in / out
        self.assertLess(steps[0],steps[5]);self.assertLess(max(abs(b-a) for a,b in zip(steps,steps[1:])),0.3*max(steps),'smooth')
        for f in list(range(0,40))+list(range(53,70)):self.assertEqual(out['frames'][f],lm['frames'][f],f'frame {f} is untouched')
        single=meshedit.apply(lm,{'keys':{'30':{'dx':0.05,'dy':0,'scale':1,'rot':0}}},ASPECT)
        self.assertEqual([f for f in range(70) if single['frames'][f]!=lm['frames'][f]],[30],'a single key affects only its frame')
    def test_off_range_and_input_untouched(self):
        lm=landmarks();before=json.dumps(lm)
        out=meshedit.apply(lm,{'off':[[5,7]],'expr':{'10':{'jaw':1}}},ASPECT)
        self.assertEqual([f['frame'] for f in out['frames'] if not f['faces']],[5,6,7,20,21])
        self.assertEqual({f['frame']:f['status'] for f in out['frames'] if f.get('edited')=='off'},{5:'off',6:'off',7:'off'})
        self.assertEqual([f['frame'] for f in out['frames'] if f.get('edited') is True],[10]);self.assertEqual(json.dumps(lm),before,'apply never changes its input')
        sec=meshedit.edited_section(lm,{'off':[[5,7]],'keys':{'2':{'dx':.1}},'expr':{'10':{'jaw':1}}},out)
        self.assertEqual((sec['off_frames'],sec['keyed_frames'],sec['transformed_frames'],sec['expression_frames']),([5,6,7],[2],[2],[10]))
    def test_track_hooks_count_summary_change(self):
        t=editlayer.TRACKS['mesh'];self.assertIsInstance(t,meshedit.MeshTrack)
        value={'off':[[50,52]],'keys':{'40':{'dx':.01},'52':{'dx':.02}},'expr':{str(f):{'jaw':.5} for f in range(70,81)}}
        self.assertEqual(t.count(value),4,'one off range + two keys + one expression run')
        self.assertEqual(t.summary(value),['mesh off on frames 50–52','2 transform keys (frames 40, 52)','jaw on frames 70–80'])
        self.assertEqual((t.count({}),t.count(None),t.summary({})),(0,0,[]))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(editlayer.EditError) as e:t.change(value,Path(d),Path(d))
            self.assertIn('no face mesh',str(e.exception));self.assertTrue(e.exception.fix)
            (Path(d)/'face-landmarks.json').write_text('{}');stage,tool,params=t.change(value,Path(d),Path(d))
            self.assertEqual((stage,tool,params['base_run']),('face','mesh_edit',Path(d).name));self.assertNotEqual(params['layer_sha'],t.change({**value,'off':[[50,53]]},Path(d),Path(d))[2]['layer_sha'])

# ---------------------------------------------------------------- the local renderer

class Renderer(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name)
        write_clip(self.d/'base.mp4',[depth_composite(i) for i in range(N)]);self.base=frames_of(self.d/'base.mp4');self.lm=landmarks()
    def tearDown(self):self.tmp.cleanup()
    def face_box(self,i):
        pts=np.array([[p['x']*W,p['y']*H] for p in self.lm['frames'][min(i,19)]['faces'][0]]);x0,y0=pts.min(0).astype(int);x1,y1=pts.max(0).astype(int)+1;return max(0,x0),max(0,y0),min(W,x1),min(H,y1)
    def diff(self,a,b,i):x0,y0,x1,y1=self.face_box(i);return float(np.abs(a[y0:y1,x0:x1]-b[y0:y1,x0:x1]).mean())
    def test_off_frames_equal_the_base_clip_and_jaw_changes_pixels(self):
        with NoNetwork() as net:
            out=self.d/'a';out.mkdir();info=meshedit.render(out,meshedit.apply(self.lm,{'off':[[5,7]]},ASPECT),self.d/'base.mp4')
            edited=self.d/'b';edited.mkdir();meshedit.render(edited,meshedit.apply(self.lm,{'off':[[5,7]],'expr':{'10':{'jaw':1.0}}},ASPECT),self.d/'base.mp4')
        self.assertEqual(net.hits,[]);self.assertEqual((info['frames'],info['drawn'],info['preview_frame']),(N,N-5,0))
        got=frames_of(out/'composite-silent.mp4');self.assertEqual(len(got),N);self.assertTrue((out/'preview.jpg').exists())
        diffs=[big(got[i],self.base[i]) for i in range(N)]
        plain=[i for i in range(N) if diffs[i]==0];self.assertEqual(plain,[5,6,7,20,21],diffs)   # off frames + the two lost frames: the base clip only (codec noise aside)
        self.assertGreater(min(diffs[i] for i in range(N) if i not in plain),500,'every other frame carries the mesh')
        jaw=frames_of(edited/'composite-silent.mp4')
        self.assertGreater(big(jaw[10],got[10]),50,'the jaw slider changes the drawn pixels on its frame');self.assertEqual([i for i in range(N) if big(jaw[i],got[i])>50],[10])
    def test_drawing_matches_mesh_worker_colours_and_dimming(self):
        from PIL import Image
        bright=Image.new('RGB',(W,H));dim=Image.new('RGB',(W,H));pts=[(x,y) for x,y in FACE]
        meshedit.draw_face(bright,pts,'tracked');meshedit.draw_face(dim,pts,'filled')
        colours=lambda im:{c for _,c in im.getcolors(1<<16)}
        self.assertTrue({(50,170,205),(255,135,100),(130,255,150)}<=colours(bright));self.assertTrue({(22,76,92),(114,60,45),(58,114,67)}<=colours(dim))
    def test_missing_base_clip_is_plain(self):
        with self.assertRaises(ValueError) as e:meshedit.render(self.d,self.lm,self.d/'nope.mp4')
        self.assertIn('composite stage',str(e.exception))

# ---------------------------------------------------------------- routes, save, branches, zero calls

class Routes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=self.tmp.name;self.runs=Path(self.d)/'runs'
        self.patch_runs=patch.object(application,'RUNS',self.runs);self.patch_runs.start()
        self.patch_log=patch.object(stages.calls,'GLOBAL_LOG',Path(self.d)/'calls.log');self.patch_log.start()
        self.client=TestClient(application.app);self.parent=mesh_parent(self.d);application.jobs.pop(HEX,None);self.before=tree_hashes(self.parent)
    def tearDown(self):
        self.patch_runs.stop();self.patch_log.stop();self.tmp.cleanup()
    def layer(self,ident=HEX):return self.client.get(f'/jobs/{ident}/edits').json()
    def commit(self,track,label,fn,ident=HEX):
        body=self.layer(ident);value=fn(json.loads(json.dumps(body['layer'][track] or {})))
        r=self.client.put(f'/jobs/{ident}/edits',json={'rev':body['rev'],'label':label,'track':track,'value':value});self.assertEqual(r.status_code,200,r.text);return r.json()
    def fakes(self):
        """The heavy steps a child re-runs, faked: composite writes a real depth composite (so mesh_edit can draw on it), the
        prepared clip is a stub; the MediaPipe worker must never run for mesh edits."""
        from test_regression import FakeSteps,fake_face_root
        steps=FakeSteps();src=self.parent/'depth-composite-silent.mp4'
        def composite(original,depth,seg,directory,audio_source=None):
            steps.calls.append(('composite',Path(seg).name));shutil.copyfile(src,Path(directory)/'composite-silent.mp4')
            for n in ('mask.mp4','composite.mp4'):(Path(directory)/n).write_bytes(b'cutout:'+n.encode())
            return N
        def worker(*a,**k):raise AssertionError('the MediaPipe worker must not run for mesh edits')
        return steps,[patch('pipeline.composite',side_effect=composite),patch('audio_workflow.prepare_seedance_video',side_effect=steps.prepare_seedance_video),patch('face_mesh.mesh_worker',side_effect=worker),patch('face_mesh.ROOT',fake_face_root(self.d))]
    def save(self,ident=HEX):
        steps,patches=self.fakes()
        for p in patches:p.start()
        try:
            with NoNetwork() as net:
                r=self.client.post(f'/jobs/{ident}/edits/save');self.assertEqual(r.status_code,200,r.text);job=wait(r.json()['id'])
        finally:
            for p in patches:p.stop()
        self.assertEqual(net.hits,[],'zero external calls');self.assertEqual(job['state'],'done',job)
        return job,self.runs/job['id'],steps
    def test_parent_is_a_mediapipe_mesh_run(self):
        run=json.loads((self.parent/'run.json').read_text());self.assertEqual((run['chain']['composite']['tool'],run['chain']['face']['tool']),('depth_cutout','mediapipe_mesh'))
    def test_undo_redo_across_mask_and_mesh_edits(self):
        self.commit('mask','Add + point on frame 4',lambda v:{**v,'points':[{'id':'p1','frame':4,'x':.3,'y':.5,'label':1}],'strokes':[],'applied':[]})
        self.commit('mesh','Mesh off on frames 5–7',lambda v:{**v,'off':[[5,7]]})
        body=self.commit('mesh','Move the mesh on frame 10',lambda v:{**v,'keys':{'10':{'dx':.02,'dy':0,'scale':1,'rot':0}}})
        self.assertEqual(body['pending'],{'mask':1,'mesh':2,'words':0,'total':3});self.assertIn('face: mesh off on frames 5–7, 1 transform key (frame 10)',body['summary'])
        r=self.client.post(f'/jobs/{HEX}/edits/undo').json();self.assertEqual(r['layer']['mesh'],{'off':[[5,7]]});self.assertEqual(r['redo_label'],'Move the mesh on frame 10')
        r=self.client.post(f'/jobs/{HEX}/edits/undo').json();self.assertEqual(r['layer']['mesh'],{});self.assertEqual(len(r['layer']['mask']['points']),1)
        r=self.client.post(f'/jobs/{HEX}/edits/undo').json();self.assertEqual(r['layer']['mask'],{});self.assertFalse(r['can_undo'])
        for _ in range(3):r=self.client.post(f'/jobs/{HEX}/edits/redo').json()
        self.assertEqual(r['layer']['mesh']['keys']['10']['dx'],.02);self.assertEqual(r['pending']['total'],3);self.assertFalse(r['can_redo'])
        self.assertEqual(tree_hashes(self.parent),self.before)
    def test_mesh_only_save_is_one_child_at_face(self):
        self.commit('mesh','Mesh off on frames 5–7',lambda v:{**v,'off':[[5,7]]})
        self.commit('mesh','Move the mesh on frame 8',lambda v:{**v,'keys':{'8':{'dx':.03,'dy':.01,'scale':1.1,'rot':5}}})
        self.commit('mesh','Jaw open on frames 10–12',lambda v:{**v,'expr':{str(f):{'jaw':1.0} for f in (10,11,12)}})
        runs_before=runs_in(self.runs);job,child,steps=self.save()
        self.assertEqual(len(runs_in(self.runs)),len(runs_before)+1,'exactly one child');self.assertEqual(tree_hashes(self.parent),self.before,'parent sha256-identical')
        self.assertEqual(job['changed'],'face: mesh off on frames 5–7, 1 transform key (frame 8), jaw on frames 10–12')
        run=json.loads((child/'run.json').read_text());face=run['chain']['face'];self.assertEqual((face['tool'],face['params']['base_run']),('mesh_edit',HEX));self.assertEqual(run['edits']['stage'],'face')
        self.assertEqual(steps.names(),['prepare_seedance_video'],'only the face stage and the prepared clip re-run; no composite, no worker')
        report=json.loads((child/'stages/face/report.json').read_text());self.assertEqual((report['state'],report['tool'],report['cost_usd']),('done','mesh_edit',0))
        self.assertTrue(report['health'].startswith('Face mesh from the timeline edits (mesh off on frames 5–7'),report['health'])
        self.assertEqual(set(report['inputs']),{'original.mp4','depth-composite-silent.mp4','edit-layer/mesh.json','edit-layer/face-landmarks-base.json'})
        lm=json.loads((child/'face-landmarks.json').read_text());self.assertEqual([f['frame'] for f in lm['frames'] if not f['faces']],[5,6,7,20,21])
        self.assertEqual(json.loads((child/'edit-layer/face-landmarks-base.json').read_text()),json.loads((self.parent/'face-landmarks.json').read_text()))
        tracking=json.loads((child/'face-tracking.json').read_text());self.assertEqual((tracking['edited']['off_frames'],tracking['edited']['keyed_frames'],tracking['edited']['expression_frames']),([5,6,7],[8],[10,11,12]))
        self.assertEqual(tracking['tracked'],json.loads((self.parent/'face-tracking.json').read_text())['tracked'],'base numbers kept')
        got=frames_of(child/'composite-silent.mp4');base=frames_of(self.parent/'depth-composite-silent.mp4');parent=frames_of(self.parent/'composite-silent.mp4')
        same=[i for i in range(N) if not big(got[i],base[i])];self.assertEqual(same,[5,6,7,20,21],'depth composite only on exactly the off (and lost) frames')
        changed=[i for i in range(N) if big(got[i],parent[i])>50];self.assertEqual(changed,[5,6,7,8,10,11,12],'only the edited frames differ from the parent')
        self.assertTrue((child/'preview.jpg').exists());self.assertTrue((child/'seedance-input.mp4').exists());self.assertFalse((child/'calls.jsonl').exists())
        self.assertEqual((child/'depth-composite-silent.mp4').stat().st_ino,(self.parent/'depth-composite-silent.mp4').stat().st_ino,'the base clip is linked, not rebuilt')
        record=json.loads((child/'edit-layer.json').read_text());self.assertEqual(record['layer']['mesh']['off'],[[5,7]])
        # a branch elsewhere that re-runs the face stage keeps the edits: same inputs, same key, same landmarks
        steps2,patches=self.fakes()
        for p in patches:p.start()
        try:
            with NoNetwork():
                r=self.client.post(f'/jobs/{child.name}/branch',json={'stage':'face'});self.assertEqual(r.status_code,200,r.text);g=wait(r.json()['id'])
                r=self.client.post(f'/jobs/{child.name}/branch',json={'stage':'composite'});self.assertEqual(r.status_code,200,r.text);g2=wait(r.json()['id'])
        finally:
            for p in patches:p.stop()
        for job2 in (g,g2):
            self.assertEqual(job2['state'],'done',job2);grand=self.runs/job2['id']
            self.assertEqual(json.loads((grand/'face-landmarks.json').read_text()),lm);self.assertEqual(json.loads((grand/'run.json').read_text())['chain']['face']['tool'],'mesh_edit')
        self.assertEqual(json.loads((self.runs/g['id']/'stages/face/report.json').read_text())['key'],report['key'],'same inputs, tool and params → same cache key')
        self.assertEqual(tree_hashes(self.parent),self.before)
    def test_mask_and_mesh_session_is_one_child_at_mask_with_also_face(self):
        x0,y0,x1,y1=square_box(12)
        self.commit('mask','Add + point on frame 12',lambda v:{'points':[{'id':'p1','frame':12,'x':round((x0+x1)/2/W,4),'y':round((y0+y1)/2/H,4),'label':1}],'strokes':[],'applied':[]})
        with NoNetwork():r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'quick'});self.assertEqual(r.status_code,200,r.text)
        self.commit('mesh','Mesh off on frames 2–4',lambda v:{**v,'off':[[2,4]]})
        self.commit('mesh','Brow up on frame 9',lambda v:{**v,'expr':{'9':{'brow':1.0}}})
        runs_before=runs_in(self.runs);job,child,steps=self.save()
        self.assertEqual(len(runs_in(self.runs)),len(runs_before)+1,'exactly one child');self.assertEqual(tree_hashes(self.parent),self.before)
        run=json.loads((child/'run.json').read_text())
        self.assertEqual((run['edits']['stage'],run['chain']['mask']['tool'],run['chain']['face']['tool']),('mask','edit_layer','mesh_edit'))
        self.assertIn('face: mediapipe_mesh',run['edits']['chain_changed']);self.assertTrue(job['changed'].startswith('mask: 1 click on frame 12 applied'));self.assertIn(' · face: mesh off on frames 2–4, brow on frame 9',job['changed'])
        self.assertEqual(steps.names(),['composite','prepare_seedance_video'])
        lm=json.loads((child/'face-landmarks.json').read_text());self.assertEqual([f['frame'] for f in lm['frames'] if f.get('edited')],[2,3,4,9])
        got=frames_of(child/'composite-silent.mp4');base=frames_of(child/'depth-composite-silent.mp4')
        self.assertEqual([i for i in range(N) if not big(got[i],base[i])],[2,3,4,20,21])
        self.assertTrue((child/'edit-layer/mask').is_dir());self.assertTrue((child/'edit-layer/mesh.json').exists())
    def test_resaving_from_an_edited_child_never_writes_through_links(self):
        self.commit('mesh','Mesh off on frame 5',lambda v:{**v,'off':[[5,5]]})
        _,child,_=self.save();child_before=tree_hashes(child)
        self.commit('mesh','Move the mesh on frame 9',lambda v:{**v,'keys':{'9':{'dx':.02,'dy':0,'scale':1,'rot':0}}},ident=child.name)
        _,grand,_=self.save(child.name)
        self.assertEqual(tree_hashes(child),child_before,'the edited child is never written by a later save')
        self.assertEqual(json.loads((grand/'edit-layer/mesh.json').read_text())['layer']['keys'],{'9':{'dx':.02,'dy':0.0,'scale':1.0,'rot':0.0}})
        lm=json.loads((grand/'face-landmarks.json').read_text());self.assertEqual([f['frame'] for f in lm['frames'] if not f['faces']],[5,20,21],'off from the first save stays, the new key applies on top')
    def test_registry_and_static_files(self):
        tools=[t.name for t in stages.tools_for('face')];self.assertEqual(tools[0],'mediapipe_mesh');self.assertIn('mesh_edit',tools);self.assertFalse(stages.get_tool('face','mesh_edit').paid)
        self.assertEqual(stages.chain_for_mode('depth_mesh')['face']['tool'],'mediapipe_mesh')
        for name in ('track-face.js','meshedit.js','face-connections.json'):
            r=self.client.get('/static/'+name);self.assertEqual(r.status_code,200,name)
        conn=self.client.get('/static/face-connections.json').json();self.assertEqual({k:len(conn[k]) for k in ('tessellation','lips','left_eye','right_eye')},{'tessellation':2556,'lips':40,'left_eye':16,'right_eye':16})
        self.assertIn("import './track-face.js'",(ROOT/'static'/'tracks.js').read_text())
    def test_save_without_landmarks_is_plain(self):
        (self.parent/'face-landmarks.json').rename(self.parent/'face-landmarks.moved');self.before=tree_hashes(self.parent)
        self.commit('mesh','Mesh off on frame 5',lambda v:{**v,'off':[[5,5]]})
        r=self.client.post(f'/jobs/{HEX}/edits/save');self.assertEqual(r.status_code,400);self.assertIn('no face mesh',r.json()['message']);self.assertTrue(r.json()['fix'])

if __name__=='__main__':unittest.main()
