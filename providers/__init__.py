"""Generator registry: the Seedance 2.5 providers `enhancor` (1080p draft, needs webhook) and `fal` (480p draft, no
webhook), plus `wan` (Wan 2.2 Animate replace on fal, pose-native, one render; docs/GENERATORS.md).

`PROVIDERS` stays the Seedance pair (the default-provider rule, `/providers` and the regression suite rely on it);
`GENERATORS` lists every adapter `get_provider` knows, in the order the generator slot offers them.
"""
from config import setting

PROVIDERS=('enhancor','fal')
GENERATORS=PROVIDERS+('wan',)
KEYS={'enhancor':'ENHANCOR_API_KEY','fal':'FAL_KEY','wan':'FAL_KEY'}

def get_provider(name):
    if name=='enhancor':
        from .enhancor import Enhancor;return Enhancor()
    if name=='fal':
        from .fal import Fal;return Fal()
    if name=='wan':
        from .wan import Wan;return Wan()
    raise ValueError(f'Unknown provider {name!r}; choose one of: '+', '.join(GENERATORS))

def normalized_capabilities(name):
    """The adapter's capabilities in the shared shape (providers/capabilities.py), never a key value."""
    from .capabilities import normalize
    return normalize(get_provider(name).capabilities())

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
