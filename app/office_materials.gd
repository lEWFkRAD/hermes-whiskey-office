extends RefCounted
## Photographed PBR maps, shared across furniture to retain batching and memory.
var materials: Dictionary = {}
var textures: Dictionary = {}

func texture(path: String) -> Texture2D:
	if not textures.has(path):
		var source := Image.new()
		if source.load(ProjectSettings.globalize_path(path)) != OK: return null
		source.generate_mipmaps(path.contains("nor_gl"))
		textures[path] = ImageTexture.create_from_image(source)
	return textures[path]

func refine(source: StandardMaterial3D) -> StandardMaterial3D:
	var key := source.resource_name
	if materials.has(key): return materials[key]
	var result := source.duplicate() as StandardMaterial3D
	result.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	if key.begins_with("Walnut"):
		result.albedo_texture = texture("res://assets/pbr/dark_wood_diff_2k.jpg")
		result.uv1_triplanar = true
		result.uv1_world_triplanar = true
		result.uv1_scale = Vector3(0.8, 0.8, 0.8)
		var variation := 0.80
		if key.begins_with("Walnut_"): variation = 0.76 + float(key.trim_prefix("Walnut_").to_int()) * 0.028
		if key == "WalnutDeep": variation = 0.55
		result.albedo_color = Color(variation * 0.88, variation * 0.97, variation)
		result.normal_enabled = true
		result.normal_texture = texture("res://assets/pbr/dark_wood_nor_gl_2k.jpg")
		result.normal_scale = 0.07
		result.roughness_texture = null
		result.roughness = 0.72
		result.metallic = 0.0
		result.metallic_specular = 0.5
		result.clearcoat_enabled = false
	elif key == "Brass" or key == "BrassAged":
		result.metallic = 0.92
		result.roughness = 0.28 if key == "Brass" else 0.42
	elif key in ["BottleAmber", "BottleGreen", "Crystal"]:
		result.metallic = 0.0
		result.roughness = 0.12
		result.metallic_specular = 0.65
		result.clearcoat_enabled = true
		result.clearcoat = 0.8
		result.clearcoat_roughness = 0.08
		if key == "Crystal":
			result.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
			result.albedo_color = Color(0.84, 0.88, 0.87, 0.24)
	elif key in ["TerrariumGlass", "TubeGlass"]:
		result.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		result.albedo_color = Color(0.70, 0.86, 0.82, 0.055 if key == "TerrariumGlass" else 0.10)
		result.roughness = 0.09
		result.metallic = 0.0
		result.cull_mode = BaseMaterial3D.CULL_BACK
	elif key == "CutCrystal":
		result.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		result.albedo_color = Color(0.82, 0.91, 0.90, 0.08)
		result.roughness = 0.08
		result.metallic = 0.0
		result.clearcoat_enabled = true
		result.clearcoat = 0.35
		result.metallic_specular = 0.35
	elif key == "LinenLamp":
		result.cull_mode = BaseMaterial3D.CULL_DISABLED
		result.emission_enabled = true
		result.emission = Color("ffd6a1")
		result.emission_energy_multiplier = 0.22
	elif key.begins_with("Leaf"):
		result.cull_mode = BaseMaterial3D.CULL_DISABLED
	elif key == "LampGlow":
		result.emission_energy_multiplier = 0.45
	elif key in ["CeilingPlaster", "OlivePlaster"]:
		result.albedo_texture = texture("res://assets/pbr/white_plaster_02_diff_2k.jpg")
		result.albedo_color = Color("64695b") if key == "CeilingPlaster" else Color("515947")
		result.normal_enabled = true
		result.normal_texture = texture("res://assets/pbr/white_plaster_02_nor_gl_2k.jpg")
		result.normal_scale = 0.12
		result.uv1_triplanar = true
		result.uv1_world_triplanar = true
		result.uv1_scale = Vector3(0.3, 0.3, 0.3)
		result.roughness = 0.95
		result.metallic_specular = 0.15
	elif key == "Bone":
		result.albedo_color = Color("d5d0bc")
		result.roughness = 0.56
	materials[key] = result
	return result
