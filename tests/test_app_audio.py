import unittest,tempfile,time
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as application

def prepare(form_value):
 with tempfile.TemporaryDirectory() as d:
  calls=[]
  def fake_run(src,folder,prompt,provider,status,clean_dialogue=False):calls.append((prompt,provider,clean_dialogue))
  with patch.object(application,'RUNS',Path(d)),patch.object(application,'run',side_effect=fake_run):
   client=TestClient(application.app)
   data={'mode':'depth','prompt':'person','provider':'replicate'}
   if form_value is not None:data['clean_dialogue']=form_value
   r=client.post('/jobs',data=data,files={'video':('clip.mp4',b'video','video/mp4')})
   assert r.status_code==200,r.text
   for _ in range(100):
    if application.jobs[r.json()['id']]['state']!='running':break
    time.sleep(.05)
  return calls

class JobFormTests(unittest.TestCase):
 def test_checkbox_values_enable_clean_dialogue(self):
  for value in ['true','on','1']:self.assertEqual(prepare(value),[('person','replicate',True)],value)
 def test_default_and_false_keep_original_audio(self):
  for value in [None,'','false','off']:self.assertEqual(prepare(value),[('person','replicate',False)],value)
if __name__=='__main__':unittest.main()
