"""Run names (tidy pass, the one approved backend addition): PUT /jobs/{id}/name writes `name` into run.json, the Runs
list and tree carry it, the export README prints it next to the run id."""
import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as application,stages
from stages import export as X

HEX='d'*32

def run_with_record(root,ident=HEX):
    folder=Path(root)/ident;folder.mkdir()
    (folder/'upload.mp4').write_bytes(b'upload');(folder/'original.mp4').write_bytes(b'original')
    (folder/'workflow-mode.json').write_text(json.dumps({'mode':'face_mesh'}))
    chain=stages.chain_for_mode('face_mesh','person','replicate',False)
    stages.save_run(folder,stages.runner.new_run(folder,chain,'face_mesh',preset='Talking head'))
    (folder/'status.json').write_text(json.dumps({'id':ident,'state':'done','status':'done'}))
    return folder

class RunNameTests(unittest.TestCase):
    def test_rename_trims_caps_and_shows_up_in_the_listings(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            folder=run_with_record(d);client=TestClient(application.app)
            self.assertIsNone(client.get('/jobs').json()['runs'][0]['name'])
            r=client.put(f'/jobs/{HEX}/name',json={'name':'  Kitchen   monologue · take 2  '})
            self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['name'],'Kitchen monologue · take 2');self.assertEqual(r.json()['id'],HEX)
            self.assertEqual(json.loads((folder/'run.json').read_text())['name'],'Kitchen monologue · take 2')
            self.assertEqual(client.get('/jobs').json()['runs'][0]['name'],'Kitchen monologue · take 2')
            self.assertEqual(client.get('/jobs/tree').json()['runs'][0]['name'],'Kitchen monologue · take 2')
            self.assertEqual(client.get(f'/jobs/{HEX}/run').json()['run']['name'],'Kitchen monologue · take 2')
            # a form body works too; 80 characters at most
            r=client.put(f'/jobs/{HEX}/name',data={'name':'x'*120});self.assertEqual(len(r.json()['name']),80)
    def test_empty_name_clears_it(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            folder=run_with_record(d);client=TestClient(application.app)
            client.put(f'/jobs/{HEX}/name',json={'name':'Porch'})
            r=client.put(f'/jobs/{HEX}/name',json={'name':'   '});self.assertEqual(r.status_code,200);self.assertIsNone(r.json()['name'])
            self.assertNotIn('name',json.loads((folder/'run.json').read_text()))
            r=client.put(f'/jobs/{HEX}/name',json={});self.assertEqual(r.status_code,200);self.assertIsNone(r.json()['name'])
    def test_unknown_run_is_404_and_a_legacy_run_is_refused_plainly(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            client=TestClient(application.app)
            self.assertEqual(client.put('/jobs/'+'f'*32+'/name',json={'name':'x'}).status_code,404)
            self.assertEqual(client.put('/jobs/not-a-run/name',json={'name':'x'}).status_code,404)
            legacy=Path(d)/('a'*32);legacy.mkdir();(legacy/'upload.mp4').write_bytes(b'u')   # no run.json
            r=client.put('/jobs/'+'a'*32+'/name',json={'name':'x'});self.assertEqual(r.status_code,400);self.assertIn('fix',r.json())
            self.assertFalse((legacy/'run.json').exists())

class ReadmeNameTests(unittest.TestCase):
    def ctx(self,**kw):
        return {'name':'seedance-web-1','preset_label':'Seedance web','created':'2026-10-24','run':HEX,'exported_run':HEX,'requested_run':HEX,
                'clip':{'frames':12,'fps':24.0,'width':320,'height':192,'seconds':0.5},'mode':'face_mesh','run_preset':'Talking head','edits_line':'none',
                'why':['because'],'files':[{'file':'composite.mp4','what':'The clip.'}],'warnings':[],**kw}
    def test_readme_prints_the_name_next_to_the_run_id(self):
        text=X.readme_text(self.ctx(run_name='Kitchen monologue · take 2'))
        self.assertIn(f'Run: {HEX} · "Kitchen monologue · take 2"',text)
        self.assertNotIn('"',X.readme_text(self.ctx(run_name=None)).split('\n')[2])   # no name: the line is the plain id

if __name__=='__main__':unittest.main()
