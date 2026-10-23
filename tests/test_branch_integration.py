"""Branching proof on a real run, offline, zero Replicate calls.

Hard-links `runs/85e5dbe64df1464fa63825319ebfa104` (Advanced + Face mesh, done) to a new 32-hex id, rebuilds its
run.json with the legacy migration helper, then branches it at the face stage through `POST /jobs/{id}/branch`
with PUPPETEER_OFFLINE=1. The MediaPipe worker in `.venv-face` is local and free, so this really runs. Skipped
when the worker or the fixture run is missing. The folders it creates under runs/ are removed at the end.
"""
import unittest,json,os,time,shutil,uuid,hashlib
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as application
import stages
from stages.runner import link_artifact

ROOT=Path(__file__).resolve().parents[1];RUNS=ROOT/'runs';FIXTURE=RUNS/'85e5dbe64df1464fa63825319ebfa104';WORKER=ROOT/'.venv-face/bin/python'

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()
def hashes(folder):return {p.relative_to(folder).as_posix():sha(p) for p in Path(folder).rglob('*') if p.is_file()}

@unittest.skipUnless(WORKER.exists() and (FIXTURE/'face-tracking.json').exists() and (FIXTURE/'depth-composite-silent.mp4').exists(),'needs .venv-face and the 85e5dbe6 fixture run')
class RealBranchTests(unittest.TestCase):
    created=[]
    @classmethod
    def tearDownClass(cls):
        for folder in cls.created:shutil.rmtree(folder,ignore_errors=True)
    def wait(self,ident):
        for _ in range(1200):
            if application.jobs[ident]['state']!='running':return application.jobs[ident]
            time.sleep(.1)
        self.fail('branch did not finish')
    def test_face_branch_reruns_only_face_offline(self):
        fixture_before=hashes(FIXTURE)
        copy=RUNS/uuid.uuid4().hex;copy.mkdir();self.created.append(copy)
        for p in FIXTURE.rglob('*'):
            if p.is_file():
                target=copy/p.relative_to(FIXTURE);target.parent.mkdir(parents=True,exist_ok=True)
                (shutil.copy2 if p.name in ('status.json','mask-review.json','log.txt') else link_artifact)(p,target)   # a copy must never write into the fixture
        run,reports=stages.reconstruct(copy,with_keys=True,write=True)   # the retroactive run.json for a legacy run
        self.assertEqual(run['mode'],'depth_mesh');self.assertEqual(run['chain']['face'],{'tool':'mediapipe_mesh','params':{'strict':False,'pad':1.8,'max_gap':6},'key':run['chain']['face']['key'],'cached_from':None})
        self.assertEqual(reports['face']['frames'],{'covered':163,'filled':13,'missing':19});self.assertIn('terms matched: person, hands',reports['mask']['health'])
        copy_before={k:v for k,v in hashes(copy).items() if not k.startswith('stages/') and k!='run.json'}
        client=TestClient(application.app)
        with patch.dict(os.environ,{'PUPPETEER_OFFLINE':'1'}),patch('requests.post',side_effect=AssertionError('Replicate call attempted')),patch('raw_masks.requests.post',side_effect=AssertionError('Replicate call attempted')),patch('pipeline.requests.post',side_effect=AssertionError('Replicate call attempted')):
            # 1. parameter change on the mesh tool: the worker really runs
            r=client.post(f'/jobs/{copy.name}/branch',json={'stage':'face','tool':'mediapipe_mesh','params':{'strict':False,'pad':2.0}});self.assertEqual(r.status_code,200,r.text)
            child=RUNS/r.json()['id'];self.created.append(child);job=self.wait(child.name);self.assertEqual(job['state'],'done',job)
            # 2. the strict rule on this clip (two long gaps): the stage fails with a plain sentence, still offline, still no calls
            r=client.post(f'/jobs/{copy.name}/branch',data={'stage':'face','params':json.dumps({'strict':True})});self.assertEqual(r.status_code,200,r.text)
            strict=RUNS/r.json()['id'];self.created.append(strict);strict_job=self.wait(strict.name)
            # 3. face off
            r=client.post(f'/jobs/{copy.name}/branch',json={'stage':'face','tool':'off'});self.assertEqual(r.status_code,200,r.text)
            off=RUNS/r.json()['id'];self.created.append(off);off_job=self.wait(off.name);self.assertEqual(off_job['state'],'done',off_job)
        crun=json.loads((child/'run.json').read_text())
        self.assertEqual(crun['parent'],copy.name);self.assertEqual(crun['changed'],'face: mediapipe_mesh pad: 1.8 → 2.0');self.assertEqual(crun['mode'],'depth_mesh');self.assertEqual(crun['cost_usd_total'],0)
        self.assertEqual(json.loads((child/'status.json').read_text())['state'],'done')
        for name in ['composite-silent.mp4','seedance-input.mp4','face-tracking.json','face-landmarks.json','preview.jpg']:
            self.assertTrue((child/name).exists(),name);self.assertNotEqual((child/name).stat().st_ino,(copy/name).stat().st_ino,name+' must be a new file')
        self.assertEqual(json.loads((child/'face-tracking.json').read_text())['crop'],'face-first, padded 2.0x, smoothed; full-frame re-detection when lost')
        for name in ['upload.mp4','original.mp4','depth-raw.mp4','depth.mp4','mask.mp4','composite.mp4','depth-composite-silent.mp4','sam-report.json','sam-attempts.json','clean-masks/mask_00000.png']:
            self.assertEqual((child/name).stat().st_ino,(copy/name).stat().st_ino,name+' must be hard-linked');self.assertEqual(sha(child/name),sha(copy/name))
        for stage in ['input_doctor','audio','depth','mask','composite']:
            self.assertEqual(json.loads((child/'stages'/stage/'report.json').read_text())['cached_from'],copy.name,stage)
        face=json.loads((child/'stages/face/report.json').read_text());self.assertEqual(face['state'],'done');self.assertEqual(face['params']['pad'],2.0);self.assertEqual(face['frames']['covered']+face['frames']['filled']+face['frames']['missing'],195)
        self.assertIn('face: running mediapipe_mesh',(child/'log.txt').read_text())
        for folder in (child,strict,off):self.assertFalse((folder/'calls.jsonl').exists(),'zero external calls')
        self.assertFalse((copy/'calls.jsonl').exists())
        # the strict branch: an error state with plain words and a fix, numbers still written, nothing paid
        self.assertEqual(strict_job['state'],'error',strict_job);self.assertIn('lost face',strict_job['status']);self.assertNotIn('Traceback',strict_job['status']);self.assertTrue(strict_job.get('fix'))
        srun=json.loads((strict/'run.json').read_text());self.assertEqual(srun['changed'],'face: mediapipe_mesh strict: false → true');self.assertEqual(srun['state'],'error');self.assertIn('lost face',srun['error']['message'])
        self.assertTrue((strict/'face-tracking.json').exists());self.assertEqual(json.loads((strict/'stages/face/report.json').read_text())['state'],'error');self.assertIn('Traceback',(strict/'log.txt').read_text())
        # the off branch: the depth cutout becomes the composite again, no mesh files
        self.assertEqual(sha(off/'composite-silent.mp4'),sha(copy/'depth-composite-silent.mp4'));self.assertFalse((off/'face-tracking.json').exists());self.assertTrue((off/'seedance-input.mp4').exists())
        self.assertEqual(json.loads((off/'run.json').read_text())['mode'],'depth');self.assertEqual(json.loads((off/'workflow-mode.json').read_text()),{'mode':'depth'})
        # the parent copy and the original fixture are byte-for-byte unchanged
        copy_after={k:v for k,v in hashes(copy).items() if not k.startswith('stages/') and k!='run.json'};self.assertEqual(copy_after,copy_before)
        self.assertEqual(hashes(FIXTURE),fixture_before)
        tree=client.get('/jobs/tree').json()['runs'];node=next(n for n in tree if n['id']==copy.name)
        self.assertEqual({c['id'] for c in node['children']},{child.name,strict.name,off.name});self.assertEqual(next(c for c in node['children'] if c['id']==child.name)['changed'],crun['changed'])
        info=client.get(f'/jobs/{child.name}/run').json();self.assertFalse(info['migrated']);self.assertEqual(info['calls'],[]);self.assertEqual(info['run']['cost_usd_total'],0)

if __name__=='__main__':unittest.main()
