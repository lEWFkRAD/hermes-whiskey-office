"""Deterministic desktop IPC/input tests; no X server, audio, model, or network."""
import json
from pathlib import Path
import signal
import subprocess
import unittest
import tempfile
import types
from unittest.mock import MagicMock, patch

from PIL import Image

import desktop_bridge as bridge


class FakeDesktop:
    def __init__(self):
        self.events = []

    def move(self, x, y): self.events.append(('move', x, y))
    def button(self, button, pressed): self.events.append(('button', button, pressed))
    def key(self, key, pressed): self.events.append(('key', key, pressed))
    def cancel_pointer(self): self.events.append(('gutter',))
    def flush(self): pass
    def clipboard(self, data, mime): self.events.append(('clipboard', data, mime))
    def launch_tui(self): self.events.append(('tui',))
    def focus_desktop(self): self.events.append(('desktop',))
    def navigate_hermes(self, destination):
        self.events.append(('navigate', destination))
        return {'message': 'Opened Hermes '+destination}


class DesktopContractTests(unittest.TestCase):
    def test_desktop_restores_app_before_mapping_its_hidden_window(self):
        desktop = object.__new__(bridge.PrivateDesktop)
        desktop.main_window = 123
        desktop.generic = False
        desktop.app = types.SimpleNamespace(pid=456)
        desktop.environment = {'DISPLAY': ':private'}
        desktop.display = MagicMock()
        desktop.X = types.SimpleNamespace(Above=0)
        desktop.fit = MagicMock()
        desktop.focus = MagicMock()
        with patch('hermes_navigation.navigate') as navigate:
            desktop.focus_desktop()
            navigate.assert_called_once_with('desktop', 456, environment=desktop.environment)
        with patch('hermes_navigation.navigate', side_effect=ValueError('Ambiguous HUD')):
            desktop.display.reset_mock()
            with self.assertRaises(ValueError): desktop.focus_desktop()
            desktop.display.create_resource_object.assert_not_called()

    def test_unchanged_frames_skip_encoding_but_recreate_missing_files(self):
        desktop = object.__new__(bridge.PrivateDesktop)
        desktop.display_name = ':test'
        pixels = Image.new('RGB', (bridge.WIDTH+2*bridge.GUTTER, bridge.HEIGHT+2*bridge.GUTTER), 'red')
        desktop.ImageGrab = types.SimpleNamespace(grab=lambda **kw: pixels)
        desktop.visible_window_rectangles = lambda: (True, [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'frame.png'
            self.assertTrue(desktop.frame(path))
            stamp = path.stat().st_mtime_ns
            self.assertFalse(desktop.frame(path))
            self.assertEqual(path.stat().st_mtime_ns, stamp)
            pixels.putpixel((bridge.GUTTER, bridge.GUTTER), (0,255,0))
            self.assertTrue(desktop.frame(path))
            path.unlink()
            self.assertTrue(desktop.frame(path))

    def test_remote_surface_cannot_invoke_hermes_navigation(self):
        self.controller.hermes_commands = False
        self.assertFalse(self.send('navigate_hermes', destination='approvals'))
        self.assertFalse(self.send('launch_tui'))
        self.assertEqual(self.desktop.events, [])

    def test_navigation_is_allowlisted_and_never_sends_approval_keys(self):
        self.setUp()
        for invalid in ('approve', 'reject', 'delete', [], None, {'destination': 'tools'}):
            self.assertFalse(self.send('navigate_hermes', destination=invalid))
        self.assertEqual(self.desktop.events, [])
        self.assertTrue(self.send('navigate_hermes', destination='approvals'))
        self.assertEqual(self.desktop.events, [('gutter',), ('navigate', 'approvals')])
        self.assertEqual(self.controller.last_command['message'], 'Opened Hermes approvals')

    def setUp(self):
        self.now = 1000.
        self.desktop = FakeDesktop()
        self.controller = bridge.InputController(self.desktop, Path('/private/ipc'), 'instance', lambda: self.now)
        self.serial = 0

    def command(self, kind, **params):
        self.serial += 1
        return dict(protocol_version=1, instance_id='instance', id=str(self.serial), type=kind,
                    created_at_unix=self.now, **params)

    def send(self, kind, **params):
        return self.controller.dispatch(self.command(kind, **params))

    def test_protocol_instance_timestamp_and_malformed_types(self):
        for change in ({'protocol_version': 2}, {'protocol_version': True}, {'instance_id': 'old'},
                       {'created_at_unix': 990}, {'created_at_unix': 1002}, {'created_at_unix': float('nan')},
                       {'created_at_unix': True}, {'id': '../x'}, {'id': 1}):
            value = self.command('pointer_move', x=1, y=1)
            value.update(change)
            self.assertFalse(self.controller.dispatch(value), change)
        for value in (None, [], 'x', 1):
            self.assertFalse(self.controller.dispatch(value))
        self.assertEqual(self.desktop.events, [])

    def test_duplicate_never_replays_click(self):
        value = self.command('pointer_button', x=10, y=20, button=1, pressed=True)
        self.assertTrue(self.controller.dispatch(value))
        events = list(self.desktop.events)
        self.assertFalse(self.controller.dispatch(value))
        self.assertEqual(events, self.desktop.events)

    def test_coordinates_and_mouse_types_validated_before_input(self):
        for x, y in ((-1, 0), (1280, 0), (0, 800), (float('inf'), 0), (True, 0), ('1', 0)):
            self.assertFalse(self.send('pointer_move', x=x, y=y))
        for button, pressed in ((True, True), (4, True), (1, 'false')):
            self.assertFalse(self.send('pointer_button', x=1, y=1, button=button, pressed=pressed))
        self.assertEqual(self.desktop.events, [])

    def test_normal_release_stays_at_valid_point(self):
        self.assertTrue(self.send('pointer_button', x=20, y=30, button=1, pressed=True))
        self.assertTrue(self.send('pointer_button', x=22, y=32, button=1, pressed=False))
        self.assertEqual(self.desktop.events, [('move', 20, 30), ('button', 1, True),
                                              ('move', 22, 32), ('button', 1, False)])

    def test_cancel_moves_into_gutter_before_all_releases(self):
        self.send('pointer_button', x=200, y=400, button=1, pressed=True)
        self.send('key', keysym='Control_L', pressed=True)
        self.desktop.events.clear()
        self.assertTrue(self.send('pointer_cancel'))
        self.assertEqual(self.desktop.events, [('gutter',), ('button', 1, False), ('key', 'Control_L', False)])
        self.assertFalse(self.controller.buttons or self.controller.keys)

    def test_inactive_client_releases_safely(self):
        self.send('pointer_button', x=0, y=0, button=2, pressed=True)
        self.desktop.events.clear()
        self.now += 4.1
        self.controller.expire()
        self.assertEqual(self.desktop.events, [('gutter',), ('button', 2, False)])

    def test_release_without_press_never_injects_click(self):
        self.send('pointer_button', x=4, y=5, button=1, pressed=False)
        self.assertEqual(self.desktop.events, [('move', 4, 5)])

    def test_scroll_down_positive(self):
        self.send('pointer_wheel', x=5, y=6, delta_y=2)
        self.send('pointer_wheel', x=5, y=6, delta_y=-1)
        buttons = [item for item in self.desktop.events if item[0] == 'button']
        self.assertEqual(buttons, [('button', 5, True), ('button', 5, False)] * 2 +
                         [('button', 4, True), ('button', 4, False)])
        for value in (0, 21, float('nan'), True):
            self.assertFalse(self.send('pointer_wheel', x=5, y=6, delta_y=value))

    def test_key_names_are_data_not_executable(self):
        for value in ('Return; reboot', '', '../a', 5):
            self.assertFalse(self.send('key', keysym=value, pressed=True))
        self.assertTrue(self.send('key', keysym='Return', pressed=True))
        self.assertTrue(self.send('key', keysym='Return', pressed=False))
        self.assertEqual(self.desktop.events, [('key', 'Return', True), ('key', 'Return', False)])

    def test_text_clears_modifiers_and_pastes_without_enter(self):
        self.send('key', keysym='Shift_L', pressed=True)
        self.desktop.events.clear()
        self.assertTrue(self.send('text', text='Hello\nworld 🐕'))
        self.assertEqual(self.desktop.events, [('gutter',), ('key', 'Shift_L', False),
                                              ('clipboard', 'Hello\nworld 🐕'.encode(), 'UTF8_STRING')])
        for value in ('', 'x' * 8193, None, 'a\0b'):
            self.assertFalse(self.send('text', text=value))

    def test_image_only_explicit_capture_and_no_enter(self):
        with patch.object(bridge, 'capture_bytes', return_value=b'PNG') as capture:
            self.assertTrue(self.send('clipboard_image', image_name='view.png'))
            capture.assert_called_once_with(Path('/private/ipc'), 'view.png')
        self.assertEqual(self.desktop.events, [('gutter',), ('clipboard', b'PNG', 'image/png')])

    def test_capture_path_validation(self):
        for name in ('../view.png', '/view.png', 'a/b.png', 'a\\b.png', 'view.jpg', '', None, 'x.png\0'):
            with self.assertRaises(ValueError):
                bridge.capture_bytes(Path('/private/ipc'), name)

    def test_unknown_fields_tolerated_but_methods_rejected(self):
        self.assertTrue(self.send('pointer_move', x=1, y=2, future={'field': True}))
        self.assertFalse(self.send('exec', command=['rm', '-rf', '/']))
        self.assertEqual(self.desktop.events, [('move', 1, 2)])

    def test_shutdown_cancels_and_stops(self):
        self.send('pointer_button', x=1, y=2, button=1, pressed=True)
        self.assertTrue(self.send('shutdown'))
        self.assertTrue(self.controller.shutdown)
        self.assertEqual(self.desktop.events[-2:], [('gutter',), ('button', 1, False)])

    def test_tui_is_fixed_action(self):
        self.assertTrue(self.send('launch_tui', command='ignored'))
        self.assertEqual(self.desktop.events, [('gutter',), ('tui',)])

    def test_focus_desktop_is_fixed_action(self):
        self.assertTrue(self.send('focus_desktop', window_id=999))
        self.assertEqual(self.desktop.events, [('gutter',), ('desktop',)])

    def test_argv_validation(self):
        self.assertEqual(bridge.command_argv('["bash","run-hermes-desktop.sh"]'), ['bash', 'run-hermes-desktop.sh'])
        for value in ('echo x', '[]', '{}', '["x",1]', '[""]', '["x\\u0000"]'):
            with self.assertRaises(ValueError):
                bridge.command_argv(value)

    def test_owned_process_cleanup_escalates_only_recorded_group(self):
        process = MagicMock(pid=23456)
        process.wait.side_effect = [subprocess.TimeoutExpired('owned', 2), 0]
        with patch.object(bridge.os, 'killpg', create=True) as killpg:
            with patch.object(bridge.signal, 'SIGKILL', getattr(signal, 'SIGKILL', 9), create=True):
                bridge.stop_owned(process)
        self.assertEqual(killpg.call_args_list[0].args, (23456, signal.SIGTERM))
        self.assertEqual(killpg.call_args_list[1].args[0], 23456)
        self.assertEqual(process.wait.call_count, 2)

    def test_image_atomic_rename_follows_completed_write(self):
        desktop = bridge.PrivateDesktop(Path('/private'), ['existing-app'])
        desktop.ImageGrab = MagicMock()
        desktop.display_name = ':owned'
        desktop.visible_window_rectangles = MagicMock(return_value=(True, [(0, 0, 1280, 800)]))
        image = desktop.ImageGrab.grab.return_value.crop.return_value
        events = []
        image.save.side_effect = lambda *args, **kwargs: events.append('save')
        with patch.object(bridge.os, 'replace', side_effect=lambda *args: events.append('replace')):
            with patch.object(bridge, 'apply_window_alpha', return_value=image) as mask:
                desktop.frame(Path('/private/frame.png'))
                mask.assert_called_once_with(image, [(0, 0, 1280, 800)], True)
        desktop.ImageGrab.grab.assert_called_once_with(xdisplay=':owned')
        desktop.ImageGrab.grab.return_value.crop.assert_called_once_with((16, 16, 1296, 816))
        self.assertEqual(events, ['save', 'replace'])

    def test_hidden_main_preserves_union_of_window_rectangles(self):
        image = Image.new('RGB', (10, 8), (0, 0, 0))
        image.putpixel((9, 7), (12, 34, 56))
        result = bridge.apply_window_alpha(image, [(1, 1, 4, 4), (6, 0, 9, 2)], False)
        self.assertEqual(result.mode, 'RGBA')
        for y in range(8):
            for x in range(10):
                covered = (1 <= x < 4 and 1 <= y < 4) or (6 <= x < 9 and 0 <= y < 2)
                self.assertEqual(result.getpixel((x, y)), (*image.getpixel((x, y)), 255 if covered else 0))
        self.assertEqual(result.getpixel((2, 2)), (0, 0, 0, 255), 'Black inside UI must remain opaque')
        self.assertEqual(image.mode, 'RGB', 'Masking must not mutate the captured input')

    def test_hidden_main_clips_boxes_and_handles_overlap_and_empty_boxes(self):
        image = Image.new('RGB', (6, 4), (10, 20, 30))
        boxes = [(-3, -2, 2, 2), (1, 1, 4, 3), (3, 2, 8, 9), (7, 7, 9, 9), (4, 2, 4, 3), (5, 3, 2, 1)]
        result = bridge.apply_window_alpha(image, boxes, False)
        for y in range(4):
            for x in range(6):
                covered = any(left <= x < right and top <= y < bottom for left, top, right, bottom in boxes)
                self.assertEqual(result.getpixel((x, y))[3], 255 if covered else 0)

    def test_main_visible_keeps_whole_desktop_opaque(self):
        image = Image.new('RGBA', (3, 2), (7, 8, 9, 0))
        result = bridge.apply_window_alpha(image, [(1, 0, 2, 1)], True)
        self.assertTrue(all(result.getpixel((x, y)) == (7, 8, 9, 255) for y in range(2) for x in range(3)))
        self.assertEqual(image.getpixel((0, 0))[3], 0)

    def test_no_visible_windows_produces_transparent_frame(self):
        result = bridge.apply_window_alpha(Image.new('RGB', (3, 2), 'black'), [], False)
        self.assertEqual(result.getchannel('A').getextrema(), (0, 0))

    def test_window_interiors_do_not_claim_native_per_pixel_alpha(self):
        image = Image.new('RGBA', (4, 3), (0, 0, 0, 0))
        result = bridge.apply_window_alpha(image, [(1, 1, 3, 2)], False)
        self.assertEqual(result.getpixel((1, 1)), (0, 0, 0, 255))
        self.assertEqual(result.getpixel((0, 1)), (0, 0, 0, 0))

    def test_main_window_and_popup_fit_preserve_gutter(self):
        desktop = bridge.PrivateDesktop(Path('/private'), ['existing-app'])
        window = MagicMock(id=42)
        window.get_geometry.return_value = type('Geometry', (), dict(
            x=0, y=0, width=1600, height=1000, border_width=5))()
        desktop.fit(window, main=True)
        window.configure.assert_called_with(x=16, y=16, width=1280, height=800, border_width=0)
        desktop.fit(window, requested=dict(x=1300, y=-5, width=100, height=80))
        window.configure.assert_called_with(x=1196, y=16, width=100, height=80, border_width=0)

    def test_generic_dialog_replacement_releases_old_window_identity(self):
        from Xlib import X
        desktop = bridge.PrivateDesktop(Path('/private'), ['client'])
        desktop.generic = True
        desktop.main_window = desktop.active_window = 42
        desktop.X = X
        desktop.atoms = {}
        desktop.display = MagicMock()
        desktop.display.pending_events.side_effect = [True, False]
        desktop.display.next_event.return_value = type('Event', (), dict(type=X.DestroyNotify, window=type('Window', (), dict(id=42))()))()
        desktop.root = MagicMock()
        desktop.root.query_tree.return_value.children = []
        desktop.enforce_gutter = MagicMock()
        desktop.pump()
        self.assertIsNone(desktop.main_window)
        self.assertIsNone(desktop.active_window)
        replacement = MagicMock(id=77)
        replacement.get_attributes.return_value = type('Attrs', (), dict(map_state=X.IsViewable, override_redirect=False))()
        desktop.root.query_tree.return_value.children = [replacement]
        desktop.owner = MagicMock(id=1)
        desktop.display.pending_events.side_effect = [False]
        desktop.fit = MagicMock()
        desktop.focus = MagicMock()
        desktop.pump()
        self.assertEqual(desktop.main_window, 77)
        desktop.focus.assert_called_once_with(replacement)

    def test_cancel_backend_enforces_gutter_before_motion_and_sync(self):
        desktop = bridge.PrivateDesktop(Path('/private'), ['existing-app'])
        desktop.enforce_gutter = MagicMock()
        desktop.xtest = MagicMock()
        desktop.display = MagicMock()
        desktop.X = MagicMock(MotionNotify=6)
        order = []
        desktop.enforce_gutter.side_effect = lambda: order.append('enforce')
        desktop.xtest.fake_input.side_effect = lambda *args, **kwargs: order.append('move')
        desktop.display.sync.side_effect = lambda: order.append('sync')
        desktop.cancel_pointer()
        self.assertEqual(order, ['enforce', 'move', 'sync'])
        desktop.xtest.fake_input.assert_called_once_with(desktop.display, 6, x=0, y=0)

    def test_clipboard_second_value_queues_until_first_is_consumed(self):
        desktop = bridge.PrivateDesktop(Path('/private'), ['existing-app'])
        desktop.begin_paste = MagicMock(side_effect=lambda *_: setattr(desktop, 'paste_active', True))
        desktop.clipboard(b'a', 'UTF8_STRING')
        desktop.clipboard(b'b', 'UTF8_STRING')
        desktop.begin_paste.assert_called_once_with(b'a', 'UTF8_STRING')
        self.assertEqual(list(desktop.paste_queue), [(b'b', 'UTF8_STRING')])

    def test_terminal_paste_waits_then_sends_once_to_original_focus(self):
        desktop = bridge.PrivateDesktop(Path('/private'), ['existing-app'])
        desktop.display = MagicMock()
        desktop.display.get_input_focus.return_value.focus.id = 42
        desktop.key = MagicMock()
        desktop.pending_terminal_paste = (100.2, 42)
        with patch.object(bridge.time, 'monotonic', return_value=100.1):
            desktop.finish_terminal_paste()
        desktop.key.assert_not_called()
        with patch.object(bridge.time, 'monotonic', return_value=100.3):
            desktop.finish_terminal_paste()
            desktop.finish_terminal_paste()
        self.assertEqual([x.args for x in desktop.key.call_args_list], [
            ('Control_L', True), ('Shift_L', True), ('v', True),
            ('v', False), ('Shift_L', False), ('Control_L', False)])

    def test_delayed_terminal_paste_does_not_follow_changed_focus(self):
        desktop = bridge.PrivateDesktop(Path('/private'), ['existing-app'])
        desktop.display = MagicMock()
        desktop.display.get_input_focus.return_value.focus.id = 43
        desktop.key = MagicMock()
        desktop.pending_terminal_paste = (0, 42)
        desktop.paste_active = True
        desktop.paste_queue.append((b'next', 'UTF8_STRING'))
        desktop.finish_terminal_paste()
        desktop.key.assert_not_called()
        self.assertFalse(desktop.paste_active)
        self.assertEqual(list(desktop.paste_queue), [])

    def test_owned_launch_uses_parent_death_wrapper_and_new_group(self):
        desktop = bridge.PrivateDesktop(Path('/private'), ['existing-app'])
        with patch.object(bridge.subprocess, 'Popen') as popen:
            desktop.owned(['Xvfb', '-displayfd', '42'], pass_fds=(42,))
        args, kwargs = popen.call_args
        self.assertEqual(args[0][2], '--owned-child')
        self.assertEqual(args[0][4:], ['Xvfb', '-displayfd', '42'])
        self.assertTrue(kwargs['start_new_session'])
        self.assertEqual(kwargs['pass_fds'], (42,))


if __name__ == '__main__':
    unittest.main()
