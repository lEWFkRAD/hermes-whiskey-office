"""Read-only startup check of the desktop accepted for this office release.

No app/model startup, updater, network or config/database access.
The caller must launch the returned accepted paths, not an unrelated override.
Wrist navigation releases also bind their navigation, bridge and launcher files
to the successful desktop acceptance run. Older releases without navigation
retain their existing desktop/build checks.
Optional backend checking establishes Git HEAD and Python availability only;
it does not attest uncommitted changes, dependencies, configuration or a database.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
MAX_RECEIPT_BYTES = 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
NAVIGATION_CHECKS = (
    "navigate_tools", "navigate_skills", "navigate_mcp", "navigate_plugins",
    "navigate_settings", "navigate_artifacts", "navigate_new_session", "navigate_approvals",
)
NAVIGATION_FILES = (
    ("hermes_navigation.py", "Wrist navigation"),
    ("desktop_bridge.py", "Desktop bridge"),
    ("run-hermes-desktop.sh", "Desktop launcher"),
    ("office_workspace.py", "Office workspace instructions"),
)


class RuntimeGuardError(RuntimeError):
    """A concise user-facing reason to keep the live integration disabled."""


def require(condition, message):
    if not condition:
        raise RuntimeGuardError(message)


def absolute_path(value, label):
    require(isinstance(value, (str, Path)) and bool(str(value))
            and "\0" not in str(value), label + " path is missing or invalid.")
    path = Path(value)
    require(path.is_absolute() and ".." not in path.parts,
            label + " must use an absolute path without parent traversal.")
    return path


def regular_path(path, label, *, directory=False, allow_symlink=False):
    try:
        exists = path.is_dir() if directory else path.is_file()
        # Build evidence and payloads cannot be redirected after acceptance.
        # Backend Python may be a normal virtualenv symlink.
        redirected = not allow_symlink and any(p.is_symlink() for p in (path, *path.parents))
    except (OSError, ValueError):
        exists, redirected = False, False
    require(exists and not redirected, label + " is missing, unreadable or redirected.")
    return path


def read_report(path, label):
    regular_path(path, label)
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_RECEIPT_BYTES + 1)
        require(len(data) <= MAX_RECEIPT_BYTES, label + " is too large.")
        report = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise RuntimeGuardError(label + " is unreadable or invalid JSON.") from None
    require(isinstance(report, dict), label + " must contain a JSON object.")
    return report


def verify_hash(path, expected, label):
    require(isinstance(expected, str) and SHA256.fullmatch(expected) is not None,
            label + " has no valid accepted SHA-256.")
    regular_path(path, label)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise RuntimeGuardError(label + " cannot be read.") from None
    require(digest.hexdigest() == expected,
            label + " changed since acceptance. Re-run desktop acceptance before using it.")


def check_desktop(metadata):
    require(isinstance(metadata, dict), "Accepted pinned desktop metadata is missing.")
    receipt_path = absolute_path(metadata.get("receipt_path"), "Desktop build receipt")
    verify_hash(receipt_path, metadata.get("receipt_sha256"), "Desktop build receipt")
    receipt = read_report(receipt_path, "Desktop build receipt")
    require(receipt.get("status") == "built", "The accepted desktop build is not marked built.")
    commit = metadata.get("source_commit")
    require(isinstance(commit, str) and COMMIT.fullmatch(commit) is not None,
            "Accepted desktop source commit is invalid.")
    require(receipt.get("source_commit") == commit,
            "Desktop source commit differs from its accepted build receipt.")
    source = absolute_path(receipt.get("source_dir"), "Desktop source")
    regular_path(source, "Desktop source", directory=True)
    binary = absolute_path(metadata.get("binary"), "Desktop executable")
    require(binary.name in {"Hermes", "hermes"}
            and binary.parent == source / "apps/desktop/release/linux-unpacked",
            "Desktop executable is outside its accepted build layout.")
    require(absolute_path(receipt.get("binary"), "Build receipt executable") == binary,
            "Desktop executable differs from its accepted build receipt.")
    asar = absolute_path(metadata.get("app_asar"), "Desktop application payload")
    require(asar == binary.parent / "resources/app.asar",
            "Desktop application payload is outside its accepted build layout.")
    for path, key, label in (
        (binary, "binary_sha256", "Desktop executable"),
        (asar, "app_asar_sha256", "Desktop application payload"),
    ):
        require(metadata.get(key) == receipt.get(key),
                label + " hash differs from its accepted build receipt.")
        verify_hash(path, metadata.get(key), label)
    return {"source_commit": commit, "binary": str(binary), "app_asar": str(asar),
            "receipt_path": str(receipt_path)}


def check_backend(metadata):
    require(isinstance(metadata, dict), "Accepted backend runtime metadata must be an object.")
    root = absolute_path(metadata.get("root"), "Hermes backend")
    regular_path(root, "Hermes backend", directory=True)
    python_path = absolute_path(metadata.get("python_path"), "Hermes backend Python")
    regular_path(python_path, "Hermes backend Python", allow_symlink=True)
    commit = metadata.get("source_commit")
    require(isinstance(commit, str) and COMMIT.fullmatch(commit) is not None,
            "Accepted Hermes backend commit is invalid.")
    # A caller's Git environment must not redirect rev-parse away from -C root.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=10, shell=False, env=env)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeGuardError("Hermes backend revision could not be checked. Check Git and re-run acceptance.") from None
    require(result.returncode == 0,
            "Hermes backend revision could not be checked. Re-run acceptance.")
    require(result.stdout.strip() == commit,
            "Hermes backend changed since acceptance. Re-run acceptance before connecting.")
    return {"root": str(root), "source_commit": commit, "python_path": str(python_path)}


def check_navigation(root, acceptance):
    """Bind navigation checks to shipped code, without importing that code.

    A recorded navigation hash opts a release in even if the file was removed.
    Legacy acceptance reports may contain bridge/launcher hashes alone; those
    releases keep their original checks until a navigation module is shipped.
    """
    hashes = acceptance.get("sha256")
    navigation = root / "hermes_navigation.py"
    if not (navigation.exists() or navigation.is_symlink()
            or (isinstance(hashes, dict) and navigation.name in hashes)):
        return None
    require(isinstance(hashes, dict), "Wrist navigation has no accepted file hashes.")
    verified = {}
    for name, label in NAVIGATION_FILES:
        path = root / name
        # Optional supporting files become required once present or recorded.
        # This also detects a deleted file or a broken symlink after acceptance.
        if name == navigation.name or path.exists() or path.is_symlink() or name in hashes:
            verify_hash(path, hashes.get(name), label)
            verified[name] = hashes[name]
    checks = acceptance.get("checks")
    require(isinstance(checks, dict), "Wrist navigation acceptance results are missing.")
    for name in NAVIGATION_CHECKS:
        require(checks.get(name) is True,
                "Wrist navigation acceptance has not passed " + name.removeprefix("navigate_")
                + ". Re-run desktop acceptance before using it.")
    require(checks.get("tested_inputs_unchanged") is True,
            "Wrist navigation acceptance did not verify unchanged inputs. Re-run desktop acceptance.")
    return {"sha256": verified}


def check_plugins(root, acceptance):
    # New releases use the accepted backend for TUI as well as Desktop.
    tui = root / 'run-hermes-tui.sh'
    hashes = acceptance.get('sha256', {})
    if tui.exists() or tui.is_symlink() or (isinstance(hashes, dict) and tui.name in hashes):
        require(isinstance(hashes, dict), 'TUI launcher has no accepted file hashes.')
        verify_hash(tui, hashes.get(tui.name), 'TUI launcher')
    lock = root / 'desktop-plugins-lock.json'
    hashes = acceptance.get('sha256', {})
    if not lock.exists() and lock.name not in hashes:
        return None
    verify_hash(lock, hashes.get(lock.name), 'Desktop plugin lock')
    manifest = read_report(lock, 'Desktop plugin lock')
    directory = Path(os.environ.get('HERMES_HOME', str(Path.home()/'.hermes'))) / 'desktop-plugins'
    regular_path(directory, 'Desktop plugin directory', directory=True)
    expected = manifest.get('plugins')
    require(isinstance(expected, dict) and expected, 'Desktop plugin lock is empty or invalid.')
    observed = {p.parent.name for p in directory.glob('*/plugin.js')}
    require(observed == set(expected), 'Desktop plugins changed. Stage and accept the new plugin set before opening the office.')
    for name, digest in expected.items():
        require(isinstance(name, str) and re.fullmatch(r'[a-zA-Z0-9_-]+', name) is not None,
                'Desktop plugin lock contains an invalid ID.')
        verify_hash(directory/name/'plugin.js', digest, 'Desktop plugin '+name)
    return {'plugins': expected}


def validate_runtime(root=ROOT):
    """Return accepted launch paths, or raise RuntimeGuardError; never write files."""
    root = absolute_path(root, "Office root")
    regular_path(root, "Office root", directory=True)
    acceptance = read_report(root / "desktop-acceptance.json", "Desktop acceptance")
    require(acceptance.get("passed") is True, "Desktop acceptance has not passed.")
    require(acceptance.get("visual_review_passed") is True,
            "Desktop screenshots have not passed visual review.")
    verified = {"desktop_build": check_desktop(acceptance.get("desktop_build"))}
    navigation = check_navigation(root, acceptance)
    if navigation is not None:
        verified["navigation"] = navigation
    if "backend_runtime" in acceptance:
        verified["backend_runtime"] = check_backend(acceptance["backend_runtime"])
    plugins = check_plugins(root, acceptance)
    if plugins is not None:
        verified['desktop_plugins'] = plugins
    return verified


def main(argv=None, *, stdout=None, stderr=None):
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT), help="Absolute office app directory")
    args = parser.parse_args(argv)
    try:
        result = validate_runtime(args.root)
    except RuntimeGuardError as exc:
        print("Hermes office runtime check: " + str(exc), file=stderr)
        return 2
    detail = "Accepted desktop build verified"
    if "backend_runtime" in result:
        detail += "; backend revision and Python path verified"
    if "navigation" in result:
        detail += "; wrist navigation files and acceptance checks verified"
    print(detail + ".", file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
