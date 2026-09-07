"""Download the exact Linux x86_64 editor, verify its release digest, extract it."""
from pathlib import Path
import hashlib
import os
import urllib.request
import zipfile

VERSION = '4.7.2'
SHA256 = 'cadd3204e728a35d3f13adb7fd0d7902636b79f6b95c40c265eb73b6c35329e4'
ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / '.tools'
NAME = f'Godot_v{VERSION}-stable_linux.x86_64'

def main():
    TARGET.mkdir(exist_ok=True)
    archive = TARGET/(NAME+'.zip')
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        temporary=archive.with_suffix('.part')
        with urllib.request.urlopen(f'https://github.com/godotengine/godot/releases/download/{VERSION}-stable/{NAME}.zip', timeout=90) as response:
            data=response.read(200*1024*1024+1)
        if len(data)>200*1024*1024 or hashlib.sha256(data).hexdigest()!=SHA256:
            raise RuntimeError('Godot release checksum mismatch')
        temporary.write_bytes(data); temporary.replace(archive)
    with zipfile.ZipFile(archive) as bundle:
        # Extract only the expected executable, never arbitrary archive paths.
        (TARGET/NAME).write_bytes(bundle.read(NAME))
    (TARGET/NAME).chmod(0o755)
    print(TARGET/NAME)

if __name__=='__main__': main()
