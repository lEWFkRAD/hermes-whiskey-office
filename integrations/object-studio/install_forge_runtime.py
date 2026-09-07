"""Install pinned Trellis CUDA release and verified public GGUFs on Forge."""
from pathlib import Path
import hashlib
import json
import subprocess
import tarfile
import urllib.request

ROOT = Path.home() / 'camera-to-blender-runtime'
ROOT.mkdir(exist_ok=True)
RUNTIME = ROOT / 'runtime'
MODELS = ROOT / 'models'
RUNTIME.mkdir(exist_ok=True)
MODELS.mkdir(exist_ok=True)

def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def download(url, path, expected):
    if path.exists() and digest(path) == expected:
        print('VERIFIED existing', path.name, flush=True)
        return
    partial = path.with_suffix(path.suffix + '.partial')
    print('DOWNLOADING', path.name, flush=True)
    subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                    '--retry', '3', '--continue-at', '-', '--output', str(partial), url], check=True)
    if digest(partial) != expected:
        raise RuntimeError('Checksum mismatch: ' + str(partial))
    partial.replace(path)
    print('VERIFIED', path.name, path.stat().st_size, flush=True)

archive = ROOT / 'trellis-cuda-linux-x64-v0.6.0.tar.gz'
download('https://github.com/pwilkin/trellis.cpp/releases/download/v0.6.0/trellis-cuda-linux-x64.tar.gz',
         archive, 'ae93c21eb03b1128fb533390a6e6a92c39f43443e9b36a59a8a72cd6ce7b7655')
with tarfile.open(archive) as tar:
    tar.extractall(RUNTIME, filter='data')
revision = 'a57397bd3d351599d9729fc144b3f87c3f87d65b'  # pinned model snapshot; review licenses before downloading
manifest = get_json('https://huggingface.co/api/models/ilintar/trellis2-gguf/tree/' + revision)
files = [entry for entry in manifest if entry['type'] == 'file' and entry['path'].endswith('.gguf')]
if not files or sum(entry['size'] for entry in files) > 40 * 1024**3:
    raise RuntimeError('Unexpected model manifest; review before downloading')
(ROOT / 'model-manifest.json').write_text(json.dumps({'revision':revision, 'files':files}, indent=2))
print('MODEL REVISION', revision, 'TOTAL BYTES', sum(entry['size'] for entry in files), flush=True)
for entry in files:
    download('https://huggingface.co/ilintar/trellis2-gguf/resolve/' + revision + '/' + entry['path'] + '?download=true',
             MODELS / entry['path'], entry['lfs']['oid'])
executables = list(RUNTIME.rglob('trellis-cli')) + list(RUNTIME.rglob('trellis-server'))
print('EXECUTABLES', [str(item) for item in executables], flush=True)
for exe in executables:
    result = subprocess.run([str(exe), '--help'], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (ROOT / (exe.name + '-help.txt')).write_text(result.stdout)
    print(result.stdout[:12000], flush=True)
(ROOT / 'install-complete.json').write_text(json.dumps({'version':'v0.6.0','model_revision':revision,
    'models':str(MODELS),'executables':[str(p) for p in executables]}, indent=2))
print('INSTALL_COMPLETE', flush=True)
