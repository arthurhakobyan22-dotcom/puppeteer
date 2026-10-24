"""Accessibility measurements: focus ring visibility while tabbing, unlabelled controls, click targets that are not focusable,
touch target sizes at 380 px, and the colour pairs of app.css against WCAG AA."""
import json, re
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8791'
A = '0be4cf2cadd945008a9c9131b6c75f12'; D = '3c54f2952b494f62810dfac35a4d738b'
PAGES = [('quick', '/'), ('runs', '/?view=runs'), ('run-quick', f'/?job={A}&view=quick'), ('run-studio', f'/?job={A}&view=studio'), ('lab', f'/?view=lab&runs={A},{D}&stage=seedance-input.mp4'), ('run-draft', f'/?job={D}&view=quick')]

NAME_JS = """
els => els.map(e => {
  const r = e.getBoundingClientRect();
  const visible = !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length) && !e.closest('[hidden]');
  let name = e.getAttribute('aria-label') || '';
  if (!name && e.getAttribute('aria-labelledby')) name = (document.getElementById(e.getAttribute('aria-labelledby')) || {}).textContent || '';
  if (!name && e.labels && e.labels.length) name = [...e.labels].map(l => l.textContent).join(' ');
  if (!name && e.closest('label')) name = e.closest('label').textContent;
  if (!name) name = (e.textContent || '').trim();
  if (!name) name = e.getAttribute('title') || e.getAttribute('placeholder') || e.getAttribute('alt') || '';
  const glyphOnly = !/[A-Za-z0-9]{2,}/.test(name);
  return { tag: e.tagName.toLowerCase(), type: e.getAttribute('type') || '', cls: e.className && e.className.baseVal === undefined ? e.className : '', name: name.trim().slice(0, 60), glyphOnly, visible, w: Math.round(r.width), h: Math.round(r.height), text: (e.textContent || '').trim().slice(0, 30), tabindex: e.getAttribute('tabindex') };
})"""

FOCUS_JS = """
() => { const e = document.activeElement; if (!e || e === document.body) return null;
  const cs = getComputedStyle(e); let fv = false; try { fv = e.matches(':focus-visible'); } catch {}
  const parentOutline = e.closest('.upload') ? getComputedStyle(e.closest('.upload')).outlineWidth : '';
  return { tag: e.tagName.toLowerCase(), type: e.getAttribute('type') || '', text: (e.getAttribute('aria-label') || e.textContent || e.value || '').trim().slice(0, 40), outline: cs.outlineStyle + ' ' + cs.outlineWidth + ' ' + cs.outlineColor, border: cs.borderColor, boxShadow: cs.boxShadow, fv, parentOutline, inEditor: !!e.closest('.editor') }; }"""

def hexrgb(h):
    h = h.lstrip('#'); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
def lum(c):
    def f(v): return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = c; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
def ratio(fg, bg):
    a, b = lum(hexrgb(fg)), lum(hexrgb(bg)); a, b = max(a, b), min(a, b); return (a + 0.05) / (b + 0.05)
def blend(fg, bg, alpha):
    f, b = hexrgb(fg), hexrgb(bg); return '#' + ''.join(f'{round((f[i] * alpha + b[i] * (1 - alpha)) * 255):02x}' for i in range(3))

PAIRS = [
    ('body text --text', '#2b2f3a', '#fafafb', 15, False),
    ('hints / .hint, p, --muted on card', '#7a7e8a', '#ffffff', 12, False),
    ('--muted on page bg', '#7a7e8a', '#fafafb', 12, False),
    ('.mono ids (11px muted)', '#7a7e8a', '#ffffff', 11, False),
    ('.eyebrow (11px muted uppercase)', '#7a7e8a', '#fafafb', 11, False),
    ('.chip default #656977 on #f4f4f7', '#656977', '#f4f4f7', 11, False),
    ('.chip.done --ok on --ok-bg', '#1e6b3a', '#e6f4ea', 11, False),
    ('.chip.error --err on --err-bg', '#b3261e', '#fff3f3', 11, False),
    ('.chip.warn --warn on --warn-bg', '#8a6d00', '#fff6e0', 11, False),
    ('.chip.running accent on accent-soft', '#1f18c0', '#eef0fb', 11, False),
    ('.chip.imported #9a5b00 on #fff3e0', '#9a5b00', '#fff3e0', 11, False),
    ('.line.ok text', '#1e6b3a', '#e6f4ea', 13, False),
    ('.line.warn text', '#8a6d00', '#fff6e0', 13, False),
    ('.line.error text', '#b3261e', '#fff3f3', 13, False),
    ('.line.info accent on accent-soft', '#1f18c0', '#eef0fb', 13, False),
    ('primary button white on accent', '#ffffff', '#1f18c0', 14, True),
    ('primary button disabled (opacity .45 over white)', '#ffffff', blend('#1f18c0', '#ffffff', 0.45), 14, True),
    ('secondary button --text on white', '#2b2f3a', '#ffffff', 14, True),
    ('.danger button --err on white', '#b3261e', '#ffffff', 14, True),
    ('.linkish / links accent on white', '#1f18c0', '#ffffff', 12, False),
    ('summary #656977 on white', '#656977', '#ffffff', 13, False),
    ('.meta span #656977 on #f4f4f7', '#656977', '#f4f4f7', 12, False),
    ('.numbers --muted on #f4f4f7', '#7a7e8a', '#f4f4f7', 11, False),
    ('.cost.paid --warn on white', '#8a6d00', '#ffffff', 12, False),
    ('.warnings --warn on white (12px)', '#8a6d00', '#ffffff', 12, False),
    ('.tl-label muted 11px on #fafafb', '#7a7e8a', '#fafafb', 11, False),
    ('.tl-label.active accent on accent-soft', '#1f18c0', '#eef0fb', 11, False),
    ('ruler text #5c6070 on #f6f6f9', '#5c6070', '#f6f6f9', 10, False),
    ('ruler frame numbers #9a9eab on #f6f6f9', '#9a9eab', '#f6f6f9', 10, False),
    ('lane empty text #9a9eab on white', '#9a9eab', '#ffffff', 11, False),
    ('word block text #16181f on #eef0fb', '#16181f', '#eef0fb', 11, False),
    ('word block selected white on accent', '#ffffff', '#1f18c0', 11, False),
    ('.asset label 10px muted on white', '#7a7e8a', '#ffffff', 10, False),
    ('.generator-choice small #656977', '#656977', '#ffffff', 11, False),
    ('.ft-slider output muted 11px', '#7a7e8a', '#fafafb', 11, False),
    ('.upload small muted 12px on #fafafb', '#7a7e8a', '#fafafb', 12, False),
    ('nav.views inactive muted 13px', '#7a7e8a', '#fafafb', 13, True),
    ('nav.views active accent on accent-soft', '#1f18c0', '#eef0fb', 13, True),
    ('tabs inactive muted 12px', '#7a7e8a', '#ffffff', 12, True),
    ('.wand-inline / legend muted 12px', '#7a7e8a', '#fafafb', 12, False),
    ('finalize warning #d9a24a on white (inline style)', '#d9a24a', '#ffffff', 12, False),
    ('footer muted 12px', '#7a7e8a', '#fafafb', 12, False),
    ('placeholder text (Chrome default ~#757575) on #fafafb', '#757575', '#fafafb', 15, False),
    ('.status .dot accent on accent-soft (non-text)', '#1f18c0', '#eef0fb', 0, False),
    ('input border --line-strong vs #fafafb (non-text)', '#dfe2e8', '#fafafb', 0, False),
    ('card border --line vs white (non-text)', '#ececef', '#ffffff', 0, False),
    ('playhead #e5362b on white (non-text)', '#e5362b', '#ffffff', 0, False),
    ('face lane filled #e0b341 on white (non-text)', '#e0b341', '#ffffff', 0, False),
    ('face lane tracked #3aa76d on white (non-text)', '#3aa76d', '#ffffff', 0, False),
]

def contrast():
    print('\n## Contrast (WCAG AA: 4.5 normal text, 3.0 large/bold>=14px bold or >=18px, 3.0 non-text)')
    rows = []
    for label, fg, bg, px, bold in PAIRS:
        r = ratio(fg, bg); need = 3.0 if (px == 0 or px >= 24 or (bold and px >= 18.66)) else 4.5
        rows.append((label, fg, bg, px, round(r, 2), need, 'PASS' if r >= need else 'FAIL'))
    for row in rows: print('|', ' | '.join(str(x) for x in row), '|')
    return rows

def main():
    out = {'pages': {}}
    out['contrast'] = contrast()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, path in PAGES:
            res = {}
            ctx = browser.new_context(viewport={'width': 1440, 'height': 900}); page = ctx.new_page()
            page.goto(BASE + path, wait_until='domcontentloaded'); page.wait_for_selector('#view .panel', timeout=20000); page.wait_for_timeout(2500)
            if name == 'run-quick': page.click('.tl-label[data-track=mask]'); page.wait_for_timeout(600)
            # controls and names
            els = page.locator('button, a[href], input, select, textarea, [role=button], [role=option], summary').evaluate_all(NAME_JS)
            vis = [e for e in els if e['visible']]
            res['controls'] = len(vis)
            res['unnamed'] = [e for e in vis if not e['name']]
            res['glyph_only'] = [e for e in vis if e['name'] and e['glyphOnly']]
            # focus ring: tab through up to 120 stops
            page.keyboard.press('Tab'); seen = []; noring = []
            for i in range(140):
                f = page.evaluate(FOCUS_JS)
                if not f: break
                key = (f['tag'], f['text'])
                if key in seen[-3:]: pass
                seen.append(key)
                ring = (f['outline'].startswith('solid') or f['outline'].startswith('auto')) and not f['outline'].startswith('none') and 'px' in f['outline'] and not f['outline'].split()[1].startswith('0px')
                ring = ring or (f['parentOutline'] and f['parentOutline'] != '0px') or ('px' in f['boxShadow'] and f['boxShadow'] != 'none')
                if f['fv'] and not ring and f['tag'] in ('input', 'select', 'textarea'): noring.append(f)
                page.keyboard.press('Tab')
            res['tab_stops'] = len(seen); res['focus_without_ring'] = noring[:12]
            # click targets that cannot take focus
            res['pointer_only'] = page.evaluate("""() => {
              const out = [];
              for (const sel of ['.stage-overlay.interactive', '.tl-stage', '.wb', '.bg-canvas', '.wand-overlay canvas', '.tl-lane']) for (const e of document.querySelectorAll(sel)) { if (e.offsetWidth && !e.closest('[hidden]') && e.tabIndex < 0) out.push(sel); }
              return [...new Set(out)]; }""")
            ctx.close()
            # touch targets at 380
            ctx = browser.new_context(viewport={'width': 380, 'height': 800}); page = ctx.new_page()
            page.goto(BASE + path, wait_until='domcontentloaded'); page.wait_for_selector('#view .panel', timeout=20000); page.wait_for_timeout(2500)
            if name == 'run-quick': page.click('.tl-label[data-track=mask]'); page.wait_for_timeout(600)
            els = page.locator('button, a[href], input:not([type=file]), select, summary, [role=option]').evaluate_all(NAME_JS)
            vis = [e for e in els if e['visible'] and e['w'] and e['h']]
            small24 = [e for e in vis if min(e['w'], e['h']) < 24]
            small44 = [e for e in vis if min(e['w'], e['h']) < 44]
            res['targets_total'] = len(vis); res['targets_under_24'] = len(small24); res['targets_under_44'] = len(small44)
            res['under_24_examples'] = [(e['tag'], e['type'], e['name'][:30], e['w'], e['h']) for e in small24[:14]]
            res['scrollWidth380'] = page.evaluate('document.documentElement.scrollWidth')
            res['tl_scroll_overflow'] = page.evaluate("(() => { const s = document.querySelector('.tl-scroll'); return s ? [s.scrollWidth, s.clientWidth] : null; })()")
            ctx.close()
            out['pages'][name] = res
            print(f"\n## {name}: controls {res['controls']}, unnamed {len(res['unnamed'])}, glyph-only names {len(res['glyph_only'])}, tab stops {res['tab_stops']}, focus w/o ring {len(res['focus_without_ring'])}, pointer-only {res['pointer_only']}, 380: {res['targets_under_24']}/{res['targets_total']} under 24px, {res['targets_under_44']} under 44px, scrollWidth {res['scrollWidth380']}, timeline overflow {res['tl_scroll_overflow']}")
            for e in res['unnamed'][:10]: print('   unnamed:', e)
            for e in res['glyph_only'][:10]: print('   glyph-only:', e['tag'], e['name'], e['text'])
            for e in res['focus_without_ring'][:6]: print('   no ring:', e)
            for e in res['under_24_examples']: print('   <24px:', e)
        browser.close()
    json.dump(out, open('docs/tidy/measure/a11y-before.json', 'w'), indent=1, default=str)

if __name__ == '__main__': main()
