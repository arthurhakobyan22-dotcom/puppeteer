"""Prompt builder with fences + Claude vision fill (World stage, Agent 2).

- assemble: char1 + char2 + set + look → every ref has exactly one job sentence + fence, numbered 1..4 in attachment order, fences_ok empty;
  a prompt-only look lands in the text; beats come from words.json (and from pending edits when a session has them); the closing line
  appears once, with the mesh / depth clauses only when the run has them; an identity video is @Video2 and the set image @Image1.
- fences_ok: a ref without its job, two jobs, a numbering gap.
- build_prompt: unchanged for the two-reference case (the old string), one extra sentence per set / look ref numbered in upload order.
- fal / Enhancor submit_draft upload the set and look images after the character references, in that order.
- seedance_bridge.submit writes `refs` + `slots` into generation.json; the seedance route passes the slots' set / look images.
- POST /jobs/{id}/prompt/assemble → text + refs + full_prompt; warnings for a hand-edited text.
- vision: mocked requests.post → parsed SET / LIGHT, JPEG base64 payload, the instruction forbids people, the mask region is gray,
  missing key → 400 with the how-to, offline → plain error, 402 without confirm_cost, apply=true writes the two slots.
- stages.export prompt.txt uses the assembled text.
"""
import unittest,tempfile,json,io,os,base64
from pathlib import Path
from unittest.mock import patch,Mock
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient
import app as application,stages,seedance_bridge
from stages import promptkit,vision,slots,costs
from providers.base import build_prompt
from tests.test_world import synthetic_run,HEX,plate_png,write_clip,RED

OLD_TWO_REF="Base\n@Video1 is the colored-depth composite with the original dialogue embedded; use its embedded audio for performance and lip synchronization. @Image2 defines the second character's identity only, under the same rules."
WORDS=[{'text':'Hello','start':0.05,'end':0.15},{'text':'there.','start':0.15,'end':0.25},{'text':'Go','start':0.3,'end':0.45}]   # inside the 0.5 s synthetic clip

def world_run(d,mode='depth_mesh',char1='png',char2=True,words=True):
    """A synthetic run with saved references, the two assets and words.json; returns (run folder, runs root, set asset name, look asset name)."""
    root=Path(d);p=synthetic_run(root/HEX);(p/'workflow-mode.json').write_text(json.dumps({'mode':mode}))
    (p/f'char1-reference.{char1}').write_bytes(plate_png() if char1=='png' else b'identity')
    if char2:(p/'char2-reference.jpg').write_bytes(plate_png())
    assets=root/'_assets';assets.mkdir(exist_ok=True);set_name='a'*16+'.png';look_name='b'*16+'.jpg'
    (assets/set_name).write_bytes(plate_png((20,200,20)));(assets/look_name).write_bytes(plate_png((200,20,20)))
    if words:(p/'words.json').write_text(json.dumps({'engine':'test','words':WORDS}))
    return p,root,set_name,look_name

FULL={'set':{'mode':'set_ref','image':'a'*16+'.png','prompt':''},'look':{'mode':'style_ref','image':'b'*16+'.jpg','prompt':''},'light':'soft window light from the left'}

class AssembleTests(unittest.TestCase):
    def test_four_refs_one_fence_each_in_attachment_order(self):
        with tempfile.TemporaryDirectory() as d:
            p,root,set_name,look_name=world_run(d);slots.write(p,FULL)
            out=promptkit.assemble(p,runs_root=root)
            self.assertEqual([(r['n'],r['token'],r['slot'],r['file']) for r in out['refs']],[(1,'@Image1','char1','char1-reference.png'),(2,'@Image2','char2','char2-reference.jpg'),(3,'@Image3','set',set_name),(4,'@Image4','look',look_name)])
            text=out['text']
            for r in out['refs']:
                self.assertEqual(text.count(r['fence']),1,r['token']);self.assertIn(r['token']+' defines',r['fence'])
            self.assertIn("@Image1 defines the character's identity only (face, hair, outfit, proportions); do not copy its pose, expression, props, background or lighting.",text)
            self.assertIn('@Image3 defines the set only (walls, floor, furniture, depth of the room); do not use its people or lighting.',text)
            self.assertIn('@Image4 defines the rendering style only (palette, grain, contrast, brushwork); do not copy its content, people or layout.',text)
            self.assertEqual(promptkit.fences_ok(text,out['refs']),[]);self.assertEqual(out['warnings'],[])
            self.assertEqual([s['name'] for s in out['sections']],['CHARACTER','SET','LOOK','DIALOGUE BEATS','LIGHT','CONSTRAINTS'])
            self.assertLess(text.index('CHARACTER'),text.index('SET:'));self.assertLess(text.index('SET:'),text.index('LOOK:'));self.assertLess(text.index('LOOK:'),text.index('Dialogue beats'));self.assertLess(text.index('Dialogue beats'),text.index('LIGHT:'))
            self.assertIn('LIGHT: soft window light from the left',text)
            closing='Keep the camera, crop, timing and every word of the embedded dialogue; replace the whole identity including hair; remove any mesh lines or depth colours from the output.'
            self.assertEqual(text.count(closing),1);self.assertTrue(text.endswith(closing));self.assertEqual(out['closing'],closing)
    def test_beats_from_words_json_then_pending_edits(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            p,root,_,_=world_run(d);client=TestClient(application.app)
            out=promptkit.assemble(p,runs_root=root);route=client.get(f'/jobs/{HEX}/words/beats').json()
            self.assertEqual(out['beats'],route['text']);self.assertIn(out['beats'],out['text'])
            self.assertIn(' s says: "Hello there."',out['text']);self.assertIn(' s says: "Go"',out['text'])
            rev=client.get(f'/jobs/{HEX}/edits').json().get('rev')
            r=client.put(f'/jobs/{HEX}/edits',json={'rev':rev,'layer':{'words':{'words':[{'text':'Changed','start':0.1,'end':0.5}]}}});self.assertEqual(r.status_code,200,r.text)
            out=promptkit.assemble(p,runs_root=root);self.assertIn('says: "Changed"',out['text']);self.assertNotIn('Hello there',out['text'])
            self.assertEqual(out['beats'],client.get(f'/jobs/{HEX}/words/beats').json()['text'])
            client.delete(f'/jobs/{HEX}/edits')
    def test_prompt_only_look_set_modes_and_clauses(self):
        with tempfile.TemporaryDirectory() as d:
            p,root,_,_=world_run(d,mode='depth',char2=False,words=False)
            out=promptkit.assemble(p,{'look':{'mode':'prompt','prompt':'16 mm film, muted palette, soft grain'},'set':{'mode':'prompt','prompt':'a small kitchen with white tiles'}},runs_root=root)
            self.assertIn('LOOK: 16 mm film, muted palette, soft grain',out['text']);self.assertIn('SET: a small kitchen with white tiles',out['text'])
            self.assertEqual([r['token'] for r in out['refs']],['@Image1']);self.assertNotIn('Dialogue beats',out['text']);self.assertNotIn('LIGHT:',out['text'])
            self.assertTrue(out['text'].endswith('Keep the camera, crop, timing and every word of the embedded dialogue; remove any depth colours from the output.'))   # depth run: no mesh clauses
            self.assertNotIn('SET:',promptkit.assemble(p,{'set':{'mode':'original'}},runs_root=root)['text'])
            self.assertIn('SET: '+promptkit.DEPTH_LINE,promptkit.assemble(p,{'set':{'mode':'original_depth'}},runs_root=root)['text'])
            self.assertIn('SET: '+promptkit.PLATE_LINE,promptkit.assemble(p,{'set':{'mode':'true_swap','image':'a'*16+'.png'}},runs_root=root)['text'])
            self.assertEqual(len(promptkit.assemble(p,{'set':{'mode':'true_swap','image':'a'*16+'.png'}},runs_root=root)['refs']),1)   # the plate is in the composite, not a ref
            warned=promptkit.assemble(p,{'set':{'mode':'set_ref','image':None}},runs_root=root);self.assertTrue(any('no set image' in w for w in warned['warnings']))
            (p/'workflow-mode.json').write_text(json.dumps({'mode':'face_mesh'}));(p/'depth.mp4').unlink()
            self.assertTrue(promptkit.assemble(p,{},runs_root=root)['text'].endswith('; replace the whole identity including hair; remove any mesh lines from the output.'))
    def test_identity_video_is_video2_and_set_image_is_image1(self):
        with tempfile.TemporaryDirectory() as d:
            p,root,set_name,_=world_run(d,char1='mp4',char2=False);out=promptkit.assemble(p,{'set':{'mode':'set_ref','image':set_name}},runs_root=root)
            self.assertEqual([(r['token'],r['slot'],r['kind']) for r in out['refs']],[('@Video2','char1','video'),('@Image1','set','image')])
            self.assertIn("@Video2 defines the character's identity only",out['text']);self.assertIn('@Image1 defines the set only',out['text']);self.assertEqual(out['warnings'],[])
    def test_fences_ok_problems(self):
        refs=promptkit.number_refs([('char1',Path('a.png')),('set',Path('s.png'))])
        self.assertEqual(promptkit.fences_ok(refs[0]['fence']+' '+refs[1]['fence'],refs),[])
        self.assertTrue(any('never mentions' in w for w in promptkit.fences_ok('Just a prompt.',refs)))
        self.assertTrue(any('without its job' in w for w in promptkit.fences_ok('Use @Image1 and @Image2 as you like.',refs)))
        self.assertTrue(any('2 job sentences' in w for w in promptkit.fences_ok(refs[0]['fence']+' @Image1 defines the set only. '+refs[1]['fence'],refs)))
        self.assertTrue(any('@Image5 is mentioned' in w for w in promptkit.fences_ok(refs[0]['fence']+' '+refs[1]['fence']+' @Image5 defines the hat only.',refs)))
        self.assertTrue(any('@Video2' in w for w in promptkit.fences_ok(refs[0]['fence']+' '+refs[1]['fence']+' @Video2 is the voice.',refs)))

class BuildPromptTests(unittest.TestCase):
    def test_two_ref_case_is_the_old_string_and_extra_refs_add_sentences(self):
        with tempfile.TemporaryDirectory() as d:
            full,mode=build_prompt('Base',d,{'char1':Path('a.png'),'char2':Path('b.png')});self.assertEqual((full,mode),(OLD_TWO_REF,'edit'))
            full,_=build_prompt('Base',d,{'char1':Path('a.png'),'char2':Path('b.png'),'set':Path('s.png'),'look':Path('l.png')})
            self.assertEqual(full,OLD_TWO_REF+' @Image3 is the set reference only. @Image4 is the style reference only.')
            full,_=build_prompt('Base',d,{'char1':Path('a.png'),'char2':None,'look':Path('l.png')});self.assertTrue(full.endswith(' @Image2 is the style reference only.'));self.assertNotIn('set reference',full)
            full,mode=build_prompt('Base',d,{'char1':Path('a.mp4'),'char2':None,'set':Path('s.png')});self.assertEqual(mode,'multi_reference');self.assertTrue(full.endswith(' @Image1 is the set reference only.'))
            full,_=build_prompt('Base',d,{'char1':Path('a.png'),'char2':None,'set':None,'look':None});self.assertFalse(full.endswith('only.') and 'reference only' in full)

class AdapterOrderTests(unittest.TestCase):
    def test_fal_uploads_set_then_look_after_the_characters(self):
        from providers import fal as falmod
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'seedance-input.mp4').write_bytes(b'v');(p/'c1.png').write_bytes(b'i');(p/'c2.png').write_bytes(b'i');(p/'set.png').write_bytes(b'i');(p/'look.jpg').write_bytes(b'i')
            submit=Mock(return_value=Mock(request_id='fal-req'))
            with patch('providers.fal.setting',side_effect=lambda k,v='':{'FAL_KEY':'k','FAL_TASK':'editing'}.get(k,v)),patch('providers.fal.credential',return_value='k'),patch('providers.fal.load_env'),patch('providers.fal.check_video_constraints'),patch('providers.fal.check_image_constraints') as checked,\
                 patch('providers.fal.fal_client.upload_file',side_effect=lambda f,**k:'https://v3.fal.media/files/'+Path(f).name),patch('providers.fal.fal_client.submit',submit),patch('requests.post',side_effect=AssertionError('network')):
                falmod.Fal().submit_draft(p/'seedance-input.mp4',{'char1':p/'c1.png','char2':p/'c2.png','set':p/'set.png','look':p/'look.jpg'},'Base',folder=p,status=lambda s:None)
            payload=submit.call_args.kwargs['arguments']
            self.assertEqual(payload['image_urls'],['https://v3.fal.media/files/c1.png','https://v3.fal.media/files/c2.png','https://v3.fal.media/files/set.png','https://v3.fal.media/files/look.jpg'])
            self.assertTrue(payload['prompt'].endswith(' @Image3 is the set reference only. @Image4 is the style reference only.'))
            self.assertEqual([c.args[0] for c in checked.call_args_list][-2:],[p/'set.png',p/'look.jpg'])
    def test_enhancor_images_in_the_same_order(self):
        from providers import enhancor as enh
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);response=Mock(ok=True);response.json.return_value={'requestId':'enh-1'}
            for n in ('seedance-input.mp4','c1.png','set.png','look.jpg'):(p/n).write_bytes(b'x')
            with patch('providers.enhancor.credential',return_value='secret'),patch('providers.enhancor.setting',side_effect=lambda k,v='':{'ENHANCOR_WEBHOOK_URL':'https://example.org/cb','ENHANCOR_BASE_URL':'https://enhancor.test/v1'}.get(k,v)),patch('providers.enhancor.upload',side_effect=lambda f:'https://h/'+Path(f).name),patch('providers.enhancor.requests.post',return_value=response) as post:
                enh.Enhancor().submit_draft(p/'seedance-input.mp4',{'char1':p/'c1.png','char2':None,'set':p/'set.png','look':p/'look.jpg'},'Base',folder=p,status=lambda s:None)
            payload=post.call_args.kwargs['json'];self.assertEqual(payload['images'],['https://h/c1.png','https://h/set.png','https://h/look.jpg']);self.assertEqual(payload['videos'],['https://h/seedance-input.mp4'])
            self.assertTrue(payload['prompt'].endswith(' @Image2 is the set reference only. @Image3 is the style reference only.'))

class FakeAdapter:
    name='fal';label='fake';draft_endpoint=None
    def __init__(self):self.refs=None
    def require_configured(self):pass
    def capabilities(self):return {'finalize':'complete_draft','prompt':True}
    def submit_draft(self,prepared,refs,prompt,*,folder,status=print,task=None):
        self.refs=dict(refs);(Path(folder)/'seedance-request.json').write_text(json.dumps({'prompt':prompt,'task':task or 'editing'}));return 'req-1'

class SubmitTests(unittest.TestCase):
    def test_generation_json_records_refs_and_slots_and_the_route_passes_the_slot_images(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)),patch('mask_review.require_approved'),patch('seedance_bridge.wait_and_finish'),patch.dict(application.jobs,{},clear=False):
            p,root,set_name,look_name=world_run(d);(p/'audio-manifest.json').write_text('{}');(p/'seedance-input.mp4').write_bytes(b'prepared')
            slots.write(p,FULL);adapter=FakeAdapter();client=TestClient(application.app)
            with patch('seedance_bridge.get_provider',return_value=adapter):
                r=client.post(f'/jobs/{HEX}/seedance',data={'prompt':'Base','provider':'fal','confirm_cost':'true'},files=[('char1',('hero.png',plate_png(),'image/png')),('char2',('second.jpg',plate_png(),'image/jpeg'))])
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual((adapter.refs['set'],adapter.refs['look']),(root/'_assets'/set_name,root/'_assets'/look_name));self.assertEqual(adapter.refs['char1'],p/'char1-reference.png')
            g=json.loads((p/'generation.json').read_text())
            self.assertEqual([(x['n'],x['token'],x['slot'],x['file']) for x in g['refs']],[(1,'@Image1','char1','char1-reference.png'),(2,'@Image2','char2','char2-reference.jpg'),(3,'@Image3','set',set_name),(4,'@Image4','look',look_name)])
            self.assertEqual(g['slots']['set']['mode'],'set_ref');self.assertEqual(g['slots']['light'],FULL['light']);self.assertTrue(g['prompt'].endswith(' @Image3 is the set reference only. @Image4 is the style reference only.'))
            for name in ('seedance-response.json','generation.json','seedance-request.json'):(p/name).unlink()
            slots.write(p,{'set':{'mode':'original'},'look':{'mode':'follow'}})   # nothing extra when the slots do not ask for refs
            with patch('seedance_bridge.get_provider',return_value=adapter):
                self.assertEqual(seedance_bridge.submit(p,'Base',p/'char1-reference.png',provider='fal',status=lambda s:None),'req-1')
            self.assertNotIn('set',adapter.refs);self.assertEqual([x['token'] for x in json.loads((p/'generation.json').read_text())['refs']],['@Image1'])   # only char1 was passed this time

class AssembleRouteTests(unittest.TestCase):
    def test_assemble_route_text_refs_full_prompt_and_edited_warnings(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            p,root,set_name,look_name=world_run(d);client=TestClient(application.app);slots.write(p,FULL)
            r=client.post(f'/jobs/{HEX}/prompt/assemble',json={});self.assertEqual(r.status_code,200,r.text);j=r.json()
            self.assertEqual([x['token'] for x in j['refs']],['@Image1','@Image2','@Image3','@Image4']);self.assertEqual(j['warnings'],[]);self.assertFalse(j['edited'])
            self.assertTrue(j['full_prompt'].startswith(j['text']));self.assertIn('@Image3 is the set reference only. @Image4 is the style reference only.',j['full_prompt']);self.assertEqual(j['mode'],'edit')
            self.assertIn('Remove all face mesh lines',j['full_prompt']);self.assertIn(j['beats'],j['text'])
            r=client.post(f'/jobs/{HEX}/prompt/assemble',json={'slots':{'set':{'mode':'original'},'look':{'mode':'prompt','prompt':'oil paint'}}});j=r.json()
            self.assertEqual([x['token'] for x in j['refs']],['@Image1','@Image2']);self.assertIn('LOOK: oil paint',j['text']);self.assertNotIn('SET:',j['text'])
            r=client.post(f'/jobs/{HEX}/prompt/assemble',json={'text':'Make it nice with @Image9.'});j=r.json()
            self.assertTrue(j['edited']);self.assertTrue(any('@Image9' in w for w in j['warnings']));self.assertTrue(any('@Image1' in w for w in j['warnings']));self.assertTrue(j['full_prompt'].startswith('Make it nice with @Image9.'))
            self.assertEqual(client.post(f'/jobs/{HEX}/prompt/assemble',json={'slots':[1]}).status_code,400)
            self.assertEqual(client.post(f'/jobs/{"0"*32}/prompt/assemble',json={}).status_code,404)
            self.assertFalse((p/'calls.jsonl').exists())

def fake_response(text,status=200,usage=None):
    r=Mock();r.status_code=status;r.ok=status<400;r.json.return_value={'model':'claude-sonnet-5-5','stop_reason':'end_turn','content':[{'type':'text','text':text}],'usage':usage or {'input_tokens':1500,'output_tokens':40}};return r

class VisionTests(unittest.TestCase):
    def test_describe_frame_payload_parse_mask_and_cost(self):
        with tempfile.TemporaryDirectory() as d:
            p,root,_,_=world_run(d,words=False)   # 64×48 red clip, white mask box in the centre
            with patch('stages.vision.setting',return_value='sk-ant-test'),patch('stages.vision.requests.post',return_value=fake_response('SET: A small kitchen with white tiles and a wooden counter.\nLIGHT: Soft daylight from a window on the left, warm practicals.')) as post:
                out=vision.describe_frame(p,None,root)
            self.assertEqual(out['set'],'A small kitchen with white tiles and a wooden counter.');self.assertEqual(out['light'],'Soft daylight from a window on the left, warm practicals.')
            self.assertEqual((out['frame'],out['frame_s'],out['model'],out['masked'],out['warnings']),(6,0.25,'claude-sonnet-5-5',True,[]))
            self.assertEqual(out['usd'],round(1500*2/1e6+40*10/1e6,4));self.assertEqual(out['estimated_usd'],costs.price_for('claude_vision'))
            args,kwargs=post.call_args;self.assertEqual(args[0],vision.URL);self.assertEqual(kwargs['headers']['x-api-key'],'sk-ant-test');self.assertEqual(kwargs['headers']['anthropic-version'],'2023-06-01')
            payload=kwargs['json'];self.assertEqual(payload['model'],'claude-sonnet-5-5');self.assertEqual(payload['max_tokens'],vision.MAX_TOKENS)
            image=payload['messages'][0]['content'][0];self.assertEqual((image['type'],image['source']['type'],image['source']['media_type']),('image','base64','image/jpeg'))
            data=base64.b64decode(image['source']['data']);self.assertEqual(data[:3],b'\xff\xd8\xff')   # a JPEG
            img=np.asarray(Image.open(io.BytesIO(data)).convert('RGB'));self.assertEqual(img.shape,(48,64,3))
            centre=img[24,32];edge=img[2,2]
            self.assertTrue(all(abs(int(c)-128)<=8 for c in centre),centre);self.assertTrue(int(edge[0])>150 and int(edge[1])<90,edge)   # mask region gray, outside still red
            for word in ('people','clothing','faces'):self.assertIn(word,payload['system'].lower())
            self.assertIn('SET:',payload['system']);self.assertIn('LIGHT:',payload['system'])
            self.assertNotIn('sk-ant-test',json.dumps(payload))
            calls=stages.read_calls(p);self.assertEqual((calls[-1]['provider'],calls[-1]['endpoint'],calls[-1]['cost_usd']),('anthropic','messages',costs.price_for('claude_vision')))
            with patch('stages.vision.setting',return_value='sk-ant-test'),patch('stages.vision.requests.post',return_value=fake_response('SET: A loft. A woman stands in the middle.\nLIGHT: Hard sun.')):
                out=vision.describe_frame(p,0.2,root)
            self.assertEqual((out['frame'],out['set']),(5,'A loft.'));self.assertTrue(any('mentioned a person' in w for w in out['warnings']))
            self.assertEqual(costs.PRICES['claude_vision']['usd_flat'],0.0062);self.assertIn('pricing',costs.PRICES['claude_vision']['source'])
    def test_frame_without_masks_is_untouched_and_t_is_clamped(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/HEX;p.mkdir();write_clip(p/'original.mp4',RED,12,64,48)
            img,index,fps,masked=vision.frame_image(p,99);self.assertEqual((index,masked,img.size),(11,False,(64,48)));self.assertTrue(int(np.asarray(img)[24,32][0])>150)
            self.assertEqual(vision.frame_index(p,None)[0],6);self.assertEqual(vision.frame_index(p,-3)[0],0)
            with self.assertRaises(vision.VisionError):vision.frame_index(Path(d),None)
    def test_missing_key_offline_and_refusals(self):
        with tempfile.TemporaryDirectory() as d:
            p,root,_,_=world_run(d,words=False)
            with patch('stages.vision.setting',return_value=''),patch('stages.vision.requests.post',side_effect=AssertionError('network')):
                with self.assertRaises(vision.VisionError) as cm:vision.describe_frame(p,None,root)
            self.assertEqual(str(cm.exception),'No Anthropic key yet.');self.assertEqual(cm.exception.fix,vision.NO_KEY_FIX)
            with patch('stages.vision.setting',return_value='sk-ant-test'),patch.dict(os.environ,{'PUPPETEER_OFFLINE':'1'}),patch('stages.vision.requests.post',side_effect=AssertionError('network')):
                with self.assertRaises(stages.OfflineError):vision.describe_frame(p,None,root)
            self.assertFalse((p/'calls.jsonl').exists())
            with patch('stages.vision.setting',return_value='sk-ant-test'),patch('stages.vision.requests.post',return_value=fake_response('',status=401)):
                with self.assertRaises(vision.VisionError) as cm:vision.describe_frame(p,None,root)
            self.assertIn('not accepted',str(cm.exception));self.assertEqual(cm.exception.status,502)
    def test_describe_route(self):
        with tempfile.TemporaryDirectory() as d,patch.object(application,'RUNS',Path(d)):
            p,root,_,_=world_run(d,words=False);client=TestClient(application.app)
            with patch('stages.vision.setting',return_value=''):
                r=client.post(f'/jobs/{HEX}/describe',json={'confirm_cost':'true'});self.assertEqual(r.status_code,400);self.assertEqual(r.json()['message'],'No Anthropic key yet.');self.assertIn('ANTHROPIC_API_KEY=sk-ant-',r.json()['fix'])
            with patch('stages.vision.setting',return_value='sk-ant-test'),patch('stages.vision.requests.post',return_value=fake_response('SET: A loft.\nLIGHT: Hard sun from the right.')) as post:
                r=client.post(f'/jobs/{HEX}/describe',json={});self.assertEqual(r.status_code,402);self.assertEqual(r.json()['estimated_cost_usd'],costs.price_for('claude_vision'));self.assertFalse(post.called)
                r=client.post(f'/jobs/{HEX}/describe',json={'estimate_only':'true'});self.assertEqual(r.status_code,200);self.assertEqual(r.json()['estimated_cost_usd'],costs.price_for('claude_vision'));self.assertFalse(post.called)
                r=client.post(f'/jobs/{HEX}/describe',json={'t':'abc','confirm_cost':'true'});self.assertEqual(r.status_code,400);self.assertIn('fix',r.json())
                with patch.dict(os.environ,{'PUPPETEER_OFFLINE':'1'}):
                    r=client.post(f'/jobs/{HEX}/describe',json={'confirm_cost':'true'});self.assertEqual(r.status_code,400);self.assertIn('offline mode',r.json()['message']);self.assertIn('fix',r.json())
                self.assertFalse(post.called)
                r=client.post(f'/jobs/{HEX}/describe',json={'t':0.2,'confirm_cost':'true'});self.assertEqual(r.status_code,200,r.text);j=r.json()
                self.assertEqual((j['set'],j['light'],j['applied'],j['frame']),('A loft.','Hard sun from the right.',False,5));self.assertEqual(slots.read(p)['light'],'')
                r=client.post(f'/jobs/{HEX}/describe',data={'confirm_cost':'true','apply':'true'});self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['applied'])
                s=slots.read(p);self.assertEqual((s['set']['prompt'],s['light'],s['set']['mode']),('A loft.','Hard sun from the right.','original'))   # only the two lines change
            self.assertEqual(len(stages.read_calls(p)),2)

class ExportTests(unittest.TestCase):
    def test_export_prompt_text_is_the_assembled_prompt(self):
        from stages import export
        with tempfile.TemporaryDirectory() as d:
            p,root,set_name,look_name=world_run(d);slots.write(p,FULL)
            text,source=export.prompt_text(p,root);assembled=promptkit.assemble(p,runs_root=root)
            self.assertEqual(source,'promptkit');self.assertTrue(text.startswith(assembled['text']));self.assertEqual(text.count('Dialogue beats'),1)
            self.assertIn(f'@Image3  ref-03-set.png',text);self.assertIn('@Image4 defines the rendering style only',text)

if __name__=='__main__':unittest.main()
