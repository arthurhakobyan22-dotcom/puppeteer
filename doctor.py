"""Offline checks; never prints credential values or starts paid calls."""
import argparse,importlib,shutil,sys
from config import setting

PLACEHOLDERS=('your_key','your_api','replace_me','placeholder')

def key_present(name):
    value=setting(name).strip()
    return bool(value) and not any(x in value.lower() for x in PLACEHOLDERS)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--require-keys',action='store_true');parser.add_argument('--mesh',action='store_true');args=parser.parse_args()
    failed=sys.version_info<(3,12)
    print('Python:',sys.version.split()[0],'(3.12+ required)')
    for name in ['av','numpy','PIL','requests','fastapi','uvicorn','multipart','gradio_client','scipy','fal_client']:
        try:importlib.import_module(name);print(name+': OK')
        except Exception as exc:print(name+': FAILED ('+type(exc).__name__+')');failed=True
    cloudflared=bool(shutil.which('cloudflared'))
    print('cloudflared: '+('OK' if cloudflared else 'MISSING (optional; only the Enhancor callback tunnel needs it)'))
    if args.mesh:
        from pathlib import Path
        import subprocess
        worker=Path(__file__).resolve().parent/'.venv-face/bin/python'
        ready=worker.exists() and subprocess.run([str(worker),'-c','import mediapipe,av,PIL,numpy'],capture_output=True).returncode==0
        print('Face mesh worker: '+('OK' if ready else 'MISSING — run bash setup-face-mesh.sh'))
        failed=failed or not ready
    keys={}
    for key,note in [('FAL_KEY',''),('ENHANCOR_API_KEY',''),('REPLICATE_API_TOKEN',' (depth preparation and Demucs)'),('HF_TOKEN',' (optional Hugging Face depth provider)')]:
        keys[key]=key_present(key)
        print(key+': '+('configured (not verified remotely)' if keys[key] else 'MISSING')+note)
    if setting('MEDIA_HOST','tmpfiles') not in ['tmpfiles','catbox']:
        print('MEDIA_HOST must be tmpfiles or catbox');failed=True
    webhook=bool(setting('ENHANCOR_WEBHOOK_URL'))
    ready=[]
    if keys['FAL_KEY']:print('fal: READY (no webhook/tunnel needed)');ready.append('fal')
    else:print('fal: NOT READY — set FAL_KEY (fal needs no cloudflared or webhook)')
    if keys['ENHANCOR_API_KEY'] and webhook:print('enhancor: READY');ready.append('enhancor')
    else:
        missing=[]
        if not keys['ENHANCOR_API_KEY']:missing.append('ENHANCOR_API_KEY')
        if not webhook:missing.append('webhook (install cloudflared and launch the app, or set ENHANCOR_WEBHOOK_URL)')
        print('enhancor: NOT READY — missing '+' and '.join(missing))
    chosen=setting('SEEDANCE_PROVIDER').strip()
    if chosen and chosen not in ['enhancor','fal']:print('SEEDANCE_PROVIDER must be enhancor or fal');failed=True
    if failed:print('DEPENDENCIES NOT READY');return 1
    if not keys['REPLICATE_API_TOKEN']:print('Depth preparation is blocked until REPLICATE_API_TOKEN is set; face-mesh mode works without it.')
    if not ready:
        print('LOCAL UI READY; GENERATION BLOCKED until at least one provider is configured.')
        return 2 if args.require_keys else 0
    print('LOCAL SETUP READY ('+', '.join(ready)+'); provider access/balance has not been verified by this offline check.')
    return 0
if __name__=='__main__':sys.exit(main())
