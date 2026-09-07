#!/usr/bin/env python3
"""Foreground local speech IO for the office; stdout is one-shot NDJSON.

No Hermes invocation, shared state files, service management or model download.
The parent owns the conversation and should launch this helper in its own
process group. SIGINT/SIGTERM cancel the operation and clean owned children and
scratch files; SIGKILL cannot provide Python cleanup guarantees.
"""
from __future__ import annotations

import argparse
from array import array
from contextlib import contextmanager, redirect_stdout
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import wave


RECORD_SECONDS = 6
SAMPLE_RATE = 16000
MAX_TEXT_CHARS = 8000
MODEL_NAME = "base.en"


class VoiceError(Exception):
    """An actionable local dependency, device or input error."""


class VoiceCancelled(Exception):
    pass


class ProtocolParser(argparse.ArgumentParser):
    def error(self, message):
        raise VoiceError(message)


def emit(output, event, **fields):
    output.write(json.dumps({"event": event, **fields}, ensure_ascii=True) + "\n")
    output.flush()


def validate_text(text):
    if not isinstance(text, str):
        raise VoiceError("Speech input must be UTF-8 text on stdin.")
    if len(text) > MAX_TEXT_CHARS:
        raise VoiceError("Speech input exceeds the 8000-character limit; shorten the reply.")
    if "\x00" in text:
        raise VoiceError("Speech input contains a NUL character; provide plain text.")
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise VoiceError("Speech input must be valid UTF-8 text.") from exc
    text = text.strip()
    if not text:
        raise VoiceError("There is no text to speak. Pass nonempty text on stdin.")
    return text


def validate_work_dir(value, create=False):
    path = Path(value)
    if not path.is_absolute():
        raise VoiceError("--work-dir must be an absolute path to a private office directory.")
    if path.is_symlink():
        raise VoiceError("Use a private directory directly, not a work-directory symlink.")
    try:
        if create:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists():
            info = path.stat()
            if not stat.S_ISDIR(info.st_mode):
                raise VoiceError("--work-dir must name a directory.")
            if os.name == "posix":
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                    raise VoiceError("The voice work directory must be owned by this user and private (mode 0700).")
    except OSError as exc:
        raise VoiceError("Cannot access the voice work directory; choose a writable private directory owned by this user.") from exc
    return path.resolve()


@contextmanager
def scratch_area(work_dir):
    directory = validate_work_dir(work_dir, create=True)
    # Only this newly created private child is ever removed. Never clean the
    # caller's work directory or other operations' files.
    previous_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix="voice-", dir=str(directory)) as name:
            scratch = Path(name).resolve()
            if scratch.parent != directory:
                raise VoiceError("Could not create an isolated voice scratch directory.")
            yield scratch
    finally:
        os.umask(previous_umask)


def require_modules():
    missing = []
    for name in ("faster_whisper", "sounddevice", "numpy"):
        try:
            available = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            available = False
        if not available:
            missing.append(name)
    if missing:
        raise VoiceError("Install the missing packages in the voice Python environment: " + ", ".join(missing) + ".")


def require_commands(*names):
    commands = {name: shutil.which(name) for name in names}
    missing = [name for name, path in commands.items() if not path]
    if missing:
        raise VoiceError("Install the missing local audio commands: " + ", ".join(missing) + " (espeak-ng and pulseaudio-utils).")
    return commands


def cached_model_path():
    """Inspect the local snapshot only; never instantiate a Whisper model here."""
    # Defense in depth for lazy imports. This is an isolated helper process, not
    # the Hermes process or its environment.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        with redirect_stdout(sys.stderr):
            utilities = importlib.import_module("faster_whisper.utils")
            location = utilities.download_model(MODEL_NAME, local_files_only=True)
        path = Path(location)
        # Requiring tokenizer.json prevents the constructor's tokenizer fallback
        # from looking for a remote pretrained tokenizer in an incomplete cache.
        required = ("model.bin", "config.json", "tokenizer.json")
        if any(not (path / name).is_file() or (path / name).stat().st_size == 0 for name in required):
            raise ValueError("incomplete cached snapshot")
        if not any(p.is_file() and p.stat().st_size for p in path.glob("vocabulary.*")):
            raise ValueError("missing cached vocabulary")
        return path
    except VoiceCancelled:
        raise
    except Exception as exc:
        raise VoiceError("Whisper base.en is not fully cached locally. Prepare its faster-whisper cache separately before recording; no model download was attempted.") from exc


def check_dependencies():
    require_modules()
    require_commands("espeak-ng", "paplay")
    cached_model_path()
    # pactl/parecord provide the preferred WiVRn route. The sounddevice route
    # remains usable without them. Check deliberately does not open/query audio
    # devices, load model weights, record, play, or launch an audio command.


def find_wivrn_node(kind):
    if kind not in ("sources", "sinks"):
        raise ValueError("Pulse node kind must be sources or sinks")
    command = shutil.which("pactl")
    if not command:
        return None
    try:
        result = subprocess.run(
            [command, "list", "short", kind], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", timeout=5,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) > 1 and "wivrn" in fields[1].lower():
            name = fields[1]
            if kind == "sources" and name.lower().endswith(".monitor"):
                continue
            return name
    return None


class VoiceOperation:
    """Track only children and audio capture started by this invocation."""
    def __init__(self):
        self.children = []
        self.sounddevice = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    @staticmethod
    def stop_child(process):
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            # A parent group signal may have already reaped the child. Do not
            # mask the original cancellation or device error during cleanup.
            pass

    @contextmanager
    def child(self, command, **kwargs):
        try:
            process = subprocess.Popen(command, shell=False, **kwargs)
        except OSError as exc:
            raise VoiceError("Cannot launch " + Path(command[0]).name + "; verify the local audio command is installed and executable.") from exc
        self.children.append(process)
        try:
            yield process
        finally:
            self.stop_child(process)
            self.children.remove(process)

    def run_process(self, command, input_text=None, timeout=90):
        with self.child(
            command, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="strict",
        ) as process:
            try:
                process.communicate(input=input_text, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise VoiceError(Path(command[0]).name + " timed out. Check the local audio device, then retry.") from exc
            if process.returncode:
                raise VoiceError(Path(command[0]).name + " failed. Check the local audio service and selected headset/output device.")

    def stop_capture(self):
        if self.sounddevice is not None:
            try:
                self.sounddevice.stop()
            except Exception:
                pass
            self.sounddevice = None

    def close(self):
        self.stop_capture()
        for process in reversed(self.children):
            self.stop_child(process)
        self.children.clear()


@contextmanager
def cancellation_signals():
    previous = {}
    cancelled = False

    def cancel(signum, frame):
        nonlocal cancelled
        if not cancelled:
            cancelled = True
            raise VoiceCancelled()
        # Repeated graceful signals must not interrupt the cleanup already in
        # progress. The parent can still force-kill its group after a grace period.

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, cancel)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def record_with_pulse(operation, path, source):
    command = require_commands("parecord")["parecord"]
    with operation.child(
        [command, "--device=" + source, "--rate=16000", "--channels=1",
         "--format=s16le", "--file-format=wav", str(path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ) as process:
        deadline = time.monotonic() + RECORD_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise VoiceError("The WiVRn microphone stopped recording. Enable its microphone in WiVRn, reconnect, and retry.")
            time.sleep(0.1)
        process.send_signal(signal.SIGINT)  # Finalize the WAV header.
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise VoiceError("The WiVRn recorder did not finish; reconnect its microphone and retry.") from exc


def record_with_sounddevice(operation, path):
    try:
        with redirect_stdout(sys.stderr):
            sd = importlib.import_module("sounddevice")
            np = importlib.import_module("numpy")
            operation.sounddevice = sd
            devices = sd.query_devices()
            selected = next((index for index, item in enumerate(devices)
                             if "wivrn" in item["name"].lower() and item["max_input_channels"]), None)
            if selected is None:
                selected = sd.default.device[0]
            if selected is None or selected < 0:
                raise VoiceError("No input microphone is available. Connect/enable the WiVRn microphone or choose a local default input.")
            audio = sd.rec(RECORD_SECONDS * SAMPLE_RATE, samplerate=SAMPLE_RATE,
                           channels=1, dtype="float32", device=selected)
            sd.wait()
            pcm = (np.clip(audio[:, 0], -1, 1) * 32767).astype("<i2")
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(SAMPLE_RATE)
                wav.writeframes(pcm.tobytes())
    except (VoiceError, VoiceCancelled):
        raise
    except Exception as exc:
        raise VoiceError("Cannot record the microphone. Check PortAudio/audio permissions and enable the WiVRn microphone or local default input.") from exc
    finally:
        operation.stop_capture()


def record_audio(operation, path, output):
    source = find_wivrn_node("sources")
    if source:
        require_commands("parecord")
        emit(output, "status", status="listening", message="Listening for 6 seconds on the WiVRn microphone.")
        # A failed selected headset capture is an error; do not silently switch
        # to a different microphone after the user has begun speaking.
        record_with_pulse(operation, path, source)
    else:
        emit(output, "status", status="listening", message="Listening for 6 seconds on the available local input.")
        record_with_sounddevice(operation, path)


def microphone_has_signal(path):
    try:
        with wave.open(str(path), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, SAMPLE_RATE):
                raise ValueError("unexpected audio format")
            frames = wav.getnframes()
            if not 0 < frames <= SAMPLE_RATE * RECORD_SECONDS * 2:
                raise ValueError("invalid recording length")
            samples = array("h", wav.readframes(frames))
            if sys.byteorder != "little":
                samples.byteswap()
        return bool(samples and max(abs(value) for value in samples) > 32)
    except (OSError, EOFError, ValueError, wave.Error) as exc:
        raise VoiceError("The microphone did not produce a valid local WAV recording. Check the input device and retry.") from exc


def transcribe_audio(path, model_path):
    try:
        with redirect_stdout(sys.stderr):
            backend = importlib.import_module("faster_whisper")
            model = backend.WhisperModel(str(model_path), device="cpu", compute_type="int8", local_files_only=True)
            segments, _ = model.transcribe(str(path), language="en", vad_filter=True)
            text = " ".join(segment.text.strip() for segment in segments).strip()
        if len(text) > MAX_TEXT_CHARS:
            raise VoiceError("Transcription was unexpectedly long. Record a shorter utterance and retry.")
        return text
    except (VoiceError, VoiceCancelled):
        raise
    except Exception as exc:
        raise VoiceError("Local transcription failed. Verify the complete cached base.en model and faster-whisper CPU dependencies; no download was attempted.") from exc


def record_action(work_dir, operation, output):
    require_modules()
    model_path = cached_model_path()
    with scratch_area(work_dir) as scratch:
        audio = scratch / "input.wav"
        record_audio(operation, audio, output)
        if not microphone_has_signal(audio):
            raise VoiceError("No microphone signal. Enable the microphone icon in WiVRn and reconnect, or check the local default input, then try again.")
        emit(output, "status", status="transcribing", message="Transcribing locally with cached Whisper base.en.")
        text = transcribe_audio(audio, model_path)
    emit(output, "status", status="ready", message="Speech captured." if text else "No speech recognized. Try another recording.")
    emit(output, "transcript", text=text)


def speak_action(work_dir, operation, output, text):
    text = validate_text(text)
    commands = require_commands("espeak-ng", "paplay")
    with scratch_area(work_dir) as scratch:
        speech = scratch / "speech.wav"
        sink = find_wivrn_node("sinks")
        emit(output, "status", status="speaking", message="Speaking through the WiVRn headset." if sink else "Speaking through the local default output.")
        operation.run_process(
            [commands["espeak-ng"], "--stdin", "-v", "en-us+f3", "-s", "168", "-w", str(speech)],
            input_text=text, timeout=90,
        )
        if not speech.is_file() or speech.stat().st_size <= 44:
            raise VoiceError("espeak-ng did not create speech audio. Check the local speech package and retry.")
        playback = [commands["paplay"]]
        if sink:
            playback.append("--device=" + sink)
        playback.append(str(speech))
        operation.run_process(playback, timeout=max(30, min(900, len(text) / 8 + 30)))
    emit(output, "status", status="ready", message="Local speech finished.")
    emit(output, "done")


def main(argv=None, stdin=None, stdout=None):
    source = sys.stdin if stdin is None else stdin
    output = sys.stdout if stdout is None else stdout
    try:
        parser = ProtocolParser(description=__doc__)
        parser.add_argument("--action", choices=("check", "record", "speak"), required=True)
        parser.add_argument("--work-dir", required=True)
        args = parser.parse_args(argv)
        directory = validate_work_dir(args.work_dir)
        with cancellation_signals(), VoiceOperation() as operation:
            if args.action == "check":
                check_dependencies()
                emit(output, "status", status="ready", message="Local voice dependencies and cached base.en are available. Microphone and playback have not been tested.")
            elif args.action == "record":
                record_action(directory, operation, output)
            else:
                text = source.read(MAX_TEXT_CHARS + 1)
                speak_action(directory, operation, output, text)
        return 0
    except (VoiceCancelled, KeyboardInterrupt):
        emit(output, "status", status="error", message="Voice operation cancelled.")
        return 130
    except (UnicodeError, VoiceError) as exc:
        message = str(exc) if isinstance(exc, VoiceError) else "Speech input must be valid UTF-8 text."
        emit(output, "status", status="error", message=message)
        return 2
    except Exception as exc:
        emit(output, "status", status="error", message="Local voice operation failed (" + type(exc).__name__ + "). Check the audio devices and cached voice dependencies.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
