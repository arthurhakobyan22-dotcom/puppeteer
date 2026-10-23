"""Mask track of the edit layer: pending clicks preview without propagating, one Apply = one propagation pass and one
log line, quick vs full, builds on the previous result, undo, problem ticks, Grab hands on flagged frames only, save
as one child through the `edit_layer` tool, paid tools gated and offline.

Synthetic clip from test_mask_wand (a bright square moving over a dark background, 24 frames, depth near on the
square). Everything is offline and free; the hands worker is mocked.
"""
import unittest,tempfile,json,os,time,sys
from pathlib import Path
from unittest.mock import patch,Mock
import numpy as np
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parent))
import app as application
import stages
from stages import wand,masktrack,editlayer
from test_mask_wand import synthetic_run,square_box,square_mask,masks_of,tree_hashes,wait,EndpointTests,HEX,W,H,N

def runs_in(root):return sorted(p.name for p in Path(root).iterdir() if p.is_dir() and len(p.name)==32)
def click(i,label=1,dx=0.0):
    x0,y0,x1,y1=square_box(i);return {'id':f'p{i}-{label}-{dx}','frame':i,'x':round((x0+x1)/2/W+dx,4),'y':round((y0+y1)/2/H,4),'label':label}
def log_lines(runs,ident=HEX):
    path=Path(runs)/'_sessions'/ident/'log.txt';return path.read_text().splitlines() if path.exists() else []

class Base(unittest.TestCase):
    mask_of=None
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=self.tmp.name;self.runs=Path(self.d)/'runs'
        self.patch_runs=patch.object(application,'RUNS',self.runs);self.patch_runs.start()
        self.patch_log=patch.object(stages.calls,'GLOBAL_LOG',Path(self.d)/'calls.log');self.patch_log.start()
        self.client=TestClient(application.app);self.parent=self.prepared();application.jobs.pop(HEX,None);self.before=tree_hashes(self.parent)
    def tearDown(self):
        self.patch_runs.stop();self.patch_log.stop();self.tmp.cleanup()
    def prepared(self):
        folder=EndpointTests.prepared_parent(None,self.d)
        if self.mask_of is not None:
            for i in range(N):wand.write_mask(self.mask_of(i),folder/'clean-masks'/f'mask_{i:05d}.png')
        return folder
    def layer(self):return self.client.get(f'/jobs/{HEX}/edits').json()
    def commit(self,label,fn):
        body=self.layer();value=body['layer']['mask'] or {};value=fn(json.loads(json.dumps(value)))
        r=self.client.put(f'/jobs/{HEX}/edits',json={'rev':body['rev'],'label':label,'track':'mask','value':value});self.assertEqual(r.status_code,200,r.text);return r.json()
    def add_point(self,p):return self.commit(f'Add point on frame {p["frame"]}',lambda v:{**v,'points':(v.get('points') or [])+[p]})
    def result_masks(self,key):return [wand.read_mask(self.runs/'_sessions'/HEX/'mask'/'results'/key,i,(H,W)) for i in range(N)]

class EmptyMaskParent(Base):
    mask_of=staticmethod(lambda i:np.zeros((H,W),bool))
    def test_five_points_preview_without_propagation_then_one_apply_one_log_line(self):
        runs_before=runs_in(self.runs)
        with patch.object(wand,'local_propagate',wraps=wand.local_propagate) as lp,patch.object(wand,'propagate',wraps=wand.propagate) as pr:
            points=[click(4),click(4,dx=0.02),click(12),click(12,dx=-0.02),click(20)]
            for p in points:
                self.add_point(p);t0=time.time()
                r=self.client.post(f'/jobs/{HEX}/edits/mask/preview',json={'frame':p['frame']});elapsed=time.time()-t0
                self.assertEqual(r.status_code,200,r.text);body=r.json();self.assertLess(elapsed,2.0,'a preview shows within ~2 s')
                self.assertTrue(body['url'].startswith(f'/runs/_sessions/{HEX}/mask/previews/'),body['url'])
                png=self.runs/body['url'][len('/runs/'):];self.assertTrue(png.exists());self.assertEqual(png.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
                self.assertEqual(body['points_on_frame'],sum(1 for q in points[:points.index(p)+1] if q['frame']==p['frame']));self.assertGreater(body['selections'][0]['fraction'],0.02)
            self.assertEqual((lp.call_count,pr.call_count),(0,0),'no propagation before Apply')
            self.assertEqual(runs_in(self.runs),runs_before,'no branch before Apply');self.assertFalse([l for l in log_lines(self.runs) if 'propagation' in l])
            self.assertEqual(len([l for l in log_lines(self.runs) if 'mask preview' in l]),5)
            self.assertEqual(self.layer()['summary'],['mask: 5 clicks on frames 4–20 not applied'])
            r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'quick'});self.assertEqual(r.status_code,200,r.text);body=r.json()
            self.assertEqual(lp.call_count,1,'one Apply = one propagation pass over the whole list');self.assertEqual(len(lp.call_args.args[1]),5);self.assertEqual(lp.call_args.kwargs['work_side'],240)
        lines=[l for l in log_lines(self.runs) if 'propagation' in l];self.assertEqual(len(lines),1,lines)
        self.assertRegex(lines[0],r'mask propagation: 5 points on 3 frames, quick, local_propagate → \d+ frames changed')
        mask=body['layer']['mask'];self.assertEqual((mask['points'],mask['strokes'],len(mask['applied'])),([],[],1));entry=mask['applied'][0]
        self.assertEqual((entry['kind'],entry['tool'],entry['quality'],len(entry['points']),entry['base']),('fix','local_propagate','quick',5,None))
        result=self.runs/'_sessions'/HEX/'mask'/'results'/entry['result'];self.assertEqual(len(list(result.glob('mask_*.png'))),N);self.assertTrue((result/'mask.mp4').exists())
        self.assertEqual(body['apply']['video'],f'/runs/_sessions/{HEX}/mask/results/{entry["result"]}/mask.mp4');self.assertEqual(wand.frame_shape(result/'mask.mp4')[2],N)
        got=self.result_masks(entry['result']);self.assertTrue(all((got[i]&square_mask(i)).sum()>0.7*square_mask(i).sum() for i in range(N)))
        self.assertEqual(runs_in(self.runs),runs_before);self.assertEqual(tree_hashes(self.parent),self.before,'the parent is never written')
        self.assertEqual(self.layer()['summary'],['mask: 5 clicks on frames 4–20 applied, quick quality'])
    def test_quick_then_full_builds_on_previous_and_undo_restores(self):
        self.add_point(click(12))
        with patch.object(wand,'local_propagate',wraps=wand.local_propagate) as lp:
            quick=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'quick'}).json();q=quick['layer']['mask']['applied'][0]
            full=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'full','replace':q['id']});self.assertEqual(full.status_code,200,full.text);full=full.json()
            self.assertEqual([c.kwargs['work_side'] for c in lp.call_args_list],[240,480])
        applied=full['layer']['mask']['applied'];self.assertEqual(len(applied),1,'accept replaces the quick entry');f=applied[0]
        self.assertEqual((f['quality'],f['base']),('full',None));self.assertNotEqual(f['result'],q['result'])
        self.assertEqual(len([l for l in log_lines(self.runs) if 'propagation' in l]),2);self.assertIn('accept at full quality',log_lines(self.runs)[-1])
        # a brush stroke applied next builds on the full result: the square stays, the stroke is added
        stroke={'id':'s1','frame_from':2,'frame_to':5,'mode':'paint','points':[[0.1,0.9],[0.3,0.9]],'radius':0.04}
        self.commit('Brush',lambda v:{**v,'strokes':[stroke]})
        with patch.object(wand,'local_propagate',wraps=wand.local_propagate) as lp:
            r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'full'});self.assertEqual(r.status_code,200,r.text);self.assertEqual(lp.call_count,0,'strokes alone need no propagation')
        second=r.json()['layer']['mask']['applied'][1];self.assertEqual(second['base'],f['result']);self.assertIn('mask brush: 1 brush stroke on frames 2–5',log_lines(self.runs)[-1])
        before,after=self.result_masks(f['result']),self.result_masks(second['result'])
        self.assertTrue(after[3][int(0.9*H),int(0.2*W)]);self.assertFalse(before[3][int(0.9*H),int(0.2*W)]);self.assertTrue(np.array_equal(after[12],before[12]))
        self.assertEqual(self.client.get(f'/jobs/{HEX}/mask/problems').json()['result'],second['result'])
        # undo: back to the full result (still on disk), redo: forward again; nothing recomputed
        u=self.client.post(f'/jobs/{HEX}/edits/undo').json();self.assertEqual([a['result'] for a in u['layer']['mask']['applied']],[f['result']]);self.assertEqual(u['layer']['mask']['strokes'],[stroke])
        self.assertEqual(self.client.get(f'/jobs/{HEX}/mask/problems').json()['result'],f['result'])
        u=self.client.post(f'/jobs/{HEX}/edits/undo').json();self.assertEqual(u['layer']['mask']['strokes'],[]);self.assertEqual(u['layer']['mask']['applied'][0]['result'],f['result'])
        u=self.client.post(f'/jobs/{HEX}/edits/undo').json();self.assertEqual(u['layer']['mask']['applied'][0]['quality'],'quick');self.assertEqual(u['layer']['mask']['applied'][0]['result'],q['result'])
        for _ in range(2):r=self.client.post(f'/jobs/{HEX}/edits/redo').json()
        self.assertEqual(r['layer']['mask']['applied'][0]['result'],f['result']);self.assertEqual(r['layer']['mask']['strokes'],[stroke])
        # re-applying the same fixes on the same base reuses the stored result
        with patch.object(wand,'local_propagate',wraps=wand.local_propagate) as lp:
            r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'full'}).json();self.assertEqual(lp.call_count,0);self.assertTrue(r['apply']['reused']);self.assertEqual(r['apply']['result'],second['result'])
        self.assertEqual(tree_hashes(self.parent),self.before)
    def test_apply_errors_are_plain(self):
        r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={});self.assertEqual(r.status_code,400);self.assertIn('no mask fixes',r.json()['message']);self.assertTrue(r.json()['fix'])
        self.add_point(click(3))
        for bad,expect in [({'tool':'laser'},'Unknown mask tool'),({'replace':'nope'},'latest applied fix'),({'rev':99},'another tab')]:
            r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json=bad);self.assertIn(r.status_code,(400,409),bad);self.assertIn(expect,r.json()['message']);self.assertTrue(r.json()['fix'])
        r=self.client.post(f'/jobs/{HEX}/edits/mask/preview',json={'frame':3,'points':[{'frame':3,'x':4,'y':0}]});self.assertEqual(r.status_code,400);self.assertIn('fix',r.json())

class PaidAndOffline(Base):
    def test_paid_tool_quick_is_free_full_is_gated_and_offline_sends_nothing(self):
        self.add_point(click(5));self.add_point(click(9,label=0))
        r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'full','tool':'sam3_points_fal','estimate_only':True}).json()
        self.assertGreater(r['estimated_cost_usd'],0);self.assertEqual(r['tool'],'sam3_points_fal')
        r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'full','tool':'sam3_points_fal'});self.assertEqual(r.status_code,402);self.assertIn('costs about $',r.json()['message']);self.assertIn('confirm_cost=true',r.json()['fix'])
        boom=Mock(side_effect=AssertionError('network call attempted'))
        with patch.dict(os.environ,{'PUPPETEER_OFFLINE':'1'}),patch('requests.post',boom),patch('requests.get',boom),patch('raw_masks.requests.post',boom),patch('fal_client.upload_file',boom),patch('fal_client.submit',boom):
            for tool in ('sam3_points_fal','sam2_points_replicate'):
                r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'full','tool':tool,'confirm_cost':'true'});self.assertEqual(r.status_code,400,r.text)
                self.assertIn('switched off in offline mode',r.json()['message']);self.assertIn('PUPPETEER_OFFLINE',r.json()['fix']);self.assertNotIn('Traceback',r.text)
        sdir=self.runs/'_sessions'/HEX;self.assertFalse((sdir/'calls.jsonl').exists());self.assertFalse((self.parent/'calls.jsonl').exists());boom.assert_not_called()
        self.assertEqual(len(self.layer()['layer']['mask']['points']),2,'nothing applied, nothing dropped')
        # quick with a paid tool = the free local algorithm, remembered for the accept click
        r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'quick','tool':'sam3_points_fal'});self.assertEqual(r.status_code,200,r.text);entry=r.json()['layer']['mask']['applied'][0]
        self.assertEqual((entry['tool'],entry['intended_tool'],entry['quality']),('local_propagate','sam3_points_fal','quick'))
        r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'full','replace':entry['id']});self.assertEqual(r.status_code,402,'accept of a paid quick preview carries the estimate')
        self.assertEqual(tree_hashes(self.parent),self.before)
    def test_paid_call_while_editing_is_logged_in_the_session_not_the_run(self):
        self.add_point(click(5));boom=Mock(side_effect=AssertionError('network call attempted'))
        with patch('fal_client.upload_file',boom),patch('fal_client.submit',boom),patch('config.credential',return_value='k'),patch('config.load_env'):
            r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'full','tool':'sam3_points_fal','confirm_cost':'true'})
        self.assertEqual(r.status_code,500);self.assertTrue(r.json()['fix']);self.assertNotIn('AssertionError',r.json()['message'])
        calls=stages.read_calls(self.runs/'_sessions'/HEX);self.assertEqual(len(calls),1);self.assertEqual((calls[0]['provider'],calls[0]['endpoint']),('fal','fal-ai/sam-3/video-rle'));self.assertGreater(calls[0]['cost_usd'],0)
        self.assertFalse((self.parent/'calls.jsonl').exists());self.assertFalse((self.runs/'_sessions'/HEX/'mask'/'work'/'calls.jsonl').exists())
        self.assertEqual(tree_hashes(self.parent),self.before)

class ProblemTicks(unittest.TestCase):
    def test_jump_and_vanishing_part(self):
        n=40;h,w=96,160;smalls=[];areas=[]
        for i in range(n):
            m=np.zeros((h,w),bool);m[20:80,40:90]=True            # the body
            if 20<=i<24:m[20:80,40:60]=False                       # the body shrinks on 20–23: a drop at 20, a rise at 24
            if not 10<=i<14:m[40:48,120:128]=True                  # a separate small part (a hand) missing on 10–13
            areas.append(int(m.sum())*16);smalls.append(m)
        found,flagged,median=masktrack.find_problems(areas,smalls)
        kinds={(p['frame'],p['kind']):p for p in found}
        self.assertIn((10,'limb'),kinds);self.assertEqual(kinds[(10,'limb')]['span'],[10,13]);self.assertIn('missing on frames 10–13',kinds[(10,'limb')]['note'])
        self.assertEqual(kinds[(20,'jump')]['span'],[20,23]);self.assertEqual(kinds[(24,'jump')]['span'],[24,24]);self.assertNotIn((10,'jump'),kinds,'a small part is below the area threshold')
        self.assertEqual(flagged,[10,11,12,13,20,21,22,23,24])
        rise=[a+(20000 if i>=30 else 0) for i,a in enumerate(areas)];found=masktrack.find_problems(rise,smalls)[0]   # a part that appears at 30: the frames just before are flagged
        self.assertEqual(next(p for p in found if p['frame']==30)['span'],[30-masktrack.JUMP_EDGE,30])
        # a part touching the edge that leaves is not a problem
        edge=[m.copy() for m in smalls]
        for i in range(n):
            edge[i][:,150:]=False
            if i<30:edge[i][0:10,150:160]=True
        self.assertFalse([p for p in masktrack.find_problems(areas,edge)[0] if p['kind']=='limb' and p['frame']==30])
    def test_endpoint_reads_the_report_or_the_masks_and_writes_nothing(self):
        def mask_of(i):
            m=square_mask(i)
            return m if not 8<=i<12 else np.zeros((H,W),bool)
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)/'runs'):
            parent=EndpointTests.prepared_parent(None,d);client=TestClient(application.app)
            for i in range(N):wand.write_mask(mask_of(i),parent/'clean-masks'/f'mask_{i:05d}.png')
            before=tree_hashes(parent);masktrack._problem_cache.clear()
            body=client.get(f'/jobs/{HEX}/mask/problems').json();self.assertEqual(body['source'],'masks');self.assertEqual(len(body['areas']),N)
            self.assertEqual([(p['frame'],p['kind']) for p in body['frames']],[(8,'jump'),(12,'jump')]);self.assertEqual(body['flagged'],[8,9,10,11,12])
            (parent/'mask-cleanup-report.json').write_text(json.dumps([{'frame':f'mask_{i:05d}','mask_pixels':int(mask_of(i).sum())} for i in range(N)]));before=tree_hashes(parent)
            os.utime(parent/'clean-masks');masktrack._problem_cache.clear()
            body=client.get(f'/jobs/{HEX}/mask/problems').json();self.assertEqual(body['source'],'report');self.assertEqual(body['flagged'],[8,9,10,11,12])
            self.assertEqual(tree_hashes(parent),before);self.assertFalse((Path(d)/'runs'/'_sessions').exists(),'a GET creates no session')

class GrabHands(Base):
    mask_of=staticmethod(lambda i:square_mask(i) if not 8<=i<12 else np.zeros((H,W),bool))   # the "hand" (square) drops out on 8–11
    def test_only_flagged_frames_change(self):
        flagged=self.client.get(f'/jobs/{HEX}/mask/problems').json()['flagged'];self.assertEqual(flagged,[8,9,10,11,12])
        def landmarks(folder,frames,sdir):   # the worker finds the square on every frame it is asked about (and more, to prove the merge filters)
            out={}
            for i in range(N):
                x0,y0,x1,y1=square_box(i);out[i]=[[(x/W,y/H) for x,y in [(x0+6,y0+6),(x1-6,y0+6),(x1-6,y1-6),(x0+6,y1-6),((x0+x1)/2,(y0+y1)/2)]]]
            return out
        self.add_point(click(3,label=0))   # a pending click stays pending: hands go in before manual clicks
        with patch.object(masktrack,'hand_landmarks',side_effect=landmarks) as worker:
            r=self.client.post(f'/jobs/{HEX}/edits/mask/hands',json={'source':'problems'});self.assertEqual(r.status_code,200,r.text);body=r.json()
        self.assertEqual(worker.call_args.args[1],flagged)
        hands=body['hands'];self.assertTrue(set(hands['changed'])<=set(flagged));self.assertEqual(set(hands['changed']),{8,9,10,11})
        base=masks_of(self.parent);after=self.result_masks(hands['result'])
        for i in range(N):
            if i in flagged:continue
            self.assertTrue(np.array_equal(after[i],base[i]),f'frame {i} must not change')
        for i in (8,9,10,11):self.assertGreater((after[i]&square_mask(i)).sum(),0.8*square_mask(i).sum(),i)
        mask=body['layer']['mask'];self.assertEqual(len(mask['points']),1);self.assertEqual(mask['applied'][0]['kind'],'hands')
        self.assertRegex(log_lines(self.runs)[-1],r'grab hands: 5 flagged frames \(problems\), mediapipe_hands → hands on 5 frames, 4 frames changed')
        # the next Apply builds on the hands result
        r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'quick'}).json();self.assertEqual(r['layer']['mask']['applied'][1]['base'],hands['result'])
        # a range works too; an empty selection is a plain error
        r=self.client.post(f'/jobs/{HEX}/edits/mask/hands',json={'source':'range'});self.assertEqual(r.status_code,400);self.assertIn('Select a range',r.json()['message'])
        self.assertEqual(tree_hashes(self.parent),self.before)
    def test_missing_setup_is_plain(self):
        with patch.object(masktrack,'ROOT',Path(self.d)):
            r=self.client.post(f'/jobs/{HEX}/edits/mask/hands',json={'source':'range','from':2,'to':4});self.assertEqual(r.status_code,400);self.assertIn('setup-face-mesh.sh',r.json()['fix'])

class SaveAsOneChild(Base):
    mask_of=staticmethod(lambda i:np.zeros((H,W),bool))
    def test_save_refuses_unapplied_then_one_child_uses_the_session_mask(self):
        from test_regression import FakeSteps,fake_face_root
        self.add_point(click(12));r=self.client.post(f'/jobs/{HEX}/edits/mask/apply',json={'quality':'full'}).json();key=r['apply']['result']
        self.add_point(click(20,label=0))
        r=self.client.post(f'/jobs/{HEX}/edits/save');self.assertEqual(r.status_code,400);self.assertEqual(r.json()['track'],'mask')
        self.assertIn('1 mask click is not applied yet. Apply them to the clip first, or remove them.',r.json()['message']);self.assertIn('Save without them',r.json()['fix'])
        self.commit('Drop unapplied',lambda v:{**v,'points':[]})
        runs_before=runs_in(self.runs);steps=FakeSteps()
        patches=[patch('pipeline.composite',side_effect=steps.composite),patch('audio_workflow.prepare_seedance_video',side_effect=steps.prepare_seedance_video),patch('face_mesh.ROOT',fake_face_root(self.d))]
        for p in patches:p.start()
        try:
            with patch.dict(os.environ,{'PUPPETEER_OFFLINE':'1'}):
                r=self.client.post(f'/jobs/{HEX}/edits/save');self.assertEqual(r.status_code,200,r.text);job=wait(r.json()['id'])
        finally:
            for p in patches:p.stop()
        self.assertEqual(job['state'],'done',job);self.assertEqual(len(runs_in(self.runs)),len(runs_before)+1,'exactly one child');child=self.runs/job['id']
        self.assertEqual(job['changed'],'mask: 1 click on frame 12 applied')
        run=json.loads((child/'run.json').read_text());self.assertEqual(run['chain']['mask']['tool'],'edit_layer');self.assertEqual(run['chain']['mask']['params']['base_run'],HEX);self.assertEqual(run['chain']['mask']['params']['result'],key)
        session_result=[wand.read_mask(self.runs/'_sessions'/HEX/f'saved-{child.name}'/'mask'/'results'/key,i,(H,W)) for i in range(N)]
        self.assertTrue(all(np.array_equal(a,b) for a,b in zip(masks_of(child),session_result)),'the child\'s clean-masks are the session result')
        self.assertTrue(all(np.array_equal(a,b) for a,b in zip(masks_of(child,'raw-masks'),session_result)))
        self.assertEqual(steps.names(),['composite','prepare_seedance_video']);self.assertEqual(steps.first('composite')[3],'clean-masks')
        report=json.loads((child/'sam-report.json').read_text());self.assertEqual(report['wand']['tool'],'edit_layer');self.assertIn('timeline edits',report['method'])
        self.assertTrue(json.loads((child/'stages/mask/report.json').read_text())['health'].startswith('Mask from the timeline edits (1 click on frame 12 applied)'))
        self.assertEqual(json.loads((child/'mask-edits.json').read_text())['history'][-1]['tool'],'edit_layer')
        self.assertIn('mask propagation: 1 point on 1 frame, full, local_propagate',(child/'log.txt').read_text())
        self.assertEqual(json.loads((child/'stages/depth/report.json').read_text())['cached_from'],HEX);self.assertEqual((child/'depth.mp4').stat().st_ino,(self.parent/'depth.mp4').stat().st_ino)
        self.assertEqual(tree_hashes(self.parent),self.before,'parent sha256-identical');self.assertFalse((child/'calls.jsonl').exists())

class Registry(unittest.TestCase):
    def test_edit_layer_tool_is_free_and_not_the_default(self):
        tools=[t.name for t in stages.tools_for('mask')];self.assertEqual(tools[0],'sam3_replicate');self.assertIn('edit_layer',tools)
        self.assertFalse(stages.get_tool('mask','edit_layer').paid);self.assertEqual(stages.chain_for_mode('depth')['mask']['tool'],'sam3_replicate')
        self.assertIsInstance(editlayer.TRACKS['mask'],masktrack.MaskTrack)
    def test_track_module_is_served(self):
        r=TestClient(application.app).get('/static/track-mask.js');self.assertEqual(r.status_code,200);self.assertIn('javascript',r.headers['content-type'])

if __name__=='__main__':unittest.main()
