"""NeonGrid-only client of the existing durable Camera to Blender API.

One explicit submit can issue one POST. Reconnecting with collect issues GETs
only. The camera application, its processes, and connected Blender scenes are
never modified by this client.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid

ART = Path.home() / '.local/share/hermes-whiskey-office/podium'
RUNS = ART / "photo-mesh"
# Office-port adaptation: Server records need not be on the office computer.
# The office broker never calls recover_binding or the standalone CLI.
DURABLE_RECORDS = ART / 'server-records-not-mounted'
API_BASE = os.environ.get("HERMES_OBJECT_STUDIO_URL", "http://127.0.0.1:8000").rstrip("/")
WATCH_BASE = os.environ.get("HERMES_OBJECT_STUDIO_URL", "http://127.0.0.1:8000").rstrip("/") + "/"
JOB_PATTERN = re.compile(r"[a-f0-9]{32}\Z")


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def save_json(path, value, exclusive=False):
    data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if exclusive:
        with path.open("xb") as stream:
            stream.write(data)
    else:
        pending = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        pending.write_bytes(data)
        # Windows readers/virus scanners can briefly deny replacement. Retry
        # only this atomic filesystem operation, never a generation request or
        # the exclusive attempt marker above. Preserve both files if it fails.
        for attempt in range(7):
            try:
                pending.replace(path)
                break
            except OSError as error:
                if getattr(error, "winerror", None) not in (5, 32, 33) or attempt == 6:
                    raise
                time.sleep(0.05 * 2**attempt)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_path(name, root=RUNS):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", name):
        raise ValueError("Use a short lowercase run name containing letters, digits, underscores or hyphens.")
    return root / name


def watch_url(job):
    if not JOB_PATTERN.fullmatch(job):
        raise ValueError("Invalid durable job identifier")
    return WATCH_BASE + "?job=" + job


def emit(**fields):
    print(json.dumps(fields, ensure_ascii=False), flush=True)


class Api:
    def __init__(self):
        # This driver addresses the configured Object Studio API directly, never a proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def binary(self, path, limit=256 * 1024 * 1024):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Only relative local API paths are allowed")
        with self.opener.open(API_BASE + path, timeout=35) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Response exceeds the expected artifact size")
        return data

    def get(self, path):
        return json.loads(self.binary(path, 4 * 1024 * 1024))

    def submit(self, manifest, image):
        boundary = "neongrid_" + uuid.uuid4().hex
        pieces = []
        for key, value in (("request_key", manifest["request_key"]), ("preset", manifest["preset"]), ("name", manifest["label"])):
            pieces.append(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + key + "\"\r\n\r\n" + value + "\r\n").encode())
        pieces.append(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"image\"; filename=\"" + manifest["input_file"] + "\"\r\nContent-Type: " + manifest["mime"] + "\r\n\r\n").encode())
        pieces.extend([image, ("\r\n--" + boundary + "--\r\n").encode()])
        request = urllib.request.Request(API_BASE + "/generate3d", data=b"".join(pieces), method="POST",
                                         headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
        # Deliberately no retry policy around this POST.
        with self.opener.open(request, timeout=45) as response:
            return json.loads(response.read(1024 * 1024))


def prepare(image_path, label, name, root=RUNS, preset="detailed"):
    if preset not in ("fast", "detailed"):
        raise ValueError("Choose the explicit fast or detailed preset")
    if not label.strip() or len(label) > 80 or any(ord(c) < 32 for c in label):
        raise ValueError("Supply a descriptive label of 1–80 characters without control characters")
    image_path = image_path.resolve(strict=True)
    if image_path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Input must be at most 20 MiB")
    data = image_path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        extension, mime = ".png", "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        extension, mime = ".jpg", "image/jpeg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        extension, mime = ".webp", "image/webp"
    else:
        raise ValueError("Input must be a PNG, JPEG, or WebP image")
    directory = run_path(name, root)
    directory.parent.mkdir(parents=True, exist_ok=True)
    # An existing directory is never reused for submission, even after failure.
    directory.mkdir()
    filename = "input" + extension
    (directory / filename).write_bytes(data)
    manifest = {"schema": 1, "created_at": now(), "label": label, "preset": preset,
                "api_base": API_BASE, "request_key": "neongrid:" + uuid.uuid4().hex,
                "input_file": filename, "input_sha256": sha256(data), "input_bytes": len(data),
                "source_path": str(image_path), "mime": mime,
                "isolation": "Direct /generate3d; no /isolate call. Trellis does local background preprocessing."}
    save_json(directory / "input-manifest.json", manifest, exclusive=True)
    emit(phase="prepared", directory=str(directory), input_sha256=manifest["input_sha256"])
    return directory


def bind_job(directory, job, origin):
    url = watch_url(job)
    path = directory / "job.json"
    if path.exists():
        if load_json(path)["job_id"] != job:
            raise ValueError("This run is already bound to another job")
    else:
        save_json(path, {"job_id": job, "bound_at": now(), "origin": origin,
                         "watch_url": url, "local_url": API_BASE + "/?job=" + job}, exclusive=True)
    emit(phase="bound", job_id=job, watch_url=url)
    return job


def recover_binding(directory, records=DURABLE_RECORDS, explicit_job=None):
    """Read-only reconciliation after the POST response was lost.

    Public job status intentionally omits request_key/input_hash. Match the
    existing local durable record exactly, instead of reposting to find its ID.
    """
    manifest = load_json(directory / "input-manifest.json")
    if explicit_job and not JOB_PATTERN.fullmatch(explicit_job):
        raise ValueError("Invalid explicit job identifier")
    paths = [records / (explicit_job + ".json")] if explicit_job else records.glob("*.json")
    matches = []
    for path in paths:
        try:
            record = load_json(path)
        except (OSError, ValueError):
            continue
        if record.get("deleted_at") or not JOB_PATTERN.fullmatch(str(record.get("id", ""))):
            continue
        if record.get("input_hash") != manifest["input_sha256"] or record.get("preset") != manifest["preset"]:
            continue
        if not explicit_job and record.get("request_key") != manifest["request_key"]:
            continue
        matches.append(record)
    if len(matches) != 1:
        raise RuntimeError("Submission is unresolved. No new POST was made. Inspect the saved attempt and existing Camera to Blender library; collect can be retried safely.")
    return bind_job(directory, matches[0]["id"], "Explicit verified durable record" if explicit_job else "Exact local request-key/hash reconciliation")


def submit_once(directory, api):
    manifest = load_json(directory / "input-manifest.json")
    if manifest["preset"] not in ("fast", "detailed"):
        raise ValueError("Saved preset is invalid; refusing submission")
    data = (directory / manifest["input_file"]).read_bytes()
    if sha256(data) != manifest["input_sha256"]:
        raise ValueError("Saved input changed; refusing submission")
    health = api.get("/health")
    save_json(directory / "health.json", health)
    if health.get("generation_backend") != "forge":
        raise RuntimeError("The live app is not using Forge. No submission was made.")
    listing = api.get("/api/jobs")
    busy = [{"job_id": job["id"], "stage": job.get("stage"), "watch_url": watch_url(job["id"])}
            for job in listing["jobs"] if job.get("status") == "processing"]
    save_json(directory / "preflight.json", {"checked_at": now(), "active_jobs": busy})
    if busy:
        save_json(directory / "submission.json", {"phase": "busy", "active_jobs": busy})
        emit(phase="busy", active_jobs=busy, message="No job submitted or interrupted. Leave the existing run to finish.")
        return None
    # Durable marker precedes the network mutation. Exclusive creation prevents
    # a second invocation from silently sending the same work again.
    save_json(directory / "submission-attempt.json", {"attempted_at": now(), "request_key": manifest["request_key"],
              "input_sha256": manifest["input_sha256"], "endpoint": "/generate3d", "preset": manifest["preset"]}, exclusive=True)
    try:
        result = api.submit(manifest, data)
        save_json(directory / "submission.json", {"phase": "accepted", "response": result})
        if result.get("backend") != "forge":
            raise RuntimeError("Unexpected backend response; inspect submission.json")
        return bind_job(directory, result["job_id"], "Direct submission response")
    except urllib.error.HTTPError as exc:
        detail = exc.read(8192).decode("utf-8", errors="replace")
        save_json(directory / "submission.json", {"phase": "rejected" if 400 <= exc.code < 500 else "uncertain",
                  "http_status": exc.code, "detail": detail, "request_key": manifest["request_key"]})
        raise RuntimeError("Submission returned HTTP " + str(exc.code) + ". No POST will be retried; use collect to reconcile any uncertain result. " + detail) from exc
    except Exception as exc:
        save_json(directory / "submission.json", {"phase": "uncertain", "error": str(exc), "request_key": manifest["request_key"]})
        raise RuntimeError("Submission response is uncertain. Input and attempt are saved. Use collect; do not submit again.") from exc


def save_artifact(directory, api, files, name, path, expected_bytes=None):
    target = directory / name
    previous = files.get(name)
    if previous and target.is_file() and sha256(target.read_bytes()) == previous["sha256"]:
        return
    data = api.binary(path, 256 * 1024 * 1024 if name == "final.glb" else 20 * 1024 * 1024)
    if expected_bytes is not None and len(data) != expected_bytes:
        raise ValueError("Incomplete artifact: " + name)
    if name.endswith(".glb"):
        if len(data) < 28 or data[:4] != b"glTF" or struct.unpack_from("<II", data, 4) != (2, len(data)):
            raise ValueError("Invalid or truncated GLB: " + name)
    elif not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid PNG response: " + name)
    pending = target.with_name(target.name + "." + uuid.uuid4().hex + ".part")
    pending.write_bytes(data)
    pending.replace(target)
    files[name] = {"api_path": path, "bytes": len(data), "sha256": sha256(data), "downloaded_at": now()}
    save_json(directory / "artifacts.json", files)
    emit(phase="artifact", name=name, bytes=len(data), sha256=files[name]["sha256"])


def collect(directory, api, wait=60, interval=3, records=DURABLE_RECORDS, explicit_job=None):
    manifest = load_json(directory / "input-manifest.json")
    if explicit_job or not (directory / "job.json").exists():
        job = recover_binding(directory, records, explicit_job)
    else:
        job = load_json(directory / "job.json")["job_id"]
    watch_url(job)  # Validate before constructing API routes.
    files_path = directory / "artifacts.json"
    files = load_json(files_path) if files_path.exists() else {}
    deadline = time.monotonic() + wait
    previous = None
    while True:
        state = api.get("/api/jobs/" + job)
        if state.get("id") != job:
            raise ValueError("Status response belongs to another job")
        if state.get("preset") != manifest["preset"]:
            raise ValueError("Status response has a different quality preset from the saved request")
        save_json(directory / "status.json", state)
        signature = (state["status"], state.get("stage"), sorted(state.get("checkpoints", {})))
        if signature != previous:
            progress = {"observed_at": now(), "job_id": job, "status": state["status"], "stage": state.get("stage"),
                        "elapsed_seconds": state.get("elapsed_seconds"), "checkpoints": signature[2]}
            with (directory / "progress.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(progress) + "\n")
            emit(**progress)
            previous = signature
        if state.get("photo_url"):
            save_artifact(directory, api, files, "normalized-input.png", "/api/jobs/" + job + "/photo")
        for checkpoint, filename in (("cutout", "cutout.png"), ("mesh", "surface.glb"), ("wire", "wireframe.glb")):
            info = state.get("checkpoints", {}).get(checkpoint)
            if info:
                save_artifact(directory, api, files, filename, "/api/jobs/" + job + "/checkpoints/" + checkpoint, info.get("bytes"))
        if state["status"] == "success":
            save_artifact(directory, api, files, "final.glb", "/local-models/" + job + ".glb", state.get("metrics", {}).get("bytes"))
        terminal = state["status"] in ("success", "failed", "cancelled")
        result = {"phase": "collected" if state["status"] == "success" else state["status"], "job_id": job, "preset": manifest["preset"],
                  "watch_url": watch_url(job), "directory": str(directory), "files": sorted(files),
                  "visual_quality_reviewed": False, "updated_at": now()}
        save_json(directory / "collection.json", result)
        if terminal or time.monotonic() >= deadline:
            emit(**result)
            return result
        time.sleep(min(interval, max(0, deadline - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    submit = actions.add_parser("submit", help="Create one fresh NeonGrid run and issue at most one generation POST")
    submit.add_argument("--image", required=True, type=Path)
    submit.add_argument("--label", required=True)
    submit.add_argument("--preset", choices=("fast", "detailed"), default="detailed",
                        help="Explicit quality choice; default detailed. Never changed automatically.")
    for action in (submit, actions.add_parser("collect", help="Reconcile/poll/download an existing run; never POST")):
        action.add_argument("--run", required=True)
        action.add_argument("--wait", type=float, default=60, help="Seconds of GET-only collection before returning")
    actions.choices["collect"].add_argument("--job-id", help="Explicit existing ID, verified against the local input hash and preset")
    args = parser.parse_args()
    if not 0 <= args.wait <= 1200:
        parser.error("--wait must be between 0 and 1200 seconds")
    api = Api()
    if args.action == "submit":
        directory = prepare(args.image, args.label, args.run, preset=args.preset)
        if submit_once(directory, api) is None:
            return 3
        result = collect(directory, api, args.wait)
    else:
        result = collect(run_path(args.run), api, args.wait, explicit_job=args.job_id)
    return 4 if result["phase"] in ("failed", "cancelled") else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        emit(phase="attention", error=str(error))
        raise SystemExit(2)
