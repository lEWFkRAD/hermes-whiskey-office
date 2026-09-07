extends PanelContainer
## Presentation only. The parent owns transport, sessions and authoritative state.
## Add to a CanvasLayer, call setup(), wire signals, then call update_state().
## While visible, the parent must suspend room hotkeys and polled locomotion.

signal message_submitted(text: String)
signal session_selected(id: String)
signal new_session_requested
signal voice_requested
signal close_requested
signal refresh_requested
signal cancel_requested
signal permission_replied(id: String, option_id: String)
signal share_view_requested
signal passthrough_requested(enabled: bool)

const CREAM := Color("f0e4cf")
const MUTED := Color("bcae97")
const GOLD := Color("c6a56b")
const INK := Color("171b19")
const ERROR_COLOR := Color("edb5a0")

var _built := false
var _state: Dictionary = {}
var _busy := false
var _locally_submitted := false
var _can_chat := false
var _can_sessions := false
var _can_voice := false
var _connected := false
var _awaiting_message_ack := false
var _submitted_text := ""
var _stop_requested := false
var _permission_signature := ""
var _permission_error := ""
var _permission_pending: Dictionary = {}
var _selected_session := ""
var _has_pending_state := false
var _last_pending_state := ""
var _session_signature := ""
var _message_signature := ""
var _task_signature := ""
var _previous_message_session := ""
var _connection_label: Label
var _capability_hint: Label
var _tabs: TabContainer
var _session_picker: OptionButton
var _new_session_button: Button
var _voice_button: Button
var _refresh_button: Button
var _send_button: Button
var _composer: TextEdit
var _transcript: RichTextLabel
var _task_stack: VBoxContainer
var _connection_details: RichTextLabel
var _voice_status: Label
var _tool_activity: Label
var _permission_scroll: ScrollContainer
var _permission_stack: VBoxContainer
var _stop_button: Button
var _keyboard_hint: Label
var _share_button: Button
var _keyboard_preview: RichTextLabel
var _keyboard_status: Label
var _keyboard_send: Button
var _keyboard_shift: Button
var _keyboard_keys: Array[Button] = []
var _shift_enabled := false

func _ready() -> void:
	setup()

func setup() -> void:
	if _built:
		return
	_built = true
	name = "HermesWorkbench"
	custom_minimum_size = Vector2(640, 460)
	mouse_filter = Control.MOUSE_FILTER_STOP
	focus_mode = Control.FOCUS_ALL
	add_theme_stylebox_override("panel", _panel(Color(0.055, 0.07, 0.058, 0.985), GOLD, 16))
	var theme_resource := Theme.new()
	theme_resource.default_font_size = 16
	theme_resource.set_color("font_color", "Label", CREAM)
	theme_resource.set_color("font_color", "Button", CREAM)
	theme_resource.set_color("font_disabled_color", "Button", Color("7c8174"))
	theme_resource.set_stylebox("normal", "Button", _panel(Color("26332b"), Color("68705b"), 9))
	theme_resource.set_stylebox("hover", "Button", _panel(Color("354638"), GOLD, 9))
	theme_resource.set_stylebox("pressed", "Button", _panel(Color("17291d"), GOLD, 9))
	theme_resource.set_stylebox("disabled", "Button", _panel(Color("202820"), Color("464c40"), 9))
	theme_resource.set_stylebox("focus", "Button", _focus_style())
	theme_resource.set_stylebox("panel", "TabContainer", _panel(INK, Color("4c5546"), 12))
	theme_resource.set_stylebox("tab_selected", "TabContainer", _panel(Color("303b2e"), GOLD, 9))
	theme_resource.set_stylebox("tab_unselected", "TabContainer", _panel(Color("1c251e"), Color("485140"), 9))
	theme_resource.set_color("font_selected_color", "TabContainer", CREAM)
	theme_resource.set_color("font_unselected_color", "TabContainer", MUTED)
	theme = theme_resource
	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation", 8)
	add_child(content)
	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 10)
	content.add_child(header)
	var title := _label("Work with Hermes", 25, CREAM)
	var serif := SystemFont.new()
	serif.font_names = PackedStringArray(["Georgia", "Liberation Serif", "DejaVu Serif"])
	title.add_theme_font_override("font", serif)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(title)
	_refresh_button = _button("Refresh", 86)
	_refresh_button.pressed.connect(func() -> void: refresh_requested.emit())
	header.add_child(_refresh_button)
	var close_button := _button("Close", 70)
	close_button.tooltip_text = "Close workbench · Esc"
	close_button.pressed.connect(func() -> void: close_requested.emit())
	header.add_child(close_button)
	_connection_label = _label("Not connected", 14, MUTED)
	_connection_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	content.add_child(_connection_label)
	_tabs = TabContainer.new()
	_tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
	content.add_child(_tabs)
	_build_conversation()
	_build_tasks()
	_build_connection()
	_build_keyboard()
	update_state(_state)

func _panel(background: Color, border: Color, padding: int) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = background
	style.border_color = border
	style.set_border_width_all(1)
	style.set_corner_radius_all(4)
	style.content_margin_left = padding
	style.content_margin_right = padding
	style.content_margin_top = padding
	style.content_margin_bottom = padding
	return style

func _focus_style() -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = Color.TRANSPARENT
	style.border_color = CREAM
	style.set_border_width_all(2)
	style.set_corner_radius_all(4)
	return style

func _label(text_value: String, font_size: int, color: Color = CREAM) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return label

func _button(title: String, width: float = 90.0) -> Button:
	var button := Button.new()
	button.text = title
	button.custom_minimum_size = Vector2(width, 34)
	button.focus_mode = Control.FOCUS_ALL
	return button

func _plain_text_view() -> RichTextLabel:
	var view := RichTextLabel.new()
	view.bbcode_enabled = false
	view.selection_enabled = true
	view.context_menu_enabled = true
	view.scroll_active = true
	view.fit_content = false
	view.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	view.add_theme_font_size_override("normal_font_size", 16)
	view.add_theme_color_override("default_color", CREAM)
	view.add_theme_stylebox_override("normal", _panel(Color("131b17"), Color("414c3f"), 12))
	view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	view.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return view

func _build_conversation() -> void:
	var page := VBoxContainer.new()
	page.name = "Conversation"
	page.add_theme_constant_override("separation", 8)
	_tabs.add_child(page)
	var session_row := HBoxContainer.new()
	session_row.add_theme_constant_override("separation", 8)
	page.add_child(session_row)
	session_row.add_child(_label("Office conversations", 14, MUTED))
	_session_picker = OptionButton.new()
	_session_picker.custom_minimum_size = Vector2(120, 34)
	_session_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_session_picker.fit_to_longest_item = false
	_session_picker.item_selected.connect(_on_session_selected)
	session_row.add_child(_session_picker)
	_new_session_button = _button("New", 64)
	_new_session_button.pressed.connect(_on_new_session)
	session_row.add_child(_new_session_button)
	_voice_button = _button("Speak", 76)
	_voice_button.pressed.connect(_on_voice)
	session_row.add_child(_voice_button)
	_share_button = _button("Share view", 100)
	_share_button.tooltip_text = "Send one virtual office frame into this conversation. Passthrough cameras are separate."
	_share_button.pressed.connect(func() -> void: share_view_requested.emit())
	session_row.add_child(_share_button)
	_tool_activity = _label("", 13, GOLD)
	_tool_activity.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_tool_activity.max_lines_visible = 2
	_tool_activity.visible = false
	page.add_child(_tool_activity)
	_transcript = _plain_text_view()
	_transcript.custom_minimum_size.y = 80
	_transcript.name = "Transcript"
	page.add_child(_transcript)
	_permission_scroll = ScrollContainer.new()
	_permission_scroll.name = "PendingPermissions"
	_permission_scroll.custom_minimum_size.y = 88
	_permission_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_permission_scroll.visible = false
	page.add_child(_permission_scroll)
	_permission_stack = VBoxContainer.new()
	_permission_stack.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_permission_stack.add_theme_constant_override("separation", 8)
	_permission_scroll.add_child(_permission_stack)
	_capability_hint = _label("Chat is unavailable until a connection reports its capabilities.", 14, MUTED)
	_capability_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_capability_hint.max_lines_visible = 2
	page.add_child(_capability_hint)
	_composer = TextEdit.new()
	_composer.name = "Compose"
	_composer.custom_minimum_size.y = 70
	_composer.placeholder_text = "Write to Hermes…"
	_composer.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	_composer.add_theme_font_size_override("font_size", 16)
	_composer.add_theme_color_override("font_color", CREAM)
	_composer.add_theme_color_override("caret_color", GOLD)
	_composer.add_theme_color_override("font_placeholder_color", MUTED)
	_composer.add_theme_stylebox_override("normal", _panel(Color("111a14"), Color("67735b"), 10))
	_composer.add_theme_stylebox_override("focus", _panel(Color("111a14"), GOLD, 10))
	_composer.gui_input.connect(_on_composer_input)
	_composer.text_changed.connect(_refresh_controls)
	page.add_child(_composer)
	var send_row := HBoxContainer.new()
	send_row.add_theme_constant_override("separation", 8)
	page.add_child(send_row)
	_keyboard_hint = _label("Enter for a new line · Ctrl+Enter to send", 13, MUTED)
	_keyboard_hint.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_keyboard_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_keyboard_hint.max_lines_visible = 2
	send_row.add_child(_keyboard_hint)
	_stop_button = _button("Stop", 72)
	_stop_button.pressed.connect(_on_cancel)
	_stop_button.visible = false
	send_row.add_child(_stop_button)
	_send_button = _button("Send message", 134)
	_send_button.pressed.connect(_submit_message)
	send_row.add_child(_send_button)

func _build_tasks() -> void:
	var page := VBoxContainer.new()
	page.name = "Tasks"
	page.add_theme_constant_override("separation", 10)
	_tabs.add_child(page)
	page.add_child(_label("Task board · read only", 14, MUTED))
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	page.add_child(scroll)
	_task_stack = VBoxContainer.new()
	_task_stack.add_theme_constant_override("separation", 12)
	_task_stack.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(_task_stack)

func _build_keyboard() -> void:
	# Scrolling preserves every key at the minimum window height; at the XR
	# viewport's 1280x800 size the complete keyboard is visible together.
	var page := ScrollContainer.new()
	page.name = "Keyboard"
	page.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_tabs.add_child(page)
	var keys := VBoxContainer.new()
	keys.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	keys.add_theme_constant_override("separation", 6)
	page.add_child(keys)
	keys.add_child(_label("Message draft", 18, GOLD))
	_keyboard_preview = _plain_text_view()
	_keyboard_preview.name = "KeyboardDraft"
	_keyboard_preview.custom_minimum_size.y = 88
	_keyboard_preview.add_theme_font_size_override("normal_font_size", 22)
	_keyboard_preview.scroll_following = true
	keys.add_child(_keyboard_preview)
	_add_key_row(keys, "1234567890", "!@#$%^&*()")
	_add_key_row(keys, "qwertyuiop", "QWERTYUIOP")
	_add_key_row(keys, "asdfghjkl'", "ASDFGHJKL\"")
	_add_key_row(keys, "zxcvbnm,./", "ZXCVBNM;:?")
	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 5)
	keys.add_child(actions)
	_keyboard_shift = _keyboard_button("Shift", 76)
	_keyboard_shift.toggle_mode = true
	_keyboard_shift.toggled.connect(_on_keyboard_shift)
	actions.add_child(_keyboard_shift)
	var space := _keyboard_button("Space", 130)
	space.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	space.pressed.connect(insert_text.bind(" "))
	actions.add_child(space)
	var newline := _keyboard_button("New line", 100)
	newline.pressed.connect(insert_text.bind("\n"))
	actions.add_child(newline)
	var erase := _keyboard_button("Backspace", 112)
	erase.pressed.connect(backspace_text)
	actions.add_child(erase)
	_keyboard_status = _label("", 14, MUTED)
	_keyboard_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_keyboard_status.max_lines_visible = 2
	keys.add_child(_keyboard_status)
	var send_row := HBoxContainer.new()
	send_row.add_theme_constant_override("separation", 8)
	keys.add_child(send_row)
	var back := _button("View conversation", 180)
	back.custom_minimum_size.y = 44
	back.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	back.pressed.connect(func() -> void: _tabs.current_tab = 0)
	send_row.add_child(back)
	_keyboard_send = _button("Send message", 180)
	_keyboard_send.custom_minimum_size.y = 44
	_keyboard_send.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_keyboard_send.pressed.connect(_submit_message)
	send_row.add_child(_keyboard_send)

func _keyboard_button(title: String, width: float = 44.0) -> Button:
	var button := _button(title, width)
	button.custom_minimum_size.y = 48
	button.add_theme_font_size_override("font_size", 20)
	button.focus_mode = Control.FOCUS_NONE
	_keyboard_keys.append(button)
	return button

func _add_key_row(parent: VBoxContainer, lower: String, upper: String) -> void:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 5)
	parent.add_child(row)
	for index in range(lower.length()):
		var button := _keyboard_button(lower.substr(index, 1))
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		button.set_meta("lower", lower.substr(index, 1))
		button.set_meta("upper", upper.substr(index, 1))
		button.pressed.connect(_on_keyboard_character.bind(button))
		row.add_child(button)

func _on_keyboard_character(button: Button) -> void:
	insert_text(str(button.get_meta("upper" if _shift_enabled else "lower", "")))

func _on_keyboard_shift(enabled: bool) -> void:
	_shift_enabled = enabled
	_keyboard_shift.text = "Shift ON" if enabled else "Shift"
	for button in _keyboard_keys:
		if button.has_meta("lower"):
			button.text = str(button.get_meta("upper" if enabled else "lower"))

## These operations edit the one existing draft. No key sends it automatically.
func insert_text(text_value: String) -> void:
	if _composer == null or not _composer.editable or _permission_scroll.visible:
		return
	_composer.insert_text_at_caret(text_value)
	_refresh_controls()

func backspace_text() -> void:
	if _composer == null or not _composer.editable or _permission_scroll.visible:
		return
	_composer.backspace()
	_refresh_controls()

func _refresh_keyboard() -> void:
	if _keyboard_preview == null:
		return
	var preview := _composer.text if not _composer.text.is_empty() else "Your draft will appear here."
	if _keyboard_preview.text != preview:
		_keyboard_preview.text = preview
	var locked := not _composer.editable or _permission_scroll.visible
	for button in _keyboard_keys:
		button.disabled = locked
	_keyboard_send.disabled = _send_button.disabled or _permission_scroll.visible
	_keyboard_send.text = _send_button.text
	_keyboard_status.text = _capability_hint.text
	_keyboard_status.add_theme_color_override("font_color", _capability_hint.get_theme_color("font_color"))

func _build_connection() -> void:
	var page := VBoxContainer.new()
	page.name = "Connection"
	page.add_theme_constant_override("separation", 10)
	_tabs.add_child(page)
	page.add_child(_label("Connection and available actions", 18, GOLD))
	var ar_button := CheckButton.new()
	ar_button.text = "Passthrough mode (when the headset runtime supports it)"
	ar_button.toggled.connect(func(enabled: bool) -> void: passthrough_requested.emit(enabled))
	page.add_child(ar_button)
	_connection_details = _plain_text_view()
	page.add_child(_connection_details)
	_voice_status = _label("Voice status not reported", 14, MUTED)
	_voice_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_voice_status.max_lines_visible = 3
	page.add_child(_voice_status)

func _dictionary(value: Variant) -> Dictionary:
	return value if value is Dictionary else {}

func _array(value: Variant) -> Array:
	return value if value is Array else []

func _text(value: Variant, fallback: String = "") -> String:
	return fallback if value == null else str(value)

func _enabled(value: Variant) -> bool:
	return value is bool and value

func update_state(state: Dictionary) -> void:
	_state = state.duplicate(true)
	if not _built:
		setup()
		return
	_busy = _enabled(state.get("busy", false))
	if not _busy:
		_stop_requested = false
	# An authoritative state update ends the local double-click latch. The
	# parent should publish busy=true synchronously when handling a send signal.
	_locally_submitted = false
	var connection := _dictionary(state.get("connection", {}))
	var capabilities := _dictionary(connection.get("capabilities", {}))
	var status := _text(connection.get("status", "")).to_lower()
	var connected := status == "ready"
	_connected = connected
	_can_chat = connected and _enabled(capabilities.get("chat", false))
	_can_sessions = connected and _enabled(capabilities.get("sessions", false))
	_can_voice = connected and _enabled(capabilities.get("voice", false))
	_selected_session = _text(state.get("selected_session", ""))
	_connection_label.text = _text(connection.get("label", "Not connected"), "Not connected")
	_connection_label.add_theme_color_override("font_color", GOLD if connected else ERROR_COLOR)
	_connection_label.tooltip_text = _text(connection.get("reason", ""))
	if state.has("pending_message"):
		var pending := _text(state.get("pending_message", ""))
		if (not _has_pending_state or pending != _last_pending_state) and not (_awaiting_message_ack and pending.is_empty()):
			_composer.text = pending
			_has_pending_state = true
			_last_pending_state = pending
	_update_sessions(_array(state.get("sessions", [])))
	_update_messages(_array(state.get("messages", [])))
	_update_tasks(_dictionary(state.get("tasks", {})), state.has("tasks"))
	_update_tools(_array(state.get("tools", [])))
	_update_permissions(_array(state.get("permissions", [])))
	var reason := _text(connection.get("reason", "")).strip_edges()
	var details: Array[String] = [
		_connection_label.text,
		"Status: " + (status if not status.is_empty() else "Not reported"),
		"",
		"Hermes version: " + _text(connection.get("hermes_version", "Not reported"), "Not reported"),
		"ACP protocol: " + _text(connection.get("protocol_version", "Not reported"), "Not reported"),
		"",
		"Chat: " + ("Available" if _can_chat else "Unavailable"),
		"Sessions: " + ("Available" if _can_sessions else "Unavailable"),
		"Voice: " + ("Available" if _can_voice else "Unavailable"),
		"",
		"Only capabilities reported by this connection are enabled.",
		"Office conversations are separate from ordinary Telegram and CLI conversations; those histories are not listed here.",
		"The task board shows the supplied read-only snapshot."
	]
	if not reason.is_empty():
		details.append("\nConnection details\n" + reason)
	var controls_summary := _text(state.get("controls_summary", "")).strip_edges()
	var senses_summary := _text(state.get("senses_summary", "")).strip_edges()
	if not controls_summary.is_empty():
		details.append("\nQuest controls\n" + controls_summary)
	if not senses_summary.is_empty():
		details.append("\nShared senses\n" + senses_summary)
	var error := _text(state.get("error", "")).strip_edges()
	if not error.is_empty(): details.append("\nError\n" + error)
	var last_command := _dictionary(state.get("last_command", {}))
	if not last_command.is_empty():
		details.append("\nLast command\nID: " + _text(last_command.get("id", "Not reported")))
		details.append("Status: " + _text(last_command.get("status", "Not reported")))
		var command_error := _text(last_command.get("error", "")).strip_edges()
		if not command_error.is_empty(): details.append(command_error)
	_connection_details.text = "\n".join(details)
	var voice_title := _text(state.get("voice_title", "Voice status not reported"), "Voice status not reported")
	var voice_message := _text(state.get("voice_message", ""))
	_voice_status.text = voice_title + ("\n" + voice_message if not voice_message.is_empty() else "")
	_voice_button.tooltip_text = _voice_status.text
	_refresh_controls()

func _update_sessions(sessions: Array) -> void:
	var signature := JSON.stringify([sessions, _selected_session, _can_sessions])
	if signature == _session_signature:
		return
	_session_signature = signature
	_session_picker.clear()
	_session_picker.add_item("Choose a session" if _can_sessions else "Sessions unavailable")
	_session_picker.set_item_metadata(0, "")
	var ids: Dictionary = {}
	var selected_index := 0
	for item in sessions:
		if not item is Dictionary:
			continue
		var id := _text(item.get("id", ""))
		if id.is_empty() or ids.has(id):
			continue
		ids[id] = true
		var title := _text(item.get("title", id), id)
		if title.strip_edges().is_empty(): title = id
		_session_picker.add_item(title.left(100))
		var index := _session_picker.item_count - 1
		_session_picker.set_item_metadata(index, id)
		_session_picker.set_item_tooltip(index, title)
		if id == _selected_session: selected_index = index
	if not _selected_session.is_empty() and not ids.has(_selected_session):
		_session_picker.add_item(_selected_session.left(100))
		selected_index = _session_picker.item_count - 1
		_session_picker.set_item_metadata(selected_index, _selected_session)
	_session_picker.select(selected_index)

func _update_messages(messages: Array) -> void:
	var signature := JSON.stringify([_selected_session, messages])
	if signature == _message_signature:
		return
	_message_signature = signature
	var scrollbar := _transcript.get_v_scroll_bar()
	var follow := scrollbar.value + scrollbar.page >= scrollbar.max_value - 40.0
	var changed_session := _selected_session != _previous_message_session
	_previous_message_session = _selected_session
	var blocks: Array[String] = []
	for message in messages:
		if not message is Dictionary:
			continue
		var role := _text(message.get("role", "Message"), "Message")
		match role.to_lower():
			"user": role = "YOU"
			"assistant": role = "HERMES"
			_: role = role.to_upper()
		var content := _text(message.get("content", ""))
		blocks.append(role + "\n" + content)
	# BBCode is disabled. Even [url], [img], HTML and commands remain text.
	_transcript.text = "\n\n────────────────────────\n\n".join(blocks) if not blocks.is_empty() else "No messages in this conversation."
	if follow or changed_session:
		_scroll_to_latest.call_deferred()

func _scroll_to_latest() -> void:
	if is_instance_valid(_transcript):
		_transcript.scroll_to_line(maxi(0, _transcript.get_line_count() - 1))

func _update_tasks(tasks: Dictionary, reported: bool) -> void:
	var signature := JSON.stringify([reported, tasks])
	if signature == _task_signature:
		return
	_task_signature = signature
	for child in _task_stack.get_children():
		_task_stack.remove_child(child)
		child.queue_free()
	if not reported:
		_task_stack.add_child(_label("No task snapshot is available.", 16, MUTED))
		return
	for column in ["TODO", "RUNNING", "REVIEW", "DONE"]:
		var entries := _array(tasks.get(column, []))
		var group := PanelContainer.new()
		group.add_theme_stylebox_override("panel", _panel(Color("202920"), Color("48513f"), 12))
		_task_stack.add_child(group)
		var rows := VBoxContainer.new()
		rows.add_theme_constant_override("separation", 8)
		group.add_child(rows)
		rows.add_child(_label("%s · %d" % [column, entries.size()], 15, GOLD))
		if entries.is_empty():
			rows.add_child(_label("No tasks", 15, MUTED))
		for entry in entries:
			var title := ""
			if entry is Dictionary:
				title = _text(entry.get("title", entry.get("name", entry.get("task", "Untitled task"))))
			else:
				title = _text(entry)
			var row := _label("• " + title, 16)
			row.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
			rows.add_child(row)

func _refresh_controls() -> void:
	if not _built or _send_button == null:
		return
	var waiting := _busy or _locally_submitted or _awaiting_message_ack
	var permissions_visible := _permission_scroll.visible
	var needs_session := _selected_session.is_empty()
	_send_button.disabled = waiting or not _can_chat or needs_session or _composer.text.strip_edges().is_empty()
	_send_button.text = "Waiting…" if waiting else "Send message"
	_send_button.visible = not permissions_visible
	_composer.editable = not waiting
	_composer.visible = not permissions_visible
	_transcript.custom_minimum_size.y = 60 if permissions_visible else 80
	_keyboard_hint.text = "Choose one of the options supplied by Hermes." if permissions_visible else "Enter for a new line · Ctrl+Enter to send"
	_stop_button.visible = _busy
	_stop_button.disabled = _stop_requested
	_stop_button.text = "Stopping…" if _stop_requested else "Stop"
	_new_session_button.disabled = waiting or not _can_chat
	_session_picker.disabled = waiting or not _can_sessions
	_voice_button.disabled = waiting or not _can_voice or needs_session
	_share_button.disabled = waiting or not _can_chat or needs_session or not _enabled(_dictionary(_dictionary(_state.get("connection", {})).get("capabilities", {})).get("images", false))
	_refresh_button.disabled = waiting
	var connection := _dictionary(_state.get("connection", {}))
	var reason := _text(connection.get("reason", "")).strip_edges()
	var error := _text(_state.get("error", "")).strip_edges()
	var command := _dictionary(_state.get("last_command", {}))
	if error.is_empty(): error = _text(command.get("error", "")).strip_edges()
	_capability_hint.add_theme_color_override("font_color", MUTED)
	if not error.is_empty():
		_capability_hint.text = error
		_capability_hint.add_theme_color_override("font_color", ERROR_COLOR)
	elif permissions_visible:
		_capability_hint.text = "Hermes is waiting for your decision. No option is chosen automatically."
	elif waiting:
		_capability_hint.text = "Waiting for Hermes…" if _busy else "Message submitted. Waiting for acknowledgement…"
	elif not _can_chat:
		_capability_hint.text = reason if not reason.is_empty() else "Chat is unavailable on this connection. Open Connection for details."
		_capability_hint.add_theme_color_override("font_color", ERROR_COLOR)
	elif not reason.is_empty():
		_capability_hint.text = reason
		_capability_hint.add_theme_color_override("font_color", ERROR_COLOR)
	elif needs_session:
		_capability_hint.text = "Choose a session or create one to start a conversation."
	else:
		_capability_hint.text = "Your message will be sent to the selected Hermes conversation."
	_refresh_keyboard()

func _submit_message() -> void:
	_refresh_controls()
	if _send_button.disabled:
		return
	var content := _composer.text.strip_edges()
	_submitted_text = _composer.text
	_awaiting_message_ack = true
	_locally_submitted = true
	_refresh_controls()
	message_submitted.emit(content)

func acknowledge_message(accepted: bool) -> void:
	# Wire only to acknowledgement of this prompt command, not another action.
	# Rejected commands keep the draft; acceptance clears only the sent draft.
	if accepted and _composer.text == _submitted_text:
		_composer.text = ""
		_last_pending_state = ""
		_has_pending_state = true
	_awaiting_message_ack = false
	_locally_submitted = false
	_refresh_controls()

func _update_tools(tools: Array) -> void:
	var lines: Array[String] = []
	for entry in tools:
		if not entry is Dictionary:
			continue
		var title := _text(entry.get("title", entry.get("id", "Tool")))
		var status := _text(entry.get("status", "Status not reported"))
		lines.append(title + " · " + status)
	_tool_activity.visible = not lines.is_empty()
	_tool_activity.text = "\n".join(lines.slice(maxi(0, lines.size() - 2)))
	_tool_activity.tooltip_text = "\n".join(lines)

func _update_permissions(permissions: Array) -> void:
	var error := _text(_state.get("error", "")) + JSON.stringify(_state.get("last_command", {}))
	if error != _permission_error:
		_permission_error = error
		# Only a reported command error permits retrying a choice that failed.
		var command := _dictionary(_state.get("last_command", {}))
		if not _text(_state.get("error", "")).is_empty() or not _text(command.get("error", "")).is_empty():
			_permission_pending.clear()
	var active_ids: Dictionary = {}
	for permission in permissions:
		if permission is Dictionary:
			active_ids[_text(permission.get("id", ""))] = true
	for id in _permission_pending.keys():
		if not active_ids.has(id): _permission_pending.erase(id)
	var signature := JSON.stringify([permissions, _permission_pending, _connected, _stop_requested])
	if signature == _permission_signature:
		return
	var previously_visible := _permission_scroll.visible
	_permission_signature = signature
	for child in _permission_stack.get_children():
		_permission_stack.remove_child(child)
		child.queue_free()
	var count := 0
	for permission in permissions:
		if not permission is Dictionary:
			continue
		var id := _text(permission.get("id", ""))
		if id.is_empty():
			continue
		count += 1
		var title := _label(_text(permission.get("title", "Permission requested")), 15, GOLD)
		title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		_permission_stack.add_child(title)
		var options := _array(permission.get("options", []))
		var option_count := 0
		for option in options:
			if not option is Dictionary:
				continue
			var option_id := _text(option.get("id", ""))
			if option_id.is_empty() or not option.has("label"):
				continue
			option_count += 1
			var choice := _button(_text(option.get("label")), 0)
			choice.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
			choice.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			choice.disabled = not _connected or _stop_requested or _permission_pending.has(id)
			choice.tooltip_text = _text(option.get("label"))
			choice.pressed.connect(_on_permission_choice.bind(id, option_id))
			_permission_stack.add_child(choice)
		if option_count == 0:
			_permission_stack.add_child(_label("No selectable options were provided.", 14, ERROR_COLOR))
		elif _permission_pending.has(id):
			_permission_stack.add_child(_label("Decision sent. Waiting for acknowledgement…", 13, MUTED))
	_permission_scroll.visible = count > 0
	_tabs.set_tab_title(0, "Conversation · decision" if count > 0 else "Conversation")
	if count > 0 and not previously_visible:
		_tabs.current_tab = 0

func _on_permission_choice(id: String, option_id: String) -> void:
	if not _connected or _stop_requested or _permission_pending.has(id):
		return
	# Check against the current supplied choices; never invent an approval id.
	for permission in _array(_state.get("permissions", [])):
		if not permission is Dictionary or _text(permission.get("id", "")) != id:
			continue
		for option in _array(permission.get("options", [])):
			if option is Dictionary and _text(option.get("id", "")) == option_id:
				_permission_pending[id] = true
				_update_permissions(_array(_state.get("permissions", [])))
				permission_replied.emit(id, option_id)
				return

func _on_cancel() -> void:
	if not _busy or _stop_requested:
		return
	_stop_requested = true
	_refresh_controls()
	_update_permissions(_array(_state.get("permissions", [])))
	cancel_requested.emit()

func _on_session_selected(index: int) -> void:
	if _busy or not _can_sessions:
		return
	var id := _text(_session_picker.get_item_metadata(index))
	if not id.is_empty() and id != _selected_session:
		session_selected.emit(id)

func _on_new_session() -> void:
	if _can_chat and not _busy and not _locally_submitted:
		new_session_requested.emit()

func _on_voice() -> void:
	if _can_voice and not _busy and not _locally_submitted:
		voice_requested.emit()

func _on_composer_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_ENTER and (event.ctrl_pressed or event.meta_pressed):
			_composer.accept_event()
			_submit_message()
		elif event.keycode == KEY_ESCAPE:
			_composer.accept_event()
			close_requested.emit()

func _unhandled_key_input(event: InputEvent) -> void:
	if not is_visible_in_tree():
		return
	if event is InputEventKey:
		if event.pressed and not event.echo and event.keycode == KEY_ESCAPE:
			close_requested.emit()
		get_viewport().set_input_as_handled()

func focus_compose() -> void:
	if _composer and _composer.editable:
		_tabs.current_tab = 0
		_composer.grab_focus()

func draft_text() -> String:
	return _composer.text if _composer else ""
