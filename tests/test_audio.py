import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from fractions import Fraction
import av,numpy as np
from audio_workflow import prepare_seedance_video,read_audio,write_audio,RATE
from pipeline import writer,put,finish

def sine(seconds=1,hz=440):
    n=int(RATE*seconds);return np.tile((np.sin(np.arange(n)*2*np.pi*hz/RATE)*.1).astype(np.float32),(2,1))

def make_upload(path,samples,codec='aac',container=None,frames=24):
    with av.open(str(path),'w',format=container) as out:
        v=out.add_stream('libx264',rate=24);v.width=64;v.height=64;v.pix_fmt='yuv420p'
        a=out.add_stream(codec,rate=RATE);a.layout='stereo'
        for i in range(frames):
            f=av.VideoFrame.from_ndarray(np.full((64,64,3),40,dtype=np.uint8),format='rgb24');f.pts=i;f.time_base=Fraction(1,24)
            for packet in v.encode(f):out.mux(packet)
        for packet in v.encode():out.mux(packet)
        for i in range(0,samples.shape[1],4096):
            f=av.AudioFrame.from_ndarray(np.ascontiguousarray(samples[:,i:i+4096]),format='fltp',layout='stereo');f.sample_rate=RATE;f.pts=i
            for packet in a.encode(f):out.mux(packet)
        for packet in a.encode():out.mux(packet)

def make_composite(path,frames=24):
    c,s=writer(path,64,64)
    for i in range(frames):put(c,s,np.full((64,64,3),150,dtype=np.uint8),i)
    finish(c,s)

def packets(path):
    with av.open(str(path)) as c:return [bytes(x) for x in c.demux(audio=0) if x.dts is not None]

def video_frames(path):
    with av.open(str(path)) as c:return sum(1 for _ in c.decode(video=0))

class AudioTests(unittest.TestCase):
 def test_default_embeds_original_audio_sample_for_sample(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);make_upload(p/'upload.mp4',sine());make_composite(p/'composite-silent.mp4')
   target=prepare_seedance_video(p,clean_dialogue=False)
   self.assertEqual(target,p/'seedance-input.mp4')
   self.assertTrue(np.array_equal(read_audio(p/'seedance-input.mp4'),read_audio(p/'upload.mp4')))
   self.assertEqual(packets(p/'upload.mp4'),packets(p/'seedance-input.mp4'))
   self.assertEqual(video_frames(p/'seedance-input.mp4'),24)
   manifest=json.loads((p/'audio-manifest.json').read_text())
   self.assertFalse(manifest['clean_dialogue']);self.assertEqual(manifest['audio_remux'],'copy')
   self.assertEqual(manifest['embedded_audio'],'entire original source audio');self.assertEqual(manifest['final_audio'],'entire original source audio')
   self.assertTrue(manifest['discard_seedance_audio']);self.assertEqual(manifest['seedance_video'],'seedance-input.mp4')
   self.assertFalse((p/'vocals.wav').exists())
 def test_default_signature_is_original_audio(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);make_upload(p/'upload.mp4',sine());make_composite(p/'composite-silent.mp4')
   prepare_seedance_video(p)
   self.assertEqual(packets(p/'upload.mp4'),packets(p/'seedance-input.mp4'))
   self.assertFalse(json.loads((p/'audio-manifest.json').read_text())['clean_dialogue'])
 def test_unmuxable_source_codec_is_reencoded(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);make_upload(p/'upload.mp4',sine(),codec='pcm_s16le',container='matroska');make_composite(p/'composite-silent.mp4')
   prepare_seedance_video(p,clean_dialogue=False)
   with av.open(str(p/'seedance-input.mp4')) as c:self.assertEqual(c.streams.audio[0].codec_context.name,'aac')
   embedded=read_audio(p/'seedance-input.mp4');original=read_audio(p/'upload.mp4')
   self.assertLess(abs(embedded.shape[1]-original.shape[1]),RATE//10)
   manifest=json.loads((p/'audio-manifest.json').read_text())
   self.assertEqual(manifest['audio_remux'],'reencoded');self.assertEqual(manifest['embedded_audio'],'entire original source audio');self.assertFalse(manifest['clean_dialogue'])
 def test_clean_dialogue_embeds_vocals(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);make_upload(p/'upload.mp4',sine(hz=220));make_composite(p/'composite-silent.mp4')
   vocals=sine(hz=880);write_audio(p/'vocals.wav',vocals)
   (p/'audio-manifest.json').write_text(json.dumps({'prediction_id':'demucs-test'}))
   prepare_seedance_video(p,clean_dialogue=True)
   embedded=read_audio(p/'seedance-input.mp4')
   self.assertLess(abs(embedded.shape[1]-vocals.shape[1]),RATE//10)
   self.assertNotEqual(packets(p/'upload.mp4'),packets(p/'seedance-input.mp4'))
   # The embedded tone is the 880 Hz vocal stem, not the 220 Hz source mix.
   spectrum=np.abs(np.fft.rfft(embedded[0,:RATE]));self.assertEqual(int(np.argmax(spectrum)),880)
   manifest=json.loads((p/'audio-manifest.json').read_text())
   self.assertTrue(manifest['clean_dialogue']);self.assertEqual(manifest['embedded_audio'],'vocals.wav (Demucs)');self.assertEqual(manifest['prediction_id'],'demucs-test')
   self.assertEqual(manifest['final_audio'],'entire original source audio');self.assertTrue(manifest['discard_seedance_audio'])
 def test_clean_dialogue_requires_vocals(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);make_upload(p/'upload.mp4',sine());make_composite(p/'composite-silent.mp4')
   with self.assertRaisesRegex(ValueError,'vocals.wav'):prepare_seedance_video(p,clean_dialogue=True)
   self.assertFalse((p/'seedance-input.mp4').exists())

def run_pipeline(folder,clean_dialogue):
 import pipeline
 def fake_depth(src,dst,*a,**k):Path(dst).write_bytes(b'depth')
 with patch('audio_workflow.separate') as separate,patch('audio_workflow.prepare_seedance_video') as prepare,patch('pipeline.normalize',return_value={'frames':1}),patch('pipeline.depth_replicate',side_effect=fake_depth),patch('raw_masks.segment_raw',return_value=folder/'masks'),patch('raw_masks.clean_border_fragments',side_effect=lambda x:x),patch('pipeline.composite'):
  pipeline.run(folder/'upload.mp4',folder,'person','replicate',lambda s:None,clean_dialogue)
 return separate,prepare

class PipelineAudioTests(unittest.TestCase):
 def test_separate_skipped_without_clean_dialogue(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);separate,prepare=run_pipeline(p,False)
   separate.assert_not_called();prepare.assert_called_once_with(p,False)
   self.assertFalse(json.loads((p/'manifest.json').read_text())['clean_dialogue'])
 def test_separate_runs_with_clean_dialogue(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);separate,prepare=run_pipeline(p,True)
   separate.assert_called_once();prepare.assert_called_once_with(p,True)
   self.assertTrue(json.loads((p/'manifest.json').read_text())['clean_dialogue'])

if __name__=='__main__':unittest.main()
