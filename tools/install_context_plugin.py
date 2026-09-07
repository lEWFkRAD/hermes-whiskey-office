"""Explicitly install the bundled context plugin; refuse to overwrite other code."""
from pathlib import Path
import hashlib
import json
import os
ROOT=Path(__file__).resolve().parents[1]
home=Path(os.environ.get('HERMES_HOME',str(Path.home()/'.hermes')))
directory=home/'desktop-plugins'
target=directory/'hermes-office-context/plugin.js'
source=(ROOT/'app/office-context-plugin.js').read_bytes()
if target.is_symlink() or any(p.is_symlink() for p in target.parents):
    raise SystemExit('Plugin destination must not be redirected.')
if target.exists() and target.read_bytes()!=source:
    raise SystemExit('Existing plugin differs. Back it up and review the change before replacing it.')
target.parent.mkdir(parents=True,exist_ok=True)
target.write_bytes(source)
plugins={p.parent.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob('*/plugin.js')}
(ROOT/'app/desktop-plugins-lock.json').write_text(json.dumps({'plugins':plugins},indent=2)+'\n')
print('Context plugin installed. Enable it in Hermes, restart Desktop, and run acceptance.')
