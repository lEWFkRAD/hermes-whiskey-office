"""Own the office integration for exactly the lifetime of the native app."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


def prefer_headset_audio(env):
    """Select existing WiVRn devices for these children; never change defaults."""
    for kind, variable in [('sources', 'PULSE_SOURCE'), ('sinks', 'PULSE_SINK')]:
        if env.get(variable):
            continue
        try:
            result = subprocess.run(['pactl', 'list', 'short', kind], env=env, capture_output=True, text=True, timeout=2, check=True)
            for line in result.stdout.splitlines():
                fields = line.split()
                if len(fields) > 1 and 'wivrn' in fields[1].lower() and not (kind == 'sources' and fields[1].endswith('.monitor')):
                    env[variable] = fields[1]
                    break
        except (OSError, subprocess.SubprocessError):
            pass


def stop_owned(process):
    if process.poll() is not None:
        return
    if os.name == 'posix':
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--godot', required=True)
    parser.add_argument('godot_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    env = os.environ.copy()
    if os.name == 'posix':
        runtime = Path('/run/user')/str(os.getuid())
        if runtime.is_dir() and runtime.stat().st_uid == os.getuid():
            env.setdefault('XDG_RUNTIME_DIR', str(runtime))
            if (runtime/'pulse/native').exists():
                env.setdefault('PULSE_SERVER', 'unix:'+str(runtime/'pulse/native'))
        prefer_headset_audio(env)
    data = Path(env.get('HERMES_OFFICE_DATA_DIR', str(Path.home()/'.local/share/hermes-whiskey-office'))).resolve()
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    env['HERMES_OFFICE_DATA_DIR'] = str(data)
    workspace = data/'workspace'
    workspace.mkdir(exist_ok=True, mode=0o700)
    if 'HERMES_OFFICE_ACP_COMMAND' not in env and os.name == 'posix':
        env['HERMES_OFFICE_ACP_COMMAND'] = json.dumps(['bash', str(root/'run-hermes-acp.sh')])
    voice_python = Path(env.get('HERMES_OFFICE_BACKEND_ROOT', str(Path.home()/'.hermes/hermes-agent')))/'venv/bin/python'
    if voice_python.is_file() and 'HERMES_OFFICE_VOICE_COMMAND' not in env:
        env['HERMES_OFFICE_VOICE_COMMAND'] = json.dumps([str(voice_python), str(root/'voice_io.py')])
    with tempfile.TemporaryDirectory(prefix='hermes-office-') as temporary:
        ipc = Path(temporary)
        (ipc/'commands').mkdir(mode=0o700)
        env['HERMES_OFFICE_BRIDGE_DIR'] = str(ipc)
        integration = env.get('HERMES_OFFICE_INTEGRATION', 'desktop')
        if integration == 'desktop':
            env['HERMES_DESKTOP_IPC_DIR'] = str(ipc)
            command = env.get('HERMES_OFFICE_DESKTOP_COMMAND', json.dumps(['bash', str(root/'run-hermes-desktop.sh')]))
            bridge_args = [sys.executable, str(root/'desktop_bridge.py'), '--ipc-dir', str(ipc), '--command', command]
        else:
            bridge_args = [sys.executable, str(root/'office_bridge.py'), '--ipc-dir', str(ipc), '--workspace', str(workspace), '--data-dir', str(data)]
        bridge = subprocess.Popen(bridge_args, env=env, cwd=root, start_new_session=os.name == 'posix', stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        extra = args.godot_args[1:] if args.godot_args[:1] == ['--'] else args.godot_args
        app = None
        windows = None
        pipeline = None
        try:
            if env.get('HERMES_PODIUM_DISABLE') != '1':
                podium_data, podium_ipc = data/'podium', ipc/'podium'
                for path in [podium_data, podium_ipc, podium_ipc/'commands']:
                    path.mkdir(parents=True, exist_ok=True, mode=0o700)
                env['HERMES_PODIUM_DATA_DIR'] = str(podium_data)
                env['HERMES_PODIUM_IPC_DIR'] = str(podium_ipc)
                pipeline = subprocess.Popen([sys.executable, str(root/'object_pipeline.py'),
                    '--data-dir', str(podium_data), '--ipc-dir', str(podium_ipc)],
                    cwd=root, env=env, start_new_session=os.name == 'posix',
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            if integration == 'desktop':
                from window_broker import WindowBroker
                windows = WindowBroker(ipc/'windows', root, data, ipc, env, stop_owned)
                env['HERMES_WINDOWS_IPC_DIR'] = str(ipc/'windows')
            app = subprocess.Popen([args.godot, '--path', str(root), *extra], cwd=root, env=env)
            while app.poll() is None:
                if windows: windows.poll()
                time.sleep(0.05)
            return app.returncode
        except KeyboardInterrupt:
            if app and app.poll() is None:
                app.terminate()
                app.wait(timeout=5)
            return 130
        finally:
            if pipeline: stop_owned(pipeline)
            if windows and env.get('HERMES_OFFICE_WINDOWS_PREVIEW') == '1':
                snapshots = {}
                for identifier, row in windows.rows.items():
                    status = Path(row['ipc_dir'])/'status.json'
                    snapshots[identifier] = json.loads(status.read_text()) if status.is_file() else {'error': 'No client started'}
                (root/'window-preview-status.json').write_text(json.dumps({'rows': list(windows.rows.values()), 'states': snapshots}, indent=2))
            if windows: windows.close()
            # Give the adapter an explicit exit before terminating only our group.
            try:
                state = json.loads((ipc/'status.json').read_text())
                command = {'protocol_version': 1, 'instance_id': state['instance_id'], 'id': 'launcher-shutdown', 'created_at_unix': time.time(), 'method': 'shutdown', 'type': 'shutdown', 'params': {}}
                tmp = ipc/'commands/shutdown.tmp'
                tmp.write_text(json.dumps(command))
                tmp.replace(ipc/'commands/shutdown.json')
                bridge.wait(timeout=3)
            except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
                pass
            stop_owned(bridge)


if __name__ == '__main__':
    raise SystemExit(main())
