"""Input doctor: checks, safe fixes with before/after notes, advice, never blocking. Offline and free.

The dark, small-face clip is built from the first 24 frames of the real fixture run (`runs/85e5…/original.mp4`,
read only): each frame is darkened to 25 % and shrunk to a seventh of the frame on a black canvas with a small
jitter, so the face is about 9 % of the frame height and the camera "shakes". The doctor must brighten the working
copy (with a before/after note), find the small face only when zoomed in, write the zoomed tracking copy, warn
about the shake, and still finish with state done. The face check really runs MediaPipe through .venv-face when it
is installed; otherwise it is injected.
"""
import unittest,tempfile,json,os
from pathlib import Path
from unittest.mock import patch
from fractions import Fraction
import numpy as np

ROOT=Path(__file__).resolve().parents[1];FIXTURE=ROOT/'runs/85e5dbe64df1464fa63825319ebfa104/original.mp4';WORKER=ROOT/'.venv-face/bin/python'

def write_clip(path,frames,fps=24):
    import av
    with av.open(str(path),'w') as c:
        s=c.add_stream('libx264',rate=fps);s.width=frames[0].shape[1];s.height=frames[0].shape[0];s.pix_fmt='yuv420p';s.options={'crf':'18','preset':'ultrafast'}
        for i,a in enumerate(frames):
            f=av.VideoFrame.from_ndarray(a,format='rgb24');f.pts=i;f.time_base=Fraction(1,fps)
            for p in s.encode(f):c.mux(p)
        for p in s.encode():c.mux(p)

def dark_small_face_clip(path,n=24,dark=0.25,shrink=7,jitter=True):
    """First n fixture frames, darkened and shrunk onto a 960×550 black canvas; returns the face box the fixture shows."""
    import av
    from PIL import Image
    rng=np.random.default_rng(7);frames=[]
    with av.open(str(FIXTURE)) as c:
        for i,f in enumerate(c.decode(video=0)):
            if i>=n:break
            a=(f.to_ndarray(format='rgb24').astype(np.float32)*dark).astype(np.uint8);h,w=a.shape[:2]
            small=np.asarray(Image.fromarray(a).resize((w//shrink//2*2,h//shrink//2*2),Image.Resampling.LANCZOS))
            canvas=np.zeros((550,960,3),np.uint8);sh,sw=small.shape[:2]
            dy,dx=(rng.integers(-16,17),rng.integers(-16,17)) if jitter else (0,0)
            y0=(550-sh)//2+int(dy);x0=(960-sw)//2+int(dx);canvas[y0:y0+sh,x0:x0+sw]=small;frames.append(canvas)
    write_clip(path,frames)
    return frames

def run_doctor(folder,params=None,status=lambda s:None):
    import stages
    tool=stages.get_tool('input_doctor','doctor');folder=Path(folder)
    return tool.run({'source':folder/'upload.mp4','folder':folder,'seconds':1.0},tool.normalize_params(params or {}),folder,status)

@unittest.skipUnless(FIXTURE.exists(),'needs the 85e5dbe6 fixture run')
class DoctorOnDarkSmallFaceClip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.folder=Path(cls.tmp.name)/('d'*32);cls.folder.mkdir()
        dark_small_face_clip(cls.folder/'upload.mp4')
        patches=[]
        if not WORKER.exists():   # no MediaPipe worker here: inject a small face found only when zoomed in
            patches.append(patch('stages.input_doctor.detect_faces',return_value={'detector':'injected','frames':[{'frame':i,'box':[0.46,0.42,0.53,0.51],'zoomed':True} for i in range(0,24,2)]}))
        for p in patches:p.start()
        try:cls.result=run_doctor(cls.folder)
        finally:
            for p in patches:p.stop()
        cls.data=cls.result['data'];cls.saved=json.loads((cls.folder/'input-doctor.json').read_text())
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_dark_detected_and_brightened_with_a_before_after_note(self):
        fixes={f['name']:f for f in self.data['fixes']}
        self.assertIn('brightness',fixes,self.data)
        fix=fixes['brightness'];self.assertLess(fix['before'],0.12);self.assertGreater(fix['after'],fix['before']);self.assertLessEqual(fix['gamma'],1.8)
        self.assertRegex(fix['note'],r'mean luma 0\.\d+ → 0\.\d+ \(gamma 1\.\d+');self.assertIn('original upload is untouched',fix['note'])
        self.assertTrue(any(c.startswith('Brightness:') and c.endswith('dark.') for c in self.data['checks']),self.data['checks'])
        self.assertEqual(self.data['measurements']['luma']['after'],fix['after'])
        self.assertGreater((self.folder/'original.mp4').stat().st_size,0)
    def test_small_face_detected_with_advice_and_zoomed_tracking_copy(self):
        self.assertTrue(any('Face is small' in a and 'move closer' in a for a in self.data['advice']),self.data['advice'])
        self.assertTrue(any(c.startswith('Face:') and c.endswith('small.') for c in self.data['checks']),self.data['checks'])
        face=self.data['measurements']['face'];self.assertLess(face['median_height_fraction'],0.12);self.assertGreater(face['frames_with_face'],0)
        fixes={f['name']:f for f in self.data['fixes']};self.assertIn('tracking_source',fixes,self.data['fixes'])
        self.assertIn('tracking-source.mp4',fixes['tracking_source']['note']);self.assertIn('untouched',fixes['tracking_source']['note'])
        self.assertTrue((self.folder/'tracking-source.mp4').exists());info=json.loads((self.folder/'tracking-source.json').read_text())
        self.assertEqual(info['original'],{'width':960,'height':550});self.assertLess(info['crop']['h'],550);self.assertGreater(fixes['tracking_source']['after'],fixes['tracking_source']['before'])
        import av
        with av.open(str(self.folder/'tracking-source.mp4')) as c:self.assertEqual(c.streams.video[0].frames,24)   # same frame count as the working copy
        self.assertIn('tracking-source.mp4',self.result['outputs'])
    def test_shake_warned_never_blocked(self):
        self.assertTrue(any('shakes' in w for w in self.result['warnings']),self.result['warnings'])
        self.assertTrue(any('Stabilise' in a for a in self.data['advice']))
        self.assertTrue(any(c.startswith('Shake:') for c in self.data['checks']))
        self.assertEqual(self.result['frames']['covered'],24);self.assertIn('fixes: brightened, zoomed tracking copy',self.result['health'])
        self.assertEqual(set(self.saved),{'checks','warnings','advice','fixes','measurements'});self.assertEqual(self.saved['checks'],self.data['checks'])
    def test_upload_untouched_and_working_copy_frame_count(self):
        import av
        with av.open(str(self.folder/'upload.mp4')) as c:self.assertEqual(c.streams.video[0].frames,24)
        self.assertEqual(self.data['normalized']['frames'],24)

@unittest.skipUnless(FIXTURE.exists(),'needs the 85e5dbe6 fixture run')
class DoctorLeavesGoodClipsAlone(unittest.TestCase):
    def test_bright_big_face_clip_gets_no_fix_and_original_matches_probe(self):
        import av,stages
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/('e'*32);folder.mkdir();frames=[]
            with av.open(str(FIXTURE)) as c:
                for i,f in enumerate(c.decode(video=0)):
                    if i>=12:break
                    frames.append(np.clip(f.to_ndarray(format='rgb24').astype(np.int16)+40,0,255).astype(np.uint8))   # lift the dark background above the threshold
            write_clip(folder/'upload.mp4',frames)
            with patch('stages.input_doctor.detect_faces',return_value={'detector':'injected','frames':[{'frame':i,'box':[0.3,0.1,0.7,0.8],'zoomed':False} for i in range(0,12,2)]}):
                result=run_doctor(folder)
            self.assertEqual([f['name'] for f in result['data']['fixes']],[]);self.assertIn('no fix needed',result['health'])
            self.assertFalse((folder/'tracking-source.mp4').exists());self.assertTrue(any(c.endswith('fine.') and c.startswith('Face') for c in result['data']['checks']))
            # the working copy is byte-identical to what `probe` (pipeline.normalize alone) writes: no fix means no rewrite
            other=Path(d)/('f'*32);other.mkdir();os.link(folder/'upload.mp4',other/'upload.mp4')
            probe=stages.get_tool('input_doctor','probe');probe.run({'source':other/'upload.mp4','folder':other},{},other,lambda s:None)
            self.assertEqual((folder/'original.mp4').read_bytes(),(other/'original.mp4').read_bytes())
    def test_unreadable_upload_degrades_to_warnings_and_lets_normalize_report(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/('a'*32);folder.mkdir();(folder/'upload.mp4').write_bytes(b'not a video')
            with patch('pipeline.normalize',return_value={'frames':3,'fps':24,'width':64,'height':64,'duration':.125}) as normalize:
                result=run_doctor(folder)
            normalize.assert_called_once();self.assertTrue(any('could not be probed' in w for w in result['warnings']))
            self.assertTrue(any('could not be analysed' in w for w in result['warnings']));self.assertEqual(result['frames']['covered'],3);self.assertEqual(result['data']['normalized']['frames'],3)
            self.assertTrue((folder/'input-doctor.json').exists())

class DoctorRegistryAndKeys(unittest.TestCase):
    def test_doctor_is_the_default_and_probe_stays(self):
        import stages
        self.assertEqual([t.name for t in stages.tools_for('input_doctor')],['probe','doctor'])
        for mode in ('depth','face_mesh','depth_mesh'):self.assertEqual(stages.chain_for_mode(mode)['input_doctor']['tool'],'doctor',mode)
        for preset in stages.list_presets():
            if preset['builtin']:self.assertEqual(preset['chain']['input_doctor']['tool'],'doctor',preset['name'])
        doctor=stages.get_tool('input_doctor','doctor');self.assertFalse(doctor.paid)
        self.assertEqual(doctor.normalize_params({})['dark_luma'],0.12);self.assertEqual(doctor.normalize_params({'small_face':'0.2'})['small_face'],0.2)
    def test_thresholds_are_part_of_the_cache_key(self):
        import stages
        from stages import cache
        doctor=stages.get_tool('input_doctor','doctor');hashes={'upload.mp4':'abc'}
        a=cache.cache_key('input_doctor','doctor',doctor.normalize_params({}),hashes);b=cache.cache_key('input_doctor','doctor',doctor.normalize_params({'dark_luma':0.3}),hashes)
        self.assertNotEqual(a,b);self.assertNotEqual(a,cache.cache_key('input_doctor','probe',{},hashes))
    def test_landmark_mapping_back_to_the_full_frame(self):
        from mesh_tracking import map_landmarks
        crop={'x0':100,'y0':50,'w':400,'h':200};original={'width':960,'height':550}
        self.assertEqual(map_landmarks([(0.0,0.0),(1.0,1.0),(0.5,0.5)],crop,original),[(100/960,50/550),(500/960,250/550),(300/960,150/550)])
        self.assertEqual(map_landmarks([],crop,original),[]);self.assertIsNone(map_landmarks(None,crop,original))

if __name__=='__main__':unittest.main()


class ForgivingInputTests(unittest.TestCase):
    """Review fix pass (2026-10-23): a silent source and a non-video upload fail softly, in plain words."""
    def silent_clip(self,path,frames=12):
        import av,numpy as np
        from fractions import Fraction
        with av.open(str(path),'w') as out:
            s=out.add_stream('libx264',rate=24);s.width=64;s.height=48;s.pix_fmt='yuv420p'
            for i in range(frames):
                f=av.VideoFrame.from_ndarray(np.full((48,64,3),i*10,np.uint8),format='rgb24');f.pts=i;f.time_base=Fraction(1,24)
                for p in s.encode(f):out.mux(p)
            for p in s.encode():out.mux(p)
    def test_source_without_audio_gives_a_silent_prepared_clip_and_export(self):
        import json,shutil,audio_workflow
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.silent_clip(p/'upload.mp4');shutil.copy(p/'upload.mp4',p/'composite-silent.mp4')
            target=audio_workflow.prepare_seedance_video(p)
            self.assertTrue(target.exists());manifest=json.loads((p/'audio-manifest.json').read_text())
            self.assertEqual(manifest['audio_remux'],'video only');self.assertIn('no audio track',manifest['embedded_audio']);self.assertIn('silent',manifest['warning'])
            shutil.copy(p/'upload.mp4',p/'seedance-result.mp4');final=audio_workflow.finish_preview(p/'seedance-result.mp4',p)
            self.assertTrue(final.exists());self.assertIn('no audio track',json.loads((p/'audio-note.json').read_text())['final_audio'])
    def test_non_video_upload_fails_in_plain_words(self):
        from stages.input_doctor import normalize_or_explain,UnreadableVideo
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'upload.mp4').write_text('not a video')
            with self.assertRaises(UnreadableVideo) as ctx:normalize_or_explain(p/'upload.mp4',p/'original.mp4')
            self.assertIn('could not be read as a video',str(ctx.exception));self.assertIn('MP4 or MOV',ctx.exception.fix);self.assertNotIn('Errno',str(ctx.exception))
