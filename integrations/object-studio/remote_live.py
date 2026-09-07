"""Sent over SSH as source. Optional NumPy previews from the same inference."""
import concurrent.futures
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import threading
import json


def clustered_mesh(path):
    """CPU-only vertex clustering of the entire decoded surface, no inference replay."""
    import numpy as np
    raw = pathlib.Path(path).read_bytes()
    vertices, faces = struct.unpack_from('<ii',raw)
    if vertices<=0 or faces<=0 or len(raw)!=8+12*(vertices+faces): raise ValueError('Invalid mesh dump')
    positions=np.frombuffer(raw,dtype='<f4',count=vertices*3,offset=8).reshape(-1,3)
    triangles=np.frombuffer(raw,dtype='<i4',count=faces*3,offset=8+vertices*12).reshape(-1,3)
    if not np.isfinite(positions).all() or triangles.min()<0 or triangles.max()>=vertices: raise ValueError('Invalid geometry')
    minimum=positions.min(axis=0); span=float(np.max(positions.max(axis=0)-minimum))
    if span<=0: raise ValueError('Empty geometry')
    cells=np.clip(((positions-minimum)*(48/span)).astype(np.int64),0,48)
    codes=cells[:,0]+cells[:,1]*49+cells[:,2]*49*49
    _, inverse=np.unique(codes,return_inverse=True)
    counts=np.bincount(inverse)
    reduced=np.column_stack([np.bincount(inverse,weights=positions[:,axis])/counts for axis in range(3)])
    mapped=inverse[triangles]
    mapped=mapped[(mapped[:,0]!=mapped[:,1]) & (mapped[:,1]!=mapped[:,2]) & (mapped[:,2]!=mapped[:,0])]
    _, unique=np.unique(np.sort(mapped,axis=1),axis=0,return_index=True)
    mapped=mapped[unique]
    # Drop unused clusters so isolated discarded vertices cannot distort framing.
    used, remap=np.unique(mapped,return_inverse=True); reduced=reduced[used]; mapped=remap.reshape(-1,3)
    reduced=reduced[:,[0,2,1]]; reduced[:,2]*=-1
    points=reduced.astype('<f4').tobytes()
    edges=np.unique(np.sort(np.concatenate([mapped[:,[0,1]],mapped[:,[1,2]],mapped[:,[2,0]]]),axis=1),axis=0)
    def glb(wire):
        indices=(edges if wire else mapped).astype('<u4').tobytes(); data=points+indices
        doc={'asset':{'version':'2.0','generator':'Camera to Blender clustered decoded mesh'},
            'scene':0,'scenes':[{'nodes':[0]}],'nodes':[{'mesh':0}],
            'buffers':[{'byteLength':len(data)}],
            'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':len(points)}, {'buffer':0,'byteOffset':len(points),'byteLength':len(indices)}],
            'accessors':[{'bufferView':0,'componentType':5126,'count':len(reduced),'type':'VEC3','min':reduced.min(axis=0).tolist(),'max':reduced.max(axis=0).tolist()},
                {'bufferView':1,'componentType':5125,'count':len(indices)//4,'type':'SCALAR'}],
            'meshes':[{'primitives':[{'attributes':{'POSITION':0},'indices':1,'mode':1 if wire else 4,'material':0}]}],
            'materials':[{'doubleSided':True,'pbrMetallicRoughness':{'baseColorFactor':[.1,.055,.3,1] if wire else [.46,.38,.75,1],'metallicFactor':0,'roughnessFactor':.85}}]}
        meta=json.dumps(doc,separators=(',',':')).encode(); meta+=b' '*(-len(meta)%4)
        return b'glTF'+struct.pack('<II',2,28+len(meta)+len(data))+struct.pack('<I4s',len(meta),b'JSON')+meta+struct.pack('<I4s',len(data),b'BIN\0')+data
    return glb(False),glb(True)


def main():
    import fcntl
    binary, models, resolution, atlas = sys.argv[1:]
    if not pathlib.Path(binary).is_file() or not pathlib.Path(models).is_dir():
        raise SystemExit('Trellis installation missing')
    with open('/tmp/camera-to-blender-trellis.lock','w') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('Another Camera to Blender job is running on Forge')
        with tempfile.TemporaryDirectory(prefix='camera-to-blender-') as work:
            root = pathlib.Path(work); source=root/'input.png'; target=root/'model.glb'
            # Image length leaves stdin open as a private control channel.
            def read_input(size):
                data=bytearray()
                while len(data)<size:
                    chunk=os.read(sys.stdin.fileno(),size-len(data))
                    if not chunk: break
                    data.extend(chunk)
                return bytes(data)
            header=read_input(4)
            if len(header)!=4: raise RuntimeError('Input disconnected')
            length=struct.unpack('>I',header)[0]
            if not 0<length<=32*1024*1024: raise ValueError('Invalid input size')
            image=read_input(length)
            if len(image)!=length: raise RuntimeError('Incomplete image')
            source.write_bytes(image)
            output_lock = threading.Lock()
            sys.stdout.buffer.write(b'CTB1'); sys.stdout.buffer.flush()
            def frame(kind, data):
                with output_lock:
                    sys.stdout.buffer.write(kind + struct.pack('>I',len(data)) + data)
                    sys.stdout.buffer.flush()
            def checkpoint(kind):
                try:
                    if kind == 'cutout': frame(b'C',(root/'model_cutout.png').read_bytes())
                    else:
                        solid, wire = clustered_mesh(root/'decoded.bin')
                        frame(b'S',solid); frame(b'W',wire)
                except Exception as exc:
                    print('Live preview unavailable: '+str(exc), file=sys.stderr, flush=True)
            env=dict(os.environ)
            env['LD_LIBRARY_PATH']=str(pathlib.Path(binary).parent)+':'+env.get('LD_LIBRARY_PATH','')
            env['TRELLIS_DUMP_DECMESH']=str(root/'decoded.bin')
            print('CAMERA_STAGE:Generating on Forge',file=sys.stderr,flush=True)
            process=subprocess.Popen([binary,str(source),str(target),'-m',models,'--gpu','0','--require-gpu',
                '--webp','off','--dump-bg','--res',resolution,'--atlas',atlas],
                env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace')
            stopped=threading.Event()
            def control():
                # Explicit STOP or loss of the owning SSH connection stops only
                # this Popen child, never unrelated Forge processes.
                os.read(sys.stdin.fileno(),1)
                if process.poll() is None:
                    stopped.set()
                    try: process.kill()
                    except ProcessLookupError: pass
            threading.Thread(target=control,daemon=True).start()
            timer=threading.Timer(900, process.kill); timer.start()
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as previews:
                    seen=set()
                    for line in process.stdout:
                        print(line,end='',file=sys.stderr,flush=True)
                        kind = 'cutout' if 'bg-removal cutout ->' in line else 'mesh' if '[dump] pre-remesh mesh ->' in line else None
                        if kind and kind not in seen:
                            seen.add(kind); previews.submit(checkpoint,kind)
                    code=process.wait()
                    if stopped.is_set():
                        print('CAMERA_STOPPED',file=sys.stderr,flush=True)
                        raise SystemExit(130)
                    if code: raise RuntimeError('Trellis generation failed')
                print('CAMERA_STAGE:Downloading model',file=sys.stderr,flush=True)
                frame(b'F',target.read_bytes())
            finally:
                timer.cancel()
                if process.poll() is None: process.kill()
                process.wait()


if __name__ == '__main__': main()
