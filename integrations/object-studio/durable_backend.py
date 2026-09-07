"""Persistent, serialized image generation. All inference remains on personal Forge."""
import asyncio
import base64
import hashlib
import json
import os
import re
import struct
import io
from PIL import Image
from pathlib import Path
import shlex
import time
import uuid
from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from job_data import JobStore, job_id, normalize_image, validate_glb

class JobStopped(Exception):
    pass

class ForgeBackend:
    def __init__(self, output_dir=None):
        self.output_dir = Path(output_dir or Path(__file__).parent / 'generated')
        self.store = JobStore(self.output_dir)
        self.jobs = self.store.jobs
        self.active = None
        self.current_job = None
        self.stop_event = None

    def update(self, key, **changes):
        self.jobs[key].update(changes)
        self.store.save(self.jobs[key])

    async def generate(self, image, request_key=None, preset='detailed', name='Untitled object'):
        if preset not in ('fast', 'detailed'):
            raise HTTPException(422, 'Choose Fast or Detailed.')
        if request_key and (len(request_key) > 100 or not request_key.isascii()):
            raise HTTPException(422, 'Invalid request identifier.')
        raw_hash = hashlib.sha256(image).hexdigest()
        if request_key:
            for key, state in self.jobs.items():
                if state.get('request_key') == request_key and not state.get('deleted_at'):
                    if state.get('input_hash') != raw_hash or state['preset'] != preset:
                        raise HTTPException(409, 'That request identifier belongs to a different photo or quality setting.')
                    return self.result(key)
        if self.active is not None and not self.active.done():
            current = self.jobs[self.current_job]
            if current.get('input_hash') == raw_hash and current['preset'] == preset:
                return self.result(self.current_job)
            raise HTTPException(409, {'message': 'Forge is already working. Open the running job, or try this photo when it finishes.', 'active_job_id': self.current_job})
        image = normalize_image(image)
        key = uuid.uuid4().hex
        (self.store.records / (key + '.png')).write_bytes(image)
        self.jobs[key] = dict(id=key, name=(name.strip() or 'Untitled object')[:80], status='processing', progress=0,
            stage='Connecting to Forge', created_at=time.time(), preset=preset, has_photo=True,
            request_key=request_key or key, input_hash=raw_hash, timings=[])
        self.store.save(self.jobs[key])
        self.current_job = key
        self.stop_event = asyncio.Event()
        self.active = asyncio.create_task(self._run(key, image))
        return self.result(key)

    def result(self, key):
        return {'preview_task_id': key, 'final_task_id': key, 'job_id': key, 'backend': 'forge'}

    def stage(self, label):
        record = self.jobs[self.current_job]
        if record.get('stop_requested'): return
        if record['stage'] != label:
            record['timings'].append({'stage': label, 'seconds': round(time.time()-record['created_at'], 2)})
            self.update(self.current_job, stage=label)

    def checkpoint(self, kind, data):
        labels = {'C': ('cutout','Isolated object','png'), 'S': ('mesh','Simplified decoded surface','glb'), 'W': ('wire','Simplified decoded wireframe','glb')}
        name, label, extension = labels[kind]
        if kind == 'C':
            with Image.open(io.BytesIO(data)) as image:
                if image.format != 'PNG' or image.width*image.height > 16_000_000:
                    raise ValueError('Invalid cutout')
                image.verify()
        elif len(data)<28 or data[:4]!=b'glTF' or struct.unpack_from('<II',data,4)!=(2,len(data)):
            raise ValueError('Invalid live mesh')
        key = self.current_job
        path = self.store.records / (key+'-'+name+'.'+extension)
        temp = path.with_suffix('.part'); temp.write_bytes(data); temp.replace(path)
        checkpoints = dict(self.jobs[key].get('checkpoints',{}))
        checkpoints[name] = {'label':label,'url':'/api/jobs/'+key+'/checkpoints/'+name,
            'seconds':round(time.time()-self.jobs[key]['created_at'],2),'bytes':len(data)}
        self.update(key, checkpoints=checkpoints, preview_method='vertex-cluster-48')

    async def read_frames(self, reader):
        final = None
        try:
            magic = await reader.readexactly(4)
        except asyncio.IncompleteReadError as exc:
            if not exc.partial: return None  # SSH error is reported from stderr.
            raise ValueError('Incomplete Forge stream') from exc
        if magic != b'CTB1': raise ValueError('Unexpected Forge stream')
        while True:
            try: header = await reader.readexactly(5)
            except asyncio.IncompleteReadError as exc:
                if exc.partial: raise ValueError('Incomplete Forge frame') from exc
                break
            kind = chr(header[0]); size = struct.unpack('>I',header[1:])[0]
            if kind not in 'CSWF' or size <= 0 or size > (256*1024*1024 if kind=='F' else 8*1024*1024):
                raise ValueError('Invalid Forge frame')
            data = await reader.readexactly(size)
            if kind=='F':
                if final is not None: raise ValueError('Duplicate final output')
                final=data
            else:
                try: self.checkpoint(kind,data)
                except (ValueError,OSError,KeyError) as exc:
                    self.update(self.current_job, preview_warning='A live checkpoint could not be displayed. Generation continues.')
        return final

    async def _generate_remote(self, image):
        from forge_backend import REMOTE_RUNNER
        ssh = os.getenv('FORGE_SSH_EXE', r'C:\Windows\System32\OpenSSH\ssh.exe' if os.name == 'nt' else 'ssh')
        host = os.environ['FORGE_SSH_HOST']
        source = base64.b64encode(REMOTE_RUNNER.encode()).decode()
        fast = self.jobs[self.current_job]['preset'] == 'fast'
        command = ['python3', '-c', "import base64;exec(base64.b64decode('" + source + "'))",
            os.environ['FORGE_TRELLIS_BIN'],
            os.environ['FORGE_TRELLIS_MODELS'],
            '512' if fast else '1024', '1024' if fast else '2048']
        if os.getenv('FORGE_SUDO', '0') == '1':
            command = ['sudo', '-n'] + command
        process = await asyncio.create_subprocess_exec(ssh, '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3', host,
            'exec ' + shlex.join(command), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        log_path = self.store.records / (self.current_job + '.log')
        tail = bytearray()

        async def logs():
            pending = ''
            with log_path.open('wb') as log:
                while chunk := await process.stderr.read(8192):
                    log.write(chunk)
                    log.flush()
                    tail.extend(chunk)
                    del tail[:-5000]
                    pending += chunk.decode('utf-8', errors='replace').replace('\r', '\n')
                    lines = pending.split('\n')
                    pending = lines.pop()[-16000:]
                    for line in lines:
                        if line.startswith('CAMERA_STAGE:'):
                            self.stage(line.split(':', 1)[1].strip())
                        elif re.match(r'^\[\d+/\d+\] ', line):
                            for marker, label in (
                                ('preprocess ', 'Removing background'),
                                ('DINOv3 conditioning', 'Analyzing photo'),
                                ('sparse-structure flow', 'Building shape'),
                                ('shape SLAT flow', 'Refining shape'),
                                ('FlexiDualGrid shape decode', 'Creating mesh'),
                                ('texture SLAT flow', 'Generating textures'),
                                ('write /', 'Packing textured model'),
                            ):
                                if marker in line:
                                    self.stage(label)
                                    break

        async def transfer():
            async def send_input():
                try:
                    process.stdin.write(struct.pack('>I',len(image))+image)
                    await process.stdin.drain()
                    await self.stop_event.wait()
                    process.stdin.write(b'S')
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    # SSH may fail before accepting stdin. Keep draining stderr
                    # so the job reports the transport error, not a pipe error.
                    pass
            sender=asyncio.create_task(send_input())
            try:
                data, _ = await asyncio.gather(self.read_frames(process.stdout), logs())
                await process.wait()
                return data
            finally:
                sender.cancel()
                await asyncio.gather(sender,return_exceptions=True)
                process.stdin.close()

        try:
            data = await asyncio.wait_for(transfer(), timeout=960)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            detail = tail.decode('utf-8', errors='replace').strip()[-1000:]
            if 'CAMERA_STOPPED' in detail: raise JobStopped()
            raise RuntimeError('Forge could not finish this model. ' + detail)
        if data is None: raise RuntimeError('Forge returned no completed model')
        return data

    async def _run(self, key, image):
        try:
            if self.jobs[key].get('stop_requested'): raise JobStopped()
            data = await self._generate_remote(image)
            self.stage('Checking geometry and textures')
            metrics = await asyncio.to_thread(validate_glb, data)
            if self.jobs[key].get('stop_requested'): raise JobStopped()
            pending = self.output_dir / (key + '.part')
            pending.write_bytes(data)
            pending.replace(self.output_dir / (key + '.glb'))
            self.update(key, status='success', progress=100, stage='Ready', metrics=metrics, finished_at=time.time())
        except JobStopped:
            self.update(key,status='cancelled',stage='Stopped',error='You stopped this job. Your photo and available checkpoints are saved for retry.',finished_at=time.time())
        except asyncio.CancelledError:
            self.update(key, status='failed', stage='Interrupted', error='The app stopped during generation. Your photo is saved for retry.', finished_at=time.time())
            raise
        except Exception as exc:
            self.update(key, status='failed', stage='Could not finish', error=str(exc) or 'Generation timed out. Your photo is saved for retry.', finished_at=time.time())

    def status(self, key):
        return self.store.public(self.store.get(key))

    def stop(self, key):
        record=self.store.get(key)
        if record['status']!='processing': return self.status(key)
        if key!=self.current_job or self.stop_event is None:
            raise HTTPException(409,'This job is not controlled by the current server.')
        self.update(key,stop_requested=True,stage='Stopping on Forge')
        self.stop_event.set()
        return self.status(key)

    def listing(self):
        return [self.store.public(r) for r in sorted(self.jobs.values(), key=lambda r: r['created_at'], reverse=True) if not r.get('deleted_at')]

    async def retry(self, key, request_key=None, preset=None):
        record = self.store.get(key)
        if record['status'] == 'processing':
            return self.result(key)
        photo = self.store.records / (key + '.png')
        if not photo.is_file():
            raise HTTPException(404, 'This older model has no saved source photo. Take or upload a new photo.')
        return await self.generate(photo.read_bytes(), request_key, preset or record['preset'], record['name'])

    def remove(self, key):
        record = self.store.get(key)
        if record['status'] == 'processing':
            raise HTTPException(409, 'This job is still running. You can leave the screen and return later.')
        self.update(key, deleted_at=time.time())
        return {'status': 'deleted', 'undo_available': True}

    def restore(self, key):
        record = self.jobs.get(job_id(key))
        if not record:
            raise HTTPException(404, 'Job not found')
        record.pop('deleted_at', None)
        self.store.save(record)
        return self.status(key)

    def photo(self, key):
        self.store.get(key)
        path = self.store.records / (key + '.png')
        if not path.is_file():
            raise HTTPException(404, 'Source photo unavailable')
        return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'private, max-age=3600'})

    def preview(self, key, name):
        record = self.store.get(key)
        if name not in ('cutout','mesh','wire') or name not in record.get('checkpoints',{}):
            raise HTTPException(404,'Checkpoint not available')
        ext = 'png' if name=='cutout' else 'glb'
        path = self.store.records / (key+'-'+name+'.'+ext)
        return FileResponse(path, media_type='image/png' if ext=='png' else 'model/gltf-binary',
            headers={'Cache-Control':'private, max-age=3600'})

    def stream(self, key):
        self.store.get(key)
        async def events():
            while True:
                state = self.status(key)
                event = 'complete' if state['status'] == 'success' else 'error' if state['status'] in ('failed','cancelled') else 'progress'
                yield 'event: ' + event + '\ndata: ' + json.dumps(state) + '\n\n'
                if event != 'progress':
                    return
                await asyncio.sleep(1)
        return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    def model(self, filename):
        if not filename.endswith('.glb'):
            raise HTTPException(404, 'Model not found')
        self.store.get(filename[:-4])
        path = self.output_dir / filename
        if not path.is_file():
            raise HTTPException(404, 'Model not found')
        return FileResponse(path, media_type='model/gltf-binary')
