"""No microphone, playback, inference or network access: all IO edges are mocked."""
from array import array
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

import voice_io as voice


def wav_file(path, sample=1000):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(voice.SAMPLE_RATE)
        output.writeframes(array("h", [sample] * 160).tobytes())


def events(output):
    return [json.loads(line) for line in output.getvalue().splitlines()]


class VoiceIOTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name).resolve()
        if os.name == "posix":
            self.directory.chmod(0o700)
        self.output = io.StringIO()

    def tearDown(self):
        self.temporary.cleanup()

    def cli(self, action, text="", work_dir=None):
        return voice.main(["--action", action, "--work-dir", str(work_dir or self.directory)],
                          stdin=io.StringIO(text), stdout=self.output)

    def cache(self, omit=None):
        cache = self.directory / "cache"
        cache.mkdir()
        for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
            if name != omit:
                (cache / name).write_bytes(b"fixture-only; never loaded")
        return cache

    def test_text_limit_is_exact_and_unicode_is_supported(self):
        self.assertEqual(voice.validate_text("x" * 8000), "x" * 8000)
        self.assertEqual(voice.validate_text("  Hello, 世界.  "), "Hello, 世界.")
        for value in ("x" * 8001, " \n\t", "hello\x00there", "\ud800"):
            with self.subTest(value=value[:20]):
                with self.assertRaises(voice.VoiceError):
                    voice.validate_text(value)

    def test_check_is_cache_only_and_never_constructs_model_or_runs_process(self):
        cache = self.cache()
        download = Mock(return_value=str(cache))
        upstream = SimpleNamespace(download_model=download)
        with patch.object(voice.importlib.util, "find_spec", return_value=object()), \
             patch.object(voice.shutil, "which", side_effect=lambda name: "/usr/bin/" + name), \
             patch.object(voice.importlib, "import_module", return_value=upstream) as imports, \
             patch.object(voice.subprocess, "Popen") as popen, \
             patch.object(voice.subprocess, "run") as run, \
             patch.dict(os.environ, {}, clear=False):
            result = self.cli("check")
        self.assertEqual(result, 0)
        download.assert_called_once_with("base.en", local_files_only=True)
        imports.assert_called_once_with("faster_whisper.utils")
        popen.assert_not_called()
        run.assert_not_called()
        self.assertEqual(events(self.output)[-1]["status"], "ready")
        self.assertIn("not been tested", events(self.output)[-1]["message"])

    def test_check_does_not_create_work_directory(self):
        absent = self.directory / "not-created"
        with patch.object(voice, "check_dependencies"):
            self.assertEqual(self.cli("check", work_dir=absent), 0)
        self.assertFalse(absent.exists())

    def test_missing_cache_never_retries_online(self):
        download = Mock(side_effect=FileNotFoundError("not cached"))
        with patch.object(voice.importlib, "import_module", return_value=SimpleNamespace(download_model=download)), \
             patch.dict(os.environ, {}, clear=False):
            with self.assertRaisesRegex(voice.VoiceError, "no model download"):
                voice.cached_model_path()
        download.assert_called_once_with("base.en", local_files_only=True)

    def test_incomplete_cache_rejects_remote_tokenizer_fallback(self):
        cache = self.cache(omit="tokenizer.json")
        with patch.object(voice.importlib, "import_module", return_value=SimpleNamespace(download_model=Mock(return_value=str(cache)))), \
             patch.dict(os.environ, {}, clear=False):
            with self.assertRaisesRegex(voice.VoiceError, "not fully cached"):
                voice.cached_model_path()

    def test_missing_commands_give_protocol_error(self):
        with patch.object(voice, "require_modules"), patch.object(voice.shutil, "which", return_value=None):
            self.assertEqual(self.cli("check"), 2)
        self.assertEqual(events(self.output)[-1]["status"], "error")
        self.assertIn("espeak-ng", events(self.output)[-1]["message"])

    def test_relative_work_directory_is_rejected_before_any_action(self):
        with patch.object(voice, "check_dependencies") as check:
            self.assertEqual(self.cli("check", work_dir="relative/path"), 2)
        check.assert_not_called()
        self.assertIn("absolute", events(self.output)[-1]["message"])

    @unittest.skipUnless(os.name == "posix", "POSIX owner/mode check")
    def test_nonprivate_existing_directory_is_rejected_without_chmod(self):
        shared = self.directory / "shared"
        shared.mkdir(mode=0o755)
        shared.chmod(0o755)
        with self.assertRaisesRegex(voice.VoiceError, "0700"):
            voice.validate_work_dir(shared)
        self.assertEqual(shared.stat().st_mode & 0o777, 0o755)

    def test_speak_passes_literal_text_on_stdin_and_cleans_private_audio(self):
        text = 'Hello; $(touch NEVER) "quoted" — test.'
        calls = []

        def fake_run(operation, command, input_text=None, timeout=90):
            calls.append((command, input_text, timeout))
            if Path(command[0]).name == "espeak-ng":
                wav_file(Path(command[command.index("-w") + 1]))

        with patch.object(voice.shutil, "which", side_effect=lambda name: "/usr/bin/" + name), \
             patch.object(voice, "find_wivrn_node", return_value="wivrn.output"), \
             patch.object(voice.VoiceOperation, "run_process", new=fake_run), \
             patch.object(voice.importlib, "import_module") as imports:
            self.assertEqual(self.cli("speak", text), 0)
        self.assertEqual(calls[0][1], text)
        self.assertIn("--stdin", calls[0][0])
        self.assertNotIn(text, calls[0][0])
        self.assertIn("--device=wivrn.output", calls[1][0])
        imports.assert_not_called()
        self.assertEqual(events(self.output)[-1], {"event": "done"})
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_oversized_stdin_is_rejected_before_commands(self):
        with patch.object(voice, "require_commands") as commands:
            self.assertEqual(self.cli("speak", "x" * 8001), 2)
        commands.assert_not_called()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_speak_failure_does_not_emit_done_and_cleans_audio(self):
        with patch.object(voice, "require_commands", return_value={"espeak-ng": "/usr/bin/espeak-ng", "paplay": "/usr/bin/paplay"}), \
             patch.object(voice, "find_wivrn_node", return_value=None), \
             patch.object(voice.VoiceOperation, "run_process", side_effect=voice.VoiceError("Playback failed")):
            self.assertEqual(self.cli("speak", "Hello"), 2)
        self.assertFalse(any(item["event"] == "done" for item in events(self.output)))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_record_protocol_and_cleanup_use_only_mock_capture_and_stt(self):
        def capture(operation, path, output):
            voice.emit(output, "status", status="listening", message="Mock capture")
            wav_file(path)

        with patch.object(voice, "require_modules"), \
             patch.object(voice, "cached_model_path", return_value=self.directory / "fake-cache"), \
             patch.object(voice, "record_audio", side_effect=capture), \
             patch.object(voice, "transcribe_audio", return_value="Review this with me.") as transcribe, \
             patch.object(voice.importlib, "import_module") as imports:
            self.assertEqual(self.cli("record"), 0)
        self.assertEqual([item.get("status") for item in events(self.output)[:-1]], ["listening", "transcribing", "ready"])
        self.assertEqual(events(self.output)[-1], {"event": "transcript", "text": "Review this with me."})
        transcribe.assert_called_once()
        imports.assert_not_called()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_silent_capture_does_not_transcribe_or_return_fake_text(self):
        with patch.object(voice, "require_modules"), \
             patch.object(voice, "cached_model_path", return_value=self.directory / "fake-cache"), \
             patch.object(voice, "record_audio", side_effect=lambda operation, path, output: wav_file(path, 0)), \
             patch.object(voice, "transcribe_audio") as transcribe:
            self.assertEqual(self.cli("record"), 2)
        transcribe.assert_not_called()
        self.assertEqual(events(self.output)[-1]["status"], "error")
        self.assertFalse(any(item["event"] == "transcript" for item in events(self.output)))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_cancelled_capture_returns_130_without_transcript_and_cleans(self):
        def capture(operation, path, output):
            wav_file(path)
            raise voice.VoiceCancelled()

        with patch.object(voice, "require_modules"), \
             patch.object(voice, "cached_model_path", return_value=self.directory / "fake-cache"), \
             patch.object(voice, "record_audio", side_effect=capture):
            self.assertEqual(self.cli("record"), 130)
        self.assertEqual(events(self.output)[-1], {"event": "status", "status": "error", "message": "Voice operation cancelled."})
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_wivrn_pulse_is_preferred_and_failure_never_switches_mics(self):
        with patch.object(voice, "find_wivrn_node", return_value="wivrn.microphone"), \
             patch.object(voice, "require_commands", return_value={"parecord": "/usr/bin/parecord"}), \
             patch.object(voice, "record_with_pulse", side_effect=voice.VoiceError("headset disconnected")) as pulse, \
             patch.object(voice, "record_with_sounddevice") as fallback:
            with self.assertRaises(voice.VoiceError):
                voice.record_audio(voice.VoiceOperation(), self.directory / "input.wav", self.output)
        pulse.assert_called_once()
        fallback.assert_not_called()

    def test_pulse_source_parser_skips_monitor_and_uses_no_shell(self):
        listing = "1\twivrn.output.monitor\tmodule\n2\twivrn.microphone\tmodule\n"
        with patch.object(voice.shutil, "which", return_value="/usr/bin/pactl"), \
             patch.object(voice.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=listing)) as run:
            self.assertEqual(voice.find_wivrn_node("sources"), "wivrn.microphone")
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.args[0], ["/usr/bin/pactl", "list", "short", "sources"])

    def test_transcription_uses_cpu_int8_and_local_cache_only(self):
        model = Mock()
        model.transcribe.return_value = ([SimpleNamespace(text=" Hello "), SimpleNamespace(text="world.")], None)
        constructor = Mock(return_value=model)
        with patch.object(voice.importlib, "import_module", return_value=SimpleNamespace(WhisperModel=constructor)):
            text = voice.transcribe_audio(self.directory / "input.wav", self.directory / "cached-base.en")
        self.assertEqual(text, "Hello world.")
        self.assertEqual(constructor.call_args.kwargs, {"device": "cpu", "compute_type": "int8", "local_files_only": True})
        self.assertEqual(model.transcribe.call_args.kwargs, {"language": "en", "vad_filter": True})

    def test_child_timeout_is_terminated_and_never_uses_shell(self):
        process = Mock()
        process.poll.return_value = None
        process.communicate.side_effect = subprocess.TimeoutExpired("espeak-ng", 1)
        with patch.object(voice.subprocess, "Popen", return_value=process) as popen:
            with voice.VoiceOperation() as operation:
                with self.assertRaisesRegex(voice.VoiceError, "timed out"):
                    operation.run_process(["/usr/bin/espeak-ng", "--stdin"], input_text="test", timeout=1)
                self.assertEqual(operation.children, [])
        process.terminate.assert_called_once()
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertEqual(process.communicate.call_args.kwargs["input"], "test")

    def test_cleanup_kills_only_owned_child_after_grace_timeout(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("parecord", 2), 0]
        operation = voice.VoiceOperation()
        operation.children.append(process)
        operation.close()
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(operation.children, [])

    def test_signal_handler_cancels_once_then_allows_cleanup(self):
        registered = {}

        def register(number, handler):
            previous = registered.get(number, signal.SIG_DFL)
            registered[number] = handler
            return previous

        with patch.object(voice.signal, "signal", side_effect=register):
            with voice.cancellation_signals():
                handler = registered[signal.SIGTERM]
                with self.assertRaises(voice.VoiceCancelled):
                    handler(signal.SIGTERM, None)
                handler(signal.SIGTERM, None)
            self.assertEqual(registered[signal.SIGTERM], signal.SIG_DFL)


if __name__ == "__main__":
    unittest.main()
