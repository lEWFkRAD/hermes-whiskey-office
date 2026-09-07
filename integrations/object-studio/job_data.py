"""Durable private job records and validation for the personal Forge workflow."""
import io
import json
import math
from pathlib import Path
import re
import struct
import time
from PIL import Image, ImageOps
from fastapi import HTTPException

def job_id(value):
    if not re.fullmatch(r'[a-f0-9]{32}', value):
        raise HTTPException(404, 'Job not found')
    return value

def normalize_image(data):
    if not data or len(data) > 20 * 1024**2:
        raise HTTPException(413, 'Choose a photo smaller than 20 MB.')
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValueError('format')
            if source.width * source.height > 40_000_000 or min(source.size) < 32:
                raise ValueError('dimensions')
            source.load()
            image = ImageOps.exif_transpose(source).convert('RGBA' if 'A' in source.getbands() else 'RGB')
            image.thumbnail((1536, 1536))
            output = io.BytesIO()
            image.save(output, format='PNG')
            return output.getvalue()
    except Exception as exc:
        raise HTTPException(415, 'Choose a readable PNG, JPEG or WebP photo, at least 32 pixels wide and under 40 megapixels.') from exc

def validate_glb(data):
    if len(data) < 28 or data[:4] != b'glTF':
        raise ValueError('Output is not a GLB model.')
    version, length = struct.unpack_from('<II', data, 4)
    if version != 2 or length != len(data):
        raise ValueError('Model download is incomplete.')
    size, kind = struct.unpack_from('<I4s', data, 12)
    if kind != b'JSON' or size % 4 or 20 + size + 8 > length:
        raise ValueError('Invalid model metadata.')
    doc = json.loads(data[20:20+size])
    pos = 20 + size
    binary_size, binary_kind = struct.unpack_from('<I4s', data, pos)
    if binary_kind != b'BIN\0' or pos + 8 + binary_size != length:
        raise ValueError('Invalid model geometry data.')
    binary = memoryview(data)[pos+8:]
    views = doc.get('bufferViews', [])
    accessors = doc.get('accessors', [])
    for view in views:
        if view.get('buffer', 0) != 0 or view.get('byteOffset', 0) < 0 or view['byteLength'] < 0 or view.get('byteOffset', 0) + view['byteLength'] > len(binary):
            raise ValueError('Model buffer extends outside the file.')
    vertices = triangles = 0
    materials = doc.get('materials', [])
    for mesh in doc.get('meshes', []):
        for primitive in mesh.get('primitives', []):
            if primitive.get('mode', 4) != 4:
                raise ValueError('Expected a triangle mesh.')
            acc = accessors[primitive['attributes']['POSITION']]
            view = views[acc['bufferView']]
            count = acc['count']
            stride = view.get('byteStride', 12)
            offset = view.get('byteOffset', 0) + acc.get('byteOffset', 0)
            if acc['type'] != 'VEC3' or acc['componentType'] != 5126 or count < 3 or stride < 12 or acc.get('byteOffset', 0)+(count-1)*stride+12 > view['byteLength']:
                raise ValueError('Invalid vertex positions.')
            for i in range(count):
                if not all(math.isfinite(v) for v in struct.unpack_from('<fff', binary, offset+i*stride)):
                    raise ValueError('Model contains invalid vertex coordinates.')
            vertices += count
            if 'indices' in primitive:
                indices = accessors[primitive['indices']]
                index_view = views[indices['bufferView']]
                fmt, width = {5121: ('B', 1), 5123: ('H', 2), 5125: ('I', 4)}[indices['componentType']]
                n = indices['count']
                start = index_view.get('byteOffset', 0)+indices.get('byteOffset', 0)
                if indices['type'] != 'SCALAR' or n % 3 or indices.get('byteOffset', 0)+n*width > index_view['byteLength']:
                    raise ValueError('Invalid triangle indices.')
                if any(v[0] >= count for v in struct.iter_unpack('<'+fmt, binary[start:start+n*width])):
                    raise ValueError('Triangle references a missing vertex.')
                triangles += n // 3
            else:
                triangles += count // 3
            if not 0 <= primitive.get('material', -1) < len(materials):
                raise ValueError('Model is missing its material.')
            if 'TEXCOORD_0' not in primitive['attributes']:
                raise ValueError('Model is missing texture coordinates.')
    textures = []
    for entry in doc.get('images', []):
        view = views[entry['bufferView']]
        start = view.get('byteOffset', 0)
        with Image.open(io.BytesIO(binary[start:start+view['byteLength']])) as image:
            textures.append(list(image.size))
            image.verify()
    if not vertices or not triangles or not textures:
        raise ValueError('Model must contain geometry and embedded textures.')
    return {'vertices': vertices, 'triangles': triangles, 'materials': len(materials), 'textures': textures, 'bytes': len(data)}

class JobStore:
    def __init__(self, root):
        self.root = Path(root)
        self.records = self.root / 'jobs'
        self.records.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        for path in self.records.glob('*.json'):
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                job_id(record['id'])
                if record['status'] == 'processing':
                    record.update(status='failed', stage='Interrupted', error='The app restarted during this job. Your photo is saved; retry when Forge is free.', finished_at=time.time())
                self.jobs[record['id']] = record
                self.save(record)
            except (ValueError, KeyError, HTTPException):
                continue
        for path in self.root.glob('*.glb'):
            if re.fullmatch(r'[a-f0-9]{32}', path.stem) and path.stem not in self.jobs:
                record = dict(id=path.stem, name='Earlier model', status='success', stage='Ready', created_at=path.stat().st_mtime, finished_at=path.stat().st_mtime, preset='detailed', has_photo=False, progress=100)
                self.jobs[path.stem] = record
                self.save(record)

    def save(self, record):
        path = self.records / (job_id(record['id']) + '.json')
        partial = path.with_suffix('.tmp')
        partial.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        partial.replace(path)

    def get(self, key):
        record = self.jobs.get(job_id(key))
        if not record or record.get('deleted_at'):
            raise HTTPException(404, 'Job not found')
        return record

    def public(self, record):
        result = {k: v for k, v in record.items() if k not in ('request_key', 'input_hash')}
        result['elapsed_seconds'] = max(0, round(record.get('finished_at', time.time()) - record['created_at']))
        result['photo_url'] = '/api/jobs/' + record['id'] + '/photo' if record.get('has_photo') else None
        if record['status'] == 'success':
            result['model_url'] = '/local-models/' + record['id'] + '.glb'
        return result
