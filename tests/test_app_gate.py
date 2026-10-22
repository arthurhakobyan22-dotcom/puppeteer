"""HTTP-level checks of the review gate: 409 until approval, approval cleared by any artifact change, files listing."""
import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as application,mask_review,seedance_bridge

PNG=b'\x89PNG\r\n\x1a\n'+b'\x00'*32

def fixture(root,mode='depth'):
 ident='a'*32;p=Path(root)/ident;p.mkdir()
 names=list(mask_review.FILES) if mode=='depth' else ['original.mp4','face-landmarks.json','composite-silent.mp4','seedance-input.mp4']
 if mode!='depth':(p/'workflow-mode.json').write_text(json.dumps({'mode':mode}))
 if mode=='depth_mesh':names+=['depth.mp4','mask.mp4','depth-composite-silent.mp4']
 for n in names:(p/n).write_bytes(b'artifact:'+n.encode())
 (p/'upload.mp4').write_bytes(b'upload');(p/'audio-manifest.json').write_text('{"clean_dialogue": false}')
 (p/'status.json').write_text(json.dumps({'id':ident,'state':'done','status':'ready'}))
 return ident,p

class ReviewGateTests(unittest.TestCase):
 def run_mode(self,mode,tamper):
  with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
   ident,p=fixture(d,mode);client=TestClient(application.app)
   files={'char1':('ref.png',PNG,'image/png')};data={'prompt':'x','provider':'fal'}
   review=client.get(f'/jobs/{ident}/mask-review').json()
   self.assertFalse(review['approved']);self.assertEqual(review['status'],'pending')
   with patch.object(seedance_bridge,'submit') as submit:
    self.assertEqual(client.post(f'/jobs/{ident}/seedance',data=data,files=files).status_code,409);submit.assert_not_called()
   self.assertEqual(client.post(f'/jobs/{ident}/mask-review',data={'approved':'true','fingerprint':review['fingerprint'],'note':'full clip'}).status_code,200)
   self.assertTrue(client.get(f'/jobs/{ident}/mask-review').json()['approved'])
   with patch.object(seedance_bridge,'submit',return_value='req-1'),patch.object(seedance_bridge,'wait_and_finish'):
    self.assertEqual(client.post(f'/jobs/{ident}/seedance',data=data,files=files).status_code,200)
   with (p/tamper).open('ab') as f:f.write(b'x')
   after=client.get(f'/jobs/{ident}/mask-review').json()
   self.assertFalse(after['approved']);self.assertEqual(after['status'],'pending');self.assertNotEqual(after['fingerprint'],review['fingerprint'])
   with patch.object(seedance_bridge,'submit') as submit:
    self.assertEqual(client.post(f'/jobs/{ident}/seedance',data=data,files=files).status_code,409);submit.assert_not_called()
   self.assertEqual(client.post(f'/jobs/{ident}/mask-review',data={'approved':'true','fingerprint':review['fingerprint'],'note':'stale'}).status_code,409)
 def test_depth_mode_mask_change_clears_approval(self):self.run_mode('depth','mask.mp4')
 def test_depth_mode_prepared_clip_change_clears_approval(self):self.run_mode('depth','seedance-input.mp4')
 def test_face_mesh_landmark_change_clears_approval(self):self.run_mode('face_mesh','face-landmarks.json')
 def test_depth_mesh_overlay_change_clears_approval(self):self.run_mode('depth_mesh','depth-composite-silent.mp4')
 def test_runs_listing(self):
  with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
   ident,p=fixture(d,'depth');(p/'mask-review.json').write_text('{}')
   q=Path(d)/('b'*32);q.mkdir();(q/'workflow-mode.json').write_text('{"mode":"face_mesh"}');(q/'upload.mp4').write_bytes(b'u')
   (q/'status.json').write_text(json.dumps({'id':'b'*32,'state':'error','status':'Face mesh worker failed: lost face 1.0–2.0 s'}))
   r=Path(d)/('c'*32);r.mkdir();(r/'face-tracking.json').write_text('{}');(r/'upload.mp4').write_bytes(b'u')   # failed before workflow-mode.json existed
   (Path(d)/'notarun').mkdir();client=TestClient(application.app)
   runs=client.get('/jobs').json()['runs'];self.assertEqual({r['id'] for r in runs},{ident,'b'*32,'c'*32})
   legacy=next(r for r in runs if r['id']=='c'*32);self.assertEqual((legacy['mode'],legacy['state']),('face_mesh','unknown'))
   depth=next(r for r in runs if r['id']==ident);mesh=next(r for r in runs if r['id']=='b'*32)
   self.assertEqual((depth['mode'],depth['state'],depth['reviewed']),('depth','done',True))
   self.assertEqual((mesh['mode'],mesh['state']),('face_mesh','error'));self.assertIn('lost face',mesh['status']);self.assertRegex(mesh['created'],r'^\d{4}-\d{2}-\d{2}T')
   self.assertEqual([r['id'] for r in runs],sorted([r['id'] for r in runs],key=lambda i:next(x['created'] for x in runs if x['id']==i),reverse=True))
 def test_files_listing_and_health(self):
  with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
   ident,p=fixture(d);(p/'hd').mkdir();(p/'hd/final-preview.mp4').write_bytes(b'v');client=TestClient(application.app)
   listed=client.get(f'/jobs/{ident}/files').json()['files']
   self.assertIn('mask.mp4',listed);self.assertIn('hd/final-preview.mp4',listed);self.assertNotIn('hd',listed)
   self.assertEqual(client.get('/jobs/'+'b'*32+'/files').status_code,404)
   self.assertEqual(client.get('/health').json(),{'status':'ok','service':'Puppeteer'})
if __name__=='__main__':unittest.main()
