"""Run the public offline suite. Never starts Hermes or a GPU generation job."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--godot', default=os.environ.get('HERMES_GODOT_BIN', str(ROOT/'.tools/Godot_v4.7.2-stable_linux.x86_64')))
parser.add_argument('--python-only', action='store_true')
args=parser.parse_args()
if args.python_only:
    subprocess.run([sys.executable,'-m','unittest','discover','-s','app','-p','test_*.py'],cwd=ROOT,check=True)
    subprocess.run(['node','app/test_office_context.cjs'],cwd=ROOT,check=True)
else:
    subprocess.run([sys.executable,'app/check_compatibility.py','--godot',args.godot,
        '--acp-command',json.dumps([sys.executable,str(ROOT/'app/fake_acp.py')]),
        '--receipt',str(ROOT/'app/compatibility-receipt.json')],cwd=ROOT,check=True)
