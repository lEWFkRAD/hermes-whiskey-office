"""Explicit update preflight: desktop input, fake-agent, Godot, ACP initialize.

Never updates Hermes, starts a model turn, or changes a service. A passing
receipt is tied to the exact office files tested. Re-run after each update.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
EXCLUDE_PARTS = {'.godot', '.acp-deps', '__pycache__', 'workspace', '.office-runtime'}
EXCLUDE_PREFIXES = ('desktop-acceptance-', 'desktop-preflight-', 'navigation-probe-')
TRACKED_SUFFIXES = {'.gd', '.py', '.sh', '.ps1', '.glb', '.tres', '.godot', '.tscn', '.txt', '.js', '.cjs'}
TRACKED_NAMES = {'office-layout.json', 'voice-config.json', 'office-assemblies.json', 'hologram-catalogue.json', 'desktop-plugins-lock.json'}


def file_hashes(root=ROOT):
    """Hash product inputs; prune generated acceptance/preflight trees entirely."""
    result = {}
    def failed_walk(error):
        raise error
    for directory, subdirs, files in os.walk(root, followlinks=False, onerror=failed_walk):
        subdirs[:] = sorted(name for name in subdirs if name not in EXCLUDE_PARTS
                            and not name.startswith(EXCLUDE_PREFIXES))
        if any((Path(directory)/name).is_symlink() for name in subdirs):
            raise ValueError('Product directories must not be symbolic links: '+directory)
        for name in sorted(files):
            path = Path(directory)/name
            if path.suffix in TRACKED_SUFFIXES or name in TRACKED_NAMES or (path.is_relative_to(root/'assets/pbr') and path.suffix in {'.jpg', '.png'}):
                if path.is_symlink():
                    raise ValueError('Product inputs must not be symbolic links: '+str(path))
                result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def execute(name, argv, timeout=90, marker=None):
    try:
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        output = result.stdout + result.stderr
        passed = result.returncode == 0 and 'SCRIPT ERROR' not in output
        if marker:
            passed = passed and marker in output and 'SCRIPT ERROR' not in output
        return {'name': name, 'passed': passed, 'exit_code': result.returncode, 'output': output[-16000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'name': name, 'passed': False, 'error': str(exc)[:500]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--godot', default='/opt/godot-4.7.2')
    parser.add_argument('--receipt', default=str(ROOT/'compatibility-receipt.json'))
    parser.add_argument('--acp-command', default=json.dumps(['bash', str(ROOT/'run-hermes-acp.sh')]))
    args = parser.parse_args()
    before = file_hashes()
    checks = [execute('adapter_conformance', [sys.executable, '-m', 'unittest', 'test_office_bridge', 'test_voice_io'], marker='OK')]
    checks.append(execute('desktop_bridge_conformance', [sys.executable, '-W', 'error::ResourceWarning', '-m', 'unittest', 'test_desktop_bridge'], marker='OK'))
    checks.append(execute('window_broker_conformance', [sys.executable, '-m', 'unittest', 'test_window_broker'], marker='OK'))
    checks.append(execute('loading_bay_conformance', [sys.executable, '-m', 'unittest', 'test_loading_bay'], marker='OK'))
    checks.append(execute('object_pipeline_conformance', [sys.executable, '-m', 'unittest', 'test_object_pipeline'], marker='OK'))
    checks.append(execute('test_office_windows.gd', [args.godot, '--headless', '--xr-mode', 'off', '--path', str(ROOT), '--script', 'res://test_office_windows.gd'], marker='HERMES_OFFICE_WINDOWS_TESTS'))
    checks.append(execute('hermes_navigation_conformance', [sys.executable, '-W', 'error::ResourceWarning', '-m', 'unittest', 'test_hermes_navigation'], marker='OK'))
    checks.append(execute('office_context_conformance', ['node', str(ROOT/'test_office_context.cjs')], marker='HERMES_OFFICE_CONTEXT_TESTS'))
    checks.append(execute('office_awareness_conformance', [args.godot, '--headless', '--xr-mode', 'off', '--path', str(ROOT), '--script', 'res://test_office_awareness.gd'], marker='HERMES_OFFICE_AWARENESS_TESTS'))
    checks.append(execute('runtime_guard_conformance', [sys.executable, '-m', 'unittest', 'test_runtime_guard'], marker='OK'))
    checks.append(execute('godot_import', [args.godot, '--headless', '--xr-mode', 'off', '--editor', '--path', str(ROOT), '--import'], timeout=150))
    checks.append(execute('test_office_tutorial.gd', [args.godot, '--headless', '--xr-mode', 'off', '--path', str(ROOT), '--script', 'res://test_office_tutorial.gd'], marker='HERMES_TUTORIAL_TESTS'))
    for script, marker in [('test_contracts.gd', 'HERMES_CONTRACT_TESTS'), ('test_office_client.gd', 'HERMES_OFFICE_CLIENT_TESTS'), ('test_xr_workbench.gd', 'HERMES_XR_WORKBENCH_TESTS'), ('test_hand_pointer.gd', 'HERMES_HAND_POINTER_TESTS'), ('test_wrist_dial.gd', 'HERMES_WRIST_DIAL_TESTS'), ('test_wrist_controls.gd', 'HERMES_WRIST_CONTROLS_TESTS'), ('test_desktop_surface.gd', 'HERMES_DESKTOP_SURFACE_TESTS')]:
        checks.append(execute(script, [args.godot, '--headless', '--xr-mode', 'off', '--path', str(ROOT), '--script', 'res://'+script], marker=marker))
    checks.append(execute('native_assets', [args.godot, '--headless', '--xr-mode', 'off', '--path', str(ROOT), '--', '--validate'], marker='HERMES_VALIDATION'))
    checks.append(execute('test_wrist_menu.gd', [args.godot, '--headless', '--xr-mode', 'off', '--path', str(ROOT), '--script', 'res://test_wrist_menu.gd'], marker='HERMES_WRIST_MENU_TESTS'))
    checks.append(execute('test_office_assembly_review.gd', [args.godot, '--headless', '--xr-mode', 'off', '--path', str(ROOT), '--script', 'res://test_office_assembly_review.gd'], marker='HERMES_OFFICE_ASSEMBLY_TESTS'))
    checks.append(execute('test_office_hologram.gd', [args.godot, '--headless', '--xr-mode', 'off', '--path', str(ROOT), '--script', 'res://test_office_hologram.gd'], marker='HERMES_HOLOGRAM_TESTS'))
    checks.append(execute('test_office_fabricator.gd', [args.godot, '--headless', '--xr-mode', 'off', '--path', str(ROOT), '--script', 'res://test_office_fabricator.gd'], marker='HERMES_FABRICATOR_TESTS'))
    checks.append(execute('hermes_initialize', [sys.executable, str(ROOT/'office_bridge.py'), '--probe', '--acp-command', args.acp_command], timeout=75))
    after = file_hashes()
    checks.append({'name': 'office_files_unchanged', 'passed': before == after})
    report = {'checked_at': time.time(), 'office_protocol': 1, 'passed': all(c['passed'] for c in checks), 'checks': checks, 'sha256': after,
              'scope': 'Only the named checks were executed: deterministic Python/Godot contracts, asset validation and ACP initialization. Real desktop pixels, headset, audio and model quality require separate acceptance.',
              'catalogue_coverage': 'The broader compatibility-cases.json catalogue is not an executed test suite; no full catalogue coverage is claimed.'}
    Path(args.receipt).write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': [{k:v for k,v in c.items() if k not in {'output'}} for c in checks], 'receipt': args.receipt}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
