import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

from object_pipeline import Pipeline, validate_glb


def glb(extra=None):
    manifest = {'asset': {'version': '2.0'}, 'meshes': [{'primitives': []}], **(extra or {})}
    data = json.dumps(manifest).encode()
    data += b' ' * (-len(data) % 4)
    return b'glTF' + struct.pack('<IIII', 2, 20+len(data), len(data), 0x4E4F534A) + data


class API:
    def __init__(self):
        self.posts = 0
        self.busy = False
        self.lost = False
        self.status = 'processing'
        self.job = 'a'*32
        self.bad = False

    def get(self, route):
        if route == '/health': return {'generation_backend': 'forge'}
        if route == '/api/jobs': return {'jobs': [{'id': self.job, 'status': 'processing'}] if self.busy else []}
        return {'id': self.job, 'preset': 'fast', 'status': self.status,
                'stage': 'Texture generation', 'metrics': {'bytes': len(glb())}}

    def submit(self, manifest, image):
        self.posts += 1
        if self.lost: raise TimeoutError('Response lost')
        return {'backend': 'forge', 'job_id': self.job}

    def binary(self, route, limit): return b'partial' if self.bad else glb()


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.api = API()
        self.p = Pipeline(self.root/'data', self.root/'ipc', self.api)
        self.image = self.root/'source.png'
        self.image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        self.request = {'id': 'b'*32, 'action': 'render', 'image': str(self.image), 'preset': 'fast'}

    def test_completion_reconnect_and_hash(self):
        self.p.submit(self.request)
        restarted = Pipeline(self.p.data, self.root/'next-ipc', self.api)
        restarted.tick()
        self.assertEqual(self.api.posts, 1)
        self.api.status = 'success'
        restarted.tick()
        row = restarted.rows()[0]
        self.assertEqual(row['phase'], 'ready')
        self.assertEqual(row['sha256'], validate_glb(Path(row['path']).read_bytes()))
        self.assertEqual(self.image.read_bytes(), b'\x89PNG\r\n\x1a\nfixture')
        restarted.tick()
        self.assertEqual(self.api.posts, 1)

    def test_duplicate_and_active_requests_do_not_repost(self):
        self.p.submit(self.request)
        self.p.tick()
        self.p.submit(self.request)
        with self.assertRaises(ValueError): self.p.submit({**self.request, 'id': 'c'*32})
        self.assertEqual(self.api.posts, 1)

    def test_uncertain_response_is_never_reposted_after_restart(self):
        self.api.lost = True
        self.p.submit(self.request)
        self.p.tick()
        self.assertEqual(self.p.rows()[0]['phase'], 'uncertain')
        restarted = Pipeline(self.p.data, self.root/'next-ipc', self.api)
        restarted.tick()
        restarted.submit(self.request)
        self.assertEqual(self.api.posts, 1)

    def test_busy_and_bad_artifact_are_not_ready(self):
        self.api.busy = True
        self.p.submit(self.request)
        self.p.tick()
        self.assertEqual(self.p.rows()[0]['phase'], 'queued')
        self.assertEqual(self.api.posts, 0)
        self.api.busy = False
        self.p.tick()
        self.api.status, self.api.bad = 'success', True
        self.p.tick()
        self.assertFalse(any(r['phase'] == 'ready' for r in self.p.rows()))
        self.assertFalse(list(self.p.runs.glob('*/final.glb')))

    def test_external_resources_and_truncated_glb_rejected(self):
        for data in [glb()[:-1], glb({'images': [{'uri': 'https://example.com/image.png'}]})]:
            with self.assertRaises(ValueError): validate_glb(data)

    def test_command_consumed_once(self):
        path = self.p.ipc/'commands/test.json'
        path.write_text(json.dumps(self.request))
        self.p.tick()
        path.write_text(json.dumps(self.request))
        self.p.tick()
        self.assertEqual(self.api.posts, 1)

    @unittest.skipUnless(os.name == 'posix', 'Forge uses POSIX worker locks')
    def test_parallel_office_worker_waits_without_reposting(self):
        import fcntl
        self.p.submit(self.request)
        with (self.p.data/'worker.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.p.tick()
            self.assertEqual(self.api.posts, 0)
        self.p.tick()
        self.assertEqual(self.api.posts, 1)


if __name__ == '__main__': unittest.main()
