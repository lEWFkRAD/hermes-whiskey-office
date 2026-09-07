"""Bounded, PID-scoped navigation of the unmodified Hermes Desktop UI.

Public API: navigate(destination, app_pid, environment=None). GI is imported only
inside a short-lived child; callers need not import GI or mutate their DBus env.
Success confirms activation of a real accessible control, not backend readiness.

Label/structure contract: official Hermes tag v2026.8.31, commit
29112bef099274229cadff79cdff7bf7b99c4b77, apps/desktop/src/:
  app/chat/sidebar/index.tsx (SidebarMenu ul, navigation buttons)
  app/skills/index.tsx; components/ui/tab-dropdown.tsx; ui/text-tab.tsx
    (Skills/Tools/MCP are BUTTONS with optional compact count, not ARIA tabs)
  app/shell/titlebar-controls.tsx (Open settings aria-label)
  app/settings/index.tsx; app/overlays/overlay-split-layout.tsx
    (Close settings, Plugins and sibling settings navigation buttons)
  app/overlays/overlay-view.tsx; app/contrib/wiring.tsx;
  app/shell/hooks/use-overlay-routing.ts
    (Close settings dismisses the overlay via replace navigation to its previous
     route; no save/discard confirmation. The pinned wrapper is presentation,
     not aria-modal. A platform-exposed Settings dialog needs scoped proof.)
  app/chat/scroll-to-bottom-button.tsx (Approval needed only scrolls to bottom)
  i18n/en.ts; components/ui/kbd.tsx (English labels and New session Ctrl N badge)

Only the pinned English wide layout is supported. Missing, duplicated, hidden,
disabled, truncated, foreign-process, or modal-obscured controls fail closed.
No keyboard synthesis, coordinates, JS, config reads, or approval decisions.

AT-SPI references (GI uses the nonlocalized Action.get_name binding):
https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/func.set_timeout.html
https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Accessible.get_process_id.html
https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Action.get_action_name.html
https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Action.do_action.html
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Mapping


DESTINATIONS = frozenset({"tools", "skills", "mcp", "plugins", "artifacts",
                          "approvals", "settings", "new_session", "voice", "dictate", "end_voice"})
HARD_TIMEOUT = 2.5
WORK_TIMEOUT = 2.15
MAX_NODES = 1600
MAX_DEPTH = 40
BUTTON = "push-button"
WINDOW_ROLES = frozenset({"frame", "window"})
SCOPE_BOUNDARIES = frozenset({"application", "frame", "window", "document-web",
                              "document-frame", "dialog", "push-button"})
SAFE_ACTIONS = frozenset({"click", "press", "activate"})
SETTINGS_NAV_LABELS = ("Providers", "Gateways", "Keyboard Shortcuts", "Plugins")
APPROVAL_GUIDANCE = ("Use the actual Hermes conversation's Approval needed control "
                     "and review the request there. No approval decision was made.")


class HermesNavigationError(ValueError):
    """The requested real-UI navigation could not be safely identified/completed."""


class _TransientSnapshotError(HermesNavigationError):
    """A read-only snapshot was invalidated; never a retryable action error."""


def _transient_gi_read_error(exc: Exception, glib_error_type: type[Exception]) -> bool:
    """Recognize specific transport/deleted-object reads, not arbitrary GI errors.

    Gio.DBusError enum: NO_REPLY=4, TIMEOUT=12, TIMED_OUT=20, UNKNOWN_OBJECT=41
    (https://docs.gtk.org/gio/error.DBusError.html). libatspi often erases the
    original D-Bus code into atspi_error/IPC=1, so that form additionally needs
    a narrow known timeout/deleted-object message. APPLICATION_GONE=0 is fatal.
    GNOME at-spi2-core atspi-misc-private.h / atspi-misc.c define these values.
    No exception message is returned to the caller or written to a log.
    """
    if not isinstance(exc, glib_error_type):
        return False
    domain, code = getattr(exc, "domain", None), getattr(exc, "code", None)
    if domain == "g-dbus-error-quark":
        return type(code) is int and code in {4, 12, 20, 41}
    if domain != "atspi_error" or code != 1:
        return False
    message = getattr(exc, "message", "")
    if not isinstance(message, str):
        return False
    if message in {"timeout from dbind", "The process appears to be hung."}:
        return True
    return re.fullmatch(r"(?:No such object path|Object does not exist at path) "
                        r"['\"]?/org/a11y/atspi/[A-Za-z0-9_/]+['\"]?\.?", message) is not None


def _arguments(destination: str, app_pid: int) -> None:
    if not isinstance(destination, str) or destination not in DESTINATIONS:
        raise HermesNavigationError("Unsupported Hermes navigation destination.")
    if type(app_pid) is not int or app_pid <= 1:
        raise HermesNavigationError("An owned Hermes process ID greater than 1 is required.")


@dataclass(frozen=True)
class Node:
    """Minimal fixture/live snapshot; text bodies and descriptions are never read."""

    key: tuple[int, ...]
    parent: tuple[int, ...] | None
    pid: int
    role: str
    name: str = ""
    visible: bool = False
    showing: bool = False
    enabled: bool = False
    sensitive: bool = False
    defunct: bool = False
    modal: bool = False

    @property
    def usable(self) -> bool:
        return self.visible and self.showing and not self.defunct

    @property
    def clickable(self) -> bool:
        return self.usable and self.enabled and self.sensitive and self.role in {BUTTON, 'toggle-button', 'menu-item', 'check-menu-item'}


@dataclass(frozen=True)
class Snapshot:
    app_pid: int
    nodes: tuple[Node, ...]
    complete: bool = True

    def checked(self, app_pid: int) -> "Snapshot":
        if not self.complete or len(self.nodes) > MAX_NODES:
            raise HermesNavigationError("Hermes accessibility tree was incomplete; navigation was not guessed.")
        if self.app_pid != app_pid or any(n.pid != app_pid for n in self.nodes):
            raise HermesNavigationError("Hermes accessibility process ownership changed.")
        keys = {n.key for n in self.nodes}
        if len(keys) != len(self.nodes) or any(n.parent is not None and n.parent not in keys for n in self.nodes):
            raise HermesNavigationError("Hermes accessibility tree structure was inconsistent.")
        return self


@dataclass(frozen=True)
class Plan:
    kind: str  # click, wait, done, guidance
    node: Node | None = None
    label: str = ""
    message: str = ""


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _label(node: Node, label: str) -> bool:
    name = _normalized(node.name)
    if label in {"Skills", "Tools"}:
        # Pinned compactNumber(): 0..999, 1k, 1.2k, 1M, etc.; not arbitrary suffixes.
        return re.fullmatch(re.escape(label) + r"(?:\s*[0-9]+(?:\.[0-9])?[kM]?)?", name) is not None
    if label == "New session":
        # The ordinary Linux default key badge. Remapped/unrecognized labels fail closed.
        return re.fullmatch(r"New session(?:\s*Ctrl\s*N)?", name) is not None
    return name == label


def _unique(nodes: list[Node], label: str, *, optional: bool = False) -> Node | None:
    if len(nodes) > 1:
        raise HermesNavigationError(f"Hermes has multiple visible {label} controls; select the intended surface manually.")
    if not nodes:
        if optional:
            return None
        raise HermesNavigationError(f"Hermes {label} control is unavailable. Open the English desktop in its wide layout.")
    if not nodes[0].clickable:
        raise HermesNavigationError(f"Hermes {label} control is disabled or unavailable.")
    return nodes[0]


def _buttons(snapshot: Snapshot, label: str) -> list[Node]:
    # Include disabled candidates when checking uniqueness. Never silently choose a
    # second enabled copy of a known disabled control.
    return [n for n in snapshot.nodes if n.usable and n.role == BUTTON and _label(n, label)]

def _voice_items(snapshot: Snapshot, label: str) -> list[Node]:
    return [n for n in snapshot.nodes if n.usable and n.role in {'toggle-button', 'menu-item', 'check-menu-item'} and _label(n, label)]


def _ancestors(node: Node, lookup: dict[tuple[int, ...], Node]) -> list[Node]:
    result = []
    seen = {node.key}
    key = node.parent
    while key is not None:
        if key in seen or len(result) >= MAX_DEPTH:
            raise HermesNavigationError("Hermes accessibility ancestry was inconsistent.")
        seen.add(key)
        item = lookup[key]
        result.append(item)
        key = item.parent
    return result


def _group(snapshot: Snapshot, labels: tuple[str, ...], *, sidebar: bool = False) -> list[Node] | None:
    """Find one small, real navigation group from pinned sibling labels.

    We stop at the document/window boundary, so same-named content elsewhere in
    a conversation cannot supply a missing sidebar or settings navigation row.
    Sidebar buttons must share their nearest HTML list. Other groups must share
    their immediate accessible parent (the pinned div/aside).
    """
    lookup = {n.key: n for n in snapshot.nodes}
    candidates: dict[tuple[int, ...], list[Node]] = {}
    for node in snapshot.nodes:
        if not node.usable or node.role != BUTTON:
            continue
        ancestors = _ancestors(node, lookup)
        group = None
        if sidebar:
            for ancestor in ancestors:
                if ancestor.role in SCOPE_BOUNDARIES:
                    break
                if ancestor.role == "list":
                    group = ancestor
                    break
        elif ancestors and ancestors[0].role not in SCOPE_BOUNDARIES:
            group = ancestors[0]
        if group is not None:
            candidates.setdefault(group.key, []).append(node)
    matches = [members for members in candidates.values()
               if all(any(_label(n, label) for n in members) for label in labels)]
    if len(matches) > 1:
        raise HermesNavigationError("Multiple Hermes navigation groups are visible; select one desktop surface manually.")
    if not matches:
        return None
    for label in labels:
        _unique([n for n in matches[0] if _label(n, label)], label)
    return matches[0]


def plan_action(destination: str, app_pid: int, snapshot: Snapshot,
                completed: tuple[str, ...] = ()) -> Plan:
    """Pure, fail-closed action planner, usable with fixtures without GI/Linux."""
    _arguments(destination, app_pid)
    snapshot.checked(app_pid)
    if destination in completed:
        return Plan("done", message=f"Selected {destination.replace('_', ' ')} in Hermes Desktop.")
    close_settings = _unique(_buttons(snapshot, "Close settings"), "Close settings", optional=True)
    settings_group = _group(snapshot, SETTINGS_NAV_LABELS) if close_settings else None
    dialogs = [n for n in snapshot.nodes if n.usable and (n.modal or n.role == "dialog")]
    # The source wrapper is role=presentation. If the platform nevertheless
    # exposes a modal Settings dialog, allow only the one dialog that actually
    # contains the verified close button AND the complete Settings nav group.
    # A nested picker/confirmation or another window/dialog always blocks this.
    settings_dialog = False
    if len(dialogs) == 1 and dialogs[0].role == "dialog" and close_settings and settings_group:
        lookup = {n.key: n for n in snapshot.nodes}
        settings_dialog = all(dialogs[0].key in {p.key for p in _ancestors(n, lookup)}
                              for n in [close_settings, *settings_group])
    blocked_by_dialog = bool(dialogs) and not settings_dialog
    if destination == "approvals":
        if not dialogs and not close_settings:
            # This exact pinned navigation button invokes requestScrollToBottom.
            jump = _unique(_buttons(snapshot, "Approval needed"), "Approval needed", optional=True)
            if jump:
                return Plan("click", jump, "approvals", APPROVAL_GUIDANCE)
        return Plan("guidance", message=APPROVAL_GUIDANCE)
    if blocked_by_dialog:
        raise HermesNavigationError("A Hermes dialog is open. Finish or dismiss it in Hermes before navigating.")
    if close_settings and destination not in {"settings", "plugins"}:
        if "close_settings" in completed:
            return Plan("wait", message="Waiting for Hermes Settings to close.")
        if not settings_group:
            raise HermesNavigationError("The Hermes Settings view could not be identified completely; close it in Hermes manually.")
        return Plan("click", close_settings, "close_settings")
    if destination in {"voice", "dictate", "end_voice"}:
        ending = _unique(_buttons(snapshot, "End voice conversation"), "End voice conversation", optional=True)
        if destination == "end_voice":
            if ending:
                return Plan("click", ending, destination)
            dictation = _unique(_buttons(snapshot, "Stop dictation"), "Stop dictation", optional=True)
            stop_item = _unique(_voice_items(snapshot, 'Stop dictation'), 'Stop dictation', optional=True)
            if stop_item:
                return Plan('click', stop_item, destination)
            if dictation:
                if 'voice_menu' in completed:
                    return Plan('wait', message='Waiting for Hermes dictation controls.')
                return Plan("click", dictation, 'voice_menu')
            return Plan("guidance", message="No active voice conversation or dictation was found. Use Hermes' visible voice controls if another surface owns the microphone.")
        if ending:
            if destination == 'dictate':
                if 'end_active_call' in completed:
                    return Plan('wait', message='Waiting for the active conversation to end before dictation.')
                return Plan('click', ending, 'end_active_call')
            return Plan("done", message="Hermes voice conversation is already active. Use End voice to stop it.")
        if destination == 'dictate':
            recording = _unique(_buttons(snapshot, 'Stop dictation') + _voice_items(snapshot, 'Stop dictation'), 'Stop dictation', optional=True)
            if recording:
                return Plan('done', message='Dictation is already recording. End voice stops it into a draft; Send asks Hermes to respond.')
            item = _unique(_voice_items(snapshot, 'Voice dictation'), 'Voice dictation', optional=True)
            if item:
                return Plan('click', item, destination)
            direct = _unique(_buttons(snapshot, 'Voice dictation'), 'Voice dictation', optional=True)
            if direct:
                return Plan('click', direct, destination)
            if 'voice_menu' in completed:
                return Plan('wait', message='Waiting for Hermes voice menu.')
            return Plan('click', _unique(_buttons(snapshot, 'Voice controls'), 'Voice controls'), 'voice_menu')
        return Plan("click", _unique(_buttons(snapshot, "Start voice conversation"), "Start voice conversation"), destination)
    if destination == "settings":
        if close_settings:
            return Plan("done", message="Hermes Settings is already open.")
        return Plan("click", _unique(_buttons(snapshot, "Open settings"), "Open settings"), "settings")
    if destination == "plugins":
        if close_settings:
            if not settings_group:
                if "open_settings" in completed:
                    return Plan("wait", message="Waiting for Hermes Settings navigation.")
                raise HermesNavigationError("The wide Hermes Settings navigation is unavailable; open Plugins in Hermes manually.")
            return Plan("click", _unique([n for n in settings_group if _label(n, "Plugins")], "Plugins"), "plugins")
        if "open_settings" in completed:
            return Plan("wait", message="Waiting for Hermes Settings navigation.")
        return Plan("click", _unique(_buttons(snapshot, "Open settings"), "Open settings"), "open_settings")
    if destination in {"skills", "tools", "mcp"}:
        group = _group(snapshot, ("Skills", "Tools", "MCP"))
        if group:
            label = {"skills": "Skills", "tools": "Tools", "mcp": "MCP"}[destination]
            return Plan("click", _unique([n for n in group if _label(n, label)], label), destination)
        if "capabilities" in completed:
            return Plan("wait", message="Waiting for the wide Hermes Capabilities buttons.")
    sidebar = _group(snapshot, ("Capabilities", "Messaging", "Artifacts", "Scheduled jobs"), sidebar=True)
    if not sidebar:
        if completed and completed[-1] == "close_settings":
            return Plan("wait", message="Waiting for the Hermes workspace after closing Settings.")
        raise HermesNavigationError("The real Hermes sidebar is unavailable. Open its English wide desktop layout.")
    label = {"artifacts": "Artifacts", "new_session": "New session"}.get(destination, "Capabilities")
    node = _unique([n for n in sidebar if _label(n, label)], label)
    return Plan("click", node, destination if label != "Capabilities" else "capabilities")


class AtspiAdapter:
    """Short-lived live adapter. Every inspected node belongs to the supplied PID."""

    def __init__(self, app_pid: int, deadline: float):
        self.pid = app_pid
        self.deadline = deadline
        self.objects: dict[tuple[int, ...], Any] = {}
        try:
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi, GLib
            self.api = Atspi
            self.glib_error_type = GLib.Error
            # No startup grace: libatspi's default can otherwise wait 15 seconds.
            if hasattr(Atspi, "set_timeout"):
                Atspi.set_timeout(100, 0)
            if Atspi.init() not in (0, 1):
                raise RuntimeError("initialization failed")
        except Exception as exc:
            raise HermesNavigationError("Hermes accessibility is unavailable. Use a Python interpreter with gi/Atspi and the desktop's private DBus session.") from exc

    def _check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise HermesNavigationError("Hermes accessibility timed out; no further navigation was attempted.")

    def _read(self, obj: Any, key: tuple[int, ...], parent: tuple[int, ...] | None) -> Node:
        self._check()
        if obj.get_process_id() != self.pid:
            raise HermesNavigationError("Hermes accessibility process ownership changed.")
        role = obj.get_role()
        role_name = getattr(role, "value_nick", None)
        if not role_name:
            role_name = self.api.role_get_name(role)
        role_name = str(role_name).lower().replace("_", "-").replace(" ", "-")
        states = obj.get_state_set()
        if states is None:
            raise _TransientSnapshotError("Hermes accessibility node disappeared during inspection.")
        has = lambda state: states.contains(getattr(self.api.StateType, state))
        # Names of structural nodes and session/document text are unnecessary.
        name = obj.get_name() or "" if role_name in {BUTTON, 'toggle-button', 'menu-item', 'check-menu-item'} else ""
        if len(name) > 160:
            name = ""  # never permit a truncated name to become an exact match
        return Node(key, parent, self.pid, role_name, name,
                    has("VISIBLE"), has("SHOWING"), has("ENABLED"), has("SENSITIVE"),
                    has("DEFUNCT"), has("MODAL"))

    def snapshot(self) -> Snapshot:
        try:
            return self._snapshot_read()
        except _TransientSnapshotError:
            self.objects = {}
            raise
        except Exception as exc:
            self.objects = {}
            if _transient_gi_read_error(exc, self.glib_error_type):
                raise _TransientSnapshotError("Hermes accessibility read was interrupted by a page transition.") from None
            raise

    def _snapshot_read(self) -> Snapshot:
        self._check()
        desktop = self.api.get_desktop(0)
        count = desktop.get_child_count()
        if count < 0 or count > 128:
            raise HermesNavigationError("Accessibility application inventory exceeded its safe limit.")
        roots = []
        for index in range(count):
            self._check()
            app = desktop.get_child_at_index(index)
            # For other applications, only the PID is read; never their names,
            # windows, controls, session text, or descendants.
            if app is not None and app.get_process_id() == self.pid:
                roots.append((index, app))
        if len(roots) != 1:
            raise HermesNavigationError("The owned Hermes process has no unique accessibility application. Enable renderer accessibility in the same private DBus session.")
        self.objects = {}
        nodes = []
        root_index, app = roots[0]
        pending = [(app, (root_index,), None)]
        while pending:
            self._check()
            obj, key, parent = pending.pop()
            if len(nodes) >= MAX_NODES or len(key) > MAX_DEPTH:
                raise HermesNavigationError("Hermes accessibility tree exceeded its safe traversal limit.")
            node = self._read(obj, key, parent)
            nodes.append(node)
            self.objects[key] = obj
            # Buttons are terminal for this task; reading their descendant text
            # would duplicate their name. Plain text nodes are also terminal.
            if node.defunct or node.role in {BUTTON, 'toggle-button', 'menu-item', 'check-menu-item', "text", "static", "entry", "password-text"}:
                continue
            child_count = obj.get_child_count()
            if child_count < 0 or len(nodes) + len(pending) + child_count > MAX_NODES:
                raise HermesNavigationError("Hermes accessibility tree exceeded its safe traversal limit.")
            for index in reversed(range(child_count)):
                self._check()
                child = obj.get_child_at_index(index)
                if child is None:
                    raise _TransientSnapshotError("Hermes accessibility node disappeared during inspection.")
                pending.append((child, key + (index,), key))
        return Snapshot(self.pid, tuple(nodes)).checked(self.pid)

    def click(self, node: Node) -> None:
        self._check()
        obj = self.objects.get(node.key)
        if obj is None or self._read(obj, node.key, node.parent) != node or not node.clickable:
            raise HermesNavigationError("Hermes navigation control changed before activation; nothing was guessed.")
        action = obj.get_action_iface()
        if action is None:
            raise HermesNavigationError("Hermes navigation control has no accessibility action.")
        count = action.get_n_actions()
        if count < 1 or count > 8:
            raise HermesNavigationError("Hermes navigation control has an unexpected action set.")
        # GI's get_name(index) is the Action interface method, not Accessible's
        # get_name(). get_action_name is present in some typelib versions.
        getter = getattr(action, "get_action_name", None) or action.get_name
        allowed_actions = SAFE_ACTIONS | {'toggle', 'check', 'uncheck'} if node.role in {'toggle-button', 'check-menu-item'} else SAFE_ACTIONS
        matches = [i for i in range(count) if getter(i) in allowed_actions]
        if len(matches) != 1:
            raise HermesNavigationError("Hermes navigation control has no unique click action.")
        self._check()
        if not action.do_action(matches[0]):
            raise HermesNavigationError("Hermes did not accept the navigation control activation.")

    def focus(self, snapshot: Snapshot) -> bool:
        """Approvals fallback only focuses a unique owned window, never a button."""
        windows = [n for n in snapshot.nodes if n.role in WINDOW_ROLES and n.usable]
        if len(windows) != 1:
            return False
        self._check()
        node = windows[0]
        obj = self.objects.get(node.key)
        if obj is None or obj.get_process_id() != self.pid:
            return False
        component = obj.get_component_iface()
        return bool(component and component.grab_focus())


def _run_navigation(destination: str, app_pid: int, adapter: Any,
                    *, deadline: float | None = None) -> dict[str, Any]:
    # Reserve a little time to encode the worker's result before the outer 2.5s
    # timeout. Waiting only inspects fresh trees, never repeats an activation.
    stop_at = (time.monotonic() + WORK_TIMEOUT if deadline is None else deadline) - 0.10
    completed: tuple[str, ...] = ()
    waiting_message = "Hermes navigation did not finish before its deadline."
    while time.monotonic() < stop_at:
        try:
            snapshot = adapter.snapshot()
        except _TransientSnapshotError:
            # This catch surrounds reads only. A failure inside click/focus is
            # never retried, even when the same GI code would be transient here.
            if not completed or completed[-1] not in {"capabilities", "open_settings", "close_settings"}:
                raise
            waiting_message = "Waiting for the Hermes accessibility tree to settle."
            remaining = stop_at - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.05, remaining))
            continue
        plan = plan_action(destination, app_pid, snapshot, completed)
        if plan.kind == "wait":
            waiting_message = plan.message
            remaining = stop_at - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.05, remaining))
            continue
        if plan.kind == "guidance":
            focused = adapter.focus(snapshot)
            return {"ok": True, "destination": destination, "status": "guidance",
                    "message": plan.message, "actions": list(completed), "focused": focused}
        if plan.kind == "done":
            return {"ok": True, "destination": destination, "status": "requested",
                    "message": plan.message, "actions": list(completed),
                    "verification": "accessible_control_activation" if completed else "visible_settings_view"}
        if len(completed) >= 3:
            raise HermesNavigationError("Hermes navigation reached its three-action limit.")
        adapter.click(plan.node)
        completed += (plan.label,)
        if plan.label == destination:
            return {"ok": True, "destination": destination, "status": "requested",
                    "message": plan.message or f"Selected {destination.replace('_', ' ')} in Hermes Desktop.",
                    "actions": list(completed), "verification": "accessible_control_activation"}
        # Give React a brief turn. The expected transition may then yield wait
        # repeatedly until visible; every iteration builds a fresh snapshot.
        remaining = stop_at - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.18 if plan.label == 'close_settings' else 0.05, remaining))
    raise HermesNavigationError(waiting_message + " The wait timed out; no navigation click was repeated. Inspect Hermes before retrying.")


def navigate(destination: str, app_pid: int, *, environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Invoke only allowlisted real controls, bounded by a 2.5s worker timeout.

    ``environment`` is passed only to the child (e.g. the owned private DBus
    address). No caller/global environment is changed. Callers should serialize
    navigation with other desktop input and focus their owned desktop surface.
    Timeout may occur after the first safe navigation click; it never retries an
    activation automatically. The parent kills only this one-shot child.
    """
    _arguments(destination, app_pid)
    if environment is not None and (not isinstance(environment, Mapping) or
            any(not isinstance(k, str) or not isinstance(v, str) for k, v in environment.items())):
        raise HermesNavigationError("The private Hermes accessibility environment is invalid.")
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", "--destination", destination,
             "--pid", str(app_pid)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=HARD_TIMEOUT,
            env=None if environment is None else dict(environment), check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HermesNavigationError("Hermes navigation timed out. A navigation step may already be visible; inspect Hermes before retrying.") from exc
    except OSError as exc:
        raise HermesNavigationError("The Hermes accessibility helper could not start.") from exc
    try:
        if len(result.stdout) > 8192:
            raise ValueError("large response")
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("not an object")
    except (ValueError, TypeError) as exc:
        raise HermesNavigationError("Hermes accessibility returned no valid navigation result.") from exc
    if result.returncode != 0 or payload.get("ok") is not True:
        message = payload.get("message")
        raise HermesNavigationError(message if isinstance(message, str) and len(message) <= 500
                                    else "Hermes accessibility navigation is unavailable.")
    if payload.get("destination") != destination or payload.get("status") not in {"requested", "guidance"}:
        raise HermesNavigationError("Hermes accessibility returned an unexpected navigation result.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", choices=sorted(DESTINATIONS), required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        _arguments(args.destination, args.pid)
        if args.worker:
            if not sys.platform.startswith("linux"):
                raise HermesNavigationError("Hermes AT-SPI navigation requires the Linux desktop host.")
            deadline = time.monotonic() + WORK_TIMEOUT
            result = _run_navigation(args.destination, args.pid, AtspiAdapter(args.pid, deadline), deadline=deadline)
        else:
            result = navigate(args.destination, args.pid)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except HermesNavigationError as exc:
        print(json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=True))
        return 2
    except Exception:
        # Do not leak the private bus address, UI content, or GI diagnostic text.
        print(json.dumps({"ok": False, "message": "Hermes accessibility changed or became unavailable; use its desktop controls manually."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
