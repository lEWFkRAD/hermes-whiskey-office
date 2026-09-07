import asyncio
import json
from pathlib import Path
import struct
import tempfile
import unittest
from fastapi import HTTPException
from durable_backend import ForgeBackend
from remote_live import clustered_mesh
from test_studio import photo, model

def frame(kind,data): return kind.encode()+struct.pack('>I',len(data))+data

class LiveBuildTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.backend=ForgeBackend(self.root)
        self.key='e'*32
        self.backend.current_job=self.key
        self.backend.jobs[self.key]={'id':self.key,'name':'test','created_at':0,'status':'processing','stage':'test','has_photo':True}

    def mesh(self):
        path=self.root/'raw.bin'
        path.write_bytes(struct.pack('<ii9f3i',3,1,0,0,0,1,0,0,0,0,1,0,1,2))
        return clustered_mesh(path)

    async def test_stream_fragmentation_persistence_and_final_identity(self):
        solid,wire=self.mesh()
        expected=model()
        raw=b'CTB1'+frame('C',photo())+frame('S',solid)+frame('W',wire)+frame('F',expected)
        reader=asyncio.StreamReader()
        task=asyncio.create_task(self.backend.read_frames(reader))
        for offset in range(0,len(raw),37):
            reader.feed_data(raw[offset:offset+37]); await asyncio.sleep(0)
        reader.feed_eof()
        self.assertEqual(await task,expected)
        self.assertEqual(set(self.backend.status(self.key)['checkpoints']),{'cutout','mesh','wire'})
        self.assertEqual(Path(self.backend.preview(self.key,'wire').path).read_bytes(),wire)
        restarted=ForgeBackend(self.root)
        self.assertEqual(set(restarted.status(self.key)['checkpoints']),{'cutout','mesh','wire'})
        with self.assertRaises(HTTPException): restarted.preview(self.key,'../raw.bin')
        restarted.remove(self.key)
        with self.assertRaises(HTTPException): restarted.preview(self.key,'mesh')

    async def test_invalid_cutout_does_not_destroy_final(self):
        reader=asyncio.StreamReader(); reader.feed_data(b'CTB1'+frame('C',b'bad png')+frame('F',model())); reader.feed_eof()
        self.assertEqual(await self.backend.read_frames(reader),model())
        self.assertIn('preview_warning',self.backend.jobs[self.key])

    async def test_invalid_or_incomplete_frame_rejected(self):
        for raw in (b'nope',b'CTB1F'+struct.pack('>I',300*1024*1024),b'CTB1'+frame('F',b'test')[:-1]):
            reader=asyncio.StreamReader(); reader.feed_data(raw); reader.feed_eof()
            with self.assertRaises((ValueError,asyncio.IncompleteReadError)): await self.backend.read_frames(reader)

    def test_mesh_coordinates_and_actual_face_sampling(self):
        solid,wire=self.mesh()
        length=struct.unpack_from('<I',solid,12)[0]; doc=json.loads(solid[20:20+length])
        self.assertEqual(doc['accessors'][0]['max'],[1,1,0])
        self.assertEqual(doc['accessors'][0]['count'],3)
        length=struct.unpack_from('<I',wire,12)[0]; doc=json.loads(wire[20:20+length])
        self.assertEqual(doc['meshes'][0]['primitives'][0]['mode'],1)
        self.assertEqual(doc['accessors'][1]['count'],6)

if __name__=='__main__': unittest.main()
