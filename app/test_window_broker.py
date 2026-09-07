"""Ownership and IPC tests. No connections, credentials, or X server required."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import window_broker as w


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root/'window-sources.json'
        self.rows = [{'id': f'host-{i}', 'title': f'Window {i}', 'machine': f'Host {i}',
                      'command': [sys.executable, '-c', 'pass']} for i in range(9)]
        self.config.write_text(json.dumps(self.rows))
        self.stop = Mock()
        self.broker = w.WindowBroker(self.root/'windows', self.root, self.root, self.root/'primary', {}, self.stop)
        self.serial = 0
        self.spawn = patch.object(w.subprocess, 'Popen', side_effect=lambda *a, **k: Mock(poll=Mock(return_value=None))).start()
        self.addCleanup(patch.stopall)

    def command(self, source='host-0', kind='open', **extra):
        self.serial += 1
        value = dict(protocol_version=1, instance_id=self.broker.instance, id=f'command-{self.serial}',
                     created_at_unix=time.time(), source_id=source, type=kind)
        value.update(extra)
        return value

    def test_lazy_independent_and_reopen_idempotent(self):
        self.assertEqual(self.spawn.call_count, 0)
        self.assertTrue(self.broker.request(self.command()))
        self.broker.request(self.command())
        self.broker.request(self.command('host-1'))
        self.assertEqual(self.spawn.call_count, 2)
        self.assertIsNot(self.broker.processes['host-0'], self.broker.processes['host-1'])
        first, second = self.spawn.call_args_list
        self.assertNotEqual(first.args[0][3], second.args[0][3])
        self.assertIn('--generic', first.args[0])
        self.assertTrue(first.kwargs['start_new_session'])

    def test_stale_foreign_replay_and_unknown_refused(self):
        for extra in [dict(instance_id='other'), dict(created_at_unix=time.time()-12),
                      dict(created_at_unix=float('nan')), dict(source_id='../../other'), dict(type='execute'), dict(id=[]),
                      dict(created_at_unix=time.time()+10)]:
            self.assertFalse(self.broker.request(self.command(**extra)))
        command = self.command()
        self.assertTrue(self.broker.request(command))
        self.assertFalse(self.broker.request(command))
        self.assertEqual(self.spawn.call_count, 1)

    def test_request_cannot_replace_operator_command(self):
        self.broker.request(self.command(command=['/untrusted', '--secret']))
        self.assertEqual(json.loads(self.spawn.call_args.args[0][-1]), self.rows[0]['command'])
        published = (self.root/'windows/windows.json').read_text()
        self.assertNotIn('command', published)

    def test_disconnect_stops_only_selected_client_and_frees_slot(self):
        for i in range(8): self.broker.request(self.command(f'host-{i}'))
        self.assertEqual(self.spawn.call_count, 7)
        self.assertEqual(self.broker.rows['host-7']['status'], 'error')
        owned = self.broker.processes['host-0']
        self.broker.request(self.command('host-0', 'disconnect'))
        self.stop.assert_called_once_with(owned)
        self.broker.request(self.command('host-7'))
        self.assertEqual(self.spawn.call_count, 8)
        self.broker.close()
        self.assertEqual(self.stop.call_count, 8)

    def test_failure_isolated_and_reopen_restarts(self):
        self.broker.request(self.command())
        self.broker.processes['host-0'].poll.return_value = 1
        self.broker.poll()
        self.assertEqual(self.broker.rows['host-0']['status'], 'error')
        self.assertEqual(self.broker.rows['hermes']['status'], 'running')
        self.broker.request(self.command())
        self.assertEqual(self.spawn.call_count, 2)

    def test_malformed_files_are_consumed_without_launching(self):
        commands = self.root/'windows/commands'
        (commands/'bad.json').write_text('{bad')
        (commands/'huge.json').write_text('x'*4097)
        self.broker.poll()
        self.assertEqual(list(commands.iterdir()), [])
        self.assertEqual(self.spawn.call_count, 0)

    def test_dedupe_memory_is_bounded(self):
        self.broker.seen = {f'old-{i}' for i in range(8192)}
        self.assertFalse(self.broker.request(self.command()))
        self.assertEqual(len(self.broker.seen), 8192)

    def test_configuration_rejects_unsafe_identifiers_and_shell_strings(self):
        for changes in [dict(id='../host'), dict(id='hermes'), dict(id='loading-bay'), dict(command='execute anything'),
                        dict(command=['relative']), dict(machine='host\nother')]:
            row = dict(self.rows[0], **changes)
            self.config.write_text(json.dumps([row]))
            with self.assertRaises(ValueError): w.sources(self.config)


if __name__ == '__main__': unittest.main()
