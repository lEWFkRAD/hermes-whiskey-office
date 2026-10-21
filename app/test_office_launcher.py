"""Process-exit races, with no child processes or live integrations."""
import signal
import subprocess
import unittest
from unittest.mock import Mock, patch

import office_launcher as launcher


class ShutdownTests(unittest.TestCase):
    def test_exited_child_needs_no_signal(self):
        process = Mock(poll=Mock(return_value=0))
        launcher.stop_owned(process)
        process.terminate.assert_not_called()
        process.wait.assert_not_called()

    def test_posix_exit_race_is_reaped(self):
        process = Mock(pid=123, poll=Mock(return_value=None))
        with patch.object(launcher.os, 'name', 'posix'), patch.object(
            launcher.os, 'killpg', create=True, side_effect=ProcessLookupError
        ) as kill:
            launcher.stop_owned(process)
        kill.assert_called_once_with(123, signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=5)

    def test_posix_exit_race_after_timeout_is_reaped(self):
        process = Mock(pid=123, poll=Mock(return_value=None))
        process.wait.side_effect = [subprocess.TimeoutExpired('child', 5), 0]
        with patch.object(launcher.os, 'name', 'posix'), patch.object(
            launcher.os, 'killpg', create=True, side_effect=[None, ProcessLookupError]
        ) as kill, patch.object(launcher.signal, 'SIGKILL', 9, create=True):
            launcher.stop_owned(process)
        self.assertEqual(kill.call_count, 2)
        self.assertEqual(process.wait.call_count, 2)

    def test_windows_exit_race_is_reaped(self):
        process = Mock(poll=Mock(return_value=None))
        process.terminate.side_effect = ProcessLookupError
        with patch.object(launcher.os, 'name', 'nt'):
            launcher.stop_owned(process)
        process.wait.assert_called_once_with(timeout=5)

    def test_permission_errors_are_not_hidden(self):
        process = Mock(pid=123, poll=Mock(return_value=None))
        with patch.object(launcher.os, 'name', 'posix'), patch.object(
            launcher.os, 'killpg', create=True, side_effect=PermissionError
        ):
            with self.assertRaises(PermissionError):
                launcher.stop_owned(process)


if __name__ == '__main__':
    unittest.main()
