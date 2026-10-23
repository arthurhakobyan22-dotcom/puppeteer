"""Export kit (stage 3, Agent 4): every preset on a synthetic 12-frame 24 fps run (the zip opens, ffprobe fps / frame counts
match, README names every file), the transparent face mesh (ProRes 4444 with a real alpha channel: 0 away from the face,
>0 on a mesh line, and the same as an RGBA PNG sequence), the person alpha, pending timeline edits saved first as one free
branch and the child exported (the frames switched off have an empty alpha), the routes (items with reasons, POST then
poll, zip download, plain 400s / 402 / 404) and that nothing is written into the parent but its export records.
"""
import unittest,tempfile,json,os,sys,time,shutil,subprocess,zipfile,io
from pathlib import Path
from unittest.mock import patch
import numpy as np
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parent))
import app as application
import stages
from stages import export as X,export_presets as P,meshedit,editlayer,wand
from test_mask_wand import write_clip,tree_hashes,wait
from test_words import write_av

ROOT=Path(__file__).resolve().parents[1]
HEX='e'*32
W,H,N,FPS=320,192,12,24
FACE=[tuple(p) for p in json.loads((ROOT/'tests'/'fixtures'/'mesh-edit-cases.json').read_text())['face']]
FFMPEG=X.ffmpeg_path();FFPROBE=X.ffprobe_path()
needs_ffmpeg=unittest.skipUnless(FFMPEG and FFPROBE,'ffmpeg / ffprobe are not installed')
PNG=(b'\x89PNG\r\n\x1a\n')

def box(i):x0=40+i*8;y0=60+(i%6)*2;return x0,y0,x0+56,y0+56
def square(i):
    m=np.zeros((H,W),bool);x0,y0,x1,y1=box(i);m[y0:y1,x0:x1]=True;return m
def landmarks(n=N,missing=(10,),filled=(1,)):
    frames=[]
    for i in range(n):
        status='missing' if i in missing else 'filled' if i in filled else 'tracked'
        faces=[] if status=='missing' else [[{'x':x+0.004*i,'y':y} for x,y in FACE]]
        frames.append({'frame':i,'time':round(i/FPS,4),'status':status,'faces':faces})
    return {'fps':FPS,'frames':frames,'summary':{'frames':n,'tracked':n-len(missing)-len(filled),'filled':len(filled),'missing':len(missing)}}

def export_parent(d,ident=HEX):
    """A synthetic Advanced + mesh run with sound: 12 frames at 24 fps, 320×192; every prepared file is a real clip."""
    folder=Path(d)/'runs'/ident;folder.mkdir(parents=True)
    rng=np.random.default_rng(2);rgb=[];dep=[];masks=[];comp=[]
    for i in range(N):
        a=np.full((H,W,3),28,np.uint8)+rng.integers(0,6,(H,W,3),dtype=np.uint8);x0,y0,x1,y1=box(i);a[y0:y1,x0:x1]=(220,200,60);rgb.append(a)
        dpt=np.full((H,W,3),30,np.uint8);dpt[y0:y1,x0:x1]=230;dep.append(dpt)
        masks.append(np.repeat(np.where(square(i),255,0).astype(np.uint8)[:,:,None],3,axis=2))
        c=np.zeros((H,W,3),np.uint8);c[:,:,0]=np.linspace(40,200,W,dtype=np.uint8)[None,:];c[:,:,1]=90+i*2;c[:,:,2]=np.linspace(180,60,H,dtype=np.uint8)[:,None];comp.append(c)
    write_clip(folder/'original.mp4',rgb);write_clip(folder/'depth.mp4',dep);write_clip(folder/'mask.mp4',masks);write_clip(folder/'depth-composite-silent.mp4',comp)
    write_av(folder/'upload.mp4',rgb)   # the source with an AAC tone
    (folder/'clean-masks').mkdir()
    for i in range(N):wand.write_mask(square(i),folder/'clean-masks'/f'mask_{i:05d}.png')
    lm=landmarks();(folder/'face-landmarks.json').write_text(json.dumps(lm))
    from mesh_tracking import evaluate
    st=[f['status'] for f in lm['frames']]
    (folder/'face-tracking.json').write_text(json.dumps({**evaluate(st,FPS,strict=False),'fps':FPS,'missing_frames':[i for i,s in enumerate(st) if s=='missing'],'filled_frames':[i for i,s in enumerate(st) if s=='filled']}))
    meshedit.render(folder,lm,folder/'depth-composite-silent.mp4')   # composite-silent.mp4 + preview.jpg, the mesh drawn like the face stage
    import audio_workflow;audio_workflow.prepare_seedance_video(folder)   # seedance-input.mp4 = composite-silent + the original audio packets
    shutil.copyfile(folder/'composite-silent.mp4',folder/'composite.mp4')
    (folder/'words.json').write_text(json.dumps({'version':1,'engine':'mlx-whisper:test','language':'en','singing':False,'words':[{'text':'Hello','start':0.05,'end':0.2},{'text':'there,','start':0.22,'end':0.3},{'text':'friend.','start':0.35,'end':0.45}]}))
    from PIL import Image
    Image.new('RGB',(32,32),(200,40,40)).save(folder/'char1-reference.png')
    (folder/'workflow-mode.json').write_text(json.dumps({'mode':'depth_mesh'}));(folder/'manifest.json').write_text(json.dumps({'frames':N,'prompt':'square'}));(folder/'sam-report.json').write_text(json.dumps({'prompt':'square','frames':N}))
    (folder/'status.json').write_text(json.dumps({'id':ident,'state':'done','status':'Complete'}))
    stages.reconstruct(folder,with_keys=True,write=True)
    return folder

def probe(path):
    """{codec, pix_fmt, fps, frames, width, height, profile} of the first video stream, {codec, sample_rate} for audio."""
    out=subprocess.run([FFPROBE,'-v','error','-count_frames','-show_entries','stream=codec_type,codec_name,pix_fmt,r_frame_rate,nb_read_frames,width,height,profile,sample_rate','-of','json',str(path)],stdout=subprocess.PIPE,check=True).stdout
    streams=json.loads(out)['streams'];v=next((s for s in streams if s['codec_type']=='video'),None);a=next((s for s in streams if s['codec_type']=='audio'),None)
    res={}
    if v:
        num,den=v['r_frame_rate'].split('/');res.update(codec=v['codec_name'],pix_fmt=v.get('pix_fmt'),fps=int(num)/int(den),frames=int(v['nb_read_frames']),width=v['width'],height=v['height'],profile=v.get('profile'))
    if a:res.update(audio=a['codec_name'],sample_rate=int(a.get('sample_rate') or 0))
    return res

def rgba_frames(path):
    import av
    with av.open(str(path)) as c:return [f.to_ndarray(format='rgba') for f in c.decode(video=0)]

def lip_point(i):
    conn=json.loads((ROOT/'static'/'face-connections.json').read_text());a,b=conn['lips'][0];x,y=FACE[a];return round((x+0.004*i)*W),round(y*H)

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=self.tmp.name;self.runs=Path(self.d)/'runs'
        self.rp=patch.object(application,'RUNS',self.runs);self.rp.start();self.parent=export_parent(self.d);self.client=TestClient(application.app)
        application.jobs.pop(HEX,None);self.tracks=dict(editlayer.TRACKS)
    def tearDown(self):
        editlayer.TRACKS.clear();editlayer.TRACKS.update(self.tracks);self.rp.stop();self.tmp.cleanup()
    def build(self,preset,items=None,**kw):
        lines=[];r=X.build_export(self.parent,items,preset,self.runs,status=lines.append,**kw);r['status_lines']=lines;return r

# ---------------------------------------------------------------- presets

@needs_ffmpeg
class Presets(Base):
    def check_common(self,r):
        self.assertTrue(r['zip'].exists() and r['folder'].is_dir());self.assertEqual((r['fps'],r['frames'],r['width'],r['height']),(24.0,N,W,H))
        with zipfile.ZipFile(r['zip']) as z:
            names=z.namelist();self.assertTrue(names and all(n.startswith(r['name']+'/') for n in names));self.assertIn(r['name']+'/README.txt',names)
            readme=z.read(r['name']+'/README.txt').decode()
        self.assertEqual(readme,r['readme']);self.assertIn(f'{N} frames at 24 fps · {W}×{H}',readme);self.assertIn('Run: '+HEX,readme)
        for f in r['files']:
            self.assertIn(f['file'],readme,f);self.assertTrue(f['what']);self.assertTrue((r['folder']/f['file'].split('/')[0]).exists(),f)
        self.assertEqual(sorted(p.name for p in r['folder'].iterdir()),sorted({f['file'].split('/')[0] for f in r['files']}|{'README.txt'}))
        for f in r['files']:
            path=r['folder']/f['file'].split('/')[0]
            if path.is_dir():
                pngs=sorted(path.glob('frame_*.png'));self.assertEqual(len(pngs),N,f);self.assertEqual(pngs[0].name,'frame_00000.png');self.assertTrue(pngs[0].read_bytes().startswith(PNG))
            elif path.suffix in ('.mp4','.mov'):
                p=probe(path);self.assertEqual((p['fps'],p['frames'],p['width'],p['height']),(24.0,N,W,H),f)
        rec=json.loads((self.parent/'export'/(r['name']+'.json')).read_text());self.assertEqual((rec['state'],rec['name'],rec['exported_run']),('done',r['name'],HEX))
    def test_seedance_web(self):
        r=self.build('seedance_web');self.check_common(r)
        files=[f['file'] for f in r['files']];self.assertEqual(files,['composite.mp4','prompt.txt','ref-01-char1.png'])
        p=probe(r['folder']/'composite.mp4');self.assertEqual((p['codec'],p['audio'],p['sample_rate']),('h264','aac',48000))
        text=(r['folder']/'prompt.txt').read_text();self.assertIn('@Image1 defines the character',text);self.assertIn('Dialogue beats',text);self.assertIn('0.1–0.5 s says: "Hello there, friend."',text);self.assertIn('@Image1  ref-01-char1.png',text)
        self.assertIn('web upload box',r['readme'])
    def test_kling(self):
        r=self.build('kling');self.check_common(r)
        self.assertEqual([f['file'] for f in r['files']],['composite.mp4','mask.mp4','prompt.txt'])
        a=rgba_frames(r['folder']/'mask.mp4')[3];self.assertGreater(a[90,70,0],200);self.assertLess(a[5,5,0],40)   # white inside the square on frame 3, black outside
    def test_comfyui(self):
        r=self.build('comfyui');self.check_common(r)
        files=[f['file'] for f in r['files']]
        self.assertEqual(files,['composite-silent/frame_%05d.png','depth/frame_%05d.png','mask/frame_%05d.png','face-landmarks.json','words.srt','words.json','run.json','frames.json'])   # table order
        self.assertEqual(json.loads((r['folder']/'frames.json').read_text()),{'fps':24.0,'fps_text':'24','frames':N,'width':W,'height':H})
        from PIL import Image
        self.assertEqual(Image.open(r['folder']/'depth'/'frame_00005.png').size,(W,H))
        self.assertEqual(json.loads((r['folder']/'run.json').read_text())['chain']['face']['tool'],'mediapipe_mesh')
        srt=(r['folder']/'words.srt').read_text();self.assertTrue(srt.startswith('1\n00:00:00,050 --> '));self.assertIn('Hello there, friend.',srt)
    def test_after_effects(self):
        r=self.build('after_effects');self.check_common(r)
        self.assertEqual([f['file'] for f in r['files']],['composite-silent.mov','face-mesh-alpha.mov','person-alpha.mov','audio-original.wav','words.srt','words.json'])
        p=probe(r['folder']/'composite-silent.mov');self.assertEqual((p['codec'],p['pix_fmt']),('prores','yuv422p10le'))
        a=probe(r['folder']/'audio-original.wav');self.assertEqual((a['audio'],a['sample_rate']),('pcm_s16le',48000))
        self.assertIn('ProRes 4444',r['readme'])
    def test_custom_is_what_is_ticked_and_refuses_empty(self):
        r=self.build('custom',['depth','landmarks','run','audio_original'],alpha_format='png');self.check_common(r)
        self.assertEqual([f['file'] for f in r['files']],['depth.mp4','audio-original.wav','face-landmarks.json','run.json'])
        with self.assertRaises(X.ExportError) as cm:self.build('custom',[])
        self.assertIn('Nothing is ticked',str(cm.exception));self.assertTrue(cm.exception.fix)
        with self.assertRaises(X.ExportError) as cm:self.build('custom',['audio_vocals'])
        self.assertIn('isolated vocals',str(cm.exception));self.assertIn('Clean dialogue',str(cm.exception))
        with self.assertRaises(X.ExportError):self.build('nope',None)
    def test_mask_from_png_folder_when_the_run_has_no_mask_video(self):
        (self.parent/'mask.mp4').unlink()
        r=self.build('custom',['mask','alpha'],alpha_format='png');self.check_common(r)
        self.assertEqual([f['file'] for f in r['files']],['mask.mp4','person-alpha/frame_%05d.png','frames.json']);self.assertIn('clean-masks',r['files'][0]['what'])
        a=rgba_frames(r['folder']/'mask.mp4')[3];self.assertGreater(a[90,70,0],200);self.assertLess(a[5,5,0],40)
    def test_ffmpeg_missing_is_a_plain_fix(self):
        with patch.object(X,'ffmpeg_path',return_value=None):
            with self.assertRaises(X.ExportError) as cm:self.build('kling')
        self.assertIn('ffmpeg',str(cm.exception));self.assertIn('brew install ffmpeg',cm.exception.fix)
        self.assertFalse((self.parent/'export').exists() and list((self.parent/'export').iterdir()))

# ---------------------------------------------------------------- the alpha channel

@needs_ffmpeg
class Alpha(Base):
    def test_prores_mesh_has_a_real_alpha_channel(self):
        r=self.build('after_effects')
        p=probe(r['folder']/'face-mesh-alpha.mov')
        self.assertEqual(p['codec'],'prores');self.assertEqual(p['profile'],'4444')
        self.assertTrue(p['pix_fmt'].startswith('yuva444p'),p)   # encoded as yuva444p10le; this ffmpeg's ProRes decoder reports the 4444 stream as yuva444p12le
        frames=rgba_frames(r['folder']/'face-mesh-alpha.mov');self.assertEqual(len(frames),N);self.assertEqual(frames[0].shape,(H,W,4))
        x,y=lip_point(0);f0=frames[0]
        self.assertEqual(int(f0[0,0,3]),0);self.assertEqual(int(f0[H-1,W-1,3]),0)
        self.assertGreater(int(f0[y,x,3]),200);self.assertGreater(int(f0[y,x,0]),200)   # a lips line: opaque and lip-coloured (255,135,100)
        self.assertEqual(int((frames[10][:,:,3]>0).sum()),0,'frame 10 has no face, so its alpha is empty')
        self.assertGreater(int((f0[:,:,3]>0).sum()),500)
        pa=rgba_frames(r['folder']/'person-alpha.mov')[3];x0,y0,x1,y1=box(3)
        self.assertGreater(int(pa[y0+10,x0+10,3]),240);self.assertEqual(int(pa[5,5,3]),0);self.assertIn('yuva444p10le',r['readme'])
        self.assertIn('ProRes 4444',r['files'][1]['what']);self.assertIn('1 frame without a mesh',r['files'][1]['what'])
    def test_png_sequences_are_rgba(self):
        from PIL import Image
        r=self.build('custom',['mesh_alpha','alpha'],mesh_format='png',alpha_format='png')
        self.assertEqual([f['file'] for f in r['files']],['face-mesh/frame_%05d.png','person-alpha/frame_%05d.png','frames.json']);self.assertTrue((r['folder']/'frames.json').exists())
        im=Image.open(r['folder']/'face-mesh'/'frame_00000.png');self.assertEqual((im.mode,im.size),('RGBA',(W,H)))
        a=np.asarray(im);x,y=lip_point(0);self.assertEqual(int(a[0,0,3]),0);self.assertGreater(int(a[y,x,3]),200)
        self.assertEqual(int(np.asarray(Image.open(r['folder']/'face-mesh'/'frame_00010.png'))[:,:,3].max()),0)
        pa=np.asarray(Image.open(r['folder']/'person-alpha'/'frame_00003.png'));self.assertEqual(pa.shape,(H,W,4));x0,y0,_,_=box(3);self.assertEqual(int(pa[y0+10,x0+10,3]),255);self.assertEqual(int(pa[5,5,3]),0)
        with zipfile.ZipFile(r['zip']) as z:self.assertEqual(sum(1 for n in z.namelist() if n.startswith(r['name']+'/face-mesh/')),N)

# ---------------------------------------------------------------- routes and pending edits

class RefusingTrack(editlayer.Track):
    label='mask';empty={}
    def count(self,value):return int((value or {}).get('n') or 0)
    def summary(self,value):return [f'{self.count(value)} mask clicks']
    def check(self,value,session_dir):return ('3 mask clicks are not applied yet. Apply them to the clip first, or remove them.','Click Apply on the Mask track, then export again.')
class PaidTrack(editlayer.Track):
    label='mask';empty={}
    def count(self,value):return int((value or {}).get('n') or 0)
    def summary(self,value):return [f'{self.count(value)} paid mask fixes']
    def change(self,value,parent,session_dir):return ('mask','sam3_replicate',{'prompt':'person'})

@needs_ffmpeg
class Routes(Base):
    def poll(self,name,ident=HEX):
        for _ in range(900):
            s=self.client.get(f'/jobs/{ident}/export/{name}').json()
            if s['state']!='running':return s
            time.sleep(.05)
        return s
    def test_get_lists_items_with_reasons_presets_and_no_pending(self):
        r=self.client.get(f'/jobs/{HEX}/export');self.assertEqual(r.status_code,200,r.text);b=r.json()
        self.assertEqual([p['name'] for p in b['presets']],['seedance_web','kling','comfyui','after_effects','custom']);self.assertTrue(all(p['what'] and len(p['why'])==2 for p in b['presets']))
        items={i['key']:i for i in b['items']};self.assertEqual(list(items),P.ITEM_KEYS)
        self.assertTrue(items['mesh_alpha']['available'] and items['composite_audio']['available'] and items['words']['available'] and items['refs']['available'])
        self.assertFalse(items['audio_vocals']['available']);self.assertIn('Clean dialogue',items['audio_vocals']['reason']);self.assertEqual(items['refs']['files'],['ref-01-char1.png'])
        self.assertEqual((b['pending']['total'],b['pending']['note'],b['pending']['problem'],b['exports'],b['running'],b['ffmpeg']),(0,None,None,[],False,True))
        self.assertEqual(b['clip']['frames'],N);self.assertEqual(self.client.get('/jobs/'+'f'*32+'/export').status_code,404)
    def test_post_poll_download_and_bad_names(self):
        before=tree_hashes(self.parent)
        r=self.client.post(f'/jobs/{HEX}/export',json={'preset':'kling'});self.assertEqual(r.status_code,200,r.text);s=r.json()
        self.assertEqual((s['state'],s['run'],s['exported_run'],s['preset'],s['items']),('running',HEX,None,'kling',['composite_audio','mask','prompt']));name=s['name']
        s=self.poll(name);self.assertEqual(s['state'],'done',s)
        self.assertEqual((s['exported_run'],s['frames'],s['fps'],[f['file'] for f in s['files']]),(HEX,N,24.0,['composite.mp4','mask.mp4','prompt.txt']));self.assertIn('README',s['readme']) ;self.assertEqual(s['zip_url'],f'/jobs/{HEX}/export/{name}.zip')
        z=self.client.get(s['zip_url']);self.assertEqual(z.status_code,200);self.assertIn(f'{HEX[:8]}-{name}.zip',z.headers['content-disposition'])
        with zipfile.ZipFile(io.BytesIO(z.content)) as zf:self.assertIn(f'{name}/README.txt',zf.namelist())
        listing=self.client.get(f'/jobs/{HEX}/export').json()['exports'];self.assertEqual([(e['name'],e['state'],e['zip_exists']) for e in listing],[(name,'done',True)])
        for bad in ['kling-2026.zip','kling-20261024-120000-zz.zip','Kling-20261024-120000.zip','kling-20261024-120000;rm.zip','kling-20261024-120000.zip.zip']:
            r=self.client.get(f'/jobs/{HEX}/export/{bad}');self.assertEqual(r.status_code,400,bad);self.assertTrue(r.json()['fix'])
        self.assertEqual(self.client.get(f'/jobs/{HEX}/export/kling-20000101-000000.zip').status_code,404);self.assertEqual(self.client.get(f'/jobs/{HEX}/export/..%2F..%2Fx.zip').status_code,404);self.assertEqual(self.client.get(f'/jobs/{HEX}/export/..%2Fsecret.zip').status_code,404)   # a decoded slash never reaches the routeself.assertEqual(self.client.get(f'/jobs/{HEX}/export/kling-20000101-000000').status_code,404)
        self.assertEqual(self.client.get(f'/jobs/{HEX}/export/not-a-name').status_code,400)
        after=tree_hashes(self.parent);self.assertEqual({k:v for k,v in after.items() if not k.startswith('export/')},before,'only export/ was written')
    def test_post_refusals_are_plain(self):
        for body,code,text in [({'preset':'laser'},400,'no export preset'),({'preset':'custom','items':['laser']},400,'no export item'),({'preset':'custom','items':[]},400,'Nothing is ticked'),
                               ({'preset':'custom','items':['audio_vocals']},400,'isolated vocals'),({'preset':'kling','mesh_format':'gif'},400,'prores or png')]:
            r=self.client.post(f'/jobs/{HEX}/export',json=body);self.assertEqual(r.status_code,code,(body,r.text));self.assertIn(text,r.json()['message']);self.assertTrue(r.json()['fix'])
        r=self.client.post(f'/jobs/{HEX}/export',data={'preset':'custom','items':'depth, run'});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['items'],['depth','run']);self.assertEqual(self.poll(r.json()['name'])['state'],'done')
        with patch.object(X,'ffmpeg_path',return_value=None):
            r=self.client.post(f'/jobs/{HEX}/export',json={'preset':'kling'});self.assertEqual(r.status_code,400);self.assertIn('brew install ffmpeg',r.json()['fix'])
            self.assertFalse(self.client.get(f'/jobs/{HEX}/export').json()['ffmpeg'])
        application.jobs[HEX]={'state':'running','status':'busy'}
        try:self.assertEqual(self.client.post(f'/jobs/{HEX}/export',json={'preset':'kling'}).status_code,409)
        finally:application.jobs.pop(HEX,None)
    def test_pending_mesh_edits_are_saved_first_and_the_child_is_exported(self):
        r=self.client.put(f'/jobs/{HEX}/edits',json={'rev':0,'label':'Mesh off on frames 3–5','track':'mesh','value':{'off':[[3,5]]}});self.assertEqual(r.status_code,200,r.text)
        b=self.client.get(f'/jobs/{HEX}/export').json()['pending']
        self.assertEqual((b['total'],b['note'],b['problem'],b['estimated_cost_usd']),(1,'1 pending edit will be saved first (free) and the export made from the new run.',None,0.0));self.assertEqual(b['summary'],['face: mesh off on frames 3–5'])
        before=tree_hashes(self.parent);runs_before=sorted(p.name for p in self.runs.iterdir() if len(p.name)==32)
        r=self.client.post(f'/jobs/{HEX}/export',json={'preset':'custom','items':['mesh_alpha','landmarks','run'],'mesh_format':'png'});self.assertEqual(r.status_code,200,r.text);s=r.json();self.assertEqual(s['pending_edits'],1)
        s=self.poll(s['name']);self.assertEqual(s['state'],'done',s)
        child=s['exported_run'];self.assertNotEqual(child,HEX);self.assertEqual(s['requested_run'],HEX);self.assertEqual(s['run'],child)
        runs_after=sorted(p.name for p in self.runs.iterdir() if len(p.name)==32);self.assertEqual(len(runs_after),len(runs_before)+1,'exactly one child')
        run=json.loads((self.runs/child/'run.json').read_text());self.assertEqual((run['parent'],run['chain']['face']['tool'],run['changed']),(HEX,'mesh_edit','face: mesh off on frames 3–5'))
        self.assertIn(f'saved first as the new version {child}',s['readme']);self.assertIn('mesh off on frames 3–5',s['readme']);self.assertIn('exported from the new version',s['readme'])
        folder=Path(s['folder']);self.assertEqual(folder.parent.parent.name,child,'the export lives in the exported run')
        from PIL import Image
        for i in (3,4,5):self.assertEqual(int(np.asarray(Image.open(folder/'face-mesh'/f'frame_{i:05d}.png'))[:,:,3].max()),0,f'frame {i} was switched off')
        a=np.asarray(Image.open(folder/'face-mesh'/'frame_00000.png'));x,y=lip_point(0);self.assertGreater(int(a[y,x,3]),200);self.assertEqual(int(a[0,0,3]),0)
        self.assertGreater(int(np.asarray(Image.open(folder/'face-mesh'/'frame_00006.png'))[:,:,3].max()),0)
        lm=json.loads((folder/'face-landmarks.json').read_text());self.assertEqual([f['status'] for f in lm['frames'][3:6]],['off','off','off']);self.assertEqual(lm['frames'][4]['faces'],[])
        self.assertTrue((folder/'edit-layer.json').exists())
        self.assertEqual(self.client.get(f'/jobs/{HEX}/edits').json()['pending']['total'],0,'the session was closed by the save')
        for ident in (HEX,child):
            z=self.client.get(f'/jobs/{ident}/export/{s["name"]}.zip');self.assertEqual(z.status_code,200,ident)
            listing=self.client.get(f'/jobs/{ident}/export').json()['exports'];self.assertEqual([(e['name'],e['exported_run']) for e in listing],[(s['name'],child)])
        after=tree_hashes(self.parent);self.assertEqual({k:v for k,v in after.items() if not k.startswith('export/')},before,'the parent only gained its export record')
        self.assertEqual([p.name for p in (self.parent/'export').iterdir()],[s['name']+'.json'])
    def test_pending_edits_that_cannot_be_saved_or_would_cost_money_are_refused(self):
        editlayer.register_track('mask',RefusingTrack())
        self.client.put(f'/jobs/{HEX}/edits',json={'rev':0,'label':'clicks','track':'mask','value':{'n':3}})
        b=self.client.get(f'/jobs/{HEX}/export').json()['pending'];self.assertEqual(b['total'],3);self.assertIn('not applied yet',b['problem']['message']);self.assertEqual(b['problem']['track'],'mask');self.assertIsNone(b['note'])
        r=self.client.post(f'/jobs/{HEX}/export',json={'preset':'kling'});self.assertEqual(r.status_code,400);self.assertIn('not applied yet',r.json()['message']);self.assertIn('Apply',r.json()['fix'])
        editlayer.register_track('mask',PaidTrack())
        b=self.client.get(f'/jobs/{HEX}/export').json()['pending'];self.assertGreater(b['estimated_cost_usd'],0);self.assertIn('paid stage',b['problem']['message'])
        r=self.client.post(f'/jobs/{HEX}/export',json={'preset':'kling'});self.assertEqual(r.status_code,402,r.text);body=r.json()
        self.assertIn('paid stage',body['message']);self.assertIn('Save the edits from the editor',body['fix']);self.assertGreater(body['estimated_cost_usd'],0)
        self.assertEqual(sorted(p.name for p in self.runs.iterdir() if len(p.name)==32),[HEX],'nothing was branched');self.assertFalse((self.parent/'export').exists())

if __name__=='__main__':unittest.main()
