"""Read owned Hermes accessibility controls; never reads conversation text."""
import dataclasses
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent

def main():
    if len(sys.argv) > 1:
        from hermes_navigation import AtspiAdapter, _run_navigation
        pid = int(sys.argv[1])
        adapter = AtspiAdapter(pid, time.monotonic()+8)
        desktop = adapter.api.get_desktop(0)
        print('APPLICATION_PIDS', [desktop.get_child_at_index(i).get_process_id() for i in range(desktop.get_child_count())], 'OWNED', pid, flush=True)
        snapshot = adapter.snapshot()
        labels={'Capabilities','Messaging','Artifacts','Scheduled jobs','Open settings','Close settings','Providers','Gateways','Keyboard Shortcuts','Plugins','MCP','Approval needed'}
        print(json.dumps([dataclasses.asdict(n) for n in snapshot.nodes if n.role=='push-button' and n.usable and (n.name in labels or n.name.startswith(('Skills','Tools','New session')))]), flush=True)
        for destination in ['tools','mcp','plugins','settings','artifacts','plugins','artifacts']:
            try:
                current=AtspiAdapter(pid,time.monotonic()+2.15)
                print(destination, _run_navigation(destination,pid,current), flush=True)
            except Exception as exc:
                print(destination, type(exc).__name__, [{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(exc.__traceback__)], flush=True)
            time.sleep(.2)
        return
    from desktop_bridge import PrivateDesktop
    folder = ROOT / ('navigation-probe-'+str(time.time_ns()))
    os.environ['HERMES_OFFICE_DATA_DIR'] = str(folder/'data')
    os.environ['HERMES_OFFICE_ACCEPTANCE_RUN'] = '1'
    ipc=folder/'ipc'
    ipc.mkdir(parents=True,mode=0o700)
    backend=PrivateDesktop(ipc,['bash',str(ROOT/'run-hermes-desktop.sh')])
    try:
        backend.start()
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            backend.pump()
            backend.frame(ipc/'frame.png')
            time.sleep(.05)
        worker=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),str(backend.app.pid)],env=backend.environment)
        deadline=time.monotonic()+25
        while worker.poll() is None and time.monotonic()<deadline:
            backend.pump()
            time.sleep(.025)
        if worker.poll() is None: worker.kill()
        return worker.wait()
    finally:
        backend.close()

if __name__=='__main__': raise SystemExit(main())
