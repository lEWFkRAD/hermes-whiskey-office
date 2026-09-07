#!/usr/bin/env python3
"""Private, foreground X11 surface for the existing Hermes desktop.

Run: desktop_bridge.py --ipc-dir ABS --command '["bash","run-hermes-desktop.sh"]'
The launcher owns this process; this process owns Xvfb and its app process groups.
It never connects to the caller's DISPLAY or accepts executable commands via IPC.
Protocol 1: atomically publish frame.png before status.json; consume unique JSON
commands bound to instance_id and created_at_unix (maximum age 4 seconds).
Coordinates are captured-image pixels; a 16px root gutter is never captured.
Cancellation moves into that gutter before button release. Every mapped root
window is clamped inside the capture rectangle, including override-redirect menus.
When the main window is hidden, only the union of viewable app-window rectangles
is opaque. Window interiors, including their own transparent margins, remain
captured and opaque; this is a geometry mask, not native per-pixel window alpha.
Text and explicit capture attachments use the private display's X11 clipboard,
then Ctrl+V. Neither operation sends Enter. Captures are basename PNGs <=4 MiB.
Only Pillow and python-xlib are required beyond Python and the installed Xvfb.
No network listener, service, global configuration edit, or model call is made.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
from pathlib import Path
import re
import secrets
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import time
import uuid

VERSION = 1
WIDTH, HEIGHT, GUTTER = 1280, 800, 16
MAX_COMMAND = 65536
MAX_IMAGE = 4 * 1024 * 1024
STALE_SECONDS = 4.0


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with open(temporary, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
    os.replace(temporary, path)


def apply_window_alpha(image, rectangles, main_viewable):
    """Preserve RGB pixels; mask outside window boxes only when main is hidden.

    Boxes are capture-relative (left, top, right, bottom), with exclusive right
    and bottom edges. Visible window interiors are deliberately fully opaque:
    black UI pixels and the app's own transparent margins are never keyed out.
    The input image is unchanged, and a visible main desktop keeps a full frame.
    """
    from PIL import Image
    result = image.convert('RGBA')
    if main_viewable:
        result.putalpha(255)
        return result
    alpha = Image.new('L', image.size, 0)
    width, height = image.size
    for left, top, right, bottom in rectangles:
        box = (max(0, left), max(0, top), min(width, right), min(height, bottom))
        if box[0] < box[2] and box[1] < box[3]:
            alpha.paste(255, box)
    result.putalpha(alpha)
    return result


def accepted_launch_environment(verified, environment):
    """Bind child launch paths to guard evidence, rejecting conflicting inputs."""
    binary = Path(verified['desktop_build']['binary'])
    accepted = {
        'HERMES_OFFICE_DESKTOP_BIN': str(binary),
        # runtime_guard has already established this exact build layout:
        # source/apps/desktop/release/linux-unpacked/Hermes.
        'HERMES_OFFICE_DESKTOP_ROOT': str(binary.parents[4]),
    }
    if 'backend_runtime' in verified:
        accepted['HERMES_OFFICE_BACKEND_ROOT'] = str(verified['backend_runtime']['root'])
    labels = {
        'HERMES_OFFICE_DESKTOP_BIN': 'Hermes desktop executable',
        'HERMES_OFFICE_DESKTOP_ROOT': 'Hermes desktop source',
        'HERMES_OFFICE_BACKEND_ROOT': 'Hermes backend',
    }
    for name, expected in accepted.items():
        current = environment.get(name)
        if not current:
            continue
        try:
            matches = Path(current).resolve() == Path(expected).resolve()
        except (OSError, ValueError, RuntimeError):
            matches = False
        if not matches:
            raise RuntimeError(labels[name] + ' override differs from the accepted runtime. '
                               'Clear the override or re-run desktop acceptance.')
    return accepted


def command_argv(value):
    try:
        result = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise ValueError('Command must be a JSON array of arguments') from exc
    if not isinstance(result, list) or not result or len(result) > 64 or any(
            not isinstance(arg, str) or not arg or '\0' in arg or len(arg) > 8192 for arg in result):
        raise ValueError('Command must be a nonempty JSON array of string arguments')
    return result


def capture_bytes(ipc, name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,180}\.png', name, re.I):
        raise ValueError('Capture must be a PNG filename')
    capture_directory = ipc / 'captures'
    directory = capture_directory.resolve()
    if capture_directory.is_symlink() or directory.parent != ipc.resolve():
        raise ValueError('Capture directory must remain inside the private IPC directory')
    path = directory / name
    if path.is_symlink() or path.resolve().parent != directory:
        raise ValueError('Capture must remain inside the private captures directory')
    # O_NOFOLLOW also closes the usual symlink substitution race on Linux.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Capture must be a regular file')
        data = stream.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Capture must be a PNG no larger than 4 MiB')
    return data


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def xauthority_record(family, address, number, cookie):
    fields = (address, number, b'MIT-MAGIC-COOKIE-1', cookie)
    return struct.pack('>H', family) + b''.join(struct.pack('>H', len(field)) + field for field in fields)


class InputController:
    """Validated input dispatcher, independent of X11 for deterministic tests."""
    def __init__(self, backend, ipc, instance_id, clock=time.time, hermes_commands=True):
        self.hermes_commands = hermes_commands
        self.backend, self.ipc, self.instance_id, self.clock = backend, ipc, instance_id, clock
        self.seen = set()
        self.seen_order = collections.deque()
        self.buttons, self.keys = set(), set()
        self.last_input = self.clock()
        self.shutdown = False
        self.last_command = {}

    def cancel(self):
        try:
            self.backend.cancel_pointer()
            for button in sorted(self.buttons):
                self.backend.button(button, False)
            self.buttons.clear()
            for keysym in sorted(self.keys):
                self.backend.key(keysym, False)
            self.keys.clear()
        finally:
            self.backend.flush()

    def expire(self):
        if (self.buttons or self.keys) and self.clock() - self.last_input > STALE_SECONDS:
            self.cancel()

    def point(self, command):
        x, y = command.get('x'), command.get('y')
        if not numeric(x) or not numeric(y) or not (0 <= x < WIDTH and 0 <= y < HEIGHT):
            raise ValueError('Pointer coordinates are outside the captured surface')
        return int(x), int(y)

    def dispatch(self, command):
        command_id = command.get('id') if isinstance(command, dict) else None
        try:
            if not isinstance(command, dict) or type(command.get('protocol_version')) is not int or command['protocol_version'] != VERSION:
                raise ValueError('Unsupported desktop IPC protocol')
            if command.get('instance_id') != self.instance_id:
                raise ValueError('Command belongs to a previous desktop instance')
            if not isinstance(command_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', command_id):
                raise ValueError('Command ID is invalid')
            if command_id in self.seen:
                raise ValueError('Duplicate command ignored')
            self.seen.add(command_id)
            self.seen_order.append(command_id)
            if len(self.seen_order) > 32768:
                # Never replay an evicted ID: timestamps also expire after four seconds.
                self.seen.remove(self.seen_order.popleft())
            timestamp = command.get('created_at_unix')
            if not numeric(timestamp) or not (-1 <= self.clock() - timestamp <= STALE_SECONDS):
                raise ValueError('Command is stale')
            kind = command.get('type')
            if not self.hermes_commands and kind in ('launch_tui', 'navigate_hermes'):
                raise ValueError('Hermes actions are unavailable in a remote-machine window')
            if kind == 'pointer_move':
                self.backend.move(*self.point(command))
            elif kind == 'pointer_button':
                point = self.point(command)
                button, pressed = command.get('button'), command.get('pressed')
                if type(button) is not int or button not in (1, 2, 3) or type(pressed) is not bool:
                    raise ValueError('Mouse button event is invalid')
                self.backend.move(*point)
                if pressed != (button in self.buttons):
                    self.backend.button(button, pressed)
                    self.buttons.add(button) if pressed else self.buttons.discard(button)
            elif kind == 'pointer_wheel':
                point = self.point(command)
                delta = command.get('delta_y')
                if not numeric(delta) or abs(delta) > 20 or delta == 0:
                    raise ValueError('Scroll delta is invalid')
                self.backend.move(*point)
                for _ in range(max(1, round(abs(delta)))):
                    self.backend.button(5 if delta > 0 else 4, True)
                    self.backend.button(5 if delta > 0 else 4, False)
            elif kind == 'key':
                keysym, pressed = command.get('keysym'), command.get('pressed')
                if not isinstance(keysym, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', keysym) or type(pressed) is not bool:
                    raise ValueError('Key event is invalid')
                if pressed != (keysym in self.keys):
                    self.backend.key(keysym, pressed)
                    self.keys.add(keysym) if pressed else self.keys.discard(keysym)
            elif kind == 'text':
                value = command.get('text')
                if not isinstance(value, str) or not value or len(value) > 8192 or '\0' in value:
                    raise ValueError('Text is empty or too long')
                self.cancel()
                self.backend.clipboard(value.encode('utf-8'), 'UTF8_STRING')
            elif kind == 'clipboard_image':
                data = capture_bytes(self.ipc, command.get('image_name'))
                self.cancel()
                self.backend.clipboard(data, 'image/png')
            elif kind in ('pointer_cancel', 'release_all'):
                self.cancel()
            elif kind == 'launch_tui':
                self.cancel()
                self.backend.launch_tui()
            elif kind == 'focus_desktop':
                self.cancel()
                self.backend.focus_desktop()
            elif kind == 'navigate_hermes':
                destination = command.get('destination')
                if not isinstance(destination, str) or destination not in {'tools', 'skills', 'mcp', 'plugins', 'artifacts', 'approvals', 'settings', 'new_session', 'voice', 'dictate', 'end_voice'}:
                    raise ValueError('Unknown Hermes navigation destination')
                self.cancel()
                result = self.backend.navigate_hermes(destination)
                self.last_input = self.clock()
                self.backend.flush()
                self.last_command = {'id': command_id, 'status': 'done', 'error': '', 'message': result.get('message', '')}
                return True
            elif kind == 'shutdown':
                self.cancel()
                self.shutdown = True
            else:
                raise ValueError('Unknown desktop command')
            self.last_input = self.clock()
            self.backend.flush()
            self.last_command = {'id': command_id, 'status': 'done', 'error': ''}
            return True
        except (ValueError, OSError) as exc:
            self.last_command = {'id': command_id if isinstance(command_id, str) else '', 'status': 'error', 'error': str(exc)}
            return False


def stop_owned(process):
    if process is None:
        return
    # Only PIDs returned by our own Popen calls are ever signalled.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)


class PrivateDesktop:
    def __init__(self, ipc, argv, progress=None, accepted_environment=None):
        self.ipc, self.argv = ipc, argv
        self.accepted_environment = dict(accepted_environment or {})
        self.xvfb = self.app = self.tui = self.display = self.bus = None
        self.owner = None
        self.clipboard_data = b''
        self.clipboard_type = None
        self.transfers = {}
        self.main_window = None
        self.environment = None
        self.active_window = None
        self.paste_queue = collections.deque()
        self.paste_active = False
        self.paste_started = self.paste_finished = 0
        self.pending_terminal_paste = None
        self.progress = progress or (lambda stage: None)
        self.server_grabbed = False
        self.generic = False

    def owned(self, argv, **kwargs):
        # An exec wrapper sets Linux PDEATHSIG in a fresh interpreter. This avoids
        # unsafe preexec_fn work and kills the direct child if this helper dies.
        wrapper = [sys.executable, str(Path(__file__).resolve()), '--owned-child', str(os.getpid())]
        return subprocess.Popen(wrapper + argv, start_new_session=True, **kwargs)

    def start(self):
        if os.name != 'posix':
            raise RuntimeError('The existing Hermes desktop capture requires Linux with Xvfb')
        self.progress('Loading private desktop capture dependencies')
        from Xlib import X, XK, Xatom, display
        from Xlib.ext import xtest
        from Xlib.protocol import event
        from PIL import ImageGrab
        self.X, self.XK, self.Xatom, self.xtest, self.event, self.ImageGrab = X, XK, Xatom, xtest, event, ImageGrab
        auth_path = self.ipc / 'Xauthority'
        cookie = secrets.token_bytes(16)
        with open(auth_path, 'wb') as stream:
            stream.write(xauthority_record(65535, b'', b'', cookie))
        os.chmod(auth_path, 0o600)
        read_fd, write_fd = os.pipe()
        try:
            self.progress('Starting private X server')
            self.xvfb = self.owned([
                'Xvfb', '-displayfd', str(write_fd), '-screen', '0',
                f'{WIDTH + GUTTER * 2}x{HEIGHT + GUTTER * 2}x24',
                '-nolisten', 'tcp', '-auth', str(auth_path), '-noreset'],
                pass_fds=(write_fd,),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.close(write_fd)
            write_fd = None
            if not select.select([read_fd], [], [], 10)[0]:
                raise RuntimeError('Private Xvfb did not become ready')
            number = os.read(read_fd, 64).decode('ascii').strip()
            if not number.isdigit():
                raise RuntimeError('Private Xvfb could not allocate a display')
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
        self.display_name = ':' + number
        # Xvfb accepts the wildcard server record; python-xlib requires an exact
        # FamilyLocal hostname + display number when finding client credentials.
        with open(auth_path, 'ab') as stream:
            stream.write(xauthority_record(256, socket.gethostname().encode(), number.encode('ascii'), cookie))
        self.environment = dict(os.environ)
        self.environment.update(self.accepted_environment)
        self.environment.update(DISPLAY=self.display_name, XAUTHORITY=str(auth_path),
                                GDK_BACKEND='x11', QT_QPA_PLATFORM='xcb')
        self.environment.pop('WAYLAND_DISPLAY', None)
        self.environment.pop('DBUS_SESSION_BUS_ADDRESS', None)
        self.environment['NO_AT_BRIDGE'] = '0'
        # Chromium's native ATK bridge also requires this process-local switch;
        # renderer accessibility alone does not register the Linux application.
        self.environment['ACCESSIBILITY_ENABLED'] = '1'
        self.progress('Starting private desktop accessibility bus')
        self.bus = self.owned(['dbus-daemon', '--session', '--nofork', '--print-address=1'],
                              env=self.environment, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if not select.select([self.bus.stdout], [], [], 3)[0]:
            raise RuntimeError('The private accessibility bus did not become ready')
        address = self.bus.stdout.readline(4096).decode('utf-8').strip()
        self.bus.stdout.close()
        if not address.startswith('unix:'):
            raise RuntimeError('The private accessibility bus is unavailable')
        self.environment['DBUS_SESSION_BUS_ADDRESS'] = address
        # Both capture and Xlib authentication are private to this helper process.
        os.environ['XAUTHORITY'] = str(auth_path)
        self.progress('Connecting to private X server')
        self.display = display.Display(self.display_name)
        self.root = self.display.screen().root
        self.root.change_attributes(event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        self.owner = self.root.create_window(0, 0, 1, 1, 0, self.display.screen().root_depth,
                                             event_mask=X.PropertyChangeMask)
        self.atoms = {name: self.display.intern_atom(name) for name in (
            'CLIPBOARD', 'TARGETS', 'UTF8_STRING', 'image/png', 'INCR',
            '_NET_SUPPORTING_WM_CHECK', '_NET_WM_NAME', '_NET_ACTIVE_WINDOW', '_NET_SUPPORTED',
            '_NET_WM_STATE', '_NET_WM_STATE_FULLSCREEN')}
        self.root.change_property(self.atoms['_NET_SUPPORTING_WM_CHECK'], Xatom.WINDOW, 32, [self.owner.id])
        self.owner.change_property(self.atoms['_NET_SUPPORTING_WM_CHECK'], Xatom.WINDOW, 32, [self.owner.id])
        self.owner.change_property(self.atoms['_NET_WM_NAME'], self.atoms['UTF8_STRING'], 8, b'Hermes Office Private Display')
        self.root.change_property(self.atoms['_NET_SUPPORTED'], Xatom.ATOM, 32,
                                  [self.atoms['_NET_ACTIVE_WINDOW'], self.atoms['_NET_WM_STATE']])
        self.progress('Initializing private window manager')
        self.display.sync()
        self.progress('Launching existing Hermes desktop')
        self.app = self.owned(self.argv, env=self.environment,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def fit(self, window, main=False, requested=None):
        if self.owner and window.id == self.owner.id:
            return
        geometry = window.get_geometry()
        values = requested or {}
        width = WIDTH if main else min(WIDTH, max(1, values.get('width', geometry.width)))
        height = HEIGHT if main else min(HEIGHT, max(1, values.get('height', geometry.height)))
        x = GUTTER if main else max(GUTTER, min(values.get('x', geometry.x), GUTTER + WIDTH - width))
        y = GUTTER if main else max(GUTTER, min(values.get('y', geometry.y), GUTTER + HEIGHT - height))
        if (geometry.x, geometry.y, geometry.width, geometry.height, geometry.border_width) != (x, y, width, height, 0):
            window.configure(x=x, y=y, width=width, height=height, border_width=0)

    def enforce_gutter(self):
        from Xlib.error import BadWindow, BadDrawable
        for window in self.root.query_tree().children:
            try:
                if window.id != self.owner.id and window.get_attributes().map_state != self.X.IsUnmapped:
                    self.fit(window, window.id == self.main_window)
            except (BadWindow, BadDrawable):
                continue
        self.display.sync()

    def focus(self, window):
        window.set_input_focus(self.X.RevertToParent, self.X.CurrentTime)
        self.active_window = window.id
        self.root.change_property(self.atoms['_NET_ACTIVE_WINDOW'], self.Xatom.WINDOW, 32, [window.id])

    def pump(self):
        from Xlib.error import BadWindow, BadDrawable
        for _ in range(1000):
            if not self.display.pending_events():
                break
            item = self.display.next_event()
            try:
                if item.type == self.X.MapRequest:
                    if self.main_window is None and not item.window.get_attributes().override_redirect:
                        self.main_window = item.window.id
                    self.fit(item.window, item.window.id == self.main_window)
                    item.window.map()
                    self.focus(item.window)
                elif self.generic and item.type in (self.X.DestroyNotify, self.X.UnmapNotify) and item.window.id == self.main_window:
                    self.main_window = None
                    self.active_window = None
                elif item.type == self.X.ConfigureRequest:
                    requested = {name: getattr(item, name) for name, bit in (
                        ('x', self.X.CWX), ('y', self.X.CWY), ('width', self.X.CWWidth), ('height', self.X.CWHeight))
                        if item.value_mask & bit}
                    self.fit(item.window, item.window.id == self.main_window, requested)
                elif item.type == self.X.ClientMessage and item.client_type == self.atoms['_NET_ACTIVE_WINDOW']:
                    item.window.configure(stack_mode=self.X.Above)
                    self.focus(item.window)
                elif item.type == self.X.SelectionRequest:
                    self.selection_request(item)
                elif item.type == self.X.PropertyNotify and item.state == self.X.PropertyDelete:
                    key = (item.window.id, item.atom)
                    transfer = self.transfers.get(key)
                    if transfer:
                        window, target, data, offset, _ = transfer
                        chunk = data[offset:offset + 65536]
                        window.change_property(item.atom, target, 8, chunk)
                        if chunk:
                            self.transfers[key] = (window, target, data, offset + len(chunk), time.monotonic())
                        else:
                            self.transfers.pop(key, None)
                            self.paste_finished = time.monotonic()
            except (BadWindow, BadDrawable):
                continue
        if self.generic and self.main_window is None:
            for window in self.root.query_tree().children:
                try:
                    attrs = window.get_attributes()
                    if window.id != self.owner.id and attrs.map_state == self.X.IsViewable and not attrs.override_redirect:
                        self.main_window = window.id
                        self.fit(window, main=True)
                        self.focus(window)
                        break
                except (BadWindow, BadDrawable):
                    continue
        for key, value in list(self.transfers.items()):
            if time.monotonic() - value[-1] > 10:
                self.transfers.pop(key, None)
        if self.paste_active and not self.transfers and self.paste_finished and time.monotonic() - self.paste_finished > 0.08:
            self.paste_active = False
        if self.paste_active and time.monotonic() - self.paste_started > 15:
            # Unfocused paste has no completion; never replay it into a later focus.
            self.paste_active = False
            self.paste_queue.clear()
        if not self.paste_active and self.paste_queue:
            self.begin_paste(*self.paste_queue.popleft())
        self.finish_terminal_paste()
        self.enforce_gutter()

    def selection_request(self, item):
        property_atom = item.property or item.target
        accepted = False
        if item.selection == self.atoms['CLIPBOARD']:
            if item.target == self.atoms['TARGETS']:
                item.requestor.change_property(property_atom, self.Xatom.ATOM, 32,
                                                [self.atoms['TARGETS'], self.clipboard_type])
                accepted = True
            elif item.target == self.clipboard_type:
                if len(self.clipboard_data) <= 65536:
                    item.requestor.change_property(property_atom, item.target, 8, self.clipboard_data)
                    self.paste_finished = time.monotonic()
                else:
                    item.requestor.change_attributes(event_mask=self.X.PropertyChangeMask)
                    item.requestor.change_property(property_atom, self.atoms['INCR'], 32, [len(self.clipboard_data)])
                    self.transfers[(item.requestor.id, property_atom)] = (
                        item.requestor, item.target, self.clipboard_data, 0, time.monotonic())
                accepted = True
        item.requestor.send_event(self.event.SelectionNotify(
            time=item.time, requestor=item.requestor, selection=item.selection,
            target=item.target, property=property_atom if accepted else self.X.NONE), propagate=False)
        self.display.flush()

    def move(self, x, y):
        self.xtest.fake_input(self.display, self.X.MotionNotify, x=x + GUTTER, y=y + GUTTER)

    def cancel_pointer(self):
        # Keep another app client from moving/remapping over the gutter between
        # the bounds check and release. InputController.flush ends this brief grab.
        self.display.grab_server()
        self.server_grabbed = True
        self.enforce_gutter()
        self.xtest.fake_input(self.display, self.X.MotionNotify, x=0, y=0)
        self.display.sync()

    def button(self, number, pressed):
        self.xtest.fake_input(self.display, self.X.ButtonPress if pressed else self.X.ButtonRelease, number)

    def key(self, name, pressed):
        keysym = self.XK.string_to_keysym(name)
        code = self.display.keysym_to_keycode(keysym) if keysym else 0
        if not code:
            raise ValueError('Key is unavailable on the private display')
        self.xtest.fake_input(self.display, self.X.KeyPress if pressed else self.X.KeyRelease, code)

    def clipboard(self, data, mime):
        if len(self.paste_queue) >= 64:
            raise ValueError('Desktop paste queue is full')
        self.paste_queue.append((data, mime))
        if not self.paste_active:
            self.begin_paste(*self.paste_queue.popleft())

    def begin_paste(self, data, mime):
        self.paste_active = True
        self.paste_started = time.monotonic()
        self.paste_finished = 0
        self.clipboard_data, self.clipboard_type = data, self.atoms[mime]
        self.owner.set_selection_owner(self.atoms['CLIPBOARD'], self.X.CurrentTime)
        self.display.sync()
        # GNOME Terminal uses Ctrl+Shift+V; Ctrl+V quotes the next character.
        # Inspect only this private display and only while our TUI is running.
        terminal = False
        if self.tui and self.tui.poll() is None:
            focused = self.display.get_input_focus().focus
            for _ in range(5):
                if not hasattr(focused, 'get_wm_class'): break
                classes = focused.get_wm_class() or ()
                if any(str(value).lower() in {'gnome-terminal', 'gnome-terminal-server'} for value in classes):
                    terminal = True
                    break
                parent = focused.query_tree().parent
                if parent == focused: break
                focused = parent
        if terminal:
            # GTK learns available clipboard targets asynchronously. An immediate
            # shortcut is discarded while Paste is disabled. Let the event loop
            # service TARGETS before sending one shortcut to the same focus.
            self.pending_terminal_paste = (time.monotonic() + .2,
                                           self.display.get_input_focus().focus.id)
            return
        self.key('Control_L', True)
        self.key('v', True)
        self.key('v', False)
        self.key('Control_L', False)
        self.display.flush()

    def finish_terminal_paste(self):
        pending = self.pending_terminal_paste
        if not pending or time.monotonic() < pending[0]:
            return
        self.pending_terminal_paste = None
        focused = self.display.get_input_focus().focus
        if getattr(focused, 'id', None) != pending[1]:
            self.paste_active = False
            self.paste_queue.clear()
            return
        for name, pressed in [('Control_L', True), ('Shift_L', True),
                              ('v', True), ('v', False),
                              ('Shift_L', False), ('Control_L', False)]:
            self.key(name, pressed)
        self.display.flush()

    def launch_tui(self):
        if self.tui and self.tui.poll() is None:
            return
        executable = Path(__file__).resolve().parent / 'run-hermes-tui.sh'
        if not executable.is_file() or not Path('/usr/bin/gnome-terminal').is_file():
            raise ValueError('The existing Hermes TUI launcher is unavailable')
        self.tui = self.owned(['/usr/bin/dbus-run-session', '--', '/usr/bin/gnome-terminal',
                                     '--wait', '--', 'bash', str(executable)], env=self.environment,
                                    stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def focus_desktop(self):
        if self.main_window is None:
            raise ValueError('The existing Hermes desktop window is unavailable')
        window = self.display.create_resource_object('window', self.main_window)
        self.fit(window, main=True)
        window.map()
        window.configure(stack_mode=self.X.Above)
        self.focus(window)

    def navigate_hermes(self, destination):
        from hermes_navigation import navigate
        self.focus_desktop()
        self.display.sync()
        return navigate(destination, self.app.pid, environment=self.environment)

    def flush(self):
        if self.server_grabbed:
            self.display.ungrab_server()
            self.server_grabbed = False
        self.display.flush()

    def visible_window_rectangles(self):
        """Snapshot this owned root's viewable app windows in capture pixels."""
        from Xlib.error import BadWindow, BadDrawable
        rectangles = []
        main_viewable = False
        for window in self.root.query_tree().children:
            if self.owner and window.id == self.owner.id:
                continue
            try:
                attributes = window.get_attributes()
                if attributes.map_state != self.X.IsViewable or attributes.win_class == self.X.InputOnly:
                    continue
                geometry = window.get_geometry()
                left, top = geometry.x - GUTTER, geometry.y - GUTTER
                rectangles.append((left, top, left + geometry.width, top + geometry.height))
                if window.id == self.main_window:
                    main_viewable = True
            except (BadWindow, BadDrawable):
                # A popup may have closed between enumerating it and reading it.
                continue
        return main_viewable, rectangles

    def frame(self, path):
        main_viewable, rectangles = self.visible_window_rectangles()
        image = self.ImageGrab.grab(xdisplay=self.display_name)
        image = image.crop((GUTTER, GUTTER, GUTTER + WIDTH, GUTTER + HEIGHT))
        image = apply_window_alpha(image, rectangles, main_viewable)
        pixels = image.tobytes()
        if pixels == getattr(self, '_last_frame_pixels', None) and path.is_file():
            return False
        temporary = path.with_name(path.name + '.tmp')
        image.save(temporary, format='PNG', compress_level=1)
        os.replace(temporary, path)
        self._last_frame_pixels = pixels
        return True

    def alive(self):
        return self.xvfb.poll() is None and self.app.poll() is None

    def close(self):
        if self.display:
            try:
                self.display.close()
            except Exception:
                pass
            self.display = None
        for process in (self.tui, self.app, self.bus, self.xvfb):
            try:
                stop_owned(process)
            except (OSError, subprocess.TimeoutExpired):
                continue


def run(ipc, argv, generic=False):
    ipc.mkdir(parents=True, exist_ok=True)
    if ipc.is_symlink():
        raise ValueError('IPC directory must not be a symbolic link')
    os.chmod(ipc, 0o700)
    for directory in (ipc / 'commands', ipc / 'captures'):
        directory.mkdir(exist_ok=True)
        if directory.is_symlink():
            raise ValueError('IPC subdirectories must not be symbolic links')
        os.chmod(directory, 0o700)
    instance_id = uuid.uuid4().hex
    state = dict(protocol_version=VERSION, instance_id=instance_id, updated_at_unix=time.time(),
                 connected=False, width=WIDTH, height=HEIGHT, frame_id=0, error='Starting Hermes desktop')
    atomic_json(ipc / 'status.json', state)
    def progress(stage):
        state.update(stage=stage, error=stage, updated_at_unix=time.time())
        atomic_json(ipc / 'status.json', state)

    desktop = controller = None
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    code = 0
    try:
        accepted_environment = {}
        script_root = Path(__file__).resolve().parent
        normal_desktop_command = (
            len(argv) == 2 and argv[0] in ('bash', '/bin/bash', '/usr/bin/bash')
            and Path(argv[1]).resolve() == script_root / 'run-hermes-desktop.sh')
        if os.environ.get('HERMES_OFFICE_ACCEPTANCE_RUN') != '1' and normal_desktop_command:
            progress('Checking the installed Hermes desktop runtime')
            from runtime_guard import RuntimeGuardError, validate_runtime
            try:
                verified = validate_runtime(script_root)
                accepted_environment = accepted_launch_environment(verified, os.environ)
            except RuntimeGuardError as exc:
                # RuntimeGuardError is deliberately human-facing. Reuse the
                # sanitized RuntimeError status path without exposing child logs.
                raise RuntimeError(str(exc)) from None
        desktop = PrivateDesktop(ipc, argv, progress, accepted_environment=accepted_environment)
        desktop.generic = generic
        controller = InputController(desktop, ipc, instance_id, hermes_commands=not generic)
        desktop.start()
        progress('Waiting for the existing Hermes desktop window')
        next_frame = 0
        while not stopping and not controller.shutdown:
            if not desktop.alive():
                raise RuntimeError('The existing Hermes desktop process exited')
            desktop.pump()
            controller.expire()
            for path in sorted((ipc / 'commands').glob('*.json'))[:512]:
                try:
                    if path.is_symlink() or path.stat().st_size > MAX_COMMAND:
                        raise ValueError('Desktop command file is invalid or too large')
                    command = json.loads(path.read_text(encoding='utf-8'))
                    controller.dispatch(command)
                except (OSError, ValueError, UnicodeError):
                    controller.last_command = {'id': path.stem, 'status': 'error', 'error': 'Malformed desktop command file'}
                finally:
                    path.unlink(missing_ok=True)
                if controller.shutdown:
                    break
            now = time.monotonic()
            if now >= next_frame:
                if state['frame_id'] == 0:
                    progress('Capturing first private desktop frame')
                changed = desktop.frame(ipc / 'frame.png')
                state.update(connected=desktop.main_window is not None, frame_id=state['frame_id'] + int(changed),
                             error='' if desktop.main_window is not None else 'Waiting for the existing Hermes desktop window',
                             updated_at_unix=time.time(), last_command=controller.last_command,
                             capture_ms=round((time.monotonic()-now)*1000, 2), target_capture_hz=30)
                atomic_json(ipc / 'status.json', state)
                next_frame = now + 1.0/30.0
            time.sleep(0.002)
    except Exception as exc:
        # Avoid subprocess stderr, credentials, command arguments, or environment in IPC.
        state['error'] = str(exc) if isinstance(exc, (RuntimeError, ValueError, ImportError)) else 'Private desktop capture failed (' + type(exc).__name__ + ')'
        code = 1
    finally:
        if desktop is not None and desktop.display:
            try:
                controller.cancel()
            except Exception:
                pass
        if desktop is not None:
            desktop.close()
        state.update(connected=False, updated_at_unix=time.time())
        if not state['error']:
            state['error'] = 'Hermes desktop surface closed'
        atomic_json(ipc / 'status.json', state)
    return code


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == '--owned-child':
        import ctypes
        expected_parent = int(sys.argv[2])
        if not sys.platform.startswith('linux'):
            return 2
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != expected_parent:
            return 2
        os.execvp(sys.argv[3], sys.argv[3:])
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ipc-dir', required=True, type=Path)
    parser.add_argument('--command', required=True)
    parser.add_argument('--generic', action='store_true', help='Remote client surface without Hermes-specific actions')
    args = parser.parse_args()
    if not args.ipc_dir.is_absolute():
        parser.error('--ipc-dir must be absolute')
    try:
        argv = command_argv(args.command)
    except ValueError as exc:
        parser.error(str(exc))
    return run(args.ipc_dir, argv, args.generic)


if __name__ == '__main__':
    sys.exit(main())
