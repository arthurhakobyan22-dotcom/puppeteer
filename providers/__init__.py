"""Seedance 2.5 provider registry: `enhancor` (1080p draft, needs webhook) and `fal` (480p draft, no webhook)."""
from config import setting

PROVIDERS=('enhancor','fal')
KEYS={'enhancor':'ENHANCOR_API_KEY','fal':'FAL_KEY'}

def get_provider(name):
    if name=='enhancor':
        from .enhancor import Enhancor;return Enhancor()
    if name=='fal':
        from .fal import Fal;return Fal()
    raise ValueError(f'Unknown provider {name!r}; choose one of: '+', '.join(PROVIDERS))

def configured(name):
    """True when the provider's key is present; the value itself is never returned."""
    if name not in KEYS:raise ValueError(f'Unknown provider {name!r}')
    return bool(setting(KEYS[name]).strip())

def default_provider():
    chosen=setting('SEEDANCE_PROVIDER').strip().lower()
    if chosen in PROVIDERS:return chosen
    for name in PROVIDERS:
        if configured(name):return name
    return 'enhancor'
