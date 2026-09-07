extends Node3D
## Visuals consume the same aim sample and hit geometry as interaction.
## No model calls, input events or scene mutations originate here.
var bodies: Array[MeshInstance3D] = []
var bones: Array[MultiMeshInstance3D] = []
var beam: MeshInstance3D
var dot: MeshInstance3D
var caption: Label3D
var material: StandardMaterial3D
var hit_distance := INF

func setup() -> void:
	material = StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = Color("65dbef")
	for side in 2:
		var body := MeshInstance3D.new()
		var capsule := CapsuleMesh.new()
		capsule.radius = 0.022
		capsule.height = 0.12
		body.mesh = capsule
		body.material_override = material
		body.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(body)
		body.hide()
		bodies.append(body)
		var skeleton := MultiMeshInstance3D.new()
		var multimesh := MultiMesh.new()
		multimesh.transform_format = MultiMesh.TRANSFORM_3D
		var bone := CylinderMesh.new()
		bone.top_radius = 0.0035
		bone.bottom_radius = 0.0035
		bone.height = 1.0
		bone.radial_segments = 6
		multimesh.mesh = bone
		multimesh.instance_count = 25
		multimesh.visible_instance_count = 0
		skeleton.multimesh = multimesh
		skeleton.material_override = material
		skeleton.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(skeleton)
		bones.append(skeleton)
	beam = MeshInstance3D.new()
	var cylinder := CylinderMesh.new()
	cylinder.top_radius = 0.0015
	cylinder.bottom_radius = 0.0025
	cylinder.height = 1.0
	cylinder.radial_segments = 8
	beam.mesh = cylinder
	beam.material_override = material.duplicate()
	beam.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(beam)
	dot = MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = 0.008
	sphere.height = 0.016
	sphere.radial_segments = 12
	sphere.rings = 6
	dot.mesh = sphere
	dot.material_override = beam.material_override
	dot.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(dot)
	caption = Label3D.new()
	caption.font_size = 24
	caption.pixel_size = 0.001
	caption.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	caption.modulate = Color("b5f4ff")
	add_child(caption)
	beam.hide()
	dot.hide()
	caption.hide()

static func segment(a: Vector3, b: Vector3) -> Transform3D:
	var delta := b - a
	if delta.length_squared() < 0.00000001: return Transform3D(Basis.from_scale(Vector3.ZERO), a)
	var y := delta.normalized()
	var x := y.cross(Vector3.FORWARD if absf(y.z) < 0.9 else Vector3.RIGHT).normalized()
	return Transform3D(Basis(x, y * delta.length(), x.cross(y)), (a + b) * 0.5)

func tracked_body(side: int, hand: Dictionary, active: bool, grip: Transform3D) -> void:
	var edges: Array = hand.get("bones", []) if hand.get("valid", false) else []
	var count := mini(edges.size(), 25)
	bones[side].multimesh.visible_instance_count = count
	for i in count:
		bones[side].multimesh.set_instance_transform(i, segment(edges[i][0], edges[i][1]))
	bodies[side].visible = active and not hand.get("valid", false)
	if bodies[side].visible: bodies[side].global_transform = grip

func aim(valid: bool, origin: Vector3, direction: Vector3, distance: float, target: String, pressed: bool, menu_open: bool) -> void:
	hit_distance = distance
	var show_ray := valid and origin.is_finite() and direction.is_finite() and direction.length_squared() > 0.9 and not menu_open
	beam.visible = show_ray
	dot.visible = show_ray
	caption.visible = show_ray and not target.is_empty()
	if not show_ray: return
	var length := distance if is_finite(distance) else 2.0
	var endpoint := origin + direction.normalized() * maxf(length, 0.02)
	beam.global_transform = segment(origin, endpoint)
	dot.global_position = endpoint
	caption.global_position = endpoint + Vector3(0, 0.045, 0)
	caption.text = target.left(55)
	(beam.material_override as StandardMaterial3D).albedo_color = Color("ffd18a") if pressed else (Color("b6ffdd") if not target.is_empty() else Color("65dbef"))
