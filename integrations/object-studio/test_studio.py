import asyncio
import io
import json
import math
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
from PIL import Image
from fastapi import HTTPException
from fastapi.testclient import TestClient
from durable_backend import ForgeBackend
from job_data import normalize_image, validate_glb
import relay_server

def photo(color='green'):
    out = io.BytesIO()
    Image.new('RGB', (64,64), color).save(out, 'PNG')
    return out.getvalue()

def model():
    parts = [struct.pack('<9f',0,0,0,1,0,0,0,1,0), struct.pack('<6f',0,0,1,0,0,1), struct.pack('<3H',0,1,2), photo()]
    binary = b''; views = []
    for part in parts:
        views.append({'buffer':0,'byteOffset':len(binary),'byteLength':len(part)})
        binary += part + b'\0'*(-len(part)%4)
    doc = {'asset':{'version':'2.0'},'buffers':[{'byteLength':len(binary)}], 'bufferViews':views,
      'accessors':[{'bufferView':0,'componentType':5126,'count':3,'type':'VEC3'}, {'bufferView':1,'componentType':5126,'count':3,'type':'VEC2'}, {'bufferView':2,'componentType':5123,'count':3,'type':'SCALAR'}],
      'meshes':[{'primitives':[{'attributes':{'POSITION':0,'TEXCOORD_0':1},'indices':2,'material':0}]}],
      'materials':[{'pbrMetallicRoughness':{'baseColorTexture':{'index':0}}}], 'textures':[{'source':0}], 'images':[{'bufferView':3,'mimeType':'image/png'}]}
    metadata = json.dumps(doc).encode(); metadata += b' '*(-len(metadata)%4)
    return b'glTF'+struct.pack('<II',2,28+len(metadata)+len(binary))+struct.pack('<I4s',len(metadata),b'JSON')+metadata+struct.pack('<I4s',len(binary),b'BIN\0')+binary

class StudioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent/'acceptance')
        self.backend = ForgeBackend(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()

    async def test_idempotency_busy_and_restart_recovery(self):
        gate=asyncio.Event(); calls=[]
        async def remote(data):
            calls.append(data); await gate.wait(); return model()
        self.backend._generate_remote=remote
        first=await self.backend.generate(photo(),'one')
        same=await self.backend.generate(photo(),'one')
        double=await self.backend.generate(photo(),'two')
        self.assertEqual(first,same); self.assertEqual(first,double)
        with self.assertRaises(HTTPException) as caught:
            await self.backend.generate(photo('blue'),'three')
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual(caught.exception.detail['active_job_id'],first['job_id'])
        with self.assertRaises(HTTPException):
            await self.backend.generate(photo('blue'),'one')
        gate.set(); await self.backend.active
        key=first['job_id']; self.assertEqual(len(calls),1)
        self.assertEqual(self.backend.status(key)['metrics']['triangles'],1)
        restarted=ForgeBackend(self.temp.name)
        self.assertEqual(restarted.status(key)['status'],'success')
        self.assertTrue(Path(restarted.photo(key).path).is_file())
        self.assertEqual((await restarted.generate(photo(),'one'))['job_id'],key)

    async def test_failure_retry_and_recoverable_delete(self):
        async def fail(data): raise RuntimeError('Forge offline')
        self.backend._generate_remote=fail
        first=await self.backend.generate(photo(),'first'); await self.backend.active
        key=first['job_id']; self.assertEqual(self.backend.status(key)['error'],'Forge offline')
        restarted=ForgeBackend(self.temp.name)
        async def good(data): return model()
        restarted._generate_remote=good
        result=await restarted.retry(key,'retry'); await restarted.active
        self.assertEqual(restarted.status(result['job_id'])['status'],'success')
        restarted.remove(key)
        with self.assertRaises(HTTPException): restarted.photo(key)
        restarted.restore(key); self.assertTrue(restarted.status(key)['has_photo'])
        with self.assertRaises(HTTPException): restarted.model('../.env')

    async def test_interrupted_state_and_corrupt_output(self):
        async def corrupt(data): return model()[:-1]
        self.backend._generate_remote=corrupt
        result=await self.backend.generate(photo(),'bad'); await self.backend.active
        key=result['job_id']; self.assertEqual(self.backend.status(key)['status'],'failed')
        self.backend.update(key,status='processing')
        restarted=ForgeBackend(self.temp.name)
        self.assertEqual(restarted.status(key)['stage'],'Interrupted')
        self.assertTrue(Path(restarted.photo(key).path).exists())

    def test_image_and_model_validation(self):
        with self.assertRaises(HTTPException): normalize_image(b'\x89PNG\r\n\x1a\ntruncated')
        self.assertEqual(validate_glb(model())['vertices'],3)
        data=bytearray(model()); size=struct.unpack_from('<I',data,12)[0]
        struct.pack_into('<f',data,28+size,float('nan'))
        with self.assertRaises(ValueError): validate_glb(data)
        jpeg=io.BytesIO(); image=Image.new('RGB',(80,40),'red'); exif=Image.Exif(); exif[274]=6; image.save(jpeg,'JPEG',exif=exif)
        result=normalize_image(jpeg.getvalue())
        with Image.open(io.BytesIO(result)) as normalized:
            self.assertEqual(normalized.size,(40,80)); self.assertFalse(normalized.getexif())

class ImportTests(unittest.TestCase):
    def test_actual_ack_required_and_owned_by_target_socket(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'acceptance') as directory:
            backend=ForgeBackend(directory)
            key='a'*32
            backend.jobs[key]={'id':key,'name':'test','created_at':time.time(),'finished_at':time.time(),'status':'success','stage':'Ready','preset':'detailed','has_photo':False}
            backend.store.save(backend.jobs[key]); (Path(directory)/(key+'.glb')).write_bytes(model())
            with patch.object(relay_server,'forge',backend), TestClient(relay_server.app) as client:
                self.assertEqual(client.post('/api/jobs/'+key+'/import').status_code,409)
                with client.websocket_connect('/ws?client=blender') as blender:
                    blender.send_json({'type':'hello','import_ack':True})
                    for _ in range(30):
                        if client.get('/api/jobs').json()['blender_connected']: break
                        time.sleep(.01)
                    result=client.post('/api/jobs/'+key+'/import'); self.assertEqual(result.status_code,200)
                    token=result.json()['request_id']; payload=blender.receive_json(); self.assertEqual(payload['request_id'],token)
                    self.assertEqual(client.get('/api/imports/'+token).json()['status'],'pending')
                    self.assertEqual(client.post('/api/jobs/'+key+'/import').json()['request_id'],token)
                    with client.websocket_connect('/ws?client=untrusted') as other:
                        other.send_json({'type':'import_result','request_id':token,'success':True,'meshes':999})
                        self.assertEqual(client.get('/api/imports/'+token).json()['status'],'pending')
                    blender.send_json({'type':'import_result','request_id':token,'success':True,'meshes':1,'materials':1})
                    for _ in range(30):
                        state=client.get('/api/imports/'+token).json()
                        if state['status']!='pending': break
                        time.sleep(.01)
                    self.assertEqual(state['status'],'success'); self.assertEqual(state['meshes'],1)

if __name__=='__main__': unittest.main()
