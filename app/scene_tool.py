"""Explicit local scene action. A completed receipt comes from the live office.

Run: python3 scene_tool.py sphere --label 'Red ball' --color ff2a2a
Never launch another Godot instance or edit the scene-context snapshot.
"""
import argparse
import json
import math
import os
from pathlib import Path
import time
import uuid


def submit(workspace, shape, label, color, radius, replace=False, timeout=12):
    workspace = Path(workspace).resolve(strict=True)
    context = json.loads((workspace/'.hermes-office-context.json').read_text())
    now = time.time()
    if context.get('schema') != 1 or context.get('running') is not True or not 0 <= now-context.get('updated_at', 0) < 3:
        raise ValueError('No fresh running office; no action submitted')
    if shape not in ('sphere', 'box') or not isinstance(label, str) or not 1 <= len(label) <= 80:
        raise ValueError('Expected sphere/box and a label of 1–80 characters')
    color = color.removeprefix('#')
    if len(color) != 6 or any(c not in '0123456789abcdefABCDEF' for c in color):
        raise ValueError('Expected six-digit RGB color')
    if not math.isfinite(radius) or not .02 <= radius <= .5:
        raise ValueError('Radius must be 0.02–0.5 meters')
    command_dir, results = workspace/'.scene-commands', workspace/'.scene-results'
    for directory in (command_dir, results):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('Live scene actions are unavailable; no action submitted')
    request_id = uuid.uuid4().hex
    request = dict(schema=1, id=request_id, instance=context['instance'], expires_at=now+15,
                   action='primitive', shape=shape, label=label, color=color, radius=radius, replace=replace)
    pending = command_dir/(request_id+'.tmp')
    with pending.open('x', encoding='utf-8') as file:
        json.dump(request, file)
    pending.rename(command_dir/(request_id+'.json'))
    deadline = time.monotonic()+timeout
    receipt = results/(request_id+'.json')
    while time.monotonic() < deadline:
        if receipt.is_file():
            result = json.loads(receipt.read_text())
            if result.get('id') != request_id:
                raise ValueError('Mismatched action receipt')
            return result
        time.sleep(.1)
    return dict(status='unconfirmed', id=request_id,
                error='No live receipt yet. Inspect .scene-results for this ID; do not blindly resubmit.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('shape', choices=['sphere', 'box'])
    parser.add_argument('--label', default='Red ball')
    parser.add_argument('--color', default='ff2a2a')
    parser.add_argument('--radius', type=float, default=.09)
    parser.add_argument('--replace', action='store_true')
    parser.add_argument('--workspace', type=Path, default=Path(os.environ.get('HERMES_OFFICE_DATA_DIR', str(Path.home()/'.local/share/hermes-whiskey-office')))/'workspace')
    args = parser.parse_args()
    try:
        result = submit(args.workspace, args.shape, args.label, args.color, args.radius, args.replace)
    except (ValueError, OSError, KeyError) as error:
        result = dict(status='error', error=str(error))
    print(json.dumps(result))
    return 0 if result['status'] == 'done' else 1


if __name__ == '__main__':
    raise SystemExit(main())
