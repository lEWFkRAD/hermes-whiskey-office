"""Record a human review of the current local Desktop acceptance captures.

Run app/smoke_desktop_bridge.py first, inspect EVERY screenshot, then provide
--reviewed. This is an operator attestation, not automatic visual validation.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from runtime_guard import validate_runtime
from smoke_desktop_bridge import tested_inputs
import os

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reviewed', action='store_true')
    args=p.parse_args()
    path=ROOT/'app/desktop-acceptance.json'
    value=json.loads(path.read_text())
    if value.get('passed') is not True: raise SystemExit('Desktop acceptance did not pass.')
    for key, current in tested_inputs(os.environ).items():
        if value.get(key)!=current: raise SystemExit('Inputs changed: rerun acceptance.')
    directory=Path(value['directory']).resolve()
    if not directory.is_relative_to(ROOT/'app'): raise SystemExit('Unexpected capture directory.')
    images=sorted(directory.glob('*.png'))
    if len(images)<14: raise SystemExit('Expected all 14 Desktop acceptance captures.')
    for image in images: print(image)
    if not args.reviewed:
        print('Inspect each image, then rerun with --reviewed. No acceptance recorded.')
        return
    value['visual_review_passed']=True
    value['visual_review']={'method':'local operator attestation', 'images':{i.name:hashlib.sha256(i.read_bytes()).hexdigest() for i in images}}
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)
    validate_runtime(ROOT/'app')
    print('Current Desktop accepted; startup will reject changed binaries, backend or navigation.')

if __name__=='__main__':main()
