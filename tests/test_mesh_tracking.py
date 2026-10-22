import unittest
from mesh_tracking import face_box,clamp_box,smooth_box,fill_gaps,ranges,evaluate,MAX_GAP

def face(x,y,size=0.1):return [(x,y),(x+size,y),(x,y+size),(x+size,y+size)]

class CropBoxTests(unittest.TestCase):
 def test_face_box_pads_and_centres(self):
  box=face_box(face(.4,.4,.2),1000,1000)
  self.assertEqual(box,(320,320,680,680))  # 200 px face, 1.8x pad = 360 px square around (500,500)
 def test_face_box_clamps_to_frame_and_minimum_size(self):
  x0,y0,x1,y1=face_box(face(.95,.95,.04),960,540)
  self.assertTrue(0<=x0<x1<=960 and 0<=y0<y1<=540)   # corner face: clamped inside the frame
  x0,y0,x1,y1=face_box(face(.5,.5,.01),960,540)
  self.assertEqual((x1-x0,y1-y0),(96,96))   # tiny face: minimum crop size
  self.assertEqual(clamp_box((-50,-50,2000,2000),640,480),(0,0,640,480))
 def test_smooth_box_averages_recent_boxes(self):
  history=[]
  self.assertEqual(smooth_box(history,(0,0,100,100)),(0,0,100,100))
  self.assertEqual(smooth_box(history,(10,10,110,110)),(5,5,105,105))
  for _ in range(10):last=smooth_box(history,(20,20,120,120),window=5)
  self.assertEqual(last,(20,20,120,120));self.assertEqual(len(history),5)

class GapFillingTests(unittest.TestCase):
 def test_short_interior_gap_is_interpolated_and_marked_filled(self):
  frames=[face(0,0),None,None,None,face(.4,.8)]
  out,status=fill_gaps(frames)
  self.assertEqual(status,['tracked','filled','filled','filled','tracked'])
  self.assertAlmostEqual(out[1][0][0],.1);self.assertAlmostEqual(out[2][0][0],.2);self.assertAlmostEqual(out[3][0][1],.6)
  self.assertEqual(len(out[2]),4)
 def test_gap_at_the_limit_is_filled_and_one_longer_is_not(self):
  out,status=fill_gaps([face(0,0)]+[None]*MAX_GAP+[face(1,1)])
  self.assertEqual(status.count('filled'),MAX_GAP);self.assertNotIn('missing',status)
  out,status=fill_gaps([face(0,0)]+[None]*(MAX_GAP+1)+[face(1,1)])
  self.assertEqual(status.count('missing'),MAX_GAP+1);self.assertEqual(out[3],None)
 def test_edge_gaps_hold_nearest_tracked_frame(self):
  out,status=fill_gaps([None,None,face(.5,.5),None])
  self.assertEqual(status,['filled','filled','tracked','filled']);self.assertEqual(out[0],face(.5,.5));self.assertEqual(out[3],face(.5,.5))
 def test_all_missing_stays_missing(self):
  out,status=fill_gaps([None]*4);self.assertEqual(status,['missing']*4)

class GapRuleTests(unittest.TestCase):
 def test_ranges_in_seconds(self):
  status=['tracked']*48+['missing']*20+['tracked']*10
  self.assertEqual(ranges(status,24),[{'start_frame':48,'end_frame':67,'frames':20,'start_s':2.0,'end_s':2.83}])
 def test_long_gap_fails_with_second_ranges(self):
  frames=[face(0,0)]*48+[None]*20+[face(0,0)]*34+[None]*18+[face(0,0)]*75
  _,status=fill_gaps(frames);report=evaluate(status,24)
  self.assertFalse(report['ok']);self.assertIn('lost face 2.0–2.83 s, 4.25–5.0 s',report['message'])
  self.assertEqual((report['tracked'],report['filled'],report['missing']),(157,0,38))
 def test_short_gaps_pass_and_are_reported_as_filled(self):
  frames=[face(0,0)]*100+[None]*5+[face(0,0)]*95
  _,status=fill_gaps(frames);report=evaluate(status,24)
  self.assertTrue(report['ok']);self.assertEqual(report['filled'],5);self.assertEqual(report['gaps'],[])
  self.assertEqual(report['filled_ranges'][0]['start_s'],4.17);self.assertEqual(report['message'],'face tracked throughout')
 def test_many_short_gaps_pass_with_a_warning(self):
  frames=([face(0,0)]*10+[None]*4)*10   # 40 of 140 frames interpolated, every gap short
  _,status=fill_gaps(frames);report=evaluate(status,24)
  self.assertTrue(report['ok']);self.assertEqual(report['missing'],0);self.assertIn('29% of frames were not detected directly (40 interpolated)',report['warning'])
 def test_missing_ratio_rule(self):
  status=['tracked']*80+['missing']*20   # one long gap: 20% missing
  report=evaluate(status,24);self.assertFalse(report['ok']);self.assertIn('20% of frames missing (limit 15%)',report['message']);self.assertIn('lost face 3.33–4.17 s',report['message'])
  self.assertEqual(evaluate(['tracked']*100,24)['warning'],'')
 def test_exactly_fifteen_percent_passes(self):
  frames=[face(0,0)]*85+[None]*3+[face(0,0)]*9+[None]*3+[face(0,0)]*100   # 6 of 200 untracked
  _,status=fill_gaps(frames);self.assertTrue(evaluate(status,24)['ok'])
  frames=[face(0,0)]*170+[None]*6+[face(0,0)]*18+[None]*6   # 12 of 200 = 6%
  _,status=fill_gaps(frames);self.assertTrue(evaluate(status,24)['ok'])
 def test_empty_clip_fails(self):
  self.assertFalse(evaluate([],24)['ok'])
if __name__=='__main__':unittest.main()
