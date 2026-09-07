"""Personal Forge runner source and persistent backend instance."""
from pathlib import Path
from durable_backend import ForgeBackend

REMOTE_RUNNER = Path(__file__).with_name('remote_live.py').read_text(encoding='utf-8')
forge = ForgeBackend()
