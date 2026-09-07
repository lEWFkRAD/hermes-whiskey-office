#!/usr/bin/env python3
"""Stage the official pinned Hermes desktop on Forge; never launch/update Hermes.

Run as your normal desktop user: python3 tools/stage_hermes_desktop.py
Only this private vendor tree is written. The existing desktop, Python backend,
Hermes home/database/config, services, and launchers are not modified. Build uses
the official scripts/install.sh desktop sequence: npm ci at the repository root,
then CSC_IDENTITY_AUTO_DISCOVERY=false npm run pack inside apps/desktop.

Source evidence used while writing this script: scripts/install.sh:3488-3595,
apps/desktop/package.json (pack), apps/desktop/scripts/assert-root-install.mjs.
The full installer is intentionally not invoked because its other stages update
runtime/configuration and configure system integration. No root/sudo is needed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import urllib.request

TAG = 'v2026.8.31'
ORIGIN = 'https://github.com/NousResearch/hermes-agent.git'
VENDOR = Path.home()/'.local/share/hermes-whiskey-office/vendor'
SOURCE = VENDOR / ('hermes-' + TAG)
EXISTING_BACKEND = Path(os.environ.get('HERMES_OFFICE_BACKEND_ROOT', str(Path.home()/'.hermes/hermes-agent')))
RECEIPT = VENDOR / ('hermes-' + TAG + '-build-receipt.json')
BUILD_STATE = VENDOR / ('hermes-' + TAG + '-build-state')
NODE_VERSION = '22.22.0'


def stage_node():
    name = f'node-v{NODE_VERSION}-linux-x64'
    target = VENDOR / name
    if (target / 'bin/node').is_file():
        return target / 'bin'
    filename = name + '.tar.xz'
    url = f'https://nodejs.org/dist/v{NODE_VERSION}/'
    checksums = urllib.request.urlopen(url + 'SHASUMS256.txt', timeout=60).read().decode()
    expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == filename)
    archive = BUILD_STATE / filename
    emit('stage', name='private-node-runtime')
    with urllib.request.urlopen(url + filename, timeout=120) as response, archive.open('wb') as output:
        shutil.copyfileobj(response, output)
    if sha256(archive) != expected:
        raise RuntimeError('Official Node archive checksum mismatch')
    with tarfile.open(archive, 'r:xz') as bundle:
        bundle.extractall(VENDOR, filter='data')
    (BUILD_STATE / 'node-runtime.json').write_text(json.dumps(dict(version=NODE_VERSION, url=url+filename, sha256=expected)))
    return target / 'bin'


def utc():
    return datetime.now(timezone.utc).isoformat()


def emit(event, **data):
    print(json.dumps(dict(event=event, **data)), flush=True)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_receipt(value):
    temporary = RECEIPT.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, RECEIPT)


def stop_owned(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


class Build:
    def __init__(self, environment, receipt, timeout):
        self.environment, self.receipt, self.timeout = environment, receipt, timeout
        self.process = None

    def run(self, name, command, cwd, timeout=None):
        log = BUILD_STATE / (name + '.log')
        step = dict(name=name, command=command, cwd=str(cwd), log=str(log), started_at=utc())
        self.receipt['steps'].append(step)
        self.receipt['stage'] = name
        write_receipt(self.receipt)
        emit('stage', name=name, log=str(log))
        try:
            with log.open('wb') as stream:
                self.process = subprocess.Popen(command, cwd=cwd, env=self.environment,
                                                stdin=subprocess.DEVNULL, stdout=stream,
                                                stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    returncode = self.process.wait(timeout=timeout or self.timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    stop_owned(self.process)
                    raise
        finally:
            self.process = None
            step['finished_at'] = utc()
        step['exit_code'] = returncode
        write_receipt(self.receipt)
        if returncode:
            raise RuntimeError(f'{name} failed with exit code {returncode}; inspect {log}')

    def read(self, command, cwd=SOURCE):
        result = subprocess.run(command, cwd=cwd, env=self.environment, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError('Read-only verification failed: ' + command[0])
        return result.stdout.strip()


def safe_directory(path):
    # Fixed targets only. Reject symlink redirection rather than following it.
    for component in (path, *path.parents):
        if component.is_symlink():
            raise RuntimeError('Refusing a symlink in staging path: ' + str(component))
    path.mkdir(parents=True, exist_ok=True)
    if path.resolve() != path:
        raise RuntimeError('Staging path is not the expected absolute path')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout-seconds', type=int, default=1800,
                        help='Wall-clock limit per dependency/build step (default:1800)')
    args = parser.parse_args()
    if not sys.platform.startswith('linux') or os.getuid() == 0:
        parser.error('Run this staging script as your normal Linux desktop user')
    if not 60 <= args.timeout_seconds <= 7200:
        parser.error('--timeout-seconds must be between60 and7200')
    for tool in ('git', 'node', 'npm'):
        if not shutil.which(tool):
            parser.error(f'{tool} is required; this script does not install global tools')

    safe_directory(VENDOR)
    safe_directory(BUILD_STATE)
    os.chmod(BUILD_STATE, 0o700)
    private_home = BUILD_STATE / 'home'
    for path in (private_home, BUILD_STATE / 'npm-cache', BUILD_STATE / 'electron-cache',
                 BUILD_STATE / 'electron-builder-cache', BUILD_STATE / 'cache', BUILD_STATE / 'tmp'):
        safe_directory(path)
    (private_home / '.npmrc').touch(exist_ok=True)
    # Build dependencies need no Hermes provider credentials or active desktop
    # environment. A private HOME also keeps npm/Electron writes out of Jeff's
    # existing caches and application state.
    environment = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR',
                   'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy', 'no_proxy')
                   if key in os.environ}
    environment.update(HOME=str(private_home), USER=os.environ.get('USER', ''), LOGNAME=os.environ.get('LOGNAME', ''), CI='1',
                       HERMES_HOME=str(private_home / 'hermes'),
                       npm_config_cache=str(BUILD_STATE / 'npm-cache'),
                       npm_config_userconfig=str(private_home / '.npmrc'),
                       XDG_CACHE_HOME=str(BUILD_STATE / 'cache'),
                       TMPDIR=str(BUILD_STATE / 'tmp'),
                       ELECTRON_CACHE=str(BUILD_STATE / 'electron-cache'),
                       ELECTRON_BUILDER_CACHE=str(BUILD_STATE / 'electron-builder-cache'),
                       CSC_IDENTITY_AUTO_DISCOVERY='false',
                       GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0')
    environment['PATH'] = str(stage_node()) + os.pathsep + environment.get('PATH', '/usr/bin:/bin')
    receipt = dict(protocol_version=1, status='building', started_at=utc(), tag=TAG, origin=ORIGIN,
                   source_dir=str(SOURCE), steps=[], existing_backend=str(EXISTING_BACKEND),
                   backend_started=False, application_launched=False, global_install_modified=False)
    build = Build(environment, receipt, args.timeout_seconds)

    def interrupted(_signum, _frame):
        if build.process:
            stop_owned(build.process)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        if SOURCE.exists():
            if SOURCE.is_symlink() or (SOURCE / '.git').is_symlink() or not (SOURCE / '.git').is_dir():
                raise RuntimeError('Existing staging destination is not the expected Git checkout')
        else:
            build.run('clone', ['git', '-c', 'advice.detachedHead=false', 'clone', '--depth', '1',
                               '--single-branch', '--branch', TAG, ORIGIN, str(SOURCE)], VENDOR, timeout=600)
        remote = build.read(['git', 'remote', 'get-url', 'origin'])
        if remote.lower().rstrip('/') != ORIGIN.lower():
            raise RuntimeError('Existing staging checkout has an unexpected origin')
        commit = build.read(['git', 'rev-parse', 'HEAD'])
        tag_commit = build.read(['git', 'rev-parse', f'refs/tags/{TAG}^{{commit}}'])
        if commit != '29112bef099274229cadff79cdff7bf7b99c4b77' or commit != tag_commit:
            raise RuntimeError('Checkout does not match the requested exact release tag')
        dirty = build.read(['git', 'status', '--porcelain', '--untracked-files=no'])
        if dirty:
            raise RuntimeError('Staging checkout has tracked changes; refusing to overwrite them')
        lockfile = SOURCE / 'package-lock.json'
        desktop = SOURCE / 'apps/desktop'
        if not lockfile.is_file() or not (desktop / 'package.json').is_file():
            raise RuntimeError('Pinned release lacks the expected root workspace lock or desktop manifest')
        root_package = json.loads((SOURCE / 'package.json').read_text())
        desktop_package = json.loads((desktop / 'package.json').read_text())
        if 'apps/*' not in root_package.get('workspaces', []) or not desktop_package.get('scripts', {}).get('pack'):
            raise RuntimeError('Pinned release desktop build contract differs; inspect it before proceeding')
        receipt.update(source_commit=commit, tag_object=build.read(['git', 'rev-parse', f'refs/tags/{TAG}']),
                       root_lock_sha256_before=sha256(lockfile), desktop_version=desktop_package.get('version'),
                       node_version=build.read(['node', '--version']), npm_version=build.read(['npm', '--version']),
                       required_engines=root_package.get('engines', {}))
        write_receipt(receipt)
        # Full root workspace install is required by assert-root-install.mjs.
        # Keep the release lock authoritative: a failed npm ci stops for review;
        # no unlocked npm install, dependency upgrade, or mirror substitution.
        build.run('npm-ci', ['npm', 'ci'], SOURCE)
        if sha256(lockfile) != receipt['root_lock_sha256_before']:
            raise RuntimeError('npm ci changed the pinned root lockfile; stopping before packaging')
        build.run('desktop-pack', ['npm', 'run', 'pack'], desktop)
        candidates = [desktop / 'release/linux-unpacked' / name for name in ('Hermes', 'hermes')]
        binary = next((path for path in candidates if path.is_file() and not path.is_symlink()
                       and os.access(path, os.X_OK)), None)
        if binary is None:
            raise RuntimeError('Desktop pack succeeded but the expected executable is missing')
        asar = binary.parent / 'resources/app.asar'
        stamp = binary.parent / 'resources/install-stamp.json'
        receipt.update(status='built', stage='complete', finished_at=utc(), binary=str(binary),
                       binary_sha256=sha256(binary), binary_size=binary.stat().st_size,
                       app_asar_sha256=sha256(asar) if asar.is_file() else None,
                       root_lock_sha256_after=sha256(lockfile),
                       tracked_changes_after_build=build.read(['git', 'status', '--porcelain', '--untracked-files=no']),
                       install_stamp=json.loads(stamp.read_text()) if stamp.is_file() else None,
                       proposed_launch_environment={
                           'HERMES_OFFICE_DESKTOP_ROOT': str(SOURCE),
                           'HERMES_OFFICE_DESKTOP_BIN': str(binary),
                           'HERMES_OFFICE_BACKEND_ROOT': str(EXISTING_BACKEND)})
        write_receipt(receipt)
        emit('built', receipt=str(RECEIPT), source_commit=commit, binary=str(binary),
             binary_sha256=receipt['binary_sha256'], app_asar_sha256=receipt['app_asar_sha256'])
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        receipt.update(status='failed', finished_at=utc(), error=str(exc) or 'Interrupted')
        write_receipt(receipt)
        emit('failed', receipt=str(RECEIPT), error=receipt['error'])
        return 1


if __name__ == '__main__':
    sys.exit(main())
