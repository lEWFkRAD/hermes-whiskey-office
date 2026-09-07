"""Reproducible, individually editable listening-room and botanical assemblies.

Run with the local bpy Python runtime. The existing room is never rebuilt.
Source parts, neutral libraries and batched geometry use the room's exporter.
"""
from pathlib import Path
import json, math, random, shutil
import bpy
from mathutils import Vector
from modeling.assemblies import AssemblyRegistry

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'assets' / 'decoration-source'
random.seed(916)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.context.preferences.filepaths.save_version = 0
A = AssemblyRegistry()
A.activate('office', 'Botanical listening collection', parent_id=None)
M = {}

def mat(name, color, rough=.5, metal=0, alpha=1, glow=0):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, alpha)
    m.use_nodes = True
    p = m.node_tree.nodes.get('Principled BSDF')
    for key, val in [('Base Color', (*color, 1)), ('Roughness', rough), ('Metallic', metal), ('Alpha', alpha)]:
        p.inputs[key].default_value = val
    if alpha < 1: m.surface_render_method = 'DITHERED'
    if glow:
        p.inputs['Emission Color'].default_value = (*color, 1)
        p.inputs['Emission Strength'].default_value = glow
    M[name] = m

for spec in [
    ('Walnut_4', (.28,.13,.055)), ('WalnutDeep', (.1,.035,.013)),
    ('Brass', (.52,.34,.12), .27,.92), ('BrassAged', (.28,.19,.085), .4,.85),
    ('AudioGraphite', (.023,.026,.027), .32,.7), ('AudioRubber', (.008,.01,.011), .72),
    ('AudioPaper', (.085,.091,.087), .82), ('AudioCeramic', (.76,.72,.62), .28),
    ('TubePlate', (.12,.14,.15), .39,.8), ('TubeFilament', (1,.23,.025), .3,0,1,4),
    ('TubeGlass', (.7,.86,.89), .1,0,.09), ('TerrariumGlass', (.68,.86,.8), .1,0,.075),
    ('Soil', (.048,.024,.013), .98), ('Gravel', (.36,.31,.22), .94),
    ('Rock', (.22,.26,.23), .92), ('Driftwood', (.17,.085,.038), .98),
    ('Moss', (.105,.20,.025), .96), ('Stem', (.065,.13,.022), .84),
    ('LeafForest', (.035,.16,.046), .48), ('LeafJade', (.065,.265,.073), .42),
    ('LeafLime', (.19,.36,.07), .51), ('LeafVein', (.29,.41,.11), .6),
    ('IvoryLetter', (.64,.61,.49), .5), ('TerrariumGlow', (.82,1,.67), .4,0,1,1.4),
]: mat(*spec)

def G(p): return Vector((p[0], -p[2], p[1]))
def finish(ob, name, material, bevel=0):
    ob.name = name
    ob.data.materials.append(M[material])
    if bevel:
        mod=ob.modifiers.new('Machined edge', 'BEVEL'); mod.width=bevel; mod.segments=2
        ob.modifiers.new('Weighted normals', 'WEIGHTED_NORMAL')
    return A.part(ob, name)
def box(name,p,size,m,bevel=.004):
    bpy.ops.mesh.primitive_cube_add(size=1, location=G(p))
    ob=bpy.context.object; ob.scale=(size[0],size[2],size[1])
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish(ob,name,m,bevel)
def cyl(name,p,r,h,m,axis=(0,1,0),r2=None,n=32):
    bpy.ops.mesh.primitive_cone_add(vertices=n, radius1=r, radius2=r if r2 is None else r2, depth=h, location=G(p))
    ob=bpy.context.object; ob.rotation_euler=G(axis).to_track_quat('Z','Y').to_euler()
    for face in ob.data.polygons: face.use_smooth=len(face.vertices)==4
    return finish(ob,name,m)
def rod(name,a,b,r,m):
    a,b=Vector(a),Vector(b)
    return cyl(name,(a+b)/2,r,(b-a).length,m,b-a,n=10)
def ball(name,p,scale,m):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=8,location=G(p))
    ob=bpy.context.object; ob.scale=(scale[0],scale[2],scale[1])
    for f in ob.data.polygons: f.use_smooth=True
    return finish(ob,name,m)
def ring(name,p,r,minor,m,axis=(0,1,0)):
    bpy.ops.mesh.primitive_torus_add(major_radius=r, minor_radius=minor,major_segments=40,minor_segments=8,location=G(p))
    ob=bpy.context.object; ob.rotation_euler=G(axis).to_track_quat('Z','Y').to_euler()
    for f in ob.data.polygons: f.use_smooth=True
    return finish(ob,name,m)

# Furniture local coordinates: u runs along the wall; v points into the room.
def P(u,y,v): return (-4.23+v,y,-3.15+u)
A.activate('listening-console', 'Walnut listening credenza', P(0,0,0), library=True)
box('Floating solid walnut top',P(0,.79,0),(.56,.065,1.54),'Walnut_4',.014)
box('Inset cabinet',P(0,.45,-.02),(.48,.59,1.42),'WalnutDeep',.013)
for u in [-.36,.36]:
    box('Raised walnut door',P(u,.46,.231),(.025,.48,.67),'Walnut_4',.006)
    rod('Brass door pull',P(u-.07,.60,.257),P(u+.07,.60,.257),.006,'Brass')
for u in [-.62,.62]:
    for v in [-.19,.19]:
        cyl('Isolation foot',P(u,.105,v),.027,.20,'AudioGraphite')
        cyl('Brass foot collar',P(u,.035,v),.029,.028,'Brass')

def speaker(u, label):
    A.activate(label, 'Walnut reference loudspeaker', P(u,0,0), library=True)
    box('Chamfered walnut enclosure',P(u,.81,.015),(.40,.92,.42),'Walnut_4',.022)
    box('Graphite inset baffle',P(u,.81,.222),(.022,.84,.362),'AudioGraphite',.008)
    box('Decoupled plinth',P(u,.285,.015),(.48,.075,.49),'AudioGraphite',.011)
    box('Weighted stand base',P(u,.04,.015),(.44,.06,.45),'AudioGraphite',.009)
    box('Short pedestal',P(u,.157,.015),(.20,.18,.20),'AudioGraphite',.007)
    for du in [-.16,.16]:
        for v in [-.12,.17]: cyl('Brass isolation spike',P(u+du,.32,v),.022,.07,'Brass',r2=.011)
    for y,r in [(.61,.142),(.955,.082),(1.125,.034)]:
        center=P(u,y,.243)
        cyl('Recessed driver basket',center,r+.014,.012,'AudioGraphite',axis=(1,0,0),n=48)
        ring('Rolled elastomer surround',P(u,y,.257),r-.01,.009,'AudioRubber',axis=(1,0,0))
        cyl('Dished paper diaphragm',P(u,y,.256),r-.016,.029,'AudioPaper',axis=(1,0,0),r2=r*.30,n=48)
        ball('Domed driver cap',P(u,y,.279),(.015,r*.31,r*.31),'AudioGraphite')
        if r>.05:
            for a in [0,math.pi/2,math.pi,3*math.pi/2]:
                cyl('Driver mounting screw',P(u+math.sin(a)*(r+.008),y+math.cos(a)*(r+.008),.254),.003,.003,'BrassAged',axis=(1,0,0),n=8)
    cyl('Bass reflex port',P(u,.43,.238),.032,.008,'AudioRubber',axis=(1,0,0))
    ring('Port chamfer',P(u,.43,.247),.032,.003,'AudioGraphite',axis=(1,0,0))
    box('Maker badge',P(u,1.215,.244),(.003,.018,.066),'Brass',.001)
speaker(-1.12,'speaker-left'); speaker(1.12,'speaker-right')

def amplifier(u,label):
    A.activate(label,'Single-ended vacuum tube amplifier',P(u,.825,0),library=True)
    box('Brushed chassis',P(u,.88,.045),(.37,.09,.37),'AudioGraphite',.009)
    box('Champagne faceplate',P(u,.88,.237),(.017,.075,.35),'Brass',.003)
    for du in [-.125,.125]:
        for v in [-.085,.17]: cyl('Rubber chassis foot',P(u+du,.832,v),.018,.024,'AudioRubber')
    for du in [-.095,.095]:
        box('Output transformer bell',P(u+du,1.00,-.067),(.14,.16,.143),'AudioGraphite',.015)
        for k in [-1,0,1]:box('Transformer lamination',P(u+du,1.01+k*.017,-.067),(.143,.003,.145),'TubePlate',.001)
    for du,h,r in [(-.105,.19,.031),(.105,.19,.031),(0,.13,.022)]:
        v=.095 if du else .17
        cyl('Ceramic tube socket',P(u+du,.937,v),r*1.1,.024,'AudioCeramic')
        cyl('Valve brass base',P(u+du,.959,v),r,.024,'BrassAged')
        cyl('Glass valve envelope',P(u+du,.969+h*.43,v),r,h*.86,'TubeGlass',n=32)
        ball('Rounded glass crown',P(u+du,.969+h*.86,v),(r,r*.48,r),'TubeGlass')
        box('Internal anode plate',P(u+du,.972+h*.39,v),(.027,h*.65,.024),'TubePlate',.002)
        for delta in [-.009,.009]:
            rod('Heater filament',P(u+du+delta,.975,v+.014),P(u+du+delta,.991+h*.60,v+.014),.0017,'TubeFilament')
        ring('Top getter',P(u+du,.969+h*.8,v),r*.62,.002,'TubePlate')
    for du in [-.11,.11]:
        cyl('Volume selector',P(u+du,.88,.258),.021,.024,'Brass',axis=(1,0,0))
        box('Selector index',P(u+du,.89,.272),(.002,.009,.002),'IvoryLetter',0)
    for i in range(9):box('Cooling vent',P(u-.105+i*.026,.927,-.14),(.027,.002,.009),'AudioRubber',0)
    cyl('Amber power jewel',P(u,.88,.248),.003,.004,'TubeFilament',axis=(1,0,0),n=12)
    for j in range(8):
        rod('Braided speaker lead',P(u+.14+math.sin(j*.6)*.017,.86-j*.068,-.22),P(u+.14+math.sin((j+1)*.6)*.017,.86-(j+1)*.068,-.22),.004,'AudioRubber')
amplifier(-.43,'tube-amplifier-left'); amplifier(.43,'tube-amplifier-right')

def leaf(name,base,tip,width,m):
    b,t=Vector(base),Vector(tip); direction=t-b
    across=direction.cross(Vector((0,1,0))).normalized()*width
    if across.length<.001: across=Vector((width,0,0))
    vertices=[];faces=[]
    # Curved outline and raised midrib replace the former four flat triangles.
    for j in range(7):
        v=j/6; bulge=math.sin(math.pi*v)**.78
        center=b+direction*v+Vector((0,width*.20*math.sin(math.pi*v),0))
        for side in [-1,0,1]:
            point=center+across*side*bulge
            if side==0:point+=Vector((0,width*.10*bulge,0))
            vertices.append(G(point))
    for j in range(6):
        for k in range(2):
            i=j*3+k;faces.append((i,i+1,i+4,i+3))
    me=bpy.data.meshes.new(name); me.from_pydata(vertices,[],faces)
    for face in me.polygons:face.use_smooth=True
    ob=bpy.data.objects.new(name,me);bpy.context.collection.objects.link(ob);finish(ob,name,m)
    rod('Leaf midrib',b,t,.0007,'LeafVein')

def terrarium(label,origin,w,d,h):
    A.activate(label,'Brass framed planted terrarium',origin,library=True)
    x,y,z=origin
    def T(a,b,c):return(x+a,y+b,z+c)
    box('Walnut display plinth',T(0,.025,0),(w+.036,.05,d+.036),'WalnutDeep',.009)
    box('Drainage gravel bed',T(0,.069,0),(w-.018,.039,d-.018),'Gravel',.005)
    box('Dark soil strata',T(0,.105,0),(w-.02,.037,d-.02),'Soil',.006)
    for dx in [-w/2,w/2]:
        for dz in [-d/2,d/2]:rod('Brass corner mullion',T(dx,.047,dz),T(dx,h,dz),.0035,'BrassAged')
    for sy in [.047,h]:
        for dz in [-d/2,d/2]:rod('Horizontal frame',T(-w/2,sy,dz),T(w/2,sy,dz),.0035,'BrassAged')
        for dx in [-w/2,w/2]:rod('Side frame',T(dx,sy,-d/2),T(dx,sy,d/2),.0035,'BrassAged')
    for dx in [-w/2,w/2]:box('Side glass pane',T(dx,(h+.05)/2,0),(.0015,h-.05,d),'TerrariumGlass',0)
    for dz in [-d/2,d/2]:box('Front rear glass pane',T(0,(h+.05)/2,dz),(w,h-.05,.0015),'TerrariumGlass',0)
    box('Glass lid',T(0,h,0),(w,.0015,d),'TerrariumGlass',0)
    rod('Lid grow light',T(-w*.35,h-.01,-d*.39),T(w*.35,h-.01,-d*.39),.0025,'TerrariumGlow')
    for _ in range(28):
        a=random.uniform(-w*.44,w*.44);c=random.uniform(-d*.4,d*.4);s=random.uniform(.008,.022)
        ball('River pebble',T(a,.129,c),(s,s*.5,s*.7),'Gravel')
    for _ in range(16):
        a=random.uniform(-w*.39,w*.39);c=random.uniform(-d*.36,d*.36)
        ball('Cushion moss',T(a,.135,c),(.025,.016,.023),'Moss')
    for i in range(3):ball('Slate outcrop',T((i-1)*w*.16,.151,-d*.16),(.042,.044,.034),'Rock')
    rod('Weathered branch',T(-w*.28,.13,0),T(w*.20,h*.51,-d*.19),.014,'Driftwood')
    # Six plants with curved stems and alternating, folded individual leaves.
    for i in range(6):
        a=random.uniform(-w*.32,w*.32);c=random.uniform(-d*.29,d*.29)
        height=random.uniform(h*.27,h*.57); angle=random.random()*math.tau
        start=Vector(T(a,.132,c));end=start+Vector((math.cos(angle)*.033,height,math.sin(angle)*.033))
        rod('Botanical stem',start,end,.0018,'Stem')
        for j in range(5):
            base=start+(end-start)*(.14+j*.16)
            for side in [-1,1]:
                theta=angle+j*.42+side*1.3
                reach=min(w*.19,.09)*(1-j*.12)
                tip=base+Vector((math.cos(theta)*reach,reach*.26,math.sin(theta)*reach))
                leaf('Lanceolate leaf',base,tip,reach*.25,['LeafForest','LeafJade','LeafLime'][(i+j)%3])
    box('Botanical specimen label',T(w*.22,.052,d/2+.006),(w*.24,.019,.002),'Brass',.001)

terrarium('listening-terrarium',P(0,.824,-.02),.32,.31,.47)
terrarium('desk-terrarium',(.91,.785,-2.85),.35,.28,.43)
terrarium('entry-terrarium',(3.49,.95,3.59),.36,.34,.57)

# Shared work island: a place for explicit file handoffs, with three machine trays.
A.activate('shared-work-island','Shared work and loading desk',(1.35,0,1.70),library=True)
box('Shared walnut desktop',(1.35,.80,1.70),(2.15,.075,.84),'Walnut_4',.022)
box('Inlaid graphite work mat',(1.35,.841,1.70),(1.95,.006,.68),'AudioGraphite',.006)
for x in [.48,2.22]:
    for z in [1.39,2.01]:
        box('Tapered desk leg',(x,.405,z),(.064,.74,.064),'WalnutDeep',.008)
        box('Brass leg shoe',(x,.054,z),(.067,.075,.067),'BrassAged',.004)
for i in range(3):
    x=.70+i*.65
    with A.assembly('handoff-tray-'+str(i),'Machine handoff tray '+str(i),(x,.85,1.72),parent_id='shared-work-island',render_group='shared-work-island'):
        box('Document tray base',(x,.853,1.72),(.52,.016,.42),'WalnutDeep',.007)
        for dx in [-.254,.254]:box('Tray side',(x+dx,.885,1.72),(.013,.064,.42),'BrassAged',.002)
        box('Tray rear',(x,.885,1.925),(.52,.064,.012),'BrassAged',.002)
        box('Machine name plate',(x,.872,1.503),(.20,.03,.005),'Brass',.002)

from modeling.lounge_collection import build as build_lounge_collection
build_lounge_collection(globals())
from modeling.podium_collection import build as build_podium_collection
build_podium_collection(globals())

manifest=A.export(OUT)
destination=ROOT/'app/assets/office-decorations.glb'
shutil.copy2(OUT/'app/assets/whiskey-room.glb',destination)
(ROOT/'decorations-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
# Ship the same neutral assemblies for live projection, without re-modeling.
library=ROOT/'app/assets/decoration-library'
library.mkdir(exist_ok=True)
catalogue=[]
for spec in manifest['assemblies']:
    if not spec.get('library_path'): continue
    source=OUT/'app'/spec['library_path'].removeprefix('res://')
    shutil.copy2(source,library/source.name)
    catalogue.append({'id':spec['id'],'name':spec['name'],'library_path':'res://assets/decoration-library/'+source.name})
(ROOT/'app/hologram-catalogue.json').write_text(json.dumps(catalogue,indent=2)+'\n')
print('DECORATIONS',json.dumps(manifest['inventory']),flush=True)
