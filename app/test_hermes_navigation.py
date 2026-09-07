"""Pure fixtures/mocks only: never connects to DBus or clicks a real desktop."""

from dataclasses import replace
import json
import os
import subprocess
import types
import unittest
from unittest.mock import Mock, patch

import hermes_navigation as nav


PID = 321


class Tree:
    def __init__(self):
        self.nodes = [nav.Node((0,), None, PID, "application")]
        self.window = self.add("", "frame", (0,))
        self.document = self.add("", "document-web", self.window.key)

    def add(self, name, role=nav.BUTTON, parent=None, **kwargs):
        parent = self.document.key if parent is None else parent
        key = parent + (len(self.nodes),)
        item = nav.Node(key, parent, PID, role, name, True, True, True, True, **kwargs)
        self.nodes.append(item)
        return item

    def sidebar(self):
        group = self.add("", "list")
        result = {}
        for label in ("New session Ctrl N", "Capabilities", "Messaging", "Artifacts", "Scheduled jobs"):
            row = self.add("", "list-item", group.key)
            result[label] = self.add(label, parent=row.key)
        return result

    def tabs(self, labels=("Skills 42", "Tools1.2k", "MCP")):
        group = self.add("", "section")
        return [self.add(label, parent=group.key) for label in labels]

    def settings(self, parent=None):
        self.add("Close settings", parent=parent)
        group = self.add("", "landmark", parent=parent)
        return [self.add(label, parent=group.key) for label in
                ("Providers", "Gateways", "Keyboard Shortcuts", "Plugins", "Tools & Keys")]

    def snapshot(self):
        return nav.Snapshot(PID, tuple(self.nodes))


class PlanningTests(unittest.TestCase):
    def test_dictation_selects_draft_recording_without_starting_a_call(self):
        tree = Tree()
        tree.add('Start voice conversation')
        dictate = tree.add('Voice dictation')
        self.assertEqual(nav.plan_action('dictate', PID, tree.snapshot()).node, dictate)
        tree.add('Stop dictation')
        self.assertEqual(nav.plan_action('dictate', PID, tree.snapshot()).kind, 'done')
        self.assertEqual(nav.plan_action('end_voice', PID, tree.snapshot()).node.name, 'Stop dictation')

    def test_voice_start_does_not_toggle_or_restart_active_call(self):
        tree = Tree()
        button = tree.add('Start voice conversation')
        self.assertEqual(nav.plan_action('voice', PID, tree.snapshot()).node, button)
        tree.add('End voice conversation')
        self.assertEqual(nav.plan_action('voice', PID, tree.snapshot()).kind, 'done')
        self.assertEqual(nav.plan_action('dictate', PID, tree.snapshot()).label, 'end_active_call')
        self.assertEqual(nav.plan_action('dictate', PID, tree.snapshot(), ('end_active_call',)).kind, 'wait')

    def test_end_voice_never_starts_a_microphone(self):
        tree = Tree()
        tree.add('Start voice conversation')
        self.assertEqual(nav.plan_action('end_voice', PID, tree.snapshot()).kind, 'guidance')
        end = tree.add('End voice conversation')
        self.assertEqual(nav.plan_action('end_voice', PID, tree.snapshot()).node, end)
        self.assertEqual(nav.plan_action('end_voice', PID, tree.snapshot(), ('end_voice',)).kind, 'done')

    def test_voice_ambiguous_or_modal_controls_fail(self):
        tree = Tree()
        tree.add('Start voice conversation')
        tree.add('Start voice conversation')
        with self.assertRaises(nav.HermesNavigationError):
            nav.plan_action('voice', PID, tree.snapshot())
        tree = Tree()
        tree.add('Start voice conversation')
        tree.add('Permission', role='dialog', modal=True)
        with self.assertRaises(nav.HermesNavigationError):
            nav.plan_action('voice', PID, tree.snapshot())

    def test_caps_first_then_fresh_tab(self):
        tree = Tree()
        sidebar = tree.sidebar()
        first = nav.plan_action("tools", PID, tree.snapshot())
        self.assertEqual((first.label, first.node), ("capabilities", sidebar["Capabilities"]))
        tabs = tree.tabs()
        second = nav.plan_action("tools", PID, tree.snapshot(), ("capabilities",))
        self.assertEqual((second.label, second.node), ("tools", tabs[1]))

    def test_caps_tabs_are_buttons_not_aria_tabs(self):
        for destination, index in (("skills", 0), ("tools", 1), ("mcp", 2)):
            with self.subTest(destination=destination):
                tree = Tree()
                tabs = tree.tabs()
                self.assertEqual(nav.plan_action(destination, PID, tree.snapshot()).node, tabs[index])

    def test_bad_count_suffix_does_not_match(self):
        tree = Tree()
        tree.tabs(("Skills 42", "Tools dangerous", "MCP"))
        with self.assertRaisesRegex(nav.HermesNavigationError, "sidebar"):
            nav.plan_action("tools", PID, tree.snapshot())

    def test_no_second_blind_click_while_caps_loading(self):
        tree = Tree()
        tree.sidebar()
        plan = nav.plan_action("tools", PID, tree.snapshot(), ("capabilities",))
        self.assertEqual(plan.kind, "wait")
        self.assertIsNone(plan.node)

    def test_identically_named_chat_button_is_not_sidebar(self):
        tree = Tree()
        for label in ("Capabilities", "Messaging", "Artifacts", "Scheduled jobs"):
            tree.add(label)  # not the actual ul navigation group
        with self.assertRaisesRegex(nav.HermesNavigationError, "sidebar"):
            nav.plan_action("artifacts", PID, tree.snapshot())

    def test_caps_names_spread_across_document_are_not_group(self):
        tree = Tree()
        for label in ("Skills", "Tools", "MCP"):
            tree.add(label)
        with self.assertRaises(nav.HermesNavigationError):
            nav.plan_action("mcp", PID, tree.snapshot())

    def test_duplicate_scoped_button_or_group_fails(self):
        tree = Tree()
        tabs = tree.tabs()
        tree.add("Tools 0", parent=tabs[1].parent)
        with self.assertRaisesRegex(nav.HermesNavigationError, "multiple visible"):
            nav.plan_action("tools", PID, tree.snapshot())
        tree = Tree()
        tree.tabs()
        tree.tabs()
        with self.assertRaisesRegex(nav.HermesNavigationError, "Multiple Hermes"):
            nav.plan_action("tools", PID, tree.snapshot())

    def test_hidden_duplicate_ignored_but_disabled_duplicate_rejected(self):
        tree = Tree()
        node = tree.add("Open settings")
        tree.nodes.append(replace(node, key=node.key + (9,), visible=False))
        self.assertEqual(nav.plan_action("settings", PID, tree.snapshot()).node, node)
        tree.nodes[-1] = replace(tree.nodes[-1], visible=True, enabled=False)
        with self.assertRaisesRegex(nav.HermesNavigationError, "multiple visible"):
            nav.plan_action("settings", PID, tree.snapshot())

    def test_disabled_hidden_and_wrong_role_are_never_clicked(self):
        for changes in ({"enabled": False}, {"sensitive": False}, {"visible": False},
                        {"showing": False}, {"defunct": True}, {"role": "text"}):
            with self.subTest(changes=changes):
                tree = Tree()
                tree.add("Open settings")
                tree.nodes[-1] = replace(tree.nodes[-1], **changes)
                with self.assertRaises(nav.HermesNavigationError):
                    nav.plan_action("settings", PID, tree.snapshot())

    def test_plugin_settings_two_step_and_existing_settings(self):
        tree = Tree()
        node = tree.add("Open settings")
        first = nav.plan_action("plugins", PID, tree.snapshot())
        self.assertEqual((first.node, first.label), (node, "open_settings"))
        tree = Tree()
        plugins = tree.settings()[3]
        self.assertEqual(nav.plan_action("plugins", PID, tree.snapshot()).node, plugins)
        self.assertEqual(nav.plan_action("settings", PID, tree.snapshot()).kind, "done")

    def test_plugins_without_settings_scope_rejected(self):
        tree = Tree()
        tree.add("Close settings")
        tree.add("Plugins")
        with self.assertRaisesRegex(nav.HermesNavigationError, "Settings navigation"):
            nav.plan_action("plugins", PID, tree.snapshot())

    def test_settings_dismissed_before_background_navigation(self):
        tree = Tree()
        tree.sidebar()
        tree.settings()
        for destination in ("tools", "skills", "mcp", "artifacts", "new_session"):
            with self.subTest(destination=destination):
                plan = nav.plan_action(destination, PID, tree.snapshot())
                self.assertEqual((plan.label, plan.node.name), ("close_settings", "Close settings"))

    def test_settings_close_is_not_repeated_and_requires_full_scope(self):
        tree = Tree()
        tree.sidebar()
        tree.settings()
        self.assertEqual(nav.plan_action("tools", PID, tree.snapshot(), ("close_settings",)).kind, "wait")
        tree = Tree()
        tree.sidebar()
        tree.add("Close settings")
        with self.assertRaisesRegex(nav.HermesNavigationError, "identified completely"):
            nav.plan_action("tools", PID, tree.snapshot())

    def test_owned_settings_modal_allowed_only_with_contained_signature(self):
        tree = Tree()
        dialog = tree.add("", "dialog", modal=True)
        tree.settings(dialog.key)
        self.assertEqual(nav.plan_action("plugins", PID, tree.snapshot()).label, "plugins")
        self.assertEqual(nav.plan_action("tools", PID, tree.snapshot()).label, "close_settings")
        self.assertEqual(nav.plan_action("settings", PID, tree.snapshot()).kind, "done")
        tree.add("", "dialog", parent=dialog.key, modal=True)
        for destination in ("plugins", "settings", "tools"):
            with self.assertRaisesRegex(nav.HermesNavigationError, "dialog"):
                nav.plan_action(destination, PID, tree.snapshot())

    def test_unrelated_or_partially_scoped_settings_dialog_blocked(self):
        tree = Tree()
        tree.settings()
        tree.add("", "dialog", modal=True)
        with self.assertRaisesRegex(nav.HermesNavigationError, "dialog"):
            nav.plan_action("tools", PID, tree.snapshot())
        tree = Tree()
        dialog = tree.add("", "dialog", modal=True)
        tree.add("Close settings", parent=dialog.key)
        group = tree.add("", "landmark")
        for label in nav.SETTINGS_NAV_LABELS:
            tree.add(label, parent=group.key)
        with self.assertRaisesRegex(nav.HermesNavigationError, "dialog"):
            nav.plan_action("plugins", PID, tree.snapshot())

    def test_approvals_in_settings_gives_guidance_without_background_jump(self):
        tree = Tree()
        tree.settings()
        tree.add("Approval needed")
        self.assertEqual(nav.plan_action("approvals", PID, tree.snapshot()).kind, "guidance")

    def test_artifacts_and_new_session_use_real_sidebar(self):
        tree = Tree()
        controls = tree.sidebar()
        for destination, label in (("artifacts", "Artifacts"), ("new_session", "New session Ctrl N")):
            self.assertEqual(nav.plan_action(destination, PID, tree.snapshot()).node, controls[label])

    def test_unrecognized_new_session_suffix_not_guessed(self):
        tree = Tree()
        controls = tree.sidebar()
        original = controls["New session Ctrl N"]
        tree.nodes[tree.nodes.index(original)] = replace(original, name="New session: delete everything")
        with self.assertRaises(nav.HermesNavigationError):
            nav.plan_action("new_session", PID, tree.snapshot())

    def test_approvals_only_known_navigation_button(self):
        tree = Tree()
        for label in ("Allow once", "Always allow", "Approve", "Reject", "Deny", "Cancel"):
            tree.add(label)
        self.assertEqual(nav.plan_action("approvals", PID, tree.snapshot()).kind, "guidance")
        jump = tree.add("Approval needed")
        plan = nav.plan_action("approvals", PID, tree.snapshot())
        self.assertEqual((plan.kind, plan.node), ("click", jump))

    def test_ambiguous_approval_navigation_fails(self):
        tree = Tree()
        tree.add("Approval needed")
        tree.add("Approval needed")
        with self.assertRaisesRegex(nav.HermesNavigationError, "multiple visible"):
            nav.plan_action("approvals", PID, tree.snapshot())

    def test_modal_gives_only_approval_guidance(self):
        tree = Tree()
        tree.add("Open settings")
        tree.add("Approval needed")
        tree.add("", "dialog", modal=True)
        self.assertEqual(nav.plan_action("approvals", PID, tree.snapshot()).kind, "guidance")
        with self.assertRaisesRegex(nav.HermesNavigationError, "dialog"):
            nav.plan_action("settings", PID, tree.snapshot())

    def test_unknown_destination_and_invalid_pid_fail_before_any_io(self):
        for destination, pid in (("approve", PID), ("reject", PID), ("javascript:alert(1)", PID),
                                 ("tools", True), ("tools", 1), ("tools", "321")):
            with self.subTest(destination=destination, pid=pid):
                with patch.object(nav.subprocess, "run") as run:
                    with self.assertRaises(nav.HermesNavigationError):
                        nav.navigate(destination, pid)
                    run.assert_not_called()

    def test_foreign_pid_and_truncated_tree_rejected(self):
        tree = Tree()
        tree.add("Open settings")
        for snapshot in (replace(tree.snapshot(), complete=False),
                         replace(tree.snapshot(), app_pid=999),
                         replace(tree.snapshot(), nodes=tuple(replace(n, pid=999) for n in tree.nodes))):
            with self.assertRaises(nav.HermesNavigationError):
                nav.plan_action("settings", PID, snapshot)

    def test_inconsistent_parent_and_cycle_rejected(self):
        tree = Tree()
        tree.sidebar()
        node = tree.nodes[-1]
        tree.nodes[-1] = replace(node, parent=(998,))
        with self.assertRaises(nav.HermesNavigationError):
            nav.plan_action("artifacts", PID, tree.snapshot())
        tree.nodes[-1] = replace(node, parent=node.key)
        with self.assertRaises(nav.HermesNavigationError):
            nav.plan_action("artifacts", PID, tree.snapshot())


class RunnerTests(unittest.TestCase):
    def test_transient_snapshot_during_close_retries_reads_only(self):
        initial = Tree()
        initial.settings()
        final = Tree()
        final.sidebar()
        adapter = Mock()
        adapter.snapshot.side_effect = [initial.snapshot(), nav._TransientSnapshotError("deleted node"),
                                       nav._TransientSnapshotError("timeout"), final.snapshot()]
        with patch.object(nav.time, "sleep"):
            result = nav._run_navigation("artifacts", PID, adapter)
        self.assertEqual(result["actions"], ["close_settings", "artifacts"])
        self.assertEqual(adapter.snapshot.call_count, 4)
        self.assertEqual(adapter.click.call_count, 2)

    def test_initial_snapshot_error_is_not_retried(self):
        adapter = Mock()
        adapter.snapshot.side_effect = nav._TransientSnapshotError("deleted node")
        with self.assertRaises(nav._TransientSnapshotError):
            nav._run_navigation("tools", PID, adapter)
        self.assertEqual(adapter.snapshot.call_count, 1)
        adapter.click.assert_not_called()

    def test_transient_click_error_is_not_retried(self):
        tree = Tree()
        tree.settings()
        adapter = Mock()
        adapter.snapshot.return_value = tree.snapshot()
        adapter.click.side_effect = nav._TransientSnapshotError("transient action error")
        with self.assertRaises(nav._TransientSnapshotError):
            nav._run_navigation("tools", PID, adapter)
        self.assertEqual(adapter.snapshot.call_count, 1)
        self.assertEqual(adapter.click.call_count, 1)

    def test_nontransient_read_errors_never_retry_after_close(self):
        initial = Tree()
        initial.settings()
        for error in (nav.HermesNavigationError("ownership changed"),
                      nav.HermesNavigationError("ambiguous control"),
                      nav.HermesNavigationError("traversal limit"), AttributeError("coding bug")):
            with self.subTest(error=error):
                adapter = Mock()
                adapter.snapshot.side_effect = [initial.snapshot(), error]
                with patch.object(nav.time, "sleep"):
                    with self.assertRaises(type(error)):
                        nav._run_navigation("tools", PID, adapter)
                self.assertEqual(adapter.snapshot.call_count, 2)
                self.assertEqual(adapter.click.call_count, 1)

    def test_repeated_transient_read_errors_still_obey_deadline(self):
        initial = Tree()
        initial.settings()
        adapter = Mock()
        calls = [0]
        def snapshot():
            calls[0] += 1
            if calls[0] == 1:
                return initial.snapshot()
            raise nav._TransientSnapshotError("deleted node")
        adapter.snapshot.side_effect = snapshot
        clock = [0.0]
        def advance(seconds):
            clock[0] += seconds
        with patch.object(nav.time, "monotonic", side_effect=lambda: clock[0]), patch.object(nav.time, "sleep", side_effect=advance):
            with self.assertRaisesRegex(nav.HermesNavigationError, "wait timed out"):
                nav._run_navigation("tools", PID, adapter, deadline=.32)
        self.assertEqual(adapter.click.call_count, 1)
        self.assertLessEqual(clock[0], .32)

    def test_delayed_capabilities_polls_fresh_trees_without_second_activation(self):
        initial = Tree()
        initial.sidebar()
        final = Tree()
        final.tabs()
        adapter = Mock()
        adapter.snapshot.side_effect = [initial.snapshot(), initial.snapshot(),
                                       initial.snapshot(), final.snapshot()]
        with patch.object(nav.time, "sleep") as sleep:
            result = nav._run_navigation("tools", PID, adapter)
        self.assertEqual(result["actions"], ["capabilities", "tools"])
        self.assertEqual(adapter.click.call_count, 2)
        self.assertEqual(adapter.snapshot.call_count, 4)
        self.assertTrue(all(call.args[0] <= .05 for call in sleep.call_args_list))

    def test_delayed_settings_handles_absent_then_partial_nav_without_reclick(self):
        initial = Tree()
        initial.add("Open settings")
        partial = Tree()
        partial.add("Close settings")
        final = Tree()
        final.settings()
        adapter = Mock()
        adapter.snapshot.side_effect = [initial.snapshot(), initial.snapshot(),
                                       partial.snapshot(), final.snapshot()]
        with patch.object(nav.time, "sleep"):
            result = nav._run_navigation("plugins", PID, adapter)
        self.assertEqual(result["actions"], ["open_settings", "plugins"])
        self.assertEqual(adapter.click.call_count, 2)
        self.assertEqual(adapter.snapshot.call_count, 4)

    def test_delayed_settings_close_waits_for_full_workspace(self):
        initial = Tree()
        initial.settings()
        partial = Tree()
        partial.add("Close settings")
        underlying = Tree()
        underlying.sidebar()
        final = Tree()
        final.tabs()
        adapter = Mock()
        adapter.snapshot.side_effect = [initial.snapshot(), initial.snapshot(), partial.snapshot(),
                                       Tree().snapshot(), underlying.snapshot(), final.snapshot()]
        with patch.object(nav.time, "sleep"):
            result = nav._run_navigation("mcp", PID, adapter)
        self.assertEqual(result["actions"], ["close_settings", "capabilities", "mcp"])
        self.assertEqual(adapter.click.call_count, 3)

    def test_pending_transition_does_not_ignore_modal_or_ambiguity(self):
        initial = Tree()
        initial.sidebar()
        modal = Tree()
        modal.add("", "dialog", modal=True)
        duplicate = Tree()
        duplicate.tabs()
        duplicate.tabs()
        for blocked in (modal, duplicate):
            with self.subTest(blocked=blocked):
                adapter = Mock()
                adapter.snapshot.side_effect = [initial.snapshot(), blocked.snapshot()]
                with patch.object(nav.time, "sleep"):
                    with self.assertRaises(nav.HermesNavigationError):
                        nav._run_navigation("tools", PID, adapter)
                self.assertEqual(adapter.snapshot.call_count, 2)
                self.assertEqual(adapter.click.call_count, 1)

    def test_action_budget_remains_three_even_with_extra_plans(self):
        tree = Tree()
        node = tree.add("Open settings")
        adapter = Mock()
        adapter.snapshot.return_value = tree.snapshot()
        with patch.object(nav.time, "sleep"), patch.object(nav, "plan_action",
                return_value=nav.Plan("click", node, "intermediate")):
            with self.assertRaisesRegex(nav.HermesNavigationError, "three-action"):
                nav._run_navigation("tools", PID, adapter)
        self.assertEqual(adapter.click.call_count, 3)

    def test_settings_to_caps_target_uses_at_most_three_fresh_actions(self):
        for destination in ("tools", "skills", "mcp"):
            with self.subTest(destination=destination):
                initial = Tree()
                initial.sidebar()
                initial.settings()
                underlying = Tree()
                underlying.sidebar()
                caps = Tree()
                caps.tabs()
                adapter = Mock()
                adapter.snapshot.side_effect = [initial.snapshot(), underlying.snapshot(), caps.snapshot()]
                with patch.object(nav.time, "sleep"):
                    result = nav._run_navigation(destination, PID, adapter)
                self.assertEqual(result["actions"], ["close_settings", "capabilities", destination])
                self.assertEqual(adapter.snapshot.call_count, 3)
                self.assertEqual(adapter.click.call_count, 3)

    def test_settings_to_sidebar_uses_two_fresh_actions(self):
        for destination in ("artifacts", "new_session"):
            with self.subTest(destination=destination):
                initial = Tree()
                initial.sidebar()
                initial.settings()
                underlying = Tree()
                underlying.sidebar()
                adapter = Mock()
                adapter.snapshot.side_effect = [initial.snapshot(), underlying.snapshot()]
                with patch.object(nav.time, "sleep"):
                    result = nav._run_navigation(destination, PID, adapter)
                self.assertEqual(result["actions"], ["close_settings", destination])
                self.assertEqual(adapter.click.call_count, 2)

    def test_stale_settings_after_close_never_retries_close(self):
        initial = Tree()
        initial.settings()
        adapter = Mock()
        adapter.snapshot.return_value = initial.snapshot()
        clock = [0.0]
        def advance(seconds):
            clock[0] += seconds
        with patch.object(nav.time, "monotonic", side_effect=lambda: clock[0]), patch.object(nav.time, "sleep", side_effect=advance):
            with self.assertRaisesRegex(nav.HermesNavigationError, "wait timed out"):
                nav._run_navigation("tools", PID, adapter, deadline=.32)
        self.assertEqual(adapter.click.call_count, 1)
        self.assertLessEqual(clock[0], .32)
        self.assertGreater(adapter.snapshot.call_count, 1)

    def test_runner_refreshes_before_each_stage(self):
        first = Tree()
        first.sidebar()
        second = Tree()
        second.tabs()
        adapter = Mock()
        adapter.snapshot.side_effect = [first.snapshot(), second.snapshot()]
        with patch.object(nav.time, "sleep"):
            result = nav._run_navigation("tools", PID, adapter)
        self.assertEqual(result["actions"], ["capabilities", "tools"])
        self.assertEqual(result["status"], "requested")
        self.assertEqual(adapter.snapshot.call_count, 2)
        self.assertEqual(adapter.click.call_count, 2)
        adapter.focus.assert_not_called()

    def test_guidance_focuses_window_without_decision(self):
        adapter = Mock()
        adapter.snapshot.return_value = Tree().snapshot()
        adapter.focus.return_value = False
        result = nav._run_navigation("approvals", PID, adapter)
        self.assertEqual(result["status"], "guidance")
        self.assertFalse(result["focused"])
        self.assertEqual(result["actions"], [])
        adapter.click.assert_not_called()

    def test_private_environment_is_child_only_and_no_shell_or_stdin(self):
        env = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/private-test-bus", "PATH": "/test"}
        before = dict(os.environ)
        payload = {"ok": True, "destination": "settings", "status": "requested"}
        with patch.object(nav.subprocess, "run", return_value=types.SimpleNamespace(
                stdout=json.dumps(payload), returncode=0)) as run:
            self.assertEqual(nav.navigate("settings", PID, environment=env), payload)
        self.assertEqual(dict(os.environ), before)
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["env"], env)
        self.assertIsNot(kwargs["env"], env)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 2.5)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(run.call_args.args[0][-2:], ["--pid", str(PID)])

    def test_timeout_reports_uncertain_navigation_and_does_not_retry(self):
        with patch.object(nav.subprocess, "run", side_effect=subprocess.TimeoutExpired("test", 2.5)) as run:
            with self.assertRaisesRegex(nav.HermesNavigationError, "may already be visible"):
                nav.navigate("settings", PID)
            self.assertEqual(run.call_count, 1)

    def test_malformed_worker_results(self):
        payloads = [(0, "[]"), (0, "not json"), (0, "x" * 8193),
                    (0, '{"ok":true,"destination":"approve","status":"requested"}'),
                    (0, '{"ok":true,"destination":"settings","status":"approved"}'),
                    (2, '{"ok":false,"message":"Unavailable test fixture"}')]
        for code, output in payloads:
            with self.subTest(output=output[:40]):
                with patch.object(nav.subprocess, "run", return_value=types.SimpleNamespace(
                        returncode=code, stdout=output)):
                    with self.assertRaises(nav.HermesNavigationError):
                        nav.navigate("settings", PID)

    def test_invalid_private_environment(self):
        with patch.object(nav.subprocess, "run") as run:
            with self.assertRaises(nav.HermesNavigationError):
                nav.navigate("settings", PID, environment={"DBUS_SESSION_BUS_ADDRESS": 7})
            run.assert_not_called()


class FakeGError(Exception):
    def __init__(self, domain="atspi_error", code=1, message="timeout from dbind"):
        super().__init__(message)
        self.domain, self.code, self.message = domain, code, message


class FakeAccessible:
    def __init__(self, pid=PID, role="section", name="", children=(), states=None):
        self.pid, self.role, self.name = pid, role, name
        self.children = list(children)
        self.states = {"VISIBLE", "SHOWING", "ENABLED", "SENSITIVE"} if states is None else states
        self.name_reads = 0
        self.child_reads = 0
        self.action = None
        self.component = None

    def get_process_id(self):
        return self.pid

    def get_role(self):
        return types.SimpleNamespace(value_nick=self.role)

    def get_state_set(self):
        return types.SimpleNamespace(contains=lambda s: s in self.states)

    def get_name(self):
        self.name_reads += 1
        return self.name

    def get_child_count(self):
        self.child_reads += 1
        return len(self.children)

    def get_child_at_index(self, index):
        return self.children[index]

    def get_action_iface(self):
        return self.action

    def get_component_iface(self):
        return self.component


def fake_adapter(desktop):
    adapter = nav.AtspiAdapter.__new__(nav.AtspiAdapter)
    adapter.pid = PID
    adapter.deadline = nav.time.monotonic() + 50
    adapter.objects = {}
    adapter.glib_error_type = FakeGError
    state_names = ("VISIBLE", "SHOWING", "ENABLED", "SENSITIVE", "DEFUNCT", "MODAL")
    adapter.api = types.SimpleNamespace(
        get_desktop=lambda i: desktop,
        StateType=types.SimpleNamespace(**{s: s for s in state_names}))
    return adapter


class AdapterTests(unittest.TestCase):
    def test_dictation_toggle_uses_its_real_accessibility_action(self):
        button = FakeAccessible(role='toggle-button', name='Voice dictation')
        action = Mock(return_value=True)
        button.action = types.SimpleNamespace(get_n_actions=lambda: 2, get_name=lambda i: ['check', 'showContextMenu'][i], do_action=action)
        adapter = fake_adapter(FakeAccessible(children=[FakeAccessible(role='application', children=[button])]))
        snapshot = adapter.snapshot()
        plan = nav.plan_action('dictate', PID, snapshot)
        adapter.click(plan.node)
        action.assert_called_once_with(0)

    def test_only_known_gi_read_errors_classified_transient(self):
        for error in (FakeGError(), FakeGError(message="The process appears to be hung."),
                      FakeGError(message="No such object path '/org/a11y/atspi/accessible/123'"),
                      FakeGError(message="Object does not exist at path /org/a11y/atspi/accessible/7"),
                      FakeGError("g-dbus-error-quark", 41), FakeGError("g-dbus-error-quark", 4)):
            self.assertTrue(nav._transient_gi_read_error(error, FakeGError))
        for error in (RuntimeError("timeout from dbind"), FakeGError(code=0),
                      FakeGError(message="Permission denied"), FakeGError(message="Unexpected type"),
                      FakeGError("g-dbus-error-quark", 9), FakeGError("unknown-domain", 1)):
            self.assertFalse(nav._transient_gi_read_error(error, FakeGError))

    def test_deleted_child_invalidates_whole_snapshot(self):
        owned = FakeAccessible(role="application", children=[None])
        adapter = fake_adapter(FakeAccessible(children=[owned]))
        with self.assertRaises(nav._TransientSnapshotError):
            adapter.snapshot()
        self.assertEqual(adapter.objects, {})

    def test_null_states_and_gi_timeout_invalidate_snapshot(self):
        for get_state in (Mock(return_value=None), Mock(side_effect=FakeGError())):
            child = FakeAccessible()
            child.get_state_set = get_state
            adapter = fake_adapter(FakeAccessible(children=[FakeAccessible(role="application", children=[child])]))
            with self.assertRaises(nav._TransientSnapshotError):
                adapter.snapshot()
            self.assertEqual(adapter.objects, {})

    def test_application_gone_and_unknown_gi_errors_not_reclassified(self):
        for error in (FakeGError(code=0), FakeGError(message="Permission denied")):
            child = FakeAccessible()
            child.get_state_set = Mock(side_effect=error)
            adapter = fake_adapter(FakeAccessible(children=[FakeAccessible(role="application", children=[child])]))
            with self.assertRaises(FakeGError):
                adapter.snapshot()
            self.assertEqual(adapter.objects, {})

    def test_foreign_application_only_pid_read_and_private_text_not_read(self):
        foreign = FakeAccessible(99, "application", "PRIVATE OTHER APP")
        text = FakeAccessible(role="text", name="PRIVATE CHAT")
        button = FakeAccessible(role=nav.BUTTON, name="Open settings")
        owned = FakeAccessible(role="application", children=[text, button])
        snapshot = fake_adapter(FakeAccessible(children=[foreign, owned])).snapshot()
        self.assertEqual(foreign.name_reads, 0)
        self.assertEqual(foreign.child_reads, 0)
        self.assertEqual(text.name_reads, 0)
        self.assertEqual(owned.name_reads, 0)
        self.assertEqual(button.name_reads, 1)
        self.assertTrue(all(n.pid == PID for n in snapshot.nodes))

    def test_foreign_descendant_fails_before_reading_name(self):
        foreign = FakeAccessible(99, nav.BUTTON, "Open settings")
        owned = FakeAccessible(role="application", children=[foreign])
        with self.assertRaisesRegex(nav.HermesNavigationError, "ownership changed"):
            fake_adapter(FakeAccessible(children=[owned])).snapshot()
        self.assertEqual(foreign.name_reads, 0)

    def test_missing_or_duplicate_owned_app_fails(self):
        for apps in ([], [FakeAccessible(role="application"), FakeAccessible(role="application")]):
            with self.assertRaisesRegex(nav.HermesNavigationError, "no unique"):
                fake_adapter(FakeAccessible(children=apps)).snapshot()

    def test_tree_and_time_limits(self):
        owned = FakeAccessible(role="application", children=[FakeAccessible()] * nav.MAX_NODES)
        with self.assertRaisesRegex(nav.HermesNavigationError, "traversal limit"):
            fake_adapter(FakeAccessible(children=[owned])).snapshot()
        adapter = fake_adapter(FakeAccessible())
        adapter.deadline = 0
        with self.assertRaisesRegex(nav.HermesNavigationError, "timed out"):
            adapter.snapshot()

    def test_revalidates_exact_node_before_only_unique_click_action(self):
        button = FakeAccessible(role=nav.BUTTON, name="Open settings")
        button.action = Mock()
        button.action.get_n_actions.return_value = 2
        button.action.get_action_name.side_effect = lambda i: ["show-menu", "click"][i]
        button.action.do_action.return_value = True
        adapter = fake_adapter(FakeAccessible(children=[FakeAccessible(role="application", children=[button])]))
        snapshot = adapter.snapshot()
        node = snapshot.nodes[-1]
        adapter.click(node)
        button.action.do_action.assert_called_once_with(1)
        button.name = "Always allow"
        with self.assertRaisesRegex(nav.HermesNavigationError, "changed before activation"):
            adapter.click(node)
        self.assertEqual(button.action.do_action.call_count, 1)

    def test_action_interface_get_name_binding_and_ambiguity(self):
        button = FakeAccessible(role=nav.BUTTON, name="Open settings")
        do_action = Mock(return_value=True)
        button.action = types.SimpleNamespace(get_n_actions=lambda: 1,
                                             get_name=lambda i: "click", do_action=do_action)
        adapter = fake_adapter(FakeAccessible(children=[FakeAccessible(role="application", children=[button])]))
        node = adapter.snapshot().nodes[-1]
        adapter.click(node)
        do_action.assert_called_once_with(0)
        button.action.get_n_actions = lambda: 2
        with self.assertRaisesRegex(nav.HermesNavigationError, "unique click"):
            adapter.click(node)
        self.assertEqual(do_action.call_count, 1)

    def test_focus_only_unique_owned_window_never_approval_button(self):
        button = FakeAccessible(role=nav.BUTTON, name="Always allow")
        button.component = Mock()
        frame = FakeAccessible(role="frame", children=[button])
        frame.component = Mock()
        frame.component.grab_focus.return_value = True
        adapter = fake_adapter(FakeAccessible(children=[FakeAccessible(role="application", children=[frame])]))
        snapshot = adapter.snapshot()
        self.assertTrue(adapter.focus(snapshot))
        frame.component.grab_focus.assert_called_once_with()
        button.component.grab_focus.assert_not_called()
        frame.pid = 999
        self.assertFalse(adapter.focus(snapshot))


if __name__ == "__main__":
    unittest.main()
