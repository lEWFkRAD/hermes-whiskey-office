"""On-demand private display clients; no host services or remote app termination."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

MAX_SOURCES = 32
MAX_CLIENTS = 7
ID = re.compile(r'[a-z][a-z0-9-]{0,47}')

def sources(config):
    if config.is_file():
        if config.is_symlink() or config.stat().st_size > 65536:
            raise ValueError('Invalid private window-source configuration')
        data = json.loads(config.read_text())
    else:
        data = [{'id': f'remote-{i}', 'title': f'Remote desktop {i}', 'machine': 'Choose machine in Remmina',
                 'command': ['/usr/bin/remmina', '--new']} for i in range(1, 4)]
    if not isinstance(data, list) or len(data) > MAX_SOURCES-1:
        raise ValueError('Window sources must be a list of at most 31 entries')
    result = []
    seen = {'hermes', 'loading-bay'}
    for row in data:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not ID.fullmatch(row['id']) or row['id'] in seen:
            raise ValueError('Window source identifiers must be unique')
        for key in ('title', 'machine'):
            if not isinstance(row.get(key), str) or not 1 <= len(row[key]) <= 80 or any(ord(c) < 32 for c in row[key]):
                raise ValueError('Window sources need readable titles and machine labels')
        argv = row.get('command')
        if not isinstance(argv, list) or not 1 <= len(argv) <= 24 or any(not isinstance(s, str) or not s or len(s) > 4096 or '\0' in s for s in argv):
            raise ValueError('Window client command must be an argument list')
        if not Path(argv[0]).is_absolute():
            raise ValueError('Window client executable must use an absolute path')
        # Configuration is local operator input, never received over the IPC API.
        result.append({key: row[key] for key in ('id', 'title', 'machine', 'command')})
        seen.add(row['id'])
    return result

class WindowBroker:
    def __init__(self, directory, root, data, primary_ipc, env, stop_process):
        self.directory, self.root = Path(directory), Path(root)
        self.env, self.stop_process = dict(env), stop_process
        self.instance = uuid.uuid4().hex
        self.processes = {}
        self.seen = set()
        self.last_publish = 0
        self.rows = {'hermes': {'id': 'hermes', 'title': 'Hermes', 'machine': 'Local computer', 'kind': 'hermes', 'ipc_dir': str(primary_ipc), 'status': 'running'}}
        self.directory.mkdir(mode=0o700)
        (self.directory/'commands').mkdir(mode=0o700)
        self.config_error = ''
        try:
            configured = sources(Path(data)/'window-sources.json')
        except (OSError, ValueError):
            configured = []
            self.config_error = 'Window source configuration could not be loaded; Hermes remains available.'
        if (self.root/'open_loading_bay.py').is_file():
            configured.append({'id':'loading-bay','title':'Loading Bay','machine':'Shared files',
                               'command':[sys.executable,str(self.root/'open_loading_bay.py')]})
        self.config = {row['id']: row for row in configured}
        for row in configured:
            self.rows[row['id']] = {key: row[key] for key in ('id', 'title', 'machine')}
            self.rows[row['id']].update(kind='remote', ipc_dir=str(self.directory/row['id']), status='closed')
        self.publish()

    def publish(self):
        value = {'protocol_version': 1, 'instance_id': self.instance, 'updated_at_unix': time.time(),
                 'sources': list(self.rows.values()), 'error': self.config_error}
        temp = self.directory/'windows.json.tmp'
        temp.write_text(json.dumps(value))
        temp.replace(self.directory/'windows.json')
        self.last_publish = time.monotonic()

    def request(self, value):
        if not isinstance(value, dict) or value.get('protocol_version') != 1 or value.get('instance_id') != self.instance:
            return False
        identifier, stamp = value.get('id'), value.get('created_at_unix')
        if not isinstance(identifier, str) or not ID.fullmatch(identifier) or identifier in self.seen:
            return False
        if type(stamp) not in (int, float) or not -2 <= time.time()-stamp <= 10:
            return False
        source = value.get('source_id')
        if not isinstance(source, str) or source not in self.config or value.get('type') not in ('open', 'disconnect'):
            return False
        if len(self.seen) >= 8192:
            # Refuse excessive work in this app session rather than forgetting IDs.
            return False
        self.seen.add(identifier)
        row = self.rows[source]
        process = self.processes.get(source)
        if value['type'] == 'disconnect':
            if process: self.stop_process(process)
            self.processes.pop(source, None)
            row['status'] = 'closed'
        elif process is None or process.poll() is not None:
            if sum(p.poll() is None for p in self.processes.values()) >= MAX_CLIENTS:
                row.update(status='error', error='Seven remote clients are already open. Disconnect one before opening another.')
            elif not Path(self.config[source]['command'][0]).is_file():
                row.update(status='error', error='This remote client is not installed.')
            else:
                ipc = Path(row['ipc_dir'])
                ipc.mkdir(mode=0o700, exist_ok=True)
                runtime = ipc/'runtime'
                runtime.mkdir(mode=0o700, exist_ok=True)
                client_env = dict(self.env, XDG_RUNTIME_DIR=str(runtime), GTK_USE_PORTAL='0', GIO_USE_VFS='local')
                argv = [sys.executable, str(self.root/'desktop_bridge.py'), '--ipc-dir', str(ipc), '--generic', '--command', json.dumps(self.config[source]['command'])]
                try:
                    self.processes[source] = subprocess.Popen(argv, env=client_env, cwd=self.root, start_new_session=True,
                                                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    row.update(status='starting', error='')
                except OSError:
                    row.update(status='error', error='The remote display client could not start.')
        self.publish()
        return True

    def poll(self):
        for path in sorted((self.directory/'commands').glob('*.json'))[:64]:
            try:
                if not path.is_symlink() and path.stat().st_size <= 4096:
                    self.request(json.loads(path.read_text()))
            except (OSError, ValueError):
                pass
            finally:
                path.unlink(missing_ok=True)
        for identifier, process in list(self.processes.items()):
            if process.poll() is not None:
                self.rows[identifier].update(status='error', error='The remote display client stopped. Reopen to reconnect.')
                del self.processes[identifier]
            else:
                self.rows[identifier]['status'] = 'running'
        if time.monotonic()-self.last_publish >= 0.5: self.publish()

    def close(self):
        for process in self.processes.values(): self.stop_process(process)
        self.processes.clear()
