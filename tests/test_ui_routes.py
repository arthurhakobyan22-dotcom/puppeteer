"""UI-facing backend bits added by the Foundation UI work (Agent 2).

- POST /jobs with `preset` + `char1` / `char2`: the references are saved next to the upload as char1-reference.<ext>.
- GET/POST /compare/picks: A/B picks persist in runs/_compare/picks.json and the folder never shows up in GET /jobs.
- POST /estimate: cost of preparing with a preset / mode before anything is uploaded.
- GET /jobs/{id}/mask-review wording while the job runs, after it failed, and when the files are ready.
- GET /jobs/{id}/run carries the clip length and the draft / completion estimates for the cost meter.
- The static app (index.html, app.js, app.css) is served.
"""
import unittest,tempfile,json,time
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as application,mask_review,stages

HEX='c'*32
PNG=b'\x89PNG\r\n\x1a\n'+b'\x00'*32

def prepared(root,ident=HEX,mode='face_mesh'):
    p=Path(root)/ident;p.mkdir()
    names=['original.mp4','face-landmarks.json','composite-silent.mp4','seedance-input.mp4']
    (p/'workflow-mode.json').write_text(json.dumps({'mode':mode}))
    for n in names:(p/n).write_bytes(b'artifact:'+n.encode())
    (p/'upload.mp4').write_bytes(b'upload')
    return p

class PresetJobTests(unittest.TestCase):
    def test_preset_with_references_saves_them_like_the_seedance_route(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)),patch.object(stages,'run_chain') as run_chain:
            client=TestClient(application.app)
            files={'video':('clip.mp4',b'video','video/mp4'),'char1':('hero.png',PNG,'image/png'),'char2':('friend.jpg',PNG,'image/jpeg')}
            r=client.post('/jobs',data={'preset':'Talking head','confirm_cost':'true'},files=files)
            self.assertEqual(r.status_code,200,r.text);body=r.json()
            self.assertEqual(body['preset'],'Talking head');self.assertEqual(body['estimated_cost_usd'],0);self.assertIn(body['state'],('running','done'))   # the mocked chain may finish before the response is read
            folder=Path(d)/body['id']
            for _ in range(100):
                if application.jobs[body['id']]['state']!='running':break
                time.sleep(.02)
            self.assertTrue((folder/'char1-reference.png').exists());self.assertTrue((folder/'char2-reference.jpg').exists())
            self.assertEqual((folder/'char1-reference.png').read_bytes(),PNG);self.assertTrue((folder/'upload.mp4').exists())
            run_chain.assert_called_once();self.assertEqual(run_chain.call_args.kwargs.get('preset'),'Talking head')
    def test_bad_reference_type_is_refused_and_nothing_is_kept(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)),patch.object(stages,'run_chain'):
            client=TestClient(application.app)
            r=client.post('/jobs',data={'preset':'Talking head','confirm_cost':'true'},files={'video':('clip.mp4',b'video','video/mp4'),'char1':('notes.txt',b'x','text/plain')})
            self.assertEqual(r.status_code,400);self.assertIn('image',r.json()['detail'])
            self.assertEqual([f for f in Path(d).iterdir() if f.is_dir()],[])
    def test_references_are_optional(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)),patch.object(stages,'run_chain'):
            client=TestClient(application.app)
            r=client.post('/jobs',data={'preset':'Talking head','confirm_cost':'true'},files={'video':('clip.mp4',b'video','video/mp4')})
            self.assertEqual(r.status_code,200,r.text)
            folder=Path(d)/r.json()['id']
            for _ in range(100):
                if application.jobs[r.json()['id']]['state']!='running':break
                time.sleep(.02)
            self.assertEqual(list(folder.glob('char*-reference.*')),[])

class EstimateTests(unittest.TestCase):
    def test_preset_and_mode_estimates(self):
        client=TestClient(application.app)
        free=client.post('/estimate',json={'preset':'Talking head','seconds':8}).json()
        self.assertTrue(free['free']);self.assertEqual(free['estimated_cost_usd'],0);self.assertEqual(free['mode'],'face_mesh');self.assertEqual(free['paid'],[])
        paid=client.post('/estimate',data={'preset':'Full body','seconds':'8.1','prompt':'person, hands'}).json()
        self.assertFalse(paid['free']);self.assertGreater(paid['estimated_cost_usd'],0);self.assertEqual([p['stage'] for p in paid['paid']],['depth','mask'])
        one_term=client.post('/estimate',data={'preset':'Full body','seconds':'8.1','prompt':'person'}).json()
        self.assertLess(one_term['estimated_cost_usd'],paid['estimated_cost_usd'])   # two SAM terms cost more than one
        mode=client.post('/estimate',json={'mode':'depth_mesh','seconds':10,'clean_dialogue':True}).json()
        self.assertEqual(mode['mode'],'depth_mesh');self.assertIn('audio',[p['stage'] for p in mode['paid']])
        r=client.post('/estimate',json={});self.assertEqual(r.status_code,400);self.assertIn('fix',r.json())
        r=client.post('/estimate',json={'preset':'nope'});self.assertEqual(r.status_code,400);self.assertIn('fix',r.json())

class ComparePickTests(unittest.TestCase):
    def test_picks_persist_and_the_folder_is_not_a_run(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            a=prepared(d,'a'*32);b=prepared(d,'b'*32);client=TestClient(application.app)
            self.assertEqual(client.get('/compare/picks').json(),{'picks':[]})
            r=client.post('/compare/picks',json={'runs':['b'*32,'a'*32],'stage':'seedance-input.mp4','picked':'b'*32,'note':'B keeps the hands'})
            self.assertEqual(r.status_code,200,r.text);pick=r.json()['pick']
            self.assertEqual(pick['comparison_id'],'a'*32+','+'b'*32+':seedance-input.mp4');self.assertEqual(pick['picked'],'b'*32);self.assertEqual(pick['note'],'B keeps the hands');self.assertIn('time',pick)
            saved=json.loads((Path(d)/'_compare'/'picks.json').read_text())['picks'];self.assertEqual(len(saved),1)
            # picking again replaces the pick for the same comparison; a different stage is a new comparison
            client.post('/compare/picks',data={'runs':'a'*32+','+'b'*32,'stage':'seedance-input.mp4','picked':'a'*32})
            client.post('/compare/picks',data={'runs':'a'*32+','+'b'*32,'stage':'depth.mp4','picked':'b'*32})
            picks=client.get('/compare/picks').json()['picks'];self.assertEqual(len(picks),2)
            self.assertEqual(client.get('/compare/picks?comparison_id='+'a'*32+','+'b'*32+':seedance-input.mp4').json()['picks'][0]['picked'],'a'*32)
            # the _compare folder is never listed as a run
            self.assertEqual({r['id'] for r in client.get('/jobs').json()['runs']},{'a'*32,'b'*32})
            self.assertEqual({r['id'] for r in client.get('/jobs/tree').json()['runs']},{'a'*32,'b'*32})
            # plain errors with a fix
            for bad in [{'runs':['a'*32],'stage':'x','picked':'a'*32},{'runs':['a'*32,'b'*32],'stage':'','picked':'a'*32},{'runs':['a'*32,'b'*32],'stage':'x','picked':'c'*32}]:
                r=client.post('/compare/picks',json=bad);self.assertEqual(r.status_code,400);self.assertIn('fix',r.json())

class ReviewWordingTests(unittest.TestCase):
    def test_preparing_failed_and_ready(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)),patch.dict(application.jobs,{},clear=False):
            p=prepared(d);(p/'seedance-input.mp4').unlink();client=TestClient(application.app)
            application.jobs[HEX]={'id':HEX,'state':'running','status':'Tracking face mesh locally'}
            review=client.get(f'/jobs/{HEX}/mask-review').json()
            self.assertEqual(review['status'],'preparing');self.assertFalse(review['approved']);self.assertIn('Preparing',review['note']);self.assertIn('Tracking face mesh',review['note'])
            application.jobs[HEX]={'id':HEX,'state':'error','status':'Face mesh worker failed: lost face 0.42–0.71 s','fix':'Use the Expressive preset.'}
            review=client.get(f'/jobs/{HEX}/mask-review').json()
            self.assertEqual(review['status'],'failed');self.assertIn('Preparation failed: Face mesh worker failed',review['note']);self.assertEqual(review['fix'],'Use the Expressive preset.')
            del application.jobs[HEX];(p/'status.json').write_text(json.dumps({'id':HEX,'state':'error','status':'Face mesh worker failed: lost face'}))
            review=client.get(f'/jobs/{HEX}/mask-review').json();self.assertEqual(review['status'],'failed');self.assertTrue(review['fix'])   # saved status, app restarted
            (p/'status.json').write_text(json.dumps({'id':HEX,'state':'done','status':'done'}))
            review=client.get(f'/jobs/{HEX}/mask-review').json();self.assertEqual(review['status'],'unavailable');self.assertTrue(review['fix'])
            (p/'seedance-input.mp4').write_bytes(b'ready')
            review=client.get(f'/jobs/{HEX}/mask-review').json();self.assertEqual(review['status'],'pending');self.assertTrue(review['fingerprint'])
            self.assertEqual(mask_review.state(p)['status'],'pending')   # the old one-argument call still works
    def test_run_info_carries_estimates_for_the_cost_meter(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            prepared(d);client=TestClient(application.app);info=client.get(f'/jobs/{HEX}/run').json()
            self.assertIn('seconds',info);self.assertEqual(set(info['estimates']['draft']),{'fal','enhancor','wan'});self.assertEqual(set(info['estimates']['complete']),{'fal','enhancor','wan'})
            self.assertGreater(info['estimates']['complete']['fal'],info['estimates']['draft']['fal'])

class StaticTests(unittest.TestCase):
    def test_app_files_are_served(self):
        client=TestClient(application.app)
        index=client.get('/');self.assertEqual(index.status_code,200);self.assertIn('/static/app.js',index.text);self.assertIn('/static/app.css',index.text)
        for name in ['tpl-start','tpl-ws-head','tpl-stage-card','tpl-edit','tpl-editor','tpl-world','tpl-generate','tpl-export','tpl-compare','tpl-runs']:self.assertIn(name,index.text)
        js=client.get('/static/app.js');self.assertEqual(js.status_code,200);self.assertIn('javascript',js.headers['content-type'])
        css=client.get('/static/app.css');self.assertEqual(css.status_code,200);self.assertIn('text/css',css.headers['content-type'])
        for module in ['api','ui','state','jobdata','edit','generate','world','stagecard','workspace','start','drawer','compare','runs','theme']:self.assertEqual(client.get(f'/static/{module}.js').status_code,200,module)
        for sheet in ['tokens','components','app']:self.assertEqual(client.get(f'/static/{sheet}.css').status_code,200,sheet)
        self.assertNotIn('<script>',index.text)   # markup only: no inline script or style (the theme boot is /static/theme.js)
        self.assertNotIn('<style>',index.text)

if __name__=='__main__':unittest.main()
