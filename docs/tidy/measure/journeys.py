"""Drive the six journeys in the real UI and count clicks. Every write is answered by a route mock (nothing under runs/
changes): POST /jobs, PUT /edits, POST /edits/*, POST /edits/save, POST /mask-review, POST /branch, POST /seedance, POST /export, PUT /slots."""
import json, pathlib, sys
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8791'
A = '0be4cf2cadd945008a9c9131b6c75f12'   # pending review, no char1
D = '3c54f2952b494f62810dfac35a4d738b'   # approved, char1 saved, draft
P = 'e3396214ca9e4cf997aaefa24c196de3'   # parent with a face-pad child
C = 'a73448dc'                            # child prefix (resolved below)
CLIP = pathlib.Path('/Users/arthurhakobyan/Desktop/puppetear/puppeteer/runs') / A / 'upload.mp4'
REF = pathlib.Path('/Users/arthurhakobyan/Desktop/puppetear/puppeteer/runs') / D / 'char1-reference.png'

class Counter:
    def __init__(self, name): self.name = name; self.n = 0; self.loads = 0; self.steps = []
    def click(self, what, n=1): self.n += n; self.steps.append((self.n, what))
    def load(self, what): self.loads += 1; self.steps.append(('load', what))
    def report(self):
        print(f'\n### {self.name}: {self.n} clicks, {self.loads} page loads')
        for k, s in self.steps: print(f'  {k}: {s}')

def ok(route, body, status=200): route.fulfill(status=status, content_type='application/json', body=json.dumps(body))

def mock_edits(page, run):
    st = {'rev': 0, 'layer': {'mask': {}, 'mesh': {}, 'words': None}, 'labels': []}
    def pending():
        m = st['layer'].get('mask') or {}; e = st['layer'].get('mesh') or {}
        pm = len(m.get('points') or []) + len(m.get('strokes') or []) + len(m.get('applied') or [])
        pe = len(e.get('off') or []) + len(e.get('keys') or {}) + len(e.get('expr') or {})
        return {'mask': pm, 'mesh': pe, 'words': 0, 'total': pm + pe}
    def body():
        return {'run': run, 'rev': st['rev'], 'layer': st['layer'], 'can_undo': bool(st['labels']), 'can_redo': False, 'undo_label': st['labels'][-1] if st['labels'] else None, 'redo_label': None, 'pending': pending(), 'summary': st['labels'][-1:], 'stale': False}
    def handle(route, req):
        if req.method == 'PUT':
            d = req.post_data_json or {}; st['layer'][d['track']] = d['value']; st['rev'] += 1; st['labels'].append(d.get('label', '')); ok(route, body())
        elif req.method == 'GET' and st['rev']: ok(route, body())
        else: route.continue_()
    page.route(f'**/jobs/{run}/edits', handle)
    page.route(f'**/jobs/{run}/edits/mask/preview', lambda r, q: ok(r, {'url': f'/jobs/{run}/mask/frame?i=' + str((q.post_data_json or {}).get('frame', 0)), 'selections': [{'mode': 'include', 'fraction': 0.01}]}))
    def apply(route, req):
        d = req.post_data_json or {}
        if d.get('estimate_only'): return ok(route, {'estimated_cost_usd': 0})
        m = st['layer'].get('mask') or {}
        st['layer']['mask'] = {'points': [], 'strokes': [], 'applied': (m.get('applied') or []) + [{'id': 'a1', 'quality': d.get('quality', 'quick'), 'frames_changed': 7, 'result': 'r1', 'points': m.get('points') or [], 'strokes': []}]}
        st['rev'] += 1; st['labels'].append('Apply'); ok(route, {'apply': {'frames_changed': 7, 'quality': d.get('quality', 'quick'), 'reused': False}, 'rev': st['rev']})
    page.route(f'**/jobs/{run}/edits/mask/apply', apply)
    page.route(f'**/jobs/{run}/edits/save', lambda r, q: ok(r, {'id': D}))
    page.route('**/_sessions/**', lambda r, q: r.fulfill(status=404, body=''))

def journey_a(browser):
    c = Counter('(a) Quick: upload -> draft button')
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900}); page = ctx.new_page()
    page.route('**/jobs', lambda r, q: ok(r, {'id': A, 'state': 'running'}) if q.method == 'POST' else r.continue_())
    approved = {'v': False}
    def review(route, req):
        if req.method == 'POST': approved['v'] = True; return ok(route, {'ok': True})
        if approved['v']: return ok(route, {'approved': True, 'status': 'approved', 'note': 'Approved.', 'fingerprint': 'x'})
        route.continue_()
    page.route(f'**/jobs/{A}/mask-review', review)
    page.route(f'**/jobs/{A}/seedance', lambda r, q: ok(r, {'detail': 'stopped by the journey script'}, 400))
    page.goto(BASE + '/', wait_until='domcontentloaded'); page.wait_for_selector('#view .panel', timeout=20000); c.load('/ (Quick)')
    page.set_input_files('input[name=video]', str(CLIP)); c.click('Choose original video (click) + pick file', 2)
    page.wait_for_timeout(800)
    c.click('Preset: first one is pre-selected (0); another preset would be +1', 0)
    page.set_input_files('input[name=char1]', str(REF)); c.click('Character 1 (click) + pick file', 2)
    page.wait_for_timeout(1200)
    label = page.locator('[data-go]').inner_text(); print('   go button:', label)
    page.click('[data-go]'); c.click(f'"{label}" (POST /jobs; the page navigates to the run)')
    page.wait_for_url('**/?job=*'); c.load('/?job=<id>&view=quick (then wait for preparation)')
    page.wait_for_timeout(2500)
    page.check('[data-check]'); c.click('Scroll to step 02; tick "I reviewed the entire prepared clip…"')
    page.click('[data-approve]'); c.click('"Approve input" (POST /mask-review)')
    page.wait_for_timeout(1500)
    btn = page.locator('[data-draft-button]'); print('   draft button:', btn.inner_text(), 'disabled=', btn.is_disabled())
    c.click('Character 1 in step 03: already saved from step 01 (0)', 0)
    if btn.is_disabled(): print('   (draft button still disabled; counting the click anyway)')
    page.click('[data-draft-button]', force=True); c.click('"Create draft · about $x" (paid; stops here)')
    page.wait_for_timeout(600)
    c.report(); ctx.close()

def journey_b(browser):
    c = Counter('(b) Fix a mask (open run, one + click, apply, save)')
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900}); page = ctx.new_page()
    mock_edits(page, A)
    page.goto(BASE + '/?view=runs', wait_until='domcontentloaded'); page.wait_for_selector('#view .panel', timeout=20000); c.load('/?view=runs')
    page.click(f'.run-row a[href*="{A}"][data-quick]'); c.click('Runs page: "Quick view" on the run')
    page.wait_for_url('**/?job=*'); c.load('/?job=<id>&view=quick'); page.wait_for_timeout(2500)
    page.click('.tl-label[data-track=mask]'); c.click('Scroll to the editor; click the "Mask" lane label')
    page.wait_for_timeout(500)
    box = page.locator('.stage-overlay').bounding_box()
    page.mouse.click(box['x'] + box['width'] * 0.5, box['y'] + box['height'] * 0.55); c.click('Click on the picture (+ include) -> pending fix + preview')
    page.wait_for_timeout(800)
    page.click('button:has-text("Apply to clip")'); c.click('"Apply to clip · quick preview · free"'); page.wait_for_timeout(800)
    acc = page.locator('button:has-text("Accept · full quality")')
    print('   accept row visible:', acc.count() > 0)
    page.click('.savebar button:has-text("Save edits")'); c.click('"Save edits · free, creates one new version" (new run opens)')
    page.wait_for_timeout(800); c.load('/?job=<child>')
    c.report(); ctx.close()

def journey_c(browser):
    c = Counter('(c) Fix the face mesh (mesh off on a range, save)')
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900}); page = ctx.new_page()
    mock_edits(page, A)
    page.goto(BASE + '/?view=runs', wait_until='domcontentloaded'); page.wait_for_selector('#view .panel', timeout=20000); c.load('/?view=runs')
    page.click(f'.run-row a[href*="{A}"][data-quick]'); c.click('Runs page: "Quick view" on the run')
    page.wait_for_url('**/?job=*'); c.load('/?job=<id>&view=quick'); page.wait_for_timeout(2500)
    page.click('.tl-label[data-track=face]'); c.click('Click the "Face" lane label (view switches to Mesh edit)'); page.wait_for_timeout(500)
    ruler = page.locator('.tl-ruler').bounding_box()
    page.mouse.move(ruler['x'] + ruler['width'] * 0.3, ruler['y'] + 10); page.mouse.down(); page.mouse.move(ruler['x'] + ruler['width'] * 0.45, ruler['y'] + 10, steps=6); page.mouse.up()
    c.click('Drag across the ruler to select the range (1 drag)'); page.wait_for_timeout(300)
    page.click('button:has-text("Mesh off on range")'); c.click('"Mesh off on range"'); page.wait_for_timeout(400)
    page.click('.savebar button:has-text("Save edits")'); c.click('"Save edits · free, creates one new version"'); page.wait_for_timeout(600); c.load('/?job=<child>')
    c.report(); ctx.close()
    c2 = Counter('(c2) Face mesh transform (drag the mesh, save)')
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900}); page = ctx.new_page(); mock_edits(page, A)
    page.goto(BASE + f'/?job={A}&view=quick', wait_until='domcontentloaded'); page.wait_for_selector('#view .panel', timeout=20000); c2.load('/?job=<id>&view=quick (from the Runs page: +1 click)'); c2.click('Runs page: open the run'); page.wait_for_timeout(2500)
    page.click('.tl-label[data-track=face]'); c2.click('Click the "Face" lane label'); page.wait_for_timeout(600)
    box = page.locator('.stage-overlay').bounding_box()
    page.mouse.move(box['x'] + box['width'] * 0.5, box['y'] + box['height'] * 0.4); page.mouse.down(); page.mouse.move(box['x'] + box['width'] * 0.52, box['y'] + box['height'] * 0.42, steps=5); page.mouse.up()
    c2.click('Drag inside the mesh box (move) -> one key'); page.wait_for_timeout(400)
    n = page.locator('.sb-summary strong').inner_text(); print('   save bar:', n)
    page.click('.savebar button:has-text("Save edits")'); c2.click('"Save edits"'); page.wait_for_timeout(500)
    c2.report(); ctx.close()

def journey_d(browser):
    c = Counter('(d) Set + look + prompt -> draft')
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900}); page = ctx.new_page()
    slots = {'id': D, 'version': 1, 'set': {'mode': 'original', 'image': None, 'prompt': '', 'fit': {}}, 'look': {'mode': 'follow', 'image': None, 'prompt': ''}, 'light': '', 'generator': {'name': None, 'task': 'auto', 'resolution': None}, 'updated': None, 'task': 'editing', 'task_source': 'set', 'derived_task': 'editing', 'file': False, 'background': 'original', 'background_label': 'Original frames', 'background_needed': None, 'background_applied': True}
    def sl(route, req):
        if req.method == 'PUT':
            d = req.post_data_json or {}
            for k in ('set', 'look'):
                if k in d: slots[k].update(d[k])
            if 'light' in d: slots['light'] = d['light']
            return ok(route, slots)
        ok(route, slots)
    page.route(f'**/jobs/{D}/slots', sl)
    page.route(f'**/jobs/{D}/seedance', lambda r, q: ok(r, {'detail': 'stopped by the journey script'}, 400))
    page.goto(BASE + '/?view=runs', wait_until='domcontentloaded'); page.wait_for_selector('#view .panel', timeout=20000); c.load('/?view=runs')
    page.click(f'.run-row a[href*="{D}"][data-quick]'); c.click('Runs page: "Quick view" on the run')
    page.wait_for_url('**/?job=*'); c.load('/?job=<id>&view=quick'); page.wait_for_timeout(2500)
    page.select_option('[data-set] select', 'set_ref'); c.click('Scroll to step 03 "Set, look and light"; Set select: open + choose "Set reference"', 2); page.wait_for_timeout(600)
    assets = page.locator('[data-set] .asset')
    print('   set plates available:', assets.count())
    if assets.count(): assets.first.click(); c.click('Pick a set plate thumbnail'); page.wait_for_timeout(400)
    else: c.click('"Upload image…" (click) + pick file', 2)
    page.select_option('[data-look] select', 'style_ref'); c.click('Look select: open + choose "Style image"', 2); page.wait_for_timeout(600)
    la = page.locator('[data-look] .asset'); print('   style images available:', la.count())
    if la.count(): la.first.click(); c.click('Pick a style image thumbnail'); page.wait_for_timeout(400)
    else: c.click('"Upload image…" (click) + pick file', 2)
    page.click('input[name=light]'); page.keyboard.type('soft window light'); c.click('Click the Light field (+ typing)'); page.wait_for_timeout(700)
    page.click('button:has-text("Build prompt from slots")'); c.click('"Build prompt from slots"'); page.wait_for_timeout(900)
    print('   prompt head:', page.locator('textarea[name=prompt]').input_value()[:80].replace('\n', ' '))
    btn = page.locator('[data-draft-button]'); print('   draft button:', btn.inner_text(), 'disabled=', btn.is_disabled())
    page.click('[data-draft-button]', force=True); c.click('"Create draft · about $x" (paid; stops here)'); page.wait_for_timeout(500)
    c.report(); ctx.close()

def journey_e(browser):
    c = Counter('(e) Export for another tool (After Effects preset)')
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900}); page = ctx.new_page()
    page.route(f'**/jobs/{D}/export', lambda r, q: ok(r, {'name': 'x', 'state': 'running'}) if q.method == 'POST' else r.continue_())
    page.route(f'**/jobs/{D}/export/x', lambda r, q: ok(r, {'name': 'x', 'state': 'error', 'status': 'stopped by the journey script'}))
    page.goto(BASE + '/?view=runs', wait_until='domcontentloaded'); page.wait_for_selector('#view .panel', timeout=20000); c.load('/?view=runs')
    page.click(f'.run-row a[href*="{D}"][data-studio]'); c.click('Runs page: "Open in Studio"')
    page.wait_for_url('**/?job=*'); c.load('/?job=<id>&view=studio'); page.wait_for_timeout(2500)
    page.click('a:has-text("Export…")'); c.click('Run header "Export…" (scrolls to the kit at the bottom)'); page.wait_for_timeout(500)
    page.select_option('[data-preset]', 'after_effects'); c.click('Target select: open + choose "After Effects / Nuke"', 2); page.wait_for_timeout(400)
    print('   alpha format row shown:', page.locator('[data-formats] select').count() > 0)
    page.click('[data-export]'); c.click('"Export · free, local"'); page.wait_for_timeout(800)
    c.report(); ctx.close()
    c2 = Counter('(e2) Export from Quick (no Studio)')
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900}); page = ctx.new_page()
    page.goto(BASE + '/?view=runs', wait_until='domcontentloaded'); page.wait_for_selector('#view .panel', timeout=20000); c2.load('/?view=runs')
    page.click(f'.run-row a[href*="{D}"][data-quick]'); c2.click('Runs page: "Quick view"'); page.wait_for_url('**/?job=*'); c2.load('/?job=<id>&view=quick'); page.wait_for_timeout(2500)
    c2.click('Scroll past steps 02 and 03 to the export kit under step 04 (scroll, 0 clicks)', 0)
    page.select_option('[data-preset]', 'after_effects'); c2.click('Target select: open + choose', 2)
    c2.click('"Export · free, local"'); c2.report(); ctx.close()

def journey_f(browser, child):
    c = Counter('(f) Branch a stage and compare in Lab')
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900}); page = ctx.new_page()
    page.route(f'**/jobs/{P}/branch', lambda r, q: ok(r, {'id': child, 'parent': P}))
    page.goto(BASE + '/?view=runs', wait_until='domcontentloaded'); page.wait_for_selector('#view .panel', timeout=20000); c.load('/?view=runs')
    page.click(f'.run-row a[href*="{P}"][data-studio]'); c.click('Runs page: "Open in Studio"')
    page.wait_for_url('**/?job=*'); c.load('/?job=<id>&view=studio'); page.wait_for_timeout(2500)
    pad = page.locator('#stage-face .params input[type=number]').first
    pad.click(); page.keyboard.press('Meta+a'); page.keyboard.type('2.0'); page.keyboard.press('Tab'); c.click('Face card: click the "pad" field, type 2.0, Tab'); page.wait_for_timeout(400)
    label = page.locator('#stage-face [data-rerun]').inner_text(); print('   rerun label:', label)
    page.click('#stage-face [data-rerun]'); c.click(f'"{label}" (estimate; free -> branches at once)'); page.wait_for_timeout(1500)
    print('   url:', page.url)
    if child not in page.url:
        page.click('#stage-face [data-rerun]'); c.click('second click (paid would need "click to confirm")'); page.wait_for_timeout(1500)
    c.load('/?job=<child>&view=studio'); page.wait_for_timeout(1500)
    page.click('.run-head button:has-text("Add to Lab")'); c.click('Child run header: "Add to Lab" (opens Lab with 1 run)'); page.wait_for_timeout(1500); c.load('/?view=lab&runs=<child>')
    page.check(f'.lab-picker input[value="{P}"]'); c.click('Lab picker: tick the parent'); page.wait_for_timeout(2000)
    print('   tiles:', page.locator('.tile').count())
    page.click('[data-play]'); c.click('"Play" (synced)'); page.wait_for_timeout(300)
    c.report(); ctx.close()

def main():
    import urllib.request
    tree = json.load(urllib.request.urlopen(BASE + '/jobs'))['runs']
    child = next(r['id'] for r in tree if r['id'].startswith(C))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for fn in (journey_a, journey_b, journey_c, journey_d, journey_e):
            try: fn(browser)
            except Exception as e: print('FAILED', fn.__name__, repr(e)[:300])
        try: journey_f(browser, child)
        except Exception as e: print('FAILED journey_f', repr(e)[:300])
        browser.close()

if __name__ == '__main__': main()
