"""Edit layer: session store, undo/redo, save as exactly one branch, `branch(also=)`, CARRY, parent never written.

Runs are made through the rack with every heavy step faked (`test_stages.fake_run`); the child runs with the same
fakes. Test tracks replace the mask / mesh hooks for a test so a save can change real stages (composite, face, mask).
"""
import unittest,tempfile,json,os,time,hashlib,sys,importlib.util,subprocess,copy
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_regression import FakeSteps,fake_face_root
from test_stages import fake_run,HEX
import app as application
import stages
from stages import editlayer,branch as branching

ROOT=Path(__file__).resolve().parents[1]
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()
def tree_hashes(folder):return {p.relative_to(folder).as_posix():sha(p) for p in Path(folder).rglob('*') if p.is_file()}
def runs_in(root):return sorted(p.name for p in Path(root).iterdir() if p.is_dir() and len(p.name)==32)
def wait(ident):
    for _ in range(400):
        if application.jobs[ident]['state']!='running':return application.jobs[ident]
        time.sleep(.05)
    return application.jobs[ident]

class StageTrack(editlayer.Track):
    """A test track whose value {n, stage, tool, params} asks for one stage change."""
    def __init__(self,label):self.label=label;self.empty={};self.materialized=[]
    def count(self,value):return int((value or {}).get('n') or 0)
    def summary(self,value):return [f'{self.count(value)} test edits']
    def change(self,value,parent,session_dir):
        v=value or {}
        return (v['stage'],v.get('tool'),{**(v.get('params') or {}),'layer_sha':editlayer.layer_sha(v),'base_run':Path(parent).name}) if v.get('stage') else None
    def materialize(self,value,child,session_dir,parent):
        self.materialized.append(Path(child).name);(Path(child)/'edit-layer').mkdir(exist_ok=True);(Path(child)/'edit-layer'/f'{self.label}.json').write_text(json.dumps(value))

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=self.tmp.name;self.runs=Path(self.d)/'runs'
        self.patch_runs=patch.object(application,'RUNS',self.runs);self.patch_runs.start()
        self.tracks=dict(editlayer.TRACKS);self.client=TestClient(application.app)
        self.parent,_=fake_run(self.d,'depth_mesh');application.jobs.pop(HEX,None)
    def tearDown(self):
        editlayer.TRACKS.clear();editlayer.TRACKS.update(self.tracks);self.patch_runs.stop();self.tmp.cleanup()
    def put(self,rev,label,track,value,**kw):
        return self.client.put(f'/jobs/{HEX}/edits',json={'rev':rev,'label':label,'track':track,'value':value,**kw})
    def run_fakes(self):
        steps=FakeSteps();patches=steps.patches(fake_face_root(self.d))
        for p in patches:p.start()
        return steps,patches

class SessionStoreTests(Base):
    def test_note_never_resurrects_a_saved_or_absent_session(self):
        # review nit: a preview arriving right after a save must not start a stray session log a later save would copy
        sdir=self.runs/'_sessions'/HEX
        self.assertFalse(editlayer.note(self.runs,HEX,'preview before any edit'));self.assertFalse(sdir.exists())
        self.assertEqual(self.put(0,'Edit','words',{'words':[],'singing':False}).status_code,200)
        self.assertTrue(editlayer.note(self.runs,HEX,'mask preview: 1 point'));self.assertIn('mask preview',(sdir/'log.txt').read_text())
        (sdir/'saved-x').mkdir();os.replace(sdir/'session.json',sdir/'saved-x'/'session.json');os.replace(sdir/'log.txt',sdir/'saved-x'/'log.txt')   # what save() leaves behind
        self.assertFalse(editlayer.note(self.runs,HEX,'late preview'));self.assertFalse((sdir/'log.txt').exists())
    def test_get_writes_nothing_put_rev_and_conflict(self):
        before=tree_hashes(self.parent)
        r=self.client.get(f'/jobs/{HEX}/edits');self.assertEqual(r.status_code,200);body=r.json()
        self.assertEqual((body['rev'],body['layer'],body['can_undo'],body['can_redo'],body['pending']['total'],body['stale']),(0,{'mask':{},'mesh':{},'words':None},False,False,0,False))
        self.assertFalse((self.runs/'_sessions').exists(),'a GET must not create a session')
        self.assertEqual(self.client.get('/jobs/'+'f'*32+'/edits').status_code,404)
        words={'words':[{'id':'w1','text':'hello','start':0.0,'end':0.4}],'singing':False}
        r=self.put(0,'Edit word "hello"','words',words);self.assertEqual(r.status_code,200,r.text);body=r.json()
        self.assertEqual((body['rev'],body['pending']['words'],body['pending']['total'],body['undo_label'],body['can_redo']),(1,1,1,'Edit word "hello"',False))
        self.assertEqual(body['summary'],['words: transcript of 1 word edited'])
        session=json.loads((self.runs/'_sessions'/HEX/'session.json').read_text());self.assertEqual(session['run'],HEX);self.assertTrue(session['base_fingerprint'])
        r=self.put(0,'Stale tab','words',None);self.assertEqual(r.status_code,409);self.assertEqual(r.json()['rev'],1);self.assertTrue(r.json()['fix'])
        self.assertEqual(self.client.get(f'/jobs/{HEX}/edits').json()['layer']['words'],words)
        r=self.client.put(f'/jobs/{HEX}/edits',json={'rev':1,'label':'whole layer','layer':{'mask':{},'mesh':{},'words':None}});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['rev'],2)
        r=self.client.put(f'/jobs/{HEX}/edits',data={'rev':'2','label':'form body','track':'words','value':json.dumps(words)});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['layer']['words'],words)
        for bad in [{'rev':3,'track':'laser','value':1},{'rev':3,'layer':[1]},{'label':'no rev','track':'words','value':None},{'rev':3,'layer':{'laser':{}}}]:
            r=self.client.put(f'/jobs/{HEX}/edits',json=bad);self.assertEqual(r.status_code,400,bad);self.assertTrue(r.json()['fix'])
        self.assertEqual(tree_hashes(self.parent),before,'nothing is written inside the run folder');self.assertFalse(list(self.parent.rglob('session.json')))
    def test_undo_redo_across_tracks_and_cap(self):
        editlayer.register_track('mesh',StageTrack('face'))
        self.assertEqual(self.put(0,'mesh 1','mesh',{'n':1}).status_code,200)
        self.assertEqual(self.put(1,'words 1','words',{'words':[{'id':'a','text':'hi','start':0,'end':.2}]}).status_code,200)
        self.assertEqual(self.put(2,'mesh 2','mesh',{'n':2}).status_code,200)
        r=self.client.post(f'/jobs/{HEX}/edits/undo').json();self.assertEqual((r['layer']['mesh'],r['redo_label'],r['undo_label'],r['rev']),({'n':1},'mesh 2','words 1',4))
        r=self.client.post(f'/jobs/{HEX}/edits/undo').json();self.assertIsNone(r['layer']['words']);self.assertEqual(r['layer']['mesh'],{'n':1})   # Cmd+Z undoes the words edit next, whatever track
        r=self.client.post(f'/jobs/{HEX}/edits/redo').json();self.assertEqual(r['layer']['words']['words'][0]['text'],'hi');self.assertEqual(r['redo_label'],'mesh 2')
        r=self.client.post(f'/jobs/{HEX}/edits/redo').json();self.assertEqual(r['layer']['mesh'],{'n':2});self.assertFalse(r['can_redo'])
        r=self.client.post(f'/jobs/{HEX}/edits/redo');self.assertEqual(r.status_code,400);self.assertIn('nothing to redo',r.json()['message'])
        self.assertEqual(self.client.post(f'/jobs/{HEX}/edits/undo',json={'rev':1}).status_code,409)
        self.client.post(f'/jobs/{HEX}/edits/undo');r=self.put(8,'new branch of history','mesh',{'n':5}).json();self.assertFalse(r['can_redo'])   # a new edit clears redo
        rev=r['rev']
        for i in range(editlayer.UNDO_CAP+15):rev=self.put(rev,f'edit {i}','mesh',{'n':i+1}).json()['rev']
        session=json.loads((self.runs/'_sessions'/HEX/'session.json').read_text());self.assertEqual(len(session['undo']),editlayer.UNDO_CAP);self.assertEqual(session['undo'][-1]['label'],f'edit {editlayer.UNDO_CAP+14}')
    def test_delete_discards_and_stale_flag(self):
        self.put(0,'w','words',{'words':[{'id':'a','text':'hi','start':0,'end':.2}]})
        self.assertFalse(self.client.get(f'/jobs/{HEX}/edits').json()['stale'])
        import mask_review
        with patch.object(mask_review,'fingerprint',return_value='changed'):self.assertTrue(self.client.get(f'/jobs/{HEX}/edits').json()['stale'])
        r=self.client.delete(f'/jobs/{HEX}/edits');self.assertEqual(r.status_code,200);self.assertEqual((r.json()['rev'],r.json()['pending']['total']),(0,0))
        self.assertFalse((self.runs/'_sessions'/HEX).exists())
        r=self.client.post(f'/jobs/{HEX}/edits/save');self.assertEqual(r.status_code,400);self.assertEqual(r.json()['message'],'There are no edits to save.')

class SaveTests(Base):
    def test_words_only_save_is_one_done_child_at_prompt(self):
        (self.parent/'words.json').write_text(json.dumps({'version':1,'engine':'mlx','language':'en','singing':False,'words':[{'text':'helo','start':0.0,'end':0.4}]}))
        (self.parent/'mouth-guidance.json').write_text('{}')
        self.assertEqual(self.put(0,'Nothing yet','words',None).status_code,200)   # notes are kept only while a session exists (review nit)
        editlayer.note(self.runs,HEX,'mask preview: 1 point on frame 4');(self.runs/'_sessions'/HEX/'calls.jsonl').write_text(json.dumps({'provider':'fal','endpoint':'x','cost_usd':0.01,'ok':True})+'\n')
        self.assertEqual(self.client.post(f'/jobs/{HEX}/edits/save').status_code,400)   # a log line alone is not an edit
        self.put(1,'Fix "helo"','words',{'words':[{'id':'w1','text':'hello','start':0.0,'end':0.4},{'id':'w2','text':'there','start':0.5,'end':0.9}],'edited':['w1','w2']})
        before=tree_hashes(self.parent);runs_before=runs_in(self.runs)
        r=self.client.post(f'/jobs/{HEX}/edits/save');self.assertEqual(r.status_code,200,r.text);body=r.json();job=wait(body['id'])
        self.assertEqual(len(runs_in(self.runs)),len(runs_before)+1,'exactly one child');child=self.runs/body['id']
        self.assertEqual((job['state'],body['parent'],body['changed'],body['estimated_cost_usd']),('done',HEX,'words: 2 words edited',0))
        self.assertEqual(job['status'],'Ready · review the prepared input and create a draft')
        words=json.loads((child/'words.json').read_text());self.assertEqual([w['text'] for w in words['words']],['hello','there']);self.assertEqual(words['engine'],'mlx')
        self.assertNotEqual((child/'words.json').stat().st_ino,(self.parent/'words.json').stat().st_ino);self.assertEqual(json.loads((self.parent/'words.json').read_text())['words'][0]['text'],'helo')
        self.assertNotEqual((child/'mouth-guidance.json').stat().st_ino,(self.parent/'mouth-guidance.json').stat().st_ino)   # CARRY links it, then the words track rewrites it for the edited words (Agent 4; fresh() first)
        self.assertEqual((self.parent/'mouth-guidance.json').read_text(),'{}');self.assertEqual([w['text'] for w in json.loads((child/'mouth-guidance.json').read_text())['words']],['hello','there'])
        for name in ['seedance-input.mp4','composite-silent.mp4','original.mp4','face-landmarks.json']:self.assertEqual((child/name).stat().st_ino,(self.parent/name).stat().st_ino,name)
        run=json.loads((child/'run.json').read_text());self.assertEqual((run['parent'],run['changed'],run['state']),(HEX,'words: 2 words edited','done'))
        record=json.loads((child/'edit-layer.json').read_text());self.assertEqual(run['edits']['layer_sha'],record['layer_sha']);self.assertEqual(run['edits']['summary'],['words: 2 words edited']);self.assertEqual(record['layer']['words']['edited'],['w1','w2'])
        self.assertEqual(record['layer_sha'],editlayer.layer_sha(record['layer']))
        self.assertIn('mask preview: 1 point on frame 4',(child/'log.txt').read_text());self.assertIn('edits saved from session',(child/'log.txt').read_text())
        self.assertEqual(json.loads((child/'calls.jsonl').read_text().splitlines()[-1])['provider'],'fal')
        self.assertFalse((child/'mask-review.json').exists());self.assertEqual(self.client.get(f'/jobs/{child.name}/mask-review').json()['status'],'pending')
        self.assertEqual(tree_hashes(self.parent),before,'the parent is sha256-identical')
        self.assertFalse((self.runs/'_sessions'/HEX/'session.json').exists());self.assertTrue((self.runs/'_sessions'/HEX/f'saved-{child.name}'/'session.json').exists())
        self.assertEqual(self.client.get(f'/jobs/{HEX}/edits').json()['rev'],0)
        self.assertEqual(self.client.post(f'/jobs/{HEX}/edits/save').status_code,400)
        listed=next(x for x in self.client.get('/jobs').json()['runs'] if x['id']==child.name);self.assertEqual(listed['changed'],'words: 2 words edited')
        self.client.put(f'/jobs/{HEX}/edits',json={'rev':0,'label':'again','track':'words','value':{'words':[]}});self.client.delete(f'/jobs/{HEX}/edits')
        self.assertTrue((self.runs/'_sessions'/HEX/f'saved-{child.name}').exists(),'discard keeps the records of earlier saves')
    def test_two_tracks_one_child_earliest_stage_with_also(self):
        mask,mesh=StageTrack('mask'),StageTrack('face');editlayer.register_track('mask',mask);editlayer.register_track('mesh',mesh)
        self.put(0,'face off','mask',{'n':2,'stage':'face','tool':'off'})   # the first-registered track asks for the LATER stage
        self.put(1,'composite original','mesh',{'n':1,'stage':'composite','tool':'original'})
        self.put(2,'a word','words',{'words':[{'id':'a','text':'hi','start':0,'end':.2}]})
        planned=editlayer.plan(self.parent,self.runs);self.assertEqual((planned['stage'],list(planned['also'])),('composite',['face']))
        before=tree_hashes(self.parent);runs_before=runs_in(self.runs);steps,patches=self.run_fakes()
        try:r=self.client.post(f'/jobs/{HEX}/edits/save',json={});self.assertEqual(r.status_code,200,r.text);job=wait(r.json()['id'])
        finally:
            for p in patches:p.stop()
        self.assertEqual(job['state'],'done',job);self.assertEqual(len(runs_in(self.runs)),len(runs_before)+1);child=self.runs/job['id']
        run=json.loads((child/'run.json').read_text());self.assertEqual((run['chain']['composite']['tool'],run['chain']['face']['tool'],run['mode']),('original','off','depth'))
        self.assertEqual(run['changed'],'mask: 2 test edits · face: 1 test edits · words: transcript of 1 word edited')
        self.assertIn('composite: depth_cutout',run['edits']['chain_changed']);self.assertIn(' · face: mediapipe_mesh',run['edits']['chain_changed'])
        self.assertEqual(steps.names(),['prepare_seedance_video'],'composite original + face off: nothing heavy re-runs');self.assertEqual(mask.materialized,[child.name]);self.assertEqual(mesh.materialized,[child.name])
        self.assertTrue((child/'edit-layer/mask.json').exists());self.assertTrue((child/'words.json').exists());self.assertEqual(sha(child/'composite-silent.mp4'),sha(self.parent/'original.mp4'))
        for stage in ['input_doctor','audio','depth','mask']:self.assertEqual(json.loads((child/'stages'/stage/'report.json').read_text())['cached_from'],HEX)
        self.assertEqual(json.loads((child/'stages/face/report.json').read_text())['state'],'off')
        self.assertEqual(tree_hashes(self.parent),before)
    def test_paid_save_needs_confirmation_and_check_refuses(self):
        mesh=StageTrack('face');editlayer.register_track('mesh',mesh)
        self.put(0,'reprompt','mesh',{'n':1,'stage':'mask','tool':'sam3_replicate','params':{'prompt':'person, hat'}})
        runs_before=runs_in(self.runs);before=tree_hashes(self.parent)
        r=self.client.post(f'/jobs/{HEX}/edits/save');self.assertEqual(r.status_code,402);self.assertGreater(r.json()['estimated_cost_usd'],0);self.assertIn('Saving these edits',r.json()['message'])
        self.assertEqual(runs_in(self.runs),runs_before);self.assertTrue((self.runs/'_sessions'/HEX/'session.json').exists())
        self.client.delete(f'/jobs/{HEX}/edits');editlayer.TRACKS.update(self.tracks)   # the real mask track (Agent 2): pending clicks refuse to save
        self.put(0,'click','mask',{'points':[{'id':'p1','frame':12,'x':.5,'y':.5,'label':1},{'id':'p2','frame':40,'x':.5,'y':.5,'label':1}]})
        r=self.client.post(f'/jobs/{HEX}/edits/save');self.assertEqual(r.status_code,400);self.assertIn('2 mask clicks are not applied yet',r.json()['message']);self.assertEqual(r.json()['track'],'mask')
        self.assertEqual(self.client.get(f'/jobs/{HEX}/edits').json()['summary'],['mask: 2 clicks on frames 12–40 not applied'])
        self.assertEqual(runs_in(self.runs),runs_before);self.assertEqual(tree_hashes(self.parent),before)

class BranchAlsoTests(unittest.TestCase):
    def test_also_changes_two_stages_in_one_child(self):
        with tempfile.TemporaryDirectory() as d:
            parent,_=fake_run(d,'depth_mesh');before=tree_hashes(parent);runs=Path(d)/'runs'
            child,chain,changed=stages.branch(parent,'composite','original',runs_root=runs,also={'face':{'tool':'off'}})
            self.assertEqual(changed,'composite: depth_cutout → original · face: mediapipe_mesh (strict: false, pad: 1.8, max_gap: 6) → off')
            self.assertEqual((chain['composite']['tool'],chain['face']['tool']),('original','off'));run=json.loads((child/'run.json').read_text());self.assertEqual(run['changed'],changed);self.assertEqual(run['mode'],'depth')
            self.assertEqual(len(runs_in(runs)),2);self.assertEqual(tree_hashes(parent),before)
            with self.assertRaises(ValueError):stages.branch(parent,'face','off',runs_root=runs,also={'mask':{'tool':'off'}})   # an also stage must come later
            with self.assertRaises(ValueError):stages.branch(parent,'face','off',runs_root=runs,also={'render':{}})
    @unittest.skipUnless(subprocess.run(['git','-C',str(ROOT),'cat-file','-e','8f6a192:stages/branch.py'],capture_output=True).returncode==0,'needs the git history')
    def test_branch_without_also_is_identical_to_before(self):
        """The branch() of commit 8f6a192 (before `also` and CARRY) and today's make the same child."""
        source=subprocess.run(['git','-C',str(ROOT),'show','8f6a192:stages/branch.py'],capture_output=True,text=True,check=True).stdout
        spec=importlib.util.spec_from_loader('stages._branch_before',loader=None);old=importlib.util.module_from_spec(spec);old.__package__='stages';exec(compile(source,'branch_before.py','exec'),old.__dict__)
        def strip(run):return {k:v for k,v in run.items() if k not in ('id','created')}
        for stage,tool,params in [('face','off',None),('face','mediapipe_mesh',{'pad':2.0}),('composite','original',None),('prompt',None,None)]:
            with tempfile.TemporaryDirectory() as d:
                parent,_=fake_run(d,'depth_mesh');runs=Path(d)/'runs'
                a,chain_a,changed_a=old.branch(parent,stage,tool,params,runs_root=runs);b,chain_b,changed_b=stages.branch(parent,stage,tool,params,runs_root=runs)
                self.assertEqual((chain_a,changed_a),(chain_b,changed_b))
                ha={k:v for k,v in tree_hashes(a).items() if k not in ('run.json','log.txt')};hb={k:v for k,v in tree_hashes(b).items() if k not in ('run.json','log.txt')}
                self.assertEqual(ha,hb,stage);self.assertEqual(strip(json.loads((a/'run.json').read_text())),strip(json.loads((b/'run.json').read_text())))
                self.assertEqual((a/'log.txt').read_text()[20:],(b/'log.txt').read_text()[20:])

class StaticEditorTests(unittest.TestCase):
    def test_editor_modules_and_template_are_served(self):
        client=TestClient(application.app);index=client.get('/').text
        for name in ['tpl-editor','data-editor','data-review-tools','data-approve']:self.assertIn(name,index)
        for module in ['editor','timeline','editlayer','tracks','track-mask','track-face','track-words']:
            r=client.get(f'/static/{module}.js');self.assertEqual(r.status_code,200,module);self.assertIn('javascript',r.headers['content-type'])

if __name__=='__main__':unittest.main()
