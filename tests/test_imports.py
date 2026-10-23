"""Import my own + downloads: each import kind on synthetic media (B/W mask video, PNG-zip mask, alpha video, depth
video, face overlay video, face landmarks JSON, finished control video), conform warnings for a mismatched file,
unreadable / wrong / too large uploads as plain errors, the "imported" label in describe / report / run chain /
summaries / tree, the mask round trip (download mask.zip → paint with PIL → import → the composite uses it), the safe
zip endpoint (no path traversal), and the parent never written.
"""
import unittest,tempfile,json,os,io,sys,zipfile,shutil
from pathlib import Path
from fractions import Fraction
from unittest.mock import patch
import numpy as np
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parent))
import app as application
import stages
from stages import imports,wand
from test_mask_wand import write_clip,square_box,square_mask,tree_hashes,wait,HEX,W,H,N
from test_words import words_parent,frames_of

ROOT=Path(__file__).resolve().parents[1]
FACE=json.loads((ROOT/'tests'/'fixtures'/'mesh-edit-cases.json').read_text())['face']

def red_depth(i):
    d=np.zeros((H,W,3),np.uint8);d[...]=(200,30,30);x0,y0,x1,y1=square_box(i);d[y0:y1,x0:x1]=230;return d

def import_parent(d):
    """A synthetic Advanced (depth) run with sound, a red-background depth video (so a mask region shows up in the
    composite), square masks and a real depth composite to draw on."""
    folder=words_parent(d,tracking=False)
    write_clip(folder/'depth.mp4',[red_depth(i) for i in range(N)]);(folder/'depth-raw.mp4').write_bytes((folder/'depth.mp4').read_bytes())
    write_clip(folder/'depth-composite-silent.mp4',[red_depth(i) for i in range(N)])
    stages.reconstruct(folder,with_keys=True,write=True)
    return folder

def mp4_bytes(frames,fps=24,size=None):
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/'x.mp4';write_clip(p,frames,fps);return p.read_bytes()

def alpha_mov(frames_rgba,fps=24):
    import av
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/'a.mov'
        with av.open(str(p),'w') as c:
            s=c.add_stream('png',rate=fps);s.width=frames_rgba[0].shape[1];s.height=frames_rgba[0].shape[0];s.pix_fmt='rgba'
            for i,a in enumerate(frames_rgba):
                f=av.VideoFrame.from_ndarray(a,format='rgba');f.pts=i;f.time_base=Fraction(1,fps)
                for pk in s.encode(f):c.mux(pk)
            for pk in s.encode():c.mux(pk)
        return p.read_bytes()

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=self.tmp.name;self.runs=Path(self.d)/'runs'
        self.rp=patch.object(application,'RUNS',self.runs);self.rp.start();self.parent=import_parent(self.d);self.client=TestClient(application.app);application.jobs.pop(HEX,None)
        self.before=tree_hashes(self.parent)
    def tearDown(self):
        self.assertEqual(tree_hashes(self.parent),self.before,'the parent is sha256-identical');self.rp.stop();self.tmp.cleanup()
    def post(self,stage,name,data,**extra):
        return self.client.post(f'/jobs/{HEX}/import',data={'stage':stage,**extra},files={'file':(name,data)})
    def child(self,r):
        self.assertEqual(r.status_code,200,r.text);job=wait(r.json()['id']);self.assertEqual(job['state'],'done',job);return self.runs/r.json()['id'],job
    def report(self,child,stage):return json.loads((child/'stages'/stage/'report.json').read_text())

class MaskImports(Base):
    def test_round_trip_download_paint_import_is_used_by_the_composite(self):
        r=self.client.get(f'/jobs/{HEX}/download/mask.zip');self.assertEqual(r.status_code,200);self.assertIn('attachment',r.headers['content-disposition'])
        z=zipfile.ZipFile(io.BytesIO(r.content));names=sorted(z.namelist());self.assertEqual(len(names),N);self.assertEqual(names[0],'mask/mask_00000.png')
        from PIL import Image,ImageDraw
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as o:
            for n in names:
                im=Image.open(io.BytesIO(z.read(n))).convert('L');ImageDraw.Draw(im).rectangle([10,10,60,60],fill=255);b=io.BytesIO();im.save(b,format='PNG');o.writestr(Path(n).name,b.getvalue())   # "edited externally"
        child,job=self.child(self.post('mask','my mask.zip',out.getvalue()))
        self.assertIn('imported',job['changed']);self.assertIn('my mask.zip',job['changed'])
        masks=[wand.read_mask(child/'clean-masks',i,(H,W)) for i in range(N)]
        self.assertTrue(all(m[35,35] for m in masks));self.assertTrue(all(np.array_equal(m[80:,:],square_mask(i)[80:,:]) for i,m in enumerate(masks)))
        rep=self.report(child,'mask');self.assertEqual(rep['tool'],'import_mask');self.assertTrue(rep['data']['imported']);self.assertEqual(rep['warnings'],[]);self.assertEqual(rep['state'],'done')
        cut=frames_of(child/'depth-composite-silent.mp4');orig=frames_of(self.parent/'original.mp4')
        self.assertGreater(cut[5][35,35,0],150);self.assertLess(cut[5][35,35,1],80,'the painted region shows the red depth: the composite used the imported mask');self.assertLess(orig[5][35,35,0],80)
        self.assertEqual(self.report(child,'composite')['state'],'done');self.assertTrue((child/'seedance-input.mp4').exists());self.assertTrue((child/'imported-mask.zip').exists())
        self.assertFalse((child/'calls.jsonl').exists())
        # labels: describe, chain, summaries, tree
        self.assertTrue(stages.get_tool('mask','import_mask').describe()['imported']);self.assertFalse(stages.get_tool('mask','sam3_replicate').describe()['imported'])
        run=json.loads((child/'run.json').read_text());self.assertEqual(run['imported'],['mask']);self.assertIn('mask: import_mask (name: my mask.zip) · imported',stages.describe_chain(run['chain']))
        self.assertTrue(all('sha' not in line and run['chain']['mask']['params']['file'] not in line for line in stages.describe_chain(run['chain'])))
        summary=next(x for x in self.client.get('/jobs').json()['runs'] if x['id']==child.name);self.assertEqual(summary['imported'],['mask']);self.assertIn('imported',summary['changed'])
        node=next(x for x in self.client.get('/jobs/tree').json()['runs'] if x['id']==HEX)['children'][0];self.assertEqual((node['id'],node['imported']),(child.name,['mask']))
        self.assertEqual(next(x for x in self.client.get('/jobs').json()['runs'] if x['id']==HEX)['imported'],[])
        self.assertTrue(list((self.runs/'_imports').glob('*.zip')))

    def test_mismatched_bw_video_conforms_with_warnings(self):
        frames=[np.zeros((96,160,3),np.uint8) for _ in range(30)]
        for f in frames:f[30:70,40:120]=255
        child,job=self.child(self.post('mask','mask.mp4',mp4_bytes(frames)))
        rep=self.report(child,'mask');self.assertEqual(rep['state'],'done')
        self.assertIn(f'Your mask had 30 frames; the clip has {N}, so the last 6 were dropped.',rep['warnings'])
        self.assertIn(f'Your mask was 160×96; it was resized to the clip\'s {W}×{H}.',rep['warnings'])
        self.assertEqual(len(list((child/'clean-masks').glob('mask_*.png'))),N);m=wand.read_mask(child/'clean-masks',3,(H,W));self.assertTrue(m[H//2,W//2]);self.assertFalse(m[5,5])
        short=[np.full((H,W,3),255,np.uint8) for _ in range(20)]
        child2,_=self.child(self.post('mask','short.mp4',mp4_bytes(short)))
        self.assertIn(f'Your mask had 20 frames; the clip has {N}, so the last frame was held for 4 more frames.',self.report(child2,'mask')['warnings'])
        thirty=[np.full((H,W,3),255,np.uint8) for _ in range(30)]
        child3,_=self.child(self.post('mask','fps.mp4',mp4_bytes(thirty,fps=30)))
        w=self.report(child3,'mask')['warnings'];self.assertIn('Your mask was 30 fps; it was resampled to the clip\'s 24 fps.',w);self.assertEqual(len(w),1,w)

    def test_alpha_video_uses_its_alpha_channel(self):
        frames=[]
        for i in range(N):
            a=np.zeros((H,W,4),np.uint8);x0,y0,x1,y1=square_box(i);a[y0:y1,x0:x1,3]=255;frames.append(a)   # black RGB everywhere: only the alpha says where
        child,_=self.child(self.post('mask','alpha.mov',alpha_mov(frames)))
        rep=self.report(child,'mask');self.assertEqual(rep['data']['mask_from'],'alpha channel');self.assertTrue(rep['data']['source']['alpha'])
        for i in (0,12,23):self.assertGreater((wand.read_mask(child/'clean-masks',i,(H,W))==square_mask(i)).mean(),0.99)

@unittest.skipUnless(shutil.which('ffmpeg'),'needs the ffmpeg command to encode VP9 / ProRes alpha test clips')
class AlphaFormats(unittest.TestCase):
    def test_vp9_webm_prores_4444_and_qtrle_alpha_are_read(self):
        import subprocess
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            for i in range(6):
                im=Image.new('RGBA',(160,96),(0,0,0,0));im.paste((0,0,0,255),(20+i*4,20,70+i*4,70));im.save(f'{d}/f{i:03d}.png')
            for name,args in [('a.webm',['-c:v','libvpx-vp9','-pix_fmt','yuva420p']),('a.mov',['-c:v','prores_ks','-profile:v','4444','-pix_fmt','yuva444p10le']),('q.mov',['-c:v','qtrle','-pix_fmt','argb'])]:
                subprocess.run(['ffmpeg','-loglevel','error','-y','-framerate','24','-i',f'{d}/f%03d.png',*args,f'{d}/{name}'],check=True)
                info={};frames=list(imports.video_frames(f'{d}/{name}',info));self.assertTrue(info['alpha'],name);self.assertEqual(len(frames),6)
                m=imports.mask_of(frames[2][1]);self.assertEqual(int(m.sum()),2500,name);self.assertTrue(m[45,40]);self.assertFalse(m[5,5])

class OtherImports(Base):
    def test_depth_import_keeps_the_mask_and_reruns_the_composite(self):
        frames=[np.full((H,W,3),40+i*5,np.uint8) for i in range(N)]
        child,job=self.child(self.post('depth','depth.mp4',mp4_bytes(frames)))
        run=json.loads((child/'run.json').read_text());self.assertEqual((run['chain']['depth']['tool'],run['chain']['mask']['tool']),('import_depth','keep_parent'));self.assertEqual(run['imported'],['depth'])
        self.assertEqual(job['estimated_cost_usd'],0);self.assertFalse((child/'calls.jsonl').exists())
        for i in (0,N-1):self.assertTrue(np.array_equal(wand.read_mask(child/'clean-masks',i,(H,W)),wand.read_mask(self.parent/'clean-masks',i,(H,W))))
        d=frames_of(child/'depth.mp4');self.assertLess(abs(d[0][5,5,0]-40),6);self.assertEqual(len(d),N)
        self.assertTrue(self.report(child,'depth')['data']['imported']);self.assertEqual(self.report(child,'composite')['state'],'done')

    def test_face_overlay_video_and_landmarks_json(self):
        over=[np.zeros((H,W,3),np.uint8) for _ in range(N)]
        for f in over:f[20:40,20:40]=(0,255,0)
        child,_=self.child(self.post('face','overlay.mp4',mp4_bytes(over)))
        out=frames_of(child/'composite-silent.mp4');self.assertGreater(out[3][30,30,1],200);self.assertLess(out[3][30,30,0],60);self.assertGreater(out[3][100,300,0],150,'black overlay pixels keep the base clip')
        rep=self.report(child,'face');self.assertTrue(rep['data']['imported']);self.assertEqual(rep['data']['kind'],'overlay');self.assertTrue((child/'preview.jpg').exists());self.assertTrue((child/'seedance-input.mp4').exists())
        lm={'fps':24,'frames':[{'faces':[[{'x':x,'y':y} for x,y in FACE]]} for _ in range(20)]}
        lm['frames'][4]={'faces':[[{'x':0.5,'y':0.5}]*10]}
        child2,_=self.child(self.post('face','face.json',json.dumps(lm).encode()))
        data=json.loads((child2/'face-landmarks.json').read_text());self.assertEqual(len(data['frames']),N);self.assertEqual(data['frames'][4]['status'],'missing');self.assertEqual(data['frames'][23]['status'],'tracked')
        w=self.report(child2,'face')['warnings'];self.assertIn(f'Your landmarks had 20 frames; the clip has {N}, so the last frame was held for 4 more frames.',w);self.assertTrue(any('point count' in x for x in w))
        self.assertEqual(json.loads((child2/'face-tracking.json').read_text())['missing_frames'],[4]);self.assertTrue((child2/'composite-silent.mp4').exists())
        bad=self.post('face','bad.json',json.dumps({'frames':[{'faces':[[{'x':0,'y':0}]]}]}).encode());self.assertEqual(bad.status_code,400);self.assertIn('468 or 478',bad.json()['message'])

    def test_control_video_switches_the_face_off_and_is_the_prepared_clip(self):
        frames=[np.full((H,W,3),(10,200,10),np.uint8) for _ in range(N)]
        child,job=self.child(self.post('composite','control.webm',mp4_bytes(frames)))   # an H.264 file named .webm: read by content
        run=json.loads((child/'run.json').read_text());self.assertEqual((run['chain']['composite']['tool'],run['chain']['face']['tool']),('import_control','off'));self.assertIn('face: off',job['changed'])
        out=frames_of(child/'composite-silent.mp4');self.assertGreater(out[0][50,50,1],180);self.assertTrue((child/'seedance-input.mp4').exists())
        self.assertEqual(self.client.get(f'/jobs/{child.name}/mask-review').json()['status'],'pending')

class Refusals(Base):
    def test_unreadable_wrong_missing_and_too_large(self):
        r=self.post('mask','broken.mp4',b'not a video at all'*100);self.assertEqual(r.status_code,400);self.assertIn('could not be read',r.json()['message']);self.assertTrue(r.json()['fix'])
        self.assertEqual([p for p in (self.runs/'_imports').iterdir() if not p.name.startswith('.')],[],'an unreadable file is not kept')
        r=self.post('mask','notes.txt',b'hello');self.assertEqual(r.status_code,400);self.assertIn('.txt',r.json()['message'])
        r=self.post('generate','x.mp4',b'1');self.assertEqual(r.status_code,400)
        r=self.client.post(f'/jobs/{HEX}/import',data={'stage':'mask'});self.assertEqual(r.status_code,400);self.assertIn('No file',r.json()['message'])
        r=self.post('mask','empty.zip',zipfile_bytes({}));self.assertEqual(r.status_code,400);self.assertIn('no PNG',r.json()['message'])
        with patch.object(imports,'MAX_BYTES',1000):
            r=self.post('mask','big.mp4',b'0'*5000);self.assertEqual(r.status_code,413);self.assertIn('larger than',r.json()['message'])
        self.assertEqual(len([p for p in self.runs.iterdir() if len(p.name)==32]),1,'no branch was made')

    def test_oversized_bodies_are_refused_before_they_are_read(self):
        # review fix 8: Content-Length over the limit → plain 413 without parsing (store() never runs); a chunked body with
        # no Content-Length is counted while it streams and cut off with the same 413; PUT edits likewise
        def never(*a,**k):raise AssertionError('the body must not be parsed or stored')
        with patch.object(imports,'MAX_BYTES',1000),patch.object(imports,'store',never):
            r=self.post('mask','big.mp4',b'0'*1_100_000);self.assertEqual(r.status_code,413,r.text);self.assertIn('larger than 0 MB',r.json()['message']);self.assertTrue(r.json()['fix'])
            body=b'--b\r\nContent-Disposition: form-data; name="stage"\r\n\r\nmask\r\n--b\r\nContent-Disposition: form-data; name="file"; filename="big.mp4"\r\n\r\n'+b'0'*1_100_000+b'\r\n--b--\r\n'
            chunks=(body[i:i+65536] for i in range(0,len(body),65536))
            r=self.client.post(f'/jobs/{HEX}/import',content=chunks,headers={'content-type':'multipart/form-data; boundary=b'});self.assertEqual(r.status_code,413,r.text);self.assertTrue(r.json()['fix'])
        from stages import editlayer
        with patch.object(editlayer,'MAX_LAYER_BYTES',1000):
            big=json.dumps({'rev':0,'label':'x','track':'words','value':{'words':[{'id':'w','text':'a'*5000,'start':0,'end':1}]}}).encode()
            r=self.client.put(f'/jobs/{HEX}/edits',content=big,headers={'content-type':'application/json'});self.assertEqual(r.status_code,413,r.text);self.assertIn('too large',r.json()['message'])
            r=self.client.put(f'/jobs/{HEX}/edits',content=(big[i:i+500] for i in range(0,len(big),500)),headers={'content-type':'application/json'});self.assertEqual(r.status_code,413,r.text)
        r=self.client.put(f'/jobs/{HEX}/edits',json={'rev':0,'label':'ok','track':'words','value':None});self.assertEqual(r.status_code,200,'a normal edit still passes')
        self.client.delete(f'/jobs/{HEX}/edits')
        self.assertFalse(list((self.runs/'_imports').glob('*.mp4')) if (self.runs/'_imports').exists() else [])

    def test_zip_downloads_refuse_paths_and_unknown_folders(self):
        (self.runs/'secret').mkdir();(self.runs/'secret'/'x.txt').write_text('no')
        os.symlink(self.runs/'secret',self.parent/'linked')
        for name,code in [('..%2F..%2Fsecret.zip',404),('...zip',400),('.hidden.zip',400),('linked.zip',404),('upload.mp4.zip',400),('original.zip',404),('mask',400),('stages.zip',200),('clean-masks.zip',200),('nothing.zip',404)]:
            r=self.client.get(f'/jobs/{HEX}/download/{name}');self.assertEqual(r.status_code,code,(name,r.text[:200]))
            if code==200:
                z=zipfile.ZipFile(io.BytesIO(r.content));self.assertTrue(all(not n.startswith('/') and '..' not in n for n in z.namelist()))
        self.assertEqual(self.client.get('/jobs/../download/mask.zip').status_code,404)
        os.unlink(self.parent/'linked')

def zipfile_bytes(files):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        for n,data in files.items():z.writestr(n,data)
    return b.getvalue()

if __name__=='__main__':unittest.main()
