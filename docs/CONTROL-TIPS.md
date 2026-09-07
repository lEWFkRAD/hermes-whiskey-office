# Learning the controls

The first tracked hand/controller session shows one short teaching card at a time. The card stays where it appeared and fades after 12 seconds. It does not capture pointing, pinch, grip or locomotion, send Hermes a message, or require completing a task. Tracking loss hides it until tracking returns.

Hands first learn the two-finger wrist-menu gesture. Opening the wheel replaces that introductory card with twist-and-pinch guidance. Pointing at an open window can show two-hand movement/resizing guidance. Controllers receive button and stick shortcuts. Tips have a cooldown and remember which lessons have already appeared.

**Senses → Help** offers Hand menu, Twist & pinch, Windows, Controllers and Voice lessons. **Tips off** persists across launches. Individual lessons can still be requested with tips disabled; **Replay tips** re-enables contextual coaching and clears the seen set. The menu closes before an explicitly requested card appears. Desktop previews can replay lessons from the same wheel without enabling automatic coaching.

When no wheel is open, **B dismisses a visible tip first**. A later press resumes the normal window-back behavior. While the wheel is open, B closes the wheel. Hand users can let cards fade or choose Tips off through Help.

The local `control-tips.json` preference file lives inside the office data directory. Its contents are only a schema version, enabled flag and known lesson IDs. There is no behavioral history, microphone data, model call or cross-device propagation. The current implementation remembers displayed lessons; it does not claim that displaying a lesson proves mastery.

Offline tests cover tracking loss, fixed placement, contextual progression, timeout, persistence, unknown IDs, replay and disabled tips. A CPU-rendered native preview was inspected for text size/layering. The revised teaching cards still require physical headset readability and comfort testing.

This change also enables the missing `xr/shaders/enabled` project setting. The first live WiVRn session revealed repeated tone-mapper shader-variant errors with it disabled; enabling it removed those errors on restart. [Godot's XR setup guide](https://docs.godotengine.org/en/4.7/tutorials/xr/setting_up_xr.html) requires both OpenXR and XR shaders. Passing desktop rendering tests alone does not establish stereo correctness.
