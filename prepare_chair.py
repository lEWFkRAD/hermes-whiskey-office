"""Normalize the actual Object Studio chair for the native office; preserve source."""
import bpy, hashlib, json, math
from mathutils import Vector
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'assets/conversions/club-chair-v1/final.glb'
OUT=ROOT/'app/assets/club-chair.glb'
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(SOURCE))
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
bpy.context.view_layer.update()
points=[o.matrix_world@Vector(c) for o in meshes for c in o.bound_box]
low=Vector([min(v[a] for v in points) for a in range(3)])
high=Vector([max(v[a] for v in points) for a in range(3)])
scale=1.25/(high.x-low.x)
offset=Vector([(high.x+low.x)/2,(high.y+low.y)/2,low.z])
tri_before=sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in meshes)
for o in meshes:
    bpy.context.view_layer.objects.active=o
    o.select_set(True)
    matrix=o.matrix_world.copy()
    for v in o.data.vertices: v.co=(matrix@v.co-offset)*scale
    o.matrix_world.identity()
    ratio=min(1,60000/tri_before)
    mod=o.modifiers.new('Office polygon budget','DECIMATE'); mod.ratio=ratio; mod.use_collapse_triangulate=True
    bpy.ops.object.modifier_apply(modifier=mod.name)
    for poly in o.data.polygons: poly.use_smooth=True
    o.name='Cognac Club Chair'
    for mat in o.data.materials:
        if mat and mat.use_nodes:
            bs=next((n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
            if bs:
                # Keep actual base color/UV atlas. Leather is dielectric.
                for link in list(bs.inputs['Metallic'].links):mat.node_tree.links.remove(link)
                bs.inputs['Metallic'].default_value=0.0
                for link in list(bs.inputs['Roughness'].links):mat.node_tree.links.remove(link)
                bs.inputs['Roughness'].default_value=.52
                bs.inputs['Coat Weight'].default_value=.04
                bs.inputs['Coat Roughness'].default_value=.35
    o.select_set(False)
bpy.context.view_layer.update()
OUT.parent.mkdir(exist_ok=True,parents=True)
for o in meshes:o.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(OUT),export_format='GLB',use_selection=True,export_yup=True,export_animations=False)
scene=bpy.context.scene
scene.render.engine='CYCLES'; scene.cycles.device='CPU'; scene.cycles.samples=16
scene.cycles.use_denoising=True; scene.cycles.max_bounces=4
scene.render.threads_mode='FIXED'; scene.render.threads=8
scene.render.resolution_x=900; scene.render.resolution_y=800; scene.render.resolution_percentage=100
scene.world=bpy.data.worlds.new('Chair review'); scene.world.use_nodes=True
scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.22,.20,.17,1)
scene.world.node_tree.nodes['Background'].inputs[1].default_value=.45
scene.view_settings.view_transform='AgX'
for name,loc,power,size in [('Key',(-2,-3,3),400,3),('Fill',(2,-1,2),180,2),('Rim',(1,2,3),300,2)]:
    data=bpy.data.lights.new(name,'AREA'); data.energy=power;data.shape='DISK';data.size=size
    ob=bpy.data.objects.new(name,data);scene.collection.objects.link(ob);ob.location=loc
    ob.rotation_euler=(Vector((0,0,.4))-ob.location).to_track_quat('-Z','Y').to_euler()
data=bpy.data.cameras.new('Chair inspection');cam=bpy.data.objects.new('Chair inspection',data);scene.collection.objects.link(cam)
cam.location=(1.25,-2.1,1.10);target=Vector((0,0,.38));cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();data.lens=55
scene.camera=cam
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'assets/club-chair.blend'))
(ROOT/'renders').mkdir(exist_ok=True)
scene.render.filepath=str(ROOT/'renders/chair-inspection.png');bpy.ops.render.render(write_still=True)
points=[o.matrix_world@Vector(c) for o in meshes for c in o.bound_box]
report={'source':str(SOURCE.relative_to(ROOT)),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'output':str(OUT.relative_to(ROOT)),'output_sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'triangles_before':tri_before,'triangles_after':sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in meshes),'bounds_blender':[[min(p[a] for p in points) for a in range(3)],[max(p[a] for p in points) for a in range(3)]],'target_width_m':1.25,'source_preserved':True,'front_axis_blender':'-Y','front_axis_godot':'+Z'}
(ROOT/'chair-report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
