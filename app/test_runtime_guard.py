"""Temporary fixture files and mocked Git only; no runtime, audio or network."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import runtime_guard as guard

NAVIGATION_RESULTS = {
    "navigate_tools": True, "navigate_skills": True, "navigate_mcp": True,
    "navigate_plugins": True, "navigate_settings": True, "navigate_artifacts": True,
    "navigate_new_session": True, "navigate_approvals": True,
    "tested_inputs_unchanged": True,
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RuntimeGuardTests(unittest.TestCase):
    def test_tui_deleted_after_acceptance_is_rejected(self):
        tui = self.root / 'run-hermes-tui.sh'
        tui.write_text('fixture')
        acceptance = {'sha256': {tui.name: digest(tui)}}
        self.assertIsNone(guard.check_plugins(self.root, acceptance))
        tui.unlink()
        with self.assertRaises(guard.RuntimeGuardError):
            guard.check_plugins(self.root, acceptance)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name).resolve()
        self.root = self.directory / "office"
        self.root.mkdir()
        self.source = self.directory / "vendor" / "hermes-pinned"
        self.binary = self.source / "apps/desktop/release/linux-unpacked/Hermes"
        self.asar = self.binary.parent / "resources/app.asar"
        self.asar.parent.mkdir(parents=True)
        self.binary.write_bytes(b"accepted desktop binary")
        self.asar.write_bytes(b"accepted application payload")
        self.receipt_path = self.source.parent / "hermes-build-receipt.json"
        self.receipt = {"status": "built", "source_commit": "a" * 40,
                        "source_dir": str(self.source), "binary": str(self.binary),
                        "binary_sha256": digest(self.binary), "app_asar_sha256": digest(self.asar)}
        self.acceptance = {"passed": True, "visual_review_passed": True,
                           "desktop_build": {"receipt_path": str(self.receipt_path),
                                             "source_commit": "a" * 40,
                                             "binary": str(self.binary), "app_asar": str(self.asar),
                                             "binary_sha256": digest(self.binary),
                                             "app_asar_sha256": digest(self.asar)}}
        self.save_receipt()
        self.save_acceptance()
        # No test is permitted to invoke a real Git process by accident.
        self.git_patch = patch.object(guard.subprocess, "run", return_value=SimpleNamespace(
            returncode=0, stdout="b" * 40 + "\n", stderr=""))
        self.git = self.git_patch.start()
        self.addCleanup(self.git_patch.stop)
        self.addCleanup(self.temp.cleanup)

    def save_receipt(self):
        self.receipt_path.write_text(json.dumps(self.receipt), encoding="utf-8")
        self.acceptance["desktop_build"]["receipt_sha256"] = digest(self.receipt_path)

    def save_acceptance(self):
        (self.root / "desktop-acceptance.json").write_text(json.dumps(self.acceptance), encoding="utf-8")

    def test_plugin_lock_rejects_changed_added_and_missing_plugins(self):
        home=self.directory/'home'
        plugin=home/'desktop-plugins/hermes-ssh/plugin.js'
        plugin.parent.mkdir(parents=True)
        plugin.write_bytes(b'accepted plugin')
        lock=self.root/'desktop-plugins-lock.json'
        lock.write_text(json.dumps({'plugins':{'hermes-ssh':digest(plugin)}}))
        acceptance={'sha256':{lock.name:digest(lock)}}
        with patch.dict(guard.os.environ, {'HERMES_HOME':str(home)}):
            self.assertIsNotNone(guard.check_plugins(self.root,acceptance))
            plugin.write_bytes(b'changed plugin')
            with self.assertRaisesRegex(guard.RuntimeGuardError,'changed'):
                guard.check_plugins(self.root,acceptance)
            plugin.write_bytes(b'accepted plugin')
            extra=home/'desktop-plugins/unreviewed/plugin.js'
            extra.parent.mkdir();extra.write_bytes(b'extra')
            with self.assertRaisesRegex(guard.RuntimeGuardError,'plugins changed'):
                guard.check_plugins(self.root,acceptance)
            extra.unlink();plugin.unlink()
            with self.assertRaisesRegex(guard.RuntimeGuardError,'plugins changed'):
                guard.check_plugins(self.root,acceptance)

    def rejects(self, message):
        with self.assertRaisesRegex(guard.RuntimeGuardError, message):
            guard.validate_runtime(self.root)

    def add_backend(self):
        backend = self.directory / "backend"
        python = backend / "venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"fixture, never execute")
        self.acceptance["backend_runtime"] = {
            "root": str(backend), "source_commit": "b" * 40, "python_path": str(python)}
        self.save_acceptance()
        return backend, python

    def add_navigation(self, *, supporting_files=True):
        names = ["hermes_navigation.py"]
        if supporting_files:
            names += ["desktop_bridge.py", "run-hermes-desktop.sh"]
        self.acceptance["sha256"] = {}
        for name in names:
            path = self.root / name
            path.write_bytes(b"raise AssertionError('fixture must never execute')\n")
            self.acceptance["sha256"][name] = digest(path)
        self.acceptance["checks"] = dict(NAVIGATION_RESULTS)
        self.save_acceptance()

    def test_accepted_build_passes_without_backend_process_or_writes(self):
        before = {str(p): p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        result = guard.validate_runtime(self.root)
        after = {str(p): p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(result["desktop_build"]["binary"], str(self.binary))
        self.git.assert_not_called()

    def test_acceptance_flags_require_boolean_true(self):
        for key in ("passed", "visual_review_passed"):
            for value in (False, None, 1, "true"):
                with self.subTest(key=key, value=value):
                    self.acceptance[key] = value
                    self.save_acceptance()
                    self.rejects("has not passed|have not passed")
            self.acceptance[key] = True

    def test_missing_or_malformed_acceptance(self):
        path = self.root / "desktop-acceptance.json"
        for content in ("{bad", "[]", "null", "\ufffd"):
            with self.subTest(content=content):
                path.write_text(content, encoding="utf-8")
                self.rejects("JSON|object")
        path.unlink()
        self.rejects("missing")

    def test_acceptance_size_is_bounded(self):
        (self.root / "desktop-acceptance.json").write_bytes(b" " * (guard.MAX_RECEIPT_BYTES + 1))
        self.rejects("too large")

    def test_missing_desktop_metadata_does_not_pass(self):
        self.acceptance.pop("desktop_build")
        self.save_acceptance()
        self.rejects("metadata is missing")

    def test_receipt_changes_are_detected_before_parsing(self):
        self.receipt_path.write_text("not the accepted receipt", encoding="utf-8")
        self.rejects("receipt changed")

    def test_receipt_status_and_commit_must_match(self):
        for field, value, message in (("status", "building", "not marked built"),
                                      ("source_commit", "c" * 40, "commit differs")):
            with self.subTest(field=field):
                original = self.receipt[field]
                self.receipt[field] = value
                self.save_receipt()
                self.save_acceptance()
                self.rejects(message)
                self.receipt[field] = original

    def test_binary_and_asar_content_changes_are_detected(self):
        for path in (self.binary, self.asar):
            with self.subTest(path=path.name):
                content = path.read_bytes()
                path.write_bytes(b"updated after acceptance")
                self.rejects("changed since acceptance")
                path.write_bytes(content)

    def test_payload_hash_must_match_receipt_even_if_file_matches_acceptance(self):
        self.asar.write_bytes(b"replacement payload")
        self.acceptance["desktop_build"]["app_asar_sha256"] = digest(self.asar)
        self.save_acceptance()
        self.rejects("hash differs")

    def test_invalid_hash_and_commit_values(self):
        metadata = self.acceptance["desktop_build"]
        for key, invalid, message in (("receipt_sha256", "x" * 64, "SHA-256"),
                                      ("source_commit", "main", "commit is invalid")):
            with self.subTest(key=key):
                original = metadata[key]
                metadata[key] = invalid
                self.save_acceptance()
                self.rejects(message)
                metadata[key] = original

    def test_absolute_paths_and_expected_payload_layout_required(self):
        metadata = self.acceptance["desktop_build"]
        for key, value, message in (("receipt_path", "relative.json", "absolute"),
                                    ("binary", str(self.directory / "Hermes"), "build layout"),
                                    ("app_asar", str(self.directory / "app.asar"), "build layout")):
            with self.subTest(key=key):
                original = metadata[key]
                metadata[key] = value
                self.save_acceptance()
                self.rejects(message)
                metadata[key] = original
        with self.assertRaisesRegex(guard.RuntimeGuardError, "absolute"):
            guard.validate_runtime("relative-office")

    def test_missing_and_redirected_payloads_fail(self):
        self.asar.unlink()
        self.rejects("missing")
        elsewhere = self.directory / "redirected-payload"
        elsewhere.write_bytes(b"accepted application payload")
        try:
            self.asar.symlink_to(elsewhere)
        except OSError:
            self.skipTest("Symlink creation unavailable for this user")
        self.rejects("redirected")

    def test_navigation_acceptance_binds_all_shipped_files_without_execution_or_writes(self):
        self.add_navigation()
        before = {str(p): p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        result = guard.validate_runtime(self.root)
        after = {str(p): p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(result["navigation"]["sha256"], self.acceptance["sha256"])
        self.git.assert_not_called()

    def test_navigation_requires_accepted_hashes(self):
        self.add_navigation()
        accepted = dict(self.acceptance["sha256"])
        for invalid in (None, [], {}, {"hermes_navigation.py": "not-a-sha256"}):
            with self.subTest(hashes=invalid):
                self.acceptance["sha256"] = invalid
                self.save_acceptance()
                self.rejects("accepted file hashes|accepted SHA-256")
        self.acceptance["sha256"] = accepted
        for name in accepted:
            with self.subTest(missing_hash=name):
                self.acceptance["sha256"] = {key: value for key, value in accepted.items() if key != name}
                self.save_acceptance()
                self.rejects("accepted SHA-256")

    def test_navigation_and_supporting_file_drift_is_rejected(self):
        self.add_navigation()
        for name in self.acceptance["sha256"]:
            with self.subTest(file=name):
                path = self.root / name
                content = path.read_bytes()
                path.write_bytes(content + b"# changed after acceptance\n")
                self.rejects("changed since acceptance")
                path.write_bytes(content)

    def test_recorded_navigation_and_supporting_files_cannot_be_removed(self):
        self.add_navigation()
        for name in self.acceptance["sha256"]:
            with self.subTest(file=name):
                path = self.root / name
                content = path.read_bytes()
                path.unlink()
                self.rejects("missing, unreadable or redirected")
                path.write_bytes(content)

    def test_navigation_only_release_allows_absent_optional_files_but_rejects_unaccepted_additions(self):
        self.add_navigation(supporting_files=False)
        self.assertEqual(set(guard.validate_runtime(self.root)["navigation"]["sha256"]),
                         {"hermes_navigation.py"})
        for name in ("desktop_bridge.py", "run-hermes-desktop.sh"):
            with self.subTest(file=name):
                path = self.root / name
                path.write_bytes(b"unaccepted supporting file")
                self.rejects("accepted SHA-256")
                path.unlink()

    def test_each_navigation_result_must_be_present_and_boolean_true(self):
        self.add_navigation()
        routes = [name for name in NAVIGATION_RESULTS if name.startswith("navigate_")]
        self.assertEqual(len(routes), 8)
        for name in routes:
            for value in (False, None, 1, "true"):
                with self.subTest(result=name, value=value):
                    self.acceptance["checks"][name] = value
                    self.save_acceptance()
                    self.rejects("has not passed " + name.removeprefix("navigate_"))
            with self.subTest(missing_result=name):
                self.acceptance["checks"].pop(name)
                self.save_acceptance()
                self.rejects("has not passed " + name.removeprefix("navigate_"))
            self.acceptance["checks"][name] = True

    def test_navigation_result_collection_must_be_an_object(self):
        self.add_navigation()
        for value in (None, [], True):
            with self.subTest(value=value):
                self.acceptance["checks"] = value
                self.save_acceptance()
                self.rejects("acceptance results are missing")

    def test_navigation_requires_unchanged_acceptance_inputs(self):
        self.add_navigation()
        for value in (False, None, 1, "true"):
            with self.subTest(value=value):
                self.acceptance["checks"]["tested_inputs_unchanged"] = value
                self.save_acceptance()
                self.rejects("did not verify unchanged inputs")
        self.acceptance["checks"].pop("tested_inputs_unchanged")
        self.save_acceptance()
        self.rejects("did not verify unchanged inputs")

    def test_legacy_release_without_navigation_keeps_existing_checks(self):
        # Previous reports recorded bridge/launcher hashes without binding them.
        self.acceptance["sha256"] = {"desktop_bridge.py": "0" * 64}
        (self.root / "desktop_bridge.py").write_bytes(b"legacy bridge")
        (self.root / "run-hermes-desktop.sh").write_bytes(b"legacy launcher")
        self.save_acceptance()
        self.assertNotIn("navigation", guard.validate_runtime(self.root))

    def test_guard_is_not_a_circular_acceptance_input(self):
        self.add_navigation()
        path = self.root / "runtime_guard.py"
        path.write_bytes(b"old guard fixture")
        self.acceptance["sha256"][path.name] = digest(path)
        self.save_acceptance()
        path.write_bytes(b"updated guard fixture")
        self.assertNotIn(path.name, guard.validate_runtime(self.root)["navigation"]["sha256"])

    def test_redirected_navigation_file_is_rejected(self):
        self.add_navigation(supporting_files=False)
        path = self.root / "hermes_navigation.py"
        elsewhere = self.directory / "redirected-navigation.py"
        elsewhere.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(elsewhere)
        except OSError:
            self.skipTest("Symlink creation unavailable for this user")
        self.rejects("redirected")

    def test_optional_backend_checks_only_git_head_and_python_file(self):
        backend, python = self.add_backend()
        with patch.dict(guard.os.environ, {"GIT_DIR": "unrelated", "GIT_WORK_TREE": "elsewhere"}):
            result = guard.validate_runtime(self.root)
        self.assertEqual(result["backend_runtime"]["python_path"], str(python))
        args, kwargs = self.git.call_args
        self.assertEqual(args[0], ["git", "-C", str(backend), "rev-parse", "HEAD"])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 10)
        self.assertNotIn("GIT_DIR", kwargs["env"])
        self.assertNotIn("GIT_WORK_TREE", kwargs["env"])
        self.assertEqual(kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")

    def test_optional_backend_revision_mismatch(self):
        self.add_backend()
        self.git.return_value.stdout = "c" * 40 + "\n"
        self.rejects("backend changed")

    def test_backend_missing_python_fails_before_git(self):
        _, python = self.add_backend()
        python.unlink()
        self.rejects("Python is missing")
        self.git.assert_not_called()

    def test_backend_metadata_types_and_paths(self):
        self.acceptance["backend_runtime"] = None
        self.save_acceptance()
        self.rejects("must be an object")
        self.add_backend()
        for key, value in (("root", "relative"), ("python_path", "relative"),
                           ("source_commit", "main")):
            with self.subTest(key=key):
                metadata = self.acceptance["backend_runtime"]
                original = metadata[key]
                metadata[key] = value
                self.save_acceptance()
                self.rejects("absolute|commit is invalid")
                metadata[key] = original

    def test_git_errors_are_concise_and_never_expose_output(self):
        self.add_backend()
        for exception in (OSError("sensitive diagnostic"),
                          subprocess.TimeoutExpired(["git"], 10)):
            with self.subTest(exception=type(exception).__name__):
                self.git.side_effect = exception
                self.rejects("revision could not be checked")
        self.git.side_effect = None
        self.git.return_value = SimpleNamespace(returncode=1, stdout="", stderr="sensitive diagnostic")
        self.rejects("revision could not be checked")

    def test_cli_exit_codes_and_default_directory(self):
        output, errors = io.StringIO(), io.StringIO()
        self.assertEqual(guard.main(["--root", str(self.root)], stdout=output, stderr=errors), 0)
        self.assertIn("verified", output.getvalue())
        self.assertEqual(errors.getvalue(), "")
        self.acceptance["passed"] = False
        self.save_acceptance()
        self.assertEqual(guard.main(["--root", str(self.root)], stdout=output, stderr=errors), 2)
        self.assertIn("has not passed", errors.getvalue())
        with patch.object(guard, "validate_runtime", return_value={"desktop_build": {}}) as check:
            self.assertEqual(guard.main([], stdout=output, stderr=errors), 0)
            check.assert_called_once_with(str(guard.ROOT))


if __name__ == "__main__":
    unittest.main()
