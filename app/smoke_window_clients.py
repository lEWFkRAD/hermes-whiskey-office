"""Explicit real client acceptance; opens connection dialogs without connecting."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from office_launcher import stop_owned
from window_broker import WindowBroker

ROOT = Path(__file__).resolve().parent

def main():
    directory = ROOT/('desktop-acceptance-windows-'+str(time.time_ns()))
    directory.mkdir(mode=0o700)
    env = dict(os.environ)
    env['XDG_RUNTIME_DIR'] = '/run/user/'+str(os.getuid())
    broker = WindowBroker(directory/'windows', ROOT, directory, directory/'primary', env, stop_owned)
    result = {'passed': False, 'directory': str(directory), 'remote_logins_attempted': 0, 'checks': {}}
    try:
        for index in (1, 2):
            broker.request(dict(protocol_version=1, instance_id=broker.instance, id=f'open-{index}',
                                created_at_unix=time.time(), source_id=f'remote-{index}', type='open'))
        deadline = time.monotonic()+35
        states = {}
        while time.monotonic() < deadline:
            broker.poll()
            for index in (1, 2):
                path = directory/f'windows/remote-{index}/status.json'
                if path.is_file(): states[str(index)] = json.loads(path.read_text())
            if len(states) == 2 and all(s.get('connected') for s in states.values()): break
            time.sleep(.1)
        result['states'] = states
        result['checks']['two_live_clients'] = len(states) == 2 and all(s.get('connected') for s in states.values())
        result['checks']['distinct_instances'] = len({s.get('instance_id') for s in states.values()}) == 2
        result['checks']['distinct_processes'] = len({p.pid for p in broker.processes.values()}) == 2
        result['passed'] = all(result['checks'].values())
        result['sha256'] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['desktop_bridge.py','window_broker.py','office_launcher.py','smoke_window_clients.py']}
    finally:
        broker.close()
    result['checked_at'] = time.time()
    (ROOT/'window-client-acceptance.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1

if __name__ == '__main__': sys.exit(main())
