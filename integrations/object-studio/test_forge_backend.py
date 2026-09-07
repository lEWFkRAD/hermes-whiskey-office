"""Contract tests use a fake remote transport, never a GPU or cloud API."""
import asyncio
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['GENERATION_BACKEND'] = 'forge'
from fastapi import HTTPException
from fastapi.testclient import TestClient
from forge_backend import ForgeBackend
import relay_server

from test_studio import photo, model
PNG = photo()
GLB = model()


class ForgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    async def test_one_generation_shared_by_both_streams_and_valid_download(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = ForgeBackend(directory)
            calls = []
            async def remote(image):
                calls.append(image)
                return GLB
            backend._generate_remote = remote
            result = await backend.generate(PNG)
            self.assertEqual(result['preview_task_id'], result['final_task_id'])
            await backend.active
            job = result['final_task_id']
            self.assertEqual(calls, [PNG])
            for _ in range(2):
                events = [event async for event in backend.stream(job).body_iterator]
                self.assertIn('event: complete', events[0])
                self.assertIn('/local-models/' + job + '.glb', events[0])
            self.assertEqual(Path(backend.model(job + '.glb').path).read_bytes(), GLB)
            restarted = ForgeBackend(directory)
            events = [event async for event in restarted.stream(job).body_iterator]
            self.assertIn('event: complete', events[0])

    async def test_busy_rejected_and_failure_reported_to_both_streams(self):
        backend = ForgeBackend(self.directory.name)
        gate = asyncio.Event()
        async def remote(image):
            await gate.wait()
            raise RuntimeError('SSH connection unavailable')
        backend._generate_remote = remote
        result = await backend.generate(PNG)
        with self.assertRaises(HTTPException) as error:
            await backend.generate(photo('blue'))
        self.assertEqual(error.exception.status_code, 409)
        gate.set()
        await backend.active
        for key in ('preview_task_id', 'final_task_id'):
            events = [event async for event in backend.stream(result[key]).body_iterator]
            self.assertIn('event: error', events[0])
            self.assertIn('SSH connection unavailable', events[0])

    async def test_rejects_corrupt_model_and_unknown_ids(self):
        backend = ForgeBackend(self.directory.name)
        async def remote(image):
            return GLB[:-1]
        backend._generate_remote = remote
        result = await backend.generate(PNG)
        await backend.active
        self.assertEqual(backend.jobs[result['final_task_id']]['status'], 'failed')
        with self.assertRaises(HTTPException):
            backend.stream('missing')
        with self.assertRaises(HTTPException):
            backend.model('../.env')

    async def test_upload_validation(self):
        backend = ForgeBackend(self.directory.name)
        for image, status in ((b'no image', 415), (b'x' * (20 * 1024 * 1024 + 1), 413)):
            with self.assertRaises(HTTPException) as error:
                await backend.generate(image)
            self.assertEqual(error.exception.status_code, status)


class ApiTests(unittest.TestCase):
    def test_forge_api_without_tripo_key(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = ForgeBackend(directory)
            async def remote(image):
                return GLB
            backend._generate_remote = remote
            with patch.object(relay_server, 'forge', backend), patch.object(relay_server, 'TRIPO_API_KEY', ''), TestClient(relay_server.app) as client:
                self.assertEqual(client.get('/health').json()['generation_backend'], 'forge')
                result = client.post('/generate3d', files={'image': ('test.png', PNG, 'image/png')})
                self.assertEqual(result.status_code, 200)
                job = result.json()['final_task_id']
                stream = client.get('/generate3d/' + job + '/stream')
                self.assertIn('event: complete', stream.text)
                model = client.get('/local-models/' + job + '.glb')
                self.assertEqual(model.content, GLB)


if __name__ == '__main__':
    unittest.main()
