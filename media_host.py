"""Public, direct media URLs for Enhancor only (fal uploads to fal storage and never calls this module).

Default host is tmpfiles (temporary, expiring links). Catbox is PUBLIC and PERSISTENT and is never used
unless the user explicitly names it in MEDIA_HOST or MEDIA_HOST_FALLBACKS; no automatic fallback to it.
Configured fallback hosts are tried only for media hosting failures, never for paid model requests."""
from pathlib import Path
from urllib.parse import urlparse
import requests,re,html,time,warnings
from config import setting

HOSTS=('tmpfiles','catbox')
CATBOX_WARNING='Catbox is a public, persistent host: this upload will stay reachable by anyone with the link. It is used only because MEDIA_HOST or MEDIA_HOST_FALLBACKS names catbox explicitly.'
_catbox_warned=False

def _warn_catbox():
    """Warn once per process the first time catbox is actually used."""
    global _catbox_warned
    if not _catbox_warned:
        _catbox_warned=True
        warnings.warn(CATBOX_WARNING)

def _upload_once(path,host):
    path=Path(path)
    with path.open('rb') as f:
        if host=='tmpfiles':
            if path.stat().st_size>100_000_000:raise ValueError('Tmpfiles limit is 100 MB; choose another host or reduce the reference.')
            r=requests.post('https://tmpfiles.org/api/v1/upload',files={'file':(path.name,f)},data={'expire':21600},timeout=180)
            r.raise_for_status();url=r.json()['data']['url']
            parsed=urlparse(url)
            if parsed.hostname!='tmpfiles.org':raise ValueError('Unexpected temporary host response')
            page=requests.get(url,timeout=60)
            page.raise_for_status()
            matches=re.findall(r'https://tmpfiles\.org/dl/[^\"\'<> ]+',page.text)
            if not matches:raise ValueError('Tmpfiles download page did not expose a direct media link')
            url=html.unescape(matches[0])
        elif host=='catbox':
            _warn_catbox()
            data={'reqtype':'fileupload'}
            if setting('CATBOX_USERHASH'):data['userhash']=setting('CATBOX_USERHASH')
            r=requests.post('https://catbox.moe/user/api.php',data=data,files={'fileToUpload':(path.name,f)},timeout=180)
            r.raise_for_status();url=r.text.strip()
        else:raise ValueError('MEDIA_HOST must be tmpfiles or catbox')
    if not url.startswith('https://'):raise ValueError('Host did not return an HTTPS media URL')
    with requests.get(url,stream=True,timeout=60) as check:
        check.raise_for_status()
        if 'text/html' in check.headers.get('Content-Type',''):raise ValueError('Media URL returned a page, not a media file')
        first=next(check.iter_content(256),b'')
        if not first or first.lstrip().lower().startswith((b'<!doctype',b'<html')):raise ValueError('Empty or HTML media response')
    return url


def upload(path):
    """Retry hosting only; never retries a paid model request. Catbox is opt-in only (default fallbacks: none)."""
    primary=(setting('MEDIA_HOST','tmpfiles') or 'tmpfiles').strip().lower()
    fallback=setting('MEDIA_HOST_FALLBACKS','')
    hosts=list(dict.fromkeys([primary]+[h.strip().lower() for h in fallback.split(',') if h.strip()]))
    if any(h not in HOSTS for h in hosts):raise ValueError('Supported media hosts: tmpfiles, catbox')
    from stages.calls import record_call
    record_call(Path(path),primary,'upload')
    errors=[]
    for host in hosts:
        for attempt in range(2):
            try:return _upload_once(path,host)
            except (requests.RequestException,ValueError,KeyError,StopIteration) as exc:
                errors.append(host+': '+type(exc).__name__)
                if attempt==0:time.sleep(1)
        warnings.warn('Media upload failed on '+host+'; trying next configured host if available.')
    raise RuntimeError('All configured media hosts failed ('+', '.join(errors)+'). No generation was submitted. Check connectivity or choose another host.')
