"""Screenshot pages of the running app at desktop and phone widths.

Usage:  .venv-shots/bin/python docs/tidy/shoot.py OUT_DIR BASE_URL name=path [name=path ...]
        e.g.  .venv-shots/bin/python docs/tidy/shoot.py docs/tidy/before http://127.0.0.1:8791 \
                 runs='/?view=runs' quick='/' studio='/?view=studio'
Writes OUT_DIR/<name>-desktop.png (1440 wide) and OUT_DIR/<name>-380.png (380 wide), full page.
Add  --wait=SELECTOR  to wait for an element,  --settle=MS  (default 1500) to wait after load,
--click=SELECTOR (repeatable, applied in order before the shot). Prints console errors per page.
"""
import sys,pathlib,json
from playwright.sync_api import sync_playwright

def main():
    args=[a for a in sys.argv[1:] if not a.startswith('--')]
    opts=[a for a in sys.argv[1:] if a.startswith('--')]
    out=pathlib.Path(args[0]);base=args[1].rstrip('/');pages=[a.split('=',1) for a in args[2:]]
    out.mkdir(parents=True,exist_ok=True)
    settle=1500;wait=None;clicks=[]
    for o in opts:
        k,_,v=o[2:].partition('=')
        if k=='settle':settle=int(v)
        elif k=='wait':wait=v
        elif k=='click':clicks.append(v)
    report={}
    with sync_playwright() as p:
        browser=p.chromium.launch()
        for name,path in pages:
            for label,w,h in (('desktop',1440,900),('380',380,800)):
                ctx=browser.new_context(viewport={'width':w,'height':h},device_scale_factor=1)
                page=ctx.new_page();errors=[]
                page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+path,wait_until='load')
                try:page.wait_for_selector('#view .panel',timeout=8000)   # the app; mockups (file://) have none
                except Exception:pass
                if wait:page.wait_for_selector(wait,timeout=15000)
                for c in clicks:
                    page.click(c);page.wait_for_timeout(400)
                page.wait_for_timeout(settle)
                sw=page.evaluate('document.documentElement.scrollWidth');cw=page.evaluate('document.documentElement.clientWidth')
                page.screenshot(path=str(out/f'{name}-{label}.png'),full_page=True)
                report[f'{name}-{label}']={'console_errors':errors,'scrollWidth':sw,'clientWidth':cw,'horizontal_scroll':sw>cw}
                ctx.close()
        browser.close()
    (out/'shots.json').write_text(json.dumps(report,indent=1))
    for k,v in report.items():print(k,'h-scroll' if v['horizontal_scroll'] else 'ok',('ERRORS: '+' | '.join(v['console_errors'])[:300]) if v['console_errors'] else '')

if __name__=='__main__':main()
