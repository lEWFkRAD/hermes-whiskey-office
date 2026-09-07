# Right-trigger dictation shortcut

A fresh right-trigger squeeze aimed away from windows invokes the existing
Hermes Desktop Dictate action. Window/menu selection and targeted grip keep their
existing controls. Holding, pressure jitter, losing tracking, or dragging off a
window cannot repeatedly start dictation. Simultaneous A/B/X/Y actions take
priority. Hand pinching keeps its existing behavior.

This shortcut starts native dictation; releasing the trigger does not stop or
send it. Use End voice / Stop dictation to finish, review the resulting draft,
then Send to ask Hermes for a reply. Native Hermes owns recording, its recording
indicator, transcription, and its existing time limit. No automatic sending or
continuous listening was added. The legacy ACP workbench has no new binding.

Status: source staged; not installed or tested on a physical Quest. Headless
checks passed: 16 input/native-action routing assertions and 14 tutorial
assertions. The routing fixture verifies the native Dictate command, not actual
microphone acquisition or audio quality. No office or microphone was launched.

Next live acceptance: squeeze away from windows, confirm the actual Hermes mic
indicator and Quest microphone source, finish dictation, review the transcript,
and explicitly send it. Verify aimed selection, menu selection, walking, turning,
tracking recovery and that no old draft is submitted automatically.
