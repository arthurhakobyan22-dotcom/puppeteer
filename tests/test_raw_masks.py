"""SAM stage: mocked Replicate HTTP only. Checks real failure reasons, term splitting, RGB retry and fallback."""
import unittest,tempfile,json,io,zipfile
from pathlib import Path
from unittest.mock import patch,Mock
import numpy as np
from PIL import Image
import raw_masks
from raw_masks import segment_raw,SamError

def png(mask):
    b=io.BytesIO();Image.fromarray((np.array(mask,dtype=np.uint8)*255)).save(b,format='PNG');return b.getvalue()
def zip_masks(masks):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        for i,m in enumerate(masks):z.writestr(f'output_masks/mask_{i:05d}.png',png(m))
    return b.getvalue()
def empty_zip():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('overlay.mp4',b'\x00'*16)
    return b.getvalue()
def box(y0,y1,x0,x1,h=8,w=8):
    m=np.zeros((h,w),bool);m[y0:y1,x0:x1]=True;return m

class FakeReplicate:
    """Routes requests.post/get by URL. `outputs` maps prompt -> zip bytes (or an exception/failed record)."""
    def __init__(self,outputs,fallback_output=None,fail_submit=None):
        self.outputs=outputs;self.fallback_output=fallback_output;self.fail_submit=fail_submit;self.predictions=[];self.n=0
    def post(self,url,**kw):
        r=Mock();r.ok=True;r.status_code=201
        if url.endswith('/files'):r.json.return_value={'urls':{'get':'https://api.replicate.com/v1/files/x'+str(self.n)}};self.n+=1;return r
        body=kw['json'];prompt=body['input']['prompt'];self.predictions.append(body)
        if self.fail_submit:
            code,detail=self.fail_submit;r.ok=False;r.status_code=code;r.json.return_value={'detail':detail};r.text=detail;return r
        record=self.outputs.get(prompt) if body['version']==raw_masks.PRIMARY_VERSION else self.fallback_output
        ident='pred-%d'%len(self.predictions)
        if isinstance(record,dict):j={'id':ident,'status':record.get('status','failed'),'error':record.get('error'),'logs':record.get('logs',''),'urls':{'get':'u'},'input':body['input']}
        else:j={'id':ident,'status':'succeeded','output':'https://replicate.delivery/'+ident+'/output.zip','urls':{'get':'u'},'input':body['input'],'metrics':{'predict_time':1},'logs':'ok'};self.blobs[j['output']]=record
        r.json.return_value=j;return r
    blobs={}
    def get(self,url,**kw):
        r=Mock();r.ok=True;r.status_code=200;r.content=self.blobs[url];return r
    def __enter__(self):
        self.patches=[patch('raw_masks.requests.post',side_effect=self.post),patch('raw_masks.requests.get',side_effect=self.get),patch('raw_masks.setting',side_effect=lambda k,d='':{'REPLICATE_API_TOKEN':'tok','SAM_FALLBACK_MODEL':d}.get(k,d)),patch('raw_masks.load_env'),patch('raw_masks.time.sleep')]
        for p in self.patches:p.start()
        return self
    def __exit__(self,*a):
        for p in self.patches:p.stop()

def masks_in(folder):
    files=sorted(Path(folder).glob('mask_*.png'));return [np.asarray(Image.open(p))>127 for p in files]

class SamTests(unittest.TestCase):
 def test_single_term_masks_are_extracted(self):
  with tempfile.TemporaryDirectory() as d,FakeReplicate({'person':zip_masks([box(0,4,0,4)]*3)}) as fake:
   Path(d,'depth.mp4').write_bytes(b'v');out=segment_raw(Path(d,'depth.mp4'),d,'person',status=lambda s:None)
   self.assertEqual(len(masks_in(out)),3);self.assertEqual(len(fake.predictions),1);self.assertEqual(fake.predictions[0]['input']['prompt'],'person')
   report=json.loads(Path(d,'sam-report.json').read_text());self.assertIn('depth',report['method']);self.assertEqual(report['attempts'][0]['frames_with_mask'],3)
   self.assertEqual(json.loads(Path(d,'sam-attempts.json').read_text())[0]['status'],'succeeded')
 def test_comma_prompt_runs_each_term_and_unions(self):
  with tempfile.TemporaryDirectory() as d,FakeReplicate({'person':zip_masks([box(0,4,0,8)]*2),'hands':zip_masks([box(4,8,0,4)]*2)}) as fake:
   Path(d,'depth.mp4').write_bytes(b'v');out=segment_raw(Path(d,'depth.mp4'),d,'person, hands',status=lambda s:None)
   self.assertEqual([p['input']['prompt'] for p in fake.predictions],['person','hands'])
   m=masks_in(out);self.assertEqual(len(m),2);self.assertTrue(m[0][0,0] and m[0][5,0] and not m[0][5,5])
 def test_empty_depth_result_retries_on_rgb_then_succeeds(self):
  outputs={'person':empty_zip()};calls=[]
  class Fake(FakeReplicate):
   def post(self,url,**kw):
    if 'predictions' in url and len(self.predictions)==1:self.outputs={'person':zip_masks([box(0,2,0,2)])}
    return super().post(url,**kw)
  with tempfile.TemporaryDirectory() as d,Fake(outputs) as fake:
   Path(d,'depth.mp4').write_bytes(b'v');Path(d,'original.mp4').write_bytes(b'o')
   out=segment_raw(Path(d,'depth.mp4'),d,'person',rgb_video=Path(d,'original.mp4'),status=calls.append)
   self.assertEqual(len(masks_in(out)),1);self.assertEqual(len(fake.predictions),2)
   report=json.loads(Path(d,'sam-report.json').read_text());self.assertEqual(report['source'],'rgb');self.assertTrue(any('retrying on the original RGB' in c for c in calls))
 def test_everything_empty_reports_empty_result_not_alignment(self):
  with tempfile.TemporaryDirectory() as d,FakeReplicate({'person':empty_zip(),'hands':empty_zip()},fallback_output=empty_zip()) as fake:
   Path(d,'depth.mp4').write_bytes(b'v');Path(d,'original.mp4').write_bytes(b'o')
   with patch('raw_masks.setting',side_effect=lambda k,dflt='':{'REPLICATE_API_TOKEN':'tok','SAM_FALLBACK_MODEL':'8digit/gener8-sam3'}.get(k,dflt)),patch('raw_masks._model_version',return_value='v-fallback'):
    with self.assertRaises(SamError) as caught:segment_raw(Path(d,'depth.mp4'),d,'person, hands',rgb_video=Path(d,'original.mp4'),status=lambda s:None)
   self.assertEqual(caught.exception.kind,'empty');msg=str(caught.exception)
   self.assertIn("no masks for prompt 'person, hands'",msg);self.assertIn('every prediction succeeded',msg);self.assertIn('8digit/gener8-sam3',msg);self.assertNotIn('alignment',msg)
   self.assertEqual(len(fake.predictions),5)   # 2 terms x 2 sources + fallback
 def test_fallback_model_output_is_used(self):
  with tempfile.TemporaryDirectory() as d,FakeReplicate({'person':empty_zip()},fallback_output=zip_masks([box(1,3,1,3)]*2)) as fake:
   Path(d,'depth.mp4').write_bytes(b'v')
   with patch('raw_masks.setting',side_effect=lambda k,dflt='':{'REPLICATE_API_TOKEN':'tok','SAM_FALLBACK_MODEL':'8digit/gener8-sam3'}.get(k,dflt)),patch('raw_masks._model_version',return_value='v-fallback'):
    out=segment_raw(Path(d,'depth.mp4'),d,'person',status=lambda s:None)
   self.assertEqual(len(masks_in(out)),2);self.assertEqual(fake.predictions[-1]['version'],'v-fallback');self.assertEqual(fake.predictions[-1]['input'],{'video':'https://api.replicate.com/v1/files/x0','prompt':'person'})
   self.assertIn('fallback 8digit/gener8-sam3',json.loads(Path(d,'sam-report.json').read_text())['method'])
 def test_billing_error_stops_immediately_with_reason(self):
  with tempfile.TemporaryDirectory() as d,FakeReplicate({},fail_submit=(402,'Insufficient credit. Add credit at replicate.com/account/billing')) as fake:
   Path(d,'depth.mp4').write_bytes(b'v');Path(d,'original.mp4').write_bytes(b'o')
   with self.assertRaises(SamError) as caught:segment_raw(Path(d,'depth.mp4'),d,'person',rgb_video=Path(d,'original.mp4'),status=lambda s:None)
   self.assertEqual(caught.exception.kind,'quota');self.assertIn('402',str(caught.exception));self.assertIn('Insufficient credit',str(caught.exception));self.assertEqual(len(fake.predictions),1)
 def test_failed_prediction_reports_model_error_and_log(self):
  failed={'status':'failed','error':'CUDA out of memory','logs':'loading\nRuntimeError: CUDA out of memory\n'}
  with tempfile.TemporaryDirectory() as d,FakeReplicate({'person':failed}) as fake:
   Path(d,'depth.mp4').write_bytes(b'v')
   with self.assertRaises(SamError) as caught:segment_raw(Path(d,'depth.mp4'),d,'person',status=lambda s:None)
   self.assertEqual(caught.exception.kind,'failed');self.assertIn('failed on Replicate: CUDA out of memory',str(caught.exception))
   self.assertEqual(json.loads(Path(d,'sam-attempts.json').read_text())[0]['error'],'CUDA out of memory')
 def test_quota_wording_in_failed_prediction_is_classified(self):
  with tempfile.TemporaryDirectory() as d,FakeReplicate({'person':{'status':'failed','error':'Rate limit exceeded for this account'}}):
   Path(d,'depth.mp4').write_bytes(b'v')
   with self.assertRaises(SamError) as caught:segment_raw(Path(d,'depth.mp4'),d,'person',status=lambda s:None)
   self.assertEqual(caught.exception.kind,'quota')
 def test_mask_video_output_is_decoded(self):
  import av
  from fractions import Fraction
  with tempfile.TemporaryDirectory() as d:
   with av.open(str(Path(d,'m.mp4')),'w') as out:
    s=out.add_stream('libx264',rate=24);s.width=64;s.height=64;s.pix_fmt='yuv420p'
    for i in range(3):
     a=np.zeros((64,64,3),np.uint8);a[8:40,8:40]=255;f=av.VideoFrame.from_ndarray(a,format='rgb24');f.pts=i;f.time_base=Fraction(1,24)
     for p in s.encode(f):out.mux(p)
    for p in s.encode():out.mux(p)
   video=Path(d,'m.mp4').read_bytes()
   with patch('raw_masks._download',return_value=video):
    count=raw_masks._collect(['https://x/labels.mp4'],Path(d,'out'),'t')
   self.assertEqual(count,3);m=masks_in(Path(d,'out'));self.assertTrue(m[0][20,20] and not m[0][2,2])
if __name__=='__main__':unittest.main()
