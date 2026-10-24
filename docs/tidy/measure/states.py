"""Screens that need a select change, a mocked write or a toast. Nothing is written under runs/: every PUT/POST that
would write is answered by a route mock. Output: docs/tidy/before/<name>-desktop.png + -380.png, shots-custom.json."""
import sys, json, pathlib
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8791'
OUT = pathlib.Path('/Users/arthurhakobyan/Desktop/puppetear/puppeteer/docs/tidy/before')
A = '0be4cf2cadd945008a9c9131b6c75f12'   # Advanced + mesh, words.json, review pending
D = '3c54f2952b494f62810dfac35a4d738b'   # draft ready, reviewed, char1 reference, stems
report = {}

def mock_edits(page):
    """Answer PUT /edits (a commit) and POST /edits/undo|redo without touching the server."""
    st = {'rev': 0, 'layer': {'mask': {}, 'mesh': {}, 'words': None}, 'labels': []}
    def pending(layer):
        m = layer.get('mask') or {}; e = layer.get('mesh') or {}; w = layer.get('words') or {}
        pm = len(m.get('points') or []) + len(m.get('strokes') or []) + len(m.get('applied') or [])
        pe = len(e.get('off') or []) + len(e.get('keys') or {}) + len(e.get('expr') or {})
        pw = len((w or {}).get('edited') or [])
        return {'mask': pm, 'mesh': pe, 'words': pw, 'total': pm + pe + pw}
    def body():
        p = pending(st['layer'])
        summ = []
        if p['mask']: summ.append(f"{p['mask']} mask fix" + ('es' if p['mask'] != 1 else ''))
        if p['mesh']: summ.append(f"face: {p['mesh']} mesh edit" + ('s' if p['mesh'] != 1 else ''))
        if p['words']: summ.append(f"{p['words']} word" + ('s' if p['words'] != 1 else '') + ' edited')
        return {'run': A, 'rev': st['rev'], 'layer': st['layer'], 'can_undo': bool(st['labels']), 'can_redo': False,
                'undo_label': st['labels'][-1] if st['labels'] else None, 'redo_label': None, 'pending': p, 'summary': summ, 'stale': False}
    def handle(route, request):
        m = request.method
        if m == 'PUT':
            data = request.post_data_json or {}
            st['layer'][data['track']] = data['value']; st['rev'] += 1; st['labels'].append(data.get('label', ''))
            route.fulfill(status=200, content_type='application/json', body=json.dumps(body()))
        elif m == 'DELETE':
            st['layer'] = {'mask': {}, 'mesh': {}, 'words': None}; st['rev'] += 1; st['labels'] = []
            route.fulfill(status=200, content_type='application/json', body=json.dumps(body()))
        elif m == 'GET' and st['rev']:
            route.fulfill(status=200, content_type='application/json', body=json.dumps(body()))
        else:
            route.continue_()
    page.route(f'**/jobs/{A}/edits', handle)
    page.route(f'**/jobs/{A}/edits/mask/preview', lambda route, req: route.fulfill(status=200, content_type='application/json',
        body=json.dumps({'url': f'/jobs/{A}/mask/frame?i=' + str((req.post_data_json or {}).get('frame', 0)), 'selections': [{'mode': 'include', 'fraction': 0.0123, 'already_in_mask': 0.1}]})))

def shoot(page, name, label):
    sw = page.evaluate('document.documentElement.scrollWidth'); cw = page.evaluate('document.documentElement.clientWidth')
    page.screenshot(path=str(OUT / f'{name}-{label}.png'), full_page=True)
    report[f'{name}-{label}'] = {'scrollWidth': sw, 'clientWidth': cw, 'horizontal_scroll': sw > cw}
    print(name, label, 'h-scroll' if sw > cw else 'ok')

def each(browser, name, fn, path, settle=2500):
    for label, w, h in (('desktop', 1440, 900), ('380', 380, 800)):
        ctx = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1)
        page = ctx.new_page(); errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        fn(page, 'pre')
        page.goto(BASE + path, wait_until='domcontentloaded'); page.wait_for_selector('#view .panel', timeout=20000); page.wait_for_timeout(settle)
        fn(page, 'post'); page.wait_for_timeout(900)
        shoot(page, name, label)
        report[f'{name}-{label}']['errors'] = errors
        ctx.close()

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # export kit with the After Effects preset (alpha format row appears)
        def ae(page, phase):
            if phase == 'post':
                page.select_option('[data-preset]', 'after_effects'); page.wait_for_timeout(300)
                page.evaluate("document.getElementById('export').scrollIntoView()")
        def custom(page, phase):
            if phase == 'post': page.select_option('[data-preset]', 'custom'); page.wait_for_timeout(300)
        # mask track with one pending + fix (mocked commit + preview)
        def maskfix(page, phase):
            if phase == 'pre': mock_edits(page); return
            page.click('.tl-label[data-track=mask]'); page.wait_for_timeout(600)
            box = page.locator('.stage-overlay').bounding_box()
            page.mouse.click(box['x'] + box['width'] * 0.5, box['y'] + box['height'] * 0.55); page.wait_for_timeout(600)
            page.keyboard.down('Alt'); page.mouse.click(box['x'] + box['width'] * 0.3, box['y'] + box['height'] * 0.4); page.keyboard.up('Alt'); page.wait_for_timeout(600)
        each(browser, 'run-editor-mask-pending-fix', maskfix, f'/?job={A}&view=quick')
        # face track: mesh off on a range, then a drag (transform key) -> pending edits + hatched lane
        def meshoff(page, phase):
            if phase == 'pre': mock_edits(page); return
            page.click('.tl-label[data-track=face]'); page.wait_for_timeout(600)
            ruler = page.locator('.tl-ruler').bounding_box()
            page.mouse.move(ruler['x'] + ruler['width'] * 0.3, ruler['y'] + 10); page.mouse.down()
            page.mouse.move(ruler['x'] + ruler['width'] * 0.45, ruler['y'] + 10, steps=6); page.mouse.up(); page.wait_for_timeout(300)
            page.click('button:has-text("Mesh off on range")'); page.wait_for_timeout(500)
        each(browser, 'run-editor-face-mesh-off-pending', meshoff, f'/?job={A}&view=quick')
        # save bar: Discard asks first
        def discard(page, phase):
            if phase == 'pre': mock_edits(page); return
            page.click('.tl-label[data-track=face]'); page.wait_for_timeout(600)
            page.click('button:has-text("Mesh off on this frame")'); page.wait_for_timeout(400)
            page.click('.savebar button:has-text("Discard")'); page.wait_for_timeout(300)
            page.evaluate("document.querySelector('.savebar').scrollIntoView()")
        each(browser, 'run-editor-savebar-discard', discard, f'/?job={A}&view=quick')
        # mask save refusal: pending clicks not applied -> notice with "Apply now" / "Save without it"
        def saverefuse(page, phase):
            if phase == 'pre': mock_edits(page); return
            page.click('.tl-label[data-track=mask]'); page.wait_for_timeout(600)
            box = page.locator('.stage-overlay').bounding_box()
            page.mouse.click(box['x'] + box['width'] * 0.5, box['y'] + box['height'] * 0.55); page.wait_for_timeout(600)
            page.click('.savebar button:has-text("Save edits")'); page.wait_for_timeout(500)
        each(browser, 'toast-save-blocked-by-pending-mask-fix', saverefuse, f'/?job={A}&view=quick')
        # error toast: Describe with no Anthropic key (400 from the server; nothing is written)
        def describe(page, phase):
            if phase == 'post':
                page.click('button:has-text("Describe set & light")'); page.wait_for_timeout(1200)
        each(browser, 'toast-error-describe-no-key', describe, f'/?job={A}&view=quick')
        # 402 toast with "Run anyway" (mocked answer from POST /hd on the draft run; nothing is sent)
        def hd402(page, phase):
            if phase == 'pre':
                page.route(f'**/jobs/{D}/hd', lambda route, req: route.fulfill(status=402, content_type='application/json', body=json.dumps({'detail': 'Completing this draft at 1080p costs about $11.34.', 'fix': 'Click "Run anyway" to confirm the cost; nothing has been sent yet.', 'estimated_cost_usd': 11.34})) if req.method == 'POST' else route.continue_())
                return
            page.click('[data-upgrade]'); page.wait_for_timeout(800)
        each(browser, 'toast-402-run-anyway', hd402, f'/?job={D}&view=quick')
        # 409 on approve (mocked): "Reload the latest preview" action
        def approve409(page, phase):
            if phase == 'pre':
                page.route(f'**/jobs/{A}/mask-review', lambda route, req: route.fulfill(status=409, content_type='application/json', body=json.dumps({'detail': 'The prepared files changed since this page was loaded.', 'fix': 'Reload the latest preview and review it again.'})) if req.method == 'POST' else route.continue_())
                return
            page.check('[data-check]'); page.click('[data-approve]'); page.wait_for_timeout(800)
            page.evaluate("document.querySelector('.review-box').scrollIntoView()")
        each(browser, 'toast-409-approve-stale', approve409, f'/?job={A}&view=quick')
        # words track: the paid engine picked while offline (warning line)
        def wordsfal(page, phase):
            if phase == 'post':
                page.click('.tl-label[data-track=words]'); page.wait_for_timeout(800)
                sel = page.locator('.words-track select')
                opts = sel.locator('option').evaluate_all('os => os.map(o => o.value)')
                paid = [o for o in opts if o != 'local']
                if paid: sel.select_option(paid[0]); page.wait_for_timeout(300)
                page.locator('.wb').first.click(); page.wait_for_timeout(300)
        each(browser, 'run-editor-words-paid-engine-offline', wordsfal, f'/?job={A}&view=quick')
        # words: a word selected (panel shows text + times)
        def wordsel(page, phase):
            if phase == 'post':
                page.click('.tl-label[data-track=words]'); page.wait_for_timeout(800)
                page.locator('.wb').nth(2).click(); page.wait_for_timeout(300)
        each(browser, 'run-editor-words-selected', wordsel, f'/?job={A}&view=quick')
        # a range selected on the ruler (counter + band), no track
        def rng(page, phase):
            if phase == 'post':
                ruler = page.locator('.tl-ruler').bounding_box()
                page.mouse.move(ruler['x'] + ruler['width'] * 0.2, ruler['y'] + 10); page.mouse.down()
                page.mouse.move(ruler['x'] + ruler['width'] * 0.5, ruler['y'] + 10, steps=6); page.mouse.up(); page.wait_for_timeout(300)
        each(browser, 'run-editor-range-selected', rng, f'/?job={A}&view=quick')
        # Studio composite card with the Set image background (select change only; nothing runs)
        def bgset(page, phase):
            if phase == 'post':
                page.select_option('#stage-composite select[aria-label=Background]', 'set_image'); page.wait_for_timeout(600)
                page.evaluate("document.getElementById('stage-composite').scrollIntoView()")
        each(browser, 'run-studio-composite-set-image', bgset, f'/?job={A}&view=studio')
        # Studio: a changed param -> "Re-run from here with these settings"
        def param(page, phase):
            if phase == 'post':
                page.select_option('#stage-face select[data-tool]', 'off'); page.wait_for_timeout(300)
                page.evaluate("document.getElementById('stage-face').scrollIntoView()")
        each(browser, 'run-studio-card-changed-setting', param, f'/?job={A}&view=studio')
        # Slots: set mode "Described" (mock the PUT so nothing is written)
        def slots(page, phase):
            if phase == 'pre':
                def h(route, req):
                    if req.method == 'PUT':
                        b = req.post_data_json or {}
                        base = {'id': D, 'version': 1, 'set': {'mode': 'prompt', 'image': None, 'prompt': '', 'fit': {}}, 'look': {'mode': 'style_ref', 'image': None, 'prompt': ''}, 'light': '', 'generator': {'name': None, 'task': 'auto', 'resolution': None}, 'updated': None, 'task': 'reference', 'task_source': 'set', 'derived_task': 'reference', 'file': False, 'background': 'original', 'background_label': 'Original frames', 'background_needed': None, 'background_applied': True}
                        route.fulfill(status=200, content_type='application/json', body=json.dumps(base))
                    else: route.continue_()
                page.route(f'**/jobs/{D}/slots', h); return
            page.select_option('[data-set] select', 'prompt'); page.wait_for_timeout(400)
            page.select_option('[data-look] select', 'style_ref'); page.wait_for_timeout(600)
            page.evaluate("document.querySelector('.slots').scrollIntoView()")
        each(browser, 'run-world-slots-described-style', slots, f'/?job={D}&view=quick')
        def details(page, phase):
            if phase == 'post':
                page.wait_for_selector('[data-sent]:not([hidden])', timeout=15000)
                for t in ('View submitted prompt', 'Import a generated result', 'Audio downloads', 'Earlier exports'):
                    loc = page.locator(f'summary:has-text("{t}")')
                    if loc.count() and loc.first.is_visible(): loc.first.click(); page.wait_for_timeout(200)
        each(browser, 'run-final-details-open', details, f'/?job={D}&view=quick')
        browser.close()
    (OUT / 'shots-custom.json').write_text(json.dumps(report, indent=1))

if __name__ == '__main__': main()
