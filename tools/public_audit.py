"""Audit Git-tracked publication inputs and the explicit asset inventory.

This is a focused privacy/integrity regression check, not a general secret scanner
or a substitute for human license/security review.
"""
from pathlib import Path
import hashlib
import json
import re
import struct
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]

def main():
    result=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True,check=True)
    paths=[ROOT/p.decode() for p in result.stdout.split(b'\0') if p]
    if not paths: raise SystemExit('No tracked files; stage the reviewed publication tree first.')
    manifest=json.loads((ROOT/'assets-manifest.json').read_text())
    problems=[]; observed=set()
    # Match credentials/private network locations without printing their values.
    patterns=[rb'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----',
        rb'gh[pousr]_[A-Za-z0-9]{30,}', rb'github_pat_[A-Za-z0-9_]{40,}',
        rb'100\.(?:[6-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}',
        rb'192\.168\.[0-9]{1,3}\.[0-9]{1,3}',
        rb'[A-Za-z0-9-]+\.tail[a-z0-9]+\.ts\.net',
        rb'[A-Z]:[/\\]Users[/\\][^/\\\s]+', rb'/home/(?!your-user)[A-Za-z0-9_-]+/']
    for path in paths:
        name=path.relative_to(ROOT).as_posix()
        if path.is_symlink(): problems.append(name+': symlink');continue
        if any(part in {'.env','.hermes','.ssh','__pycache__','generated','workspace'} for part in path.relative_to(ROOT).parts):
            problems.append(name+': private/runtime path')
        data=path.read_bytes()
        if len(data)>90*1024*1024: problems.append(name+': exceeds per-file budget')
        # GLB embeds compressed textures. Inspect its JSON metadata separately;
        # raster bytes are covered by the reviewed immutable asset inventory.
        scan=data
        if path.suffix in {'.jpg','.png'}: scan=b''
        elif path.suffix=='.glb' and data[:4]==b'glTF':
            scan=data[20:20+struct.unpack_from('<I',data,12)[0]]
        if name!='tools/public_audit.py' and any(re.search(pattern,scan) for pattern in patterns):
            problems.append(name+': possible private identity, network location or credential')
        if path.suffix in {'.glb','.png','.jpg'}:
            observed.add(name)
            row=manifest.get(name,{})
            if row.get('sha256')!=hashlib.sha256(data).hexdigest() or row.get('bytes')!=len(data):
                problems.append(name+': asset missing from inventory or changed')
            if not row.get('license') or not row.get('origin'): problems.append(name+': missing provenance')
            if path.suffix=='.glb':
                if data[:4]!=b'glTF' or struct.unpack_from('<II',data,4)!=(2,len(data)):
                    problems.append(name+': invalid GLB')
                    continue
                size,kind=struct.unpack_from('<II',data,12)
                if kind!=0x4E4F534A: problems.append(name+': missing GLB JSON');continue
                doc=json.loads(data[20:20+size])
                if any('uri' in item for item in doc.get('buffers',[])+doc.get('images',[])):
                    problems.append(name+': external resource in GLB')
    if observed!=set(manifest): problems.append('Asset manifest and tracked assets differ.')
    if problems:
        print('\n'.join(problems));return 1
    print(f'Public audit passed: {len(paths)} tracked files, {len(observed)} licensed/hash-verified assets.')
    return 0

if __name__=='__main__':raise SystemExit(main())
