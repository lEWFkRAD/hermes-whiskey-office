import asyncio
import tempfile
import unittest
from pathlib import Path
from fastapi import HTTPException
from durable_backend import ForgeBackend, JobStopped
from test_studio import photo, model

class StopTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_waits_for_confirmation_and_preserves_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=ForgeBackend(directory)
            started=asyncio.Event(); confirm=asyncio.Event()
            async def remote(image):
                started.set(); await backend.stop_event.wait(); await confirm.wait(); raise JobStopped()
            backend._generate_remote=remote
            key=(await backend.generate(photo()))['job_id']; await started.wait()
            for _ in range(2): self.assertEqual(backend.stop(key)['stage'],'Stopping on Forge')
            self.assertEqual(backend.status(key)['status'],'processing')
            with self.assertRaises(HTTPException): await backend.generate(photo('blue'))
            confirm.set(); await backend.active
            self.assertEqual(backend.status(key)['status'],'cancelled')
            self.assertTrue(Path(backend.photo(key).path).exists())
            self.assertFalse((Path(directory)/(key+'.glb')).exists())
            events=[e async for e in backend.stream(key).body_iterator]
            self.assertIn('event: error',events[0])
            async def succeed(image): return model()
            backend._generate_remote=succeed
            retry=(await backend.retry(key))['job_id']; await backend.active
            self.assertEqual(backend.status(retry)['status'],'success')
            self.assertEqual(backend.stop(retry)['status'],'success')

    async def test_stop_before_launch_does_not_start_remote(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=ForgeBackend(directory)
            async def unexpected(image): self.fail('Remote must not launch')
            backend._generate_remote=unexpected
            key=(await backend.generate(photo()))['job_id']; backend.stop(key); await backend.active
            self.assertEqual(backend.status(key)['status'],'cancelled')

if __name__=='__main__': unittest.main()
