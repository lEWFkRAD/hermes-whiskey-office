# Architecture

`app/main.gd` builds the room from the modular asset catalogue and layout. Godot owns movement, ray targeting, windows, wrist interactions and the podium. `office_launcher.py` owns short-lived capture/IPC workers; they exit with the application. It creates no system service.

`desktop_bridge.py` gives each application an owned Xvfb display and exposes captured pixels plus bounded input commands. `hermes_navigation.py` uses process-scoped AT-SPI actions for the existing Hermes UI. `window_broker.py` starts only configured command arrays; saved layout cannot introduce executable commands. Remote desktop transport belongs to its client (e.g. Remmina or SSH/xterm).

The native room publishes virtual scene facts through `office_awareness.gd`. The optional composer middleware reads fresh bounded facts only on explicit send. TUI reads the same file on demand. Screenshots are separately selected/queued; physical camera/microphone data is not part of scene context. Documents and labels are untrusted, and a pointed candidate is not a confirmed instruction.

`loading_bay.py` maintains immutable file objects, leases and conflict-preserving returns. `object_pipeline.py` journals explicit generation attempts, resumes known job IDs and validates collected GLBs. `office_fabricator.gd` delivers these models to the podium and persists placements. `office_hologram.gd` renders selectable models/files/windows without changing their source files.

The optional Object Studio adapter supplies the existing durable API and streamed progress. Its SSH worker runs a configured trellis.cpp executable and weights; `forge` remains the legacy protocol backend ID, not a required hostname. No credentials are included. The browser/Blender UI is optional to podium usage.

## Invariants to preserve

- Input becomes a prompt only through explicit Send or explicitly started continuous conversation.
- Canonical semantic state is external to a model's conversational context; local zoom/placement is not automatically a shared semantic act.
- Context expires and can be disabled. Said, inferred and committed facts must not be silently conflated.
- Commands carry an instance, ID and time bound; cancellation releases held input.
- No automatic retry after an ambiguous generation POST. Reconnect by reading a known job.
- Updates are staged and accepted against exact code/binaries before normal startup.
