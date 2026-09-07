"""Office-owned jobs through the existing Object Studio API. No server changes.

Explicit image submission only; reconnect polls known jobs without resubmitting.
The process belongs to the office launcher. Server computation survives closing
the office, and persisted job IDs resume collection on the next launch.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import time
import uuid

import object_studio_client as studio

API_BASE = os.environ.get('HERMES_OBJECT_STUDIO_URL', 'http://127.0.0.1:8000').rstrip('/')
LIMIT = 64 * 1024 * 1024


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate_glb(data):
    if len(data) < 28 or len(data) > LIMIT or data[:4] != b'glTF':
        raise ValueError('Model unavailable or exceeds the podium 64 MB limit')
    if struct.unpack_from('<II', data, 4) != (2, len(data)):
        raise ValueError('Model download is incomplete')
    size, kind = struct.unpack_from('<II', data, 12)
    if kind != 0x4E4F534A or size > len(data)-20:
        raise ValueError('Invalid model manifest')
    manifest = json.loads(data[20:20+size])
    for item in manifest.get('buffers', []) + manifest.get('images', []):
        if 'uri' in item:
            raise ValueError('Podium models must embed their buffers and textures')
    if not manifest.get('meshes'):
        raise ValueError('Model has no mesh')
    return hashlib.sha256(data).hexdigest()


class Pipeline:
    def __init__(self, data, ipc, api=None):
        self.data, self.ipc = Path(data), Path(ipc)
        self.runs = self.data/'jobs'
        for path in [self.data, self.runs, self.ipc, self.ipc/'commands']:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        studio.API_BASE = API_BASE
        self.api = api or studio.Api()
        self.message = 'Choose an image, then Render image'

    def rows(self):
        rows = []
        for path in sorted(self.runs.glob('*/office.json')):
            try:
                row = read(path)
                if re.fullmatch('[a-f0-9]{32}', row['id']) and path.parent.name == row['id']:
                    rows.append(row)
            except (OSError, ValueError, KeyError):
                continue
        return sorted(rows, key=lambda row: row.get('created_at', 0))

    def save(self, directory, row):
        studio.save_json(directory/'office.json', row)

    def submit(self, request):
        identifier = request.get('id', '')
        if not re.fullmatch('[a-f0-9]{32}', identifier):
            raise ValueError('Invalid request identifier')
        directory = self.runs/identifier
        if directory.exists():
            self.message = 'Request already saved; no duplicate render submitted'
            return
        if any(r['phase'] in ('queued', 'submitting', 'processing', 'uncertain') for r in self.rows()):
            raise ValueError('A render is active or awaiting reconciliation; collect it first')
        source = Path(request['image']).resolve(strict=True)
        label = source.stem[:60] or 'Image object'
        directory = studio.prepare(source, label, identifier, root=self.runs,
                                   preset=request.get('preset', 'fast'))
        row = {'id': identifier, 'label': label, 'phase': 'queued', 'stage': 'Waiting for Object Studio',
               'created_at': time.time(), 'preset': request.get('preset', 'fast')}
        self.save(directory, row)
        self.message = row['stage']

    def start(self, row):
        directory = self.runs/row['id']
        if (directory/'submission-attempt.json').exists():
            row.update(phase='submitting')
            self.save(directory, row)
            return
        try:
            job = studio.submit_once(directory, self.api)
            row.update(phase='processing' if job else 'queued', job_id=job or '',
                       stage='Rendering' if job else 'Waiting for the current Object Studio render to finish')
        except Exception as error:
            # A lost POST response must never cause another submission.
            bound = directory/'job.json'
            row.update(phase='processing' if bound.exists() else
                       ('uncertain' if (directory/'submission-attempt.json').exists() else 'failed'),
                       stage=str(error)[:350])
            if bound.exists(): row['job_id'] = read(bound)['job_id']
        self.save(directory, row)
        self.message = row['stage']

    def collect(self, row):
        directory = self.runs/row['id']
        if row['phase'] == 'queued':
            self.start(row)
            return
        if row['phase'] == 'submitting':
            bound = directory/'job.json'
            if bound.exists():
                row.update(phase='processing', job_id=read(bound)['job_id'])
            else:
                row.update(phase='uncertain', stage='Interrupted submission; inspect saved request before another render')
                self.save(directory, row)
                return
        job = row.get('job_id', '')
        if not studio.JOB_PATTERN.fullmatch(job): raise ValueError('Invalid saved job ID')
        state = self.api.get('/api/jobs/'+job)
        if state.get('id') != job or state.get('preset') != row['preset']:
            raise ValueError('Job response does not match the saved request')
        row.update(stage=state.get('stage', state['status']), elapsed_seconds=state.get('elapsed_seconds', 0))
        row.pop('connection_note', None)
        if state['status'] == 'success':
            binary = self.api.binary('/local-models/'+job+'.glb', LIMIT)
            expected = state.get('metrics', {}).get('bytes')
            if expected is not None and len(binary) != expected: raise ValueError('Incomplete model response')
            digest = validate_glb(binary)
            target = directory/'final.glb'
            pending = target.with_suffix('.part')
            pending.write_bytes(binary)
            pending.replace(target)
            row.update(phase='ready', stage='Ready to pick up', path=str(target), sha256=digest,
                       bytes=len(binary), finished_at=time.time())
        elif state['status'] in ('failed', 'cancelled'):
            row.update(phase=state['status'], stage=str(state.get('error') or state.get('stage') or state['status'])[:350])
        self.save(directory, row)

    def tick(self):
        # Multiple office windows may run, but only one may submit/collect at a
        # time. OS locks release on exit, so a crash cannot strand the queue.
        with (self.data/'worker.lock').open('a+b') as lock:
            try:
                if os.name == 'posix':
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    import msvcrt
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.publish()
                return
            self._tick_locked()

    def publish(self):
        studio.save_json(self.ipc/'status.json', {'updated_at': time.time(), 'message': self.message,
                        'jobs': self.rows(), 'data_dir': str(self.data)})

    def _tick_locked(self):
        for path in sorted((self.ipc/'commands').glob('*.json'))[:8]:
            try:
                if path.is_symlink() or path.stat().st_size > 8192: raise ValueError('Invalid render command')
                request = read(path)
                # Consume before any network mutation. The job ID is also a
                # durable deduplication key; ambiguous work is never reposted.
                path.rename(path.with_suffix('.consumed'))
                if request.get('action') != 'render': raise ValueError('Unknown render command')
                self.submit(request)
            except Exception as error:
                self.message = str(error)[:350]
        for row in self.rows():
            if row['phase'] not in ('queued', 'processing', 'submitting'): continue
            try:
                self.collect(row)
                self.message = row['stage']
            except Exception as error:
                row['connection_note'] = str(error)[:250]
                self.save(self.runs/row['id'], row)
                self.message = 'Connection interrupted; saved job will reconnect. '+str(error)[:180]
        self.publish()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--ipc-dir', required=True)
    args = parser.parse_args()
    pipeline = Pipeline(args.data_dir, args.ipc_dir)
    while True:
        pipeline.tick()
        time.sleep(2)


if __name__ == '__main__': main()
