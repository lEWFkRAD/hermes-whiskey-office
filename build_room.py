"""Build the editable, textured whiskey study; CPU-only Blender Python.

Coordinate helpers accept Godot world coordinates (x, up, z).
Run with the task-local bpy Python runtime. No external assets or services.
"""
from pathlib import Path
import argparse, json, math, random, sys
import bpy
import numpy as np
from mathutils import Vector
from modeling.assemblies import AssemblyRegistry
from modeling.workstation import build_monitor, build_keyboard, build_computer

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-root', type=Path, help='Write a separate candidate tree instead of replacing current assets')
parser.add_argument('--no-render', action='store_true')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:])
ROOT=(args.output_root or Path(__file__).resolve().parent).resolve()
ASSET=ROOT/'assets'; TEX=ASSET/'textures'; OUT=ROOT/'app'/'assets'; RENDER=ROOT/'renders'
for p in [ASSET,TEX,OUT,RENDER]: p.mkdir(parents=True,exist_ok=True)
random.seed(1844)
bpy.context.preferences.filepaths.save_version=0
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
for m in list(bpy.data.materials): bpy.data.materials.remove(m)
M={}; LIGHTS=[]
A=AssemblyRegistry()
A.activate('office', 'Hermes private study', parent_id=None, role='room')

def image(name, pixels, noncolor=False):
    a=np.asarray(pixels,dtype=np.float32)
    if a.ndim==2: a=np.repeat(a[:,:,None],3,axis=2)
    if a.shape[-1]==3: a=np.concatenate((a,np.ones((*a.shape[:2],1),np.float32)),axis=2)
    a=np.clip(a,0,1)
    im=bpy.data.images.new(name,width=a.shape[1],height=a.shape[0],alpha=True)
    if noncolor: im.colorspace_settings.name='Non-Color'
    im.pixels.foreach_set(a.ravel()); im.filepath_raw=str(TEX/(name+'.png')); im.file_format='PNG'; im.save()
    return im

def normal_image(name,height,strength=1):
    gy,gx=np.gradient(height)
    n=np.stack((-gx*strength,-gy*strength,np.ones_like(gx)),axis=2)
    n/=np.linalg.norm(n,axis=2)[:,:,None]
    return image(name,n*.5+.5,True)

def noise_grid(n=512,seed=7):
    rng=np.random.default_rng(seed)
    y,x=np.mgrid[0:1:complex(n),0:1:complex(n)]
    h=np.zeros((n,n),np.float32)
    for frequency,amp in [(1,.5),(3,.25),(9,.14),(24,.08),(71,.035),(181,.013)]:
        for _ in range(3):
            phase=rng.uniform(0,math.tau); angle=rng.uniform(0,math.tau)
            h+=np.sin((x*math.cos(angle)+y*math.sin(angle))*frequency*math.tau+phase)*amp/3
    return (h-h.min())/(h.max()-h.min()),x,y

def material(name,color,rough=.5,metal=0,tex=None,normal=None,emission=None):
    m=bpy.data.materials.new(name); m.diffuse_color=(*color,1); m.use_nodes=True
    p=m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value=(*color,1); p.inputs['Roughness'].default_value=rough; p.inputs['Metallic'].default_value=metal
    if tex:
        n=m.node_tree.nodes.new('ShaderNodeTexImage'); n.image=tex
        if color != (1,1,1):
            mix=m.node_tree.nodes.new('ShaderNodeMixRGB'); mix.blend_type='MULTIPLY'; mix.inputs[0].default_value=1; mix.inputs[2].default_value=(*color,1)
            m.node_tree.links.new(n.outputs['Color'],mix.inputs[1]); m.node_tree.links.new(mix.outputs[0],p.inputs['Base Color'])
        else: m.node_tree.links.new(n.outputs['Color'],p.inputs['Base Color'])
    if normal:
        n=m.node_tree.nodes.new('ShaderNodeTexImage'); n.image=normal
        norm=m.node_tree.nodes.new('ShaderNodeNormalMap'); norm.inputs['Strength'].default_value=.32
        m.node_tree.links.new(n.outputs['Color'],norm.inputs['Color']); m.node_tree.links.new(norm.outputs['Normal'],p.inputs['Normal'])
    if emission:
        p.inputs['Emission Color'].default_value=(*emission[0],1); p.inputs['Emission Strength'].default_value=emission[1]
    M[name]=m; return m

# Actual bitmap texture maps survive glTF export; no renderer-only procedural nodes.
h,x,y=noise_grid(1024,4)
grain=.5+.3*np.sin(y*410+np.sin(x*13+y*6)*3+h*12)+.1*np.sin(y*1540+h*26)
pores=np.maximum(0,np.sin(y*2740+x*11)-.91)*2
wood=np.clip(.48+.34*h+.18*grain-pores,0,1)
wood_rgb=np.stack((.22+wood*.29,.082+wood*.17,.032+wood*.09),axis=2)
woodtex=image('walnut-quarter-sawn',wood_rgb); woodnorm=normal_image('walnut-open-pore-normal',wood,6)
for i in range(6):
    # Individual baked bitmap variation keeps the PBR exporter graph simple.
    t=image('walnut-tone-'+str(i),np.clip(wood_rgb*(.73+i*.082),0,1))
    material('Walnut_'+str(i),(1,1,1),.32,tex=t,normal=woodnorm)
material('WalnutDeep',(1,1,1),.38,tex=image('walnut-dark',wood_rgb*.56),normal=woodnorm)
material('Brass',(0.50,.31,.105),.26,.82)
material('BrassAged',(.30,.195,.065),.46,.72)
material('BlackSteel',(.021,.026,.025),.33,.6)
h,x,y=noise_grid(768,12)
vein=np.abs(np.sin(x*13+y*4+h*10)); vein=np.maximum(0,.09-vein)*2
stone=np.stack((.40+h*.21-vein,.355+h*.18-vein,.278+h*.15-vein),axis=2)
material('Limestone',(1,1,1),.68,tex=image('honed-limestone',stone),normal=normal_image('limestone-normal',h,5))
h,x,y=noise_grid(512,81)
plaster=np.stack((.132+h*.060,.155+h*.067,.108+h*.045),axis=2)
material('OlivePlaster',(1,1,1),.88,tex=image('olive-lime-plaster',plaster),normal=normal_image('plaster-normal',h,10))
material('CeilingPlaster',(.235,.245,.17),.9)
material('Cream',(.65,.58,.40),.64)
leath=.35+.21*h+.065*np.sin(x*390)*np.sin(y*320)
material('OxbloodLeather',(1,1,1),.47,tex=image('oxblood-grained-leather',np.stack((leath*.29,leath*.12,leath*.08),axis=2)),normal=normal_image('leather-pebble-normal',leath,12))
material('ForestLeather',(.022,.054,.037),.5,normal=bpy.data.images['leather-pebble-normal'])
material('Ink',(.008,.012,.011),.66)
material('Paper',(.71,.665,.51),.86)
material('Bone',(.76,.68,.48),.38)
material('WarmShade',(.78,.62,.36),.85,emission=((1,.62,.27),.32))
material('LampGlow',(.95,.63,.26),.3,emission=((1,.46,.12),3.5))
material('Ember',(.49,.044,.009),.75,emission=((1,.10,.008),3.7))
material('Charcoal',(.012,.009,.006),.92)
material('BottleAmber',(.29,.090,.012),.14,.1)
material('BottleGreen',(.019,.075,.039),.12,.15)
material('Crystal',(.36,.37,.30),.085,.55)
material('Whiskey',(.45,.16,.028),.18,.15)
for name,c in [('BookWine',(.21,.04,.027)),('BookOlive',(.09,.12,.071)),('BookNavy',(.025,.062,.074)),('BookTan',(.25,.135,.058)),('BookCream',(.45,.37,.22))]:
    material(name,c,.62,normal=bpy.data.images['leather-pebble-normal'])
# Woven Persian-style rug with small floral motifs and an ornate medallion.
n=1536; yy,xx=np.mgrid[-1:1:complex(n),-1:1:complex(n)]
edge=np.maximum(abs(xx),abs(yy));theta=np.arctan2(yy,xx);rr=np.sqrt((xx*.93)**2+(yy*1.18)**2)
base=np.zeros((n,n,3),np.float32); base[:]=[.255,.105,.070]
base[edge>.935]=[.11,.12,.085]
for lo,hi in [(.917,.927),(.775,.785),(.749,.757),(.706,.714)]:base[(edge>lo)&(edge<hi)]=[.46,.335,.185]
base[(edge>.791)&(edge<.910)]=[.098,.143,.126]
lx=((xx+.071)%.153-.0765)/.0765;ly=((yy+.051)%.153-.0765)/.0765
lr=np.sqrt(lx*lx+ly*ly);la=np.arctan2(ly,lx)
petal=.33+.115*np.cos(la*8)
motif=(lr<petal)&(edge<.705)
base[motif]=[.40,.267,.129];base[(lr<petal*.55)&(edge<.705)]=[.125,.176,.151]
vine=(np.abs(np.sin(xx*65+np.sin(yy*14)*.7)+np.sin(yy*65))<.055)&(edge<.705)
base[vine]=[.37,.225,.13]
# Alternating ivory palmettes inside the main border.
along=np.where(abs(xx)>abs(yy),yy,xx);across=(edge-.85)/.055
bx=((along+.031)%.137-.0685)/.0685;br=np.sqrt(bx*bx+across*across);ba=np.arctan2(across,bx)
bp=.59+.12*np.cos(ba*6)
base[(br<bp)&(edge>.795)&(edge<.906)]=[.47,.347,.194]
base[(br<bp*.5)&(edge>.795)&(edge<.906)]=[.28,.111,.06]
med=.365*(1+.075*np.cos(theta*12)+.018*np.cos(theta*36))
base[rr<med]=[.485,.346,.177];base[rr<med*.94]=[.10,.16,.139]
base[rr<med*.88]=[.19,.24,.18];base[rr<med*.835]=[.11,.17,.15]
decoration=(np.abs(np.sin(theta*18)+np.sin(rr*142))<.25)&(rr<med*.79)&(rr>med*.28)
base[decoration]=[.46,.329,.16]
base[rr<med*.34]=[.49,.33,.155];base[rr<med*.29]=[.27,.115,.065]
base[(rr<med*.24)&(np.cos(theta*12)>.25)]=[.46,.31,.14]
# Yarn, faded dye and scattered worn knots avoid a flat printed texture.
rng=np.random.default_rng(67);noise=rng.uniform(.84,1.09,(n,n)).astype(np.float32)
wear=.91+.05*np.sin(xx*35+np.sin(yy*11)*4)+.04*np.cos(yy*28+xx*17)
weave=.91+.075*np.sin(xx*2380)*np.sin(yy*2170)
base*=((weave*wear*noise)[:,:,None])
material('PersianRug',(1,1,1),.98,tex=image('handwoven-tabriz-rug',base))

def G(p): return (p[0],-p[2],p[1])
def box(name,p,size,mat,bevel=.008,rot=0,uv=1,part_id=None,role=None):
    # Local Blender vertices; UVs preserve material maps through glTF.
    sx,sy,sz=size[0]/2,size[2]/2,size[1]/2
    verts=[(-sx,-sy,-sz),(sx,-sy,-sz),(sx,sy,-sz),(-sx,sy,-sz),(-sx,-sy,sz),(sx,-sy,sz),(sx,sy,sz),(-sx,sy,sz)]
    faces=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    mesh=bpy.data.meshes.new(name); mesh.from_pydata(verts,[],faces); mesh.update()
    ob=bpy.data.objects.new(name,mesh); bpy.context.collection.objects.link(ob); ob.location=G(p); ob.rotation_euler.z=-rot
    mesh.materials.append(M[mat]); layer=mesh.uv_layers.new(name='UVMap')
    for poly in mesh.polygons:
        for li,co in zip(poly.loop_indices,[(0,0),(uv,0),(uv,uv),(0,uv)]): layer.data[li].uv=co
    if bevel:
        mod=ob.modifiers.new('Crafted edge radii','BEVEL'); mod.width=min(bevel,min(size)*.35); mod.segments=1 if min(size)<.08 else 2
        mod=ob.modifiers.new('Weighted surface normals','WEIGHTED_NORMAL')
    return A.part(ob,name,part_id,role)

def cyl(name,p,radius,depth,mat,vertices=24,rotation=None,rad2=None,part_id=None,role=None):
    rad2=radius if rad2 is None else rad2
    verts=[(math.cos(i*math.tau/vertices)*r,math.sin(i*math.tau/vertices)*r,h) for r,h in [(radius,-depth/2),(rad2,depth/2)] for i in range(vertices)]
    faces=[tuple(reversed(range(vertices))),tuple(range(vertices,vertices*2))]+[(i,(i+1)%vertices,(i+1)%vertices+vertices,i+vertices) for i in range(vertices)]
    me=bpy.data.meshes.new(name);me.from_pydata(verts,[],faces);me.update()
    ob=bpy.data.objects.new(name,me);bpy.context.collection.objects.link(ob);ob.location=G(p);ob.data.materials.append(M[mat])
    uv=me.uv_layers.new(name='UVMap')
    for poly in me.polygons:
        for li,vi in zip(poly.loop_indices,poly.vertices):uv.data[li].uv=(vi%vertices/vertices,vi//vertices)
    if rotation: ob.rotation_euler=rotation
    for poly in ob.data.polygons: poly.use_smooth=len(poly.vertices)==4
    mod=ob.modifiers.new('Soft machined edges','BEVEL');mod.width=min(.005,depth*.12,radius*.15);mod.segments=1
    ob.modifiers.new('Weighted normals','WEIGHTED_NORMAL')
    return A.part(ob,name,part_id,role)

def sphere(name,p,scale,mat,segments=20,rings=12,part_id=None,role=None):
    verts=[(math.sin(j*math.pi/rings)*math.cos(i*math.tau/segments),math.sin(j*math.pi/rings)*math.sin(i*math.tau/segments),math.cos(j*math.pi/rings)) for j in range(rings+1) for i in range(segments)]
    faces=[(j*segments+i,(j+1)*segments+i,(j+1)*segments+(i+1)%segments,j*segments+(i+1)%segments) for j in range(rings) for i in range(segments)]
    me=bpy.data.meshes.new(name);me.from_pydata(verts,[],faces);me.update();ob=bpy.data.objects.new(name,me);bpy.context.collection.objects.link(ob);ob.location=G(p)
    ob.scale=scale[0],scale[2],scale[1];ob.data.materials.append(M[mat])
    for f in ob.data.polygons:f.use_smooth=True
    return A.part(ob,name,part_id,role)

def rod(name,a,b,r,mat,part_id=None,role=None):
    mid=tuple((a[i]+b[i])/2 for i in range(3)); vec=Vector(G(b))-Vector(G(a))
    ob=cyl(name,mid,r,vec.length,mat,16,part_id=part_id,role=role); ob.rotation_euler=vec.to_track_quat('Z','Y').to_euler();return ob

def text_mesh(name,text,p,size,mat,rotation=(math.pi/2,0,0),align='CENTER',part_id=None,role=None):
    data=bpy.data.curves.new(name,'FONT');ob=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(ob);ob.location=G(p);ob.data.body=text;ob.data.size=size;ob.data.align_x=align;ob.data.extrude=.0007;ob.data.bevel_depth=.0003;ob.data.resolution_u=3;ob.rotation_euler=rotation;ob.data.materials.append(M[mat]);return A.part(ob,name,part_id,role)

def light(name,p,power,color,radius=.25):
    data=bpy.data.lights.new(name,'POINT');data.energy=power;data.color=color;data.shadow_soft_size=radius
    ob=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(ob);ob.location=G(p)
    LIGHTS.append(dict(name=name,position=list(p),color=list(color),energy=power,radius=radius)); return ob

def area(name,p,target,power,color,size):
    data=bpy.data.lights.new(name,'AREA');data.energy=power;data.color=color;data.shape='DISK';data.size=size
    ob=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(ob);ob.location=G(p);ob.rotation_euler=(Vector(G(target))-ob.location).to_track_quat('-Z','Y').to_euler();return ob

def molding(name,p,length,along='x',mat='WalnutDeep',scale=1):
    # Stepped ogee-like layered profiles; all dimensions are actual meters.
    for j,(height,depth) in enumerate([(.038,.066),(.030,.098),(.022,.120)]):
        size=(length,height*scale,depth*scale) if along=='x' else (depth*scale,height*scale,length)
        q=list(p);q[1]+=j*.028*scale;box(name+str(j),q,size,mat,.008)

print('Building architecture',flush=True)
A.activate('floor', 'Parquet floor', role='architecture_floor')
box('Foundation',(0,-.075,0),(10.2,.15,12.2),'WalnutDeep',0)
# Alternating five-board parquet; slim seams give the floor physical depth.
for ix in range(11):
    for iz in range(13):
        bx=-4.95+ix*.9; bz=-5.85+iz*.9
        for k in range(5):
            if (ix+iz)%2: p=(bx+k*.18+.09,.010,bz+.45);size=(.177,.021,.897)
            else:p=(bx+.45,.010,bz+k*.18+.09);size=(.897,.021,.177)
            box('Parquet',p,size,'Walnut_'+str(random.randrange(6)),.003,part_id=f'parquet-{ix:02d}-{iz:02d}-{k}',role='floor_board')
for z in [-5.96,5.96]:box('Perimeter parquet border',(0,.012,z),(10,.023,.16),'WalnutDeep',.003)
for x0 in [-4.94,4.94]:box('Perimeter parquet border',(x0,.012,0),(.12,.023,11.9),'WalnutDeep',.003)
for x0 in [-4.83,4.83]:box('Floor brass inlay',(x0,.026,0),(.009,.003,11.72),'BrassAged',.001)
for z in [-5.82,5.82]:box('Floor brass inlay',(0,.026,z),(9.66,.003,.009),'BrassAged',.001)

A.activate('back-wall', 'Back wall paneling', (0,0,-6), role='architecture_wall')
box('Back lime plaster',(0,2.30,-6),(10,.0+2.7,.20),'OlivePlaster',.01,uv=4)
box('Back wainscot backing',(0,.55,-5.98),(10,1.1,.20),'WalnutDeep',.005)
for side in [-1,1]:
    A.activate('left-wall' if side<0 else 'right-wall', 'Left wall paneling' if side<0 else 'Right wall paneling', (side*5,0,0), role='architecture_wall')
    x0=side*5
    box('Side olive plaster',(x0,2.3,0),(.20,2.7,12),'OlivePlaster',.006,uv=4)
    box('Side wainscot backing',(x0,.55,0),(.20,1.1,12),'WalnutDeep',.005)
    for zi in range(12):
        z=-5.5+zi
        box('Raised walnut panel',(side*4.874,.55,z),(.055,.70,.81),'Walnut_2',.018)
        box('Recessed panel field',(side*4.835,.55,z),(.025,.55,.65),'Walnut_0',.012)
        for dz in [-.44,.44]:box('Wainscot stile',(side*4.82,.55,z+dz),(.08,.93,.065),'WalnutDeep',.008)
    for y0 in [.115,1.03]:molding('Wainscot side trim',(side*4.84,y0,0),12,'z')
    for y0 in [3.38,3.47]:molding('Side crown',(side*4.82,y0,0),12,'z',scale=1.25)
A.activate('back-wall')
for xi in range(10):
    x0=-4.5+xi;box('Back raised panel',(x0,.55,-5.86),(.81,.70,.055),'Walnut_2',.018)
for y0 in [.115,1.03]:molding('Back panel trim',(0,y0,-5.82),10)
for y0 in [3.38,3.47]:molding('Back crown',(0,y0,-5.81),10,scale=1.25)

A.activate('ceiling', 'Coffered ceiling', (0,3.67,0), role='architecture_ceiling')
box('Ceiling limewash',(0,3.67,0),(10.1,.12,12.1),'CeilingPlaster',0)
for x0 in [-4.75,-1.58,1.58,4.75]:
    box('Coffered ceiling longitudinal beam',(x0,3.49,0),(.17,.25,12),'WalnutDeep',.015)
    box('Ceiling beam brass line',(x0,3.36,0),(.014,.008,12),'BrassAged',.001)
for z in [-5.8,-2.9,0,2.9,5.8]:
    box('Coffered ceiling cross beam',(0,3.48,z),(9.65,.25,.18),'WalnutDeep',.015)
    box('Ceiling cross brass line',(0,3.35,z),(9.65,.008,.014),'BrassAged',.001)
for x0 in [-3.17,0,3.17]:
    for z in [-4.35,-1.45,1.45,4.35]:
        box('Recessed ceiling coffer',(x0,3.605,z),(2.94,.026,2.65),'OlivePlaster',.012,uv=2)
        for dx in [-1.45,1.45]:box('Coffer inner trim',(x0+dx,3.56,z),(.035,.028,2.65),'Walnut_2',.007)
        for dz in [-1.30,1.30]:box('Coffer inner trim',(x0,3.56,z+dz),(2.94,.028,.035),'Walnut_2',.007)

print('Building fireplace and library',flush=True)
A.activate('fireplace', 'Limestone fireplace', (0,0,-5.5), role='fireplace', library=True)
box('Fireplace dark interior',(0,.65,-5.76),(1.82,1.23,.16),'Charcoal',.008)
box('Fireplace stone hearth',(0,.10,-5.34),(2.72,.15,1.22),'Limestone',.025)
for x0 in [-1.05,1.05]:
    box('Fireplace stone jamb',(x0,.81,-5.52),(.32,1.31,.52),'Limestone',.022)
    box('Fireplace pilaster base',(x0,.23,-5.49),(.45,.20,.58),'Limestone',.018)
    box('Fireplace pilaster capital',(x0,1.38,-5.49),(.44,.15,.59),'Limestone',.018)
box('Fireplace lintel',(0,1.52,-5.51),(2.46,.23,.64),'Limestone',.024)
box('Mantel floating stone ledge',(0,1.70,-5.45),(2.77,.14,.80),'Limestone',.025)
box('Mantel dark reveal',(0,1.60,-5.49),(2.52,.027,.68),'WalnutDeep',.004)
box('Fireplace grate',(0,.25,-5.28),(1.70,.035,.58),'BlackSteel',.006)
for x0 in [-.7,-.47,-.24,0,.24,.47,.7]:rod('Grate prong',(x0,.23,-5.02),(x0,.45,-5.05),.015,'BlackSteel')
for idx in range(7):
    x0=random.uniform(-.5,.5);z=random.uniform(-5.53,-5.14)
    a=(x0-.30,.30+idx*.015,z);b=(x0+.31,.33+idx*.015,z+random.uniform(-.12,.12))
    rod('Charred oak log',a,b,.072,'Charcoal')
    for j in range(3):
        aa=(a[0]+.08+j*.15,a[1]+.05,a[2]-.037);bb=(aa[0]+.065,aa[1]+.005,aa[2]+.01)
        rod('Fireplace ember seam',aa,bb,.008,'Ember')
for _ in range(40):sphere('Glowing ember', (random.uniform(-.73,.73),.285,random.uniform(-5.58,-5.10)),(.025,.016,.020),'Ember',8,5)
light('FireplaceWarmth',(0,.63,-5.11),110,(1,.24,.055),.38)

# Antique overmantel panel with a quiet hand-engraved map motif.
A.activate('overmantel', 'Hermes overmantel', (0,2.42,-5.77), role='wall_decoration', library=True)
box('Overmantel walnut frame',(0,2.42,-5.77),(2.34,1.08,.09),'Walnut_2',.026)
box('Overmantel brass liner',(0,2.42,-5.71),(2.15,.90,.015),'BrassAged',.004)
box('Overmantel etched panel',(0,2.42,-5.69),(2.08,.84,.012),'ForestLeather',.003)
text_mesh('Study name','H E R M E S',(0,2.53,-5.673),.22,'Brass')
text_mesh('Study inscription','THE PRIVATE STUDY',(0,2.28,-5.671),.061,'BrassAged')
for dx in [-.89,.89]:rod('Panel corner motif',(dx,2.18,-5.673),(dx,2.64,-5.673),.005,'BrassAged')

bookmats=['BookWine','BookOlive','BookNavy','BookTan','BookCream']
def book(x0,base,z,w,h,d,mat):
    # Separate leather boards expose a real page block at the top and fore-edge.
    cover=min(.011,w*.13)
    for side in [-1,1]:box('Book leather cover',(x0+side*(w-cover)/2,base+h/2,z),(cover,h,d),mat,.003,role='book_cover')
    box('Book page block',(x0,base+h/2,z-.009),(w*.68,h-.028,d-.042),'Paper',0)
    box('Book curved spine',(x0,base+h/2,z+d/2+.002),(w,h,.026),mat,.006)
    for dy in [.03,.06,h-.038,h-.07]:box('Gilt spine raised band',(x0,base+dy,z+d/2+.019),(w*.91,.007,.003),'BrassAged',0)
    for j in range(random.randrange(2,5)):
        box('Gilt spine title',(x0,base+h*.63-j*.017,z+d/2+.020),(w*.60,.004,.002),'BrassAged',0)

for side in [-1,1]:
    cx=side*3.20
    case_id='bookcase-left' if side<0 else 'bookcase-right'
    A.activate(case_id, 'Left walnut bookcase' if side<0 else 'Right walnut bookcase', (cx,0,-5.51), role='bookcase', library=True)
    box('Library shadow backing',(cx,1.65,-5.82),(2.64,3.10,.12),'WalnutDeep',.008)
    for dx in [-1.33,1.33]:
        box('Library pilaster',(cx+dx,1.67,-5.52),(.13,3.18,.58),'Walnut_2',.015)
        box('Library pilaster brass flute',(cx+dx,1.69,-5.205),(.012,2.8,.008),'BrassAged',.002)
    for sy in [.22,.70,1.24,1.79,2.34,2.91,3.20]:
        box('Library solid shelf',(cx,sy,-5.51),(2.63,.065,.59),'Walnut_2',.01)
        box('Library shelf lip',(cx,sy-.018,-5.195),(2.69,.079,.04),'WalnutDeep',.005)
    molding('Library crown',(cx,3.18,-5.49),2.83,scale=1.3)
    for tier in range(5):
        base=[.25,.735,1.275,1.825,2.375][tier];xx=cx-1.20; book_index=0
        while xx<cx+1.12:
            w=random.uniform(.075,.115);hh=random.uniform(.27,.43)
            book_index+=1
            with A.assembly(f'{case_id}-shelf-{tier+1}-book-{book_index:02d}', f'Book {book_index}, shelf {tier+1}', (xx+w/2,base,-5.47), role='book', parent_id=case_id, render_group=case_id):
                book(xx+w/2,base,-5.47,w,hh,random.uniform(.22,.32),random.choice(bookmats))
            xx+=w+.008
    for dx in [-.95,.85]:
        cyl('Library ornament foot',(cx+dx,2.967,-5.44),.115,.065,'BrassAged')
        sphere('Library sculpted orb',(cx+dx,3.08,-5.44),(.10,.10,.10),'BrassAged')

print('Building whiskey cabinet',flush=True)
A.activate('whiskey-cabinet', 'Whiskey reserve cabinet', (4.55,0,-1.37), role='cabinet', library=True)
# Right-wall cabinet: inward facing shelves run along Godot Z.
box('Whiskey cabinet backing',(4.85,1.89,-1.37),(.10,2.67,3.43),'WalnutDeep',.012)
for z in [-3.11,.37]:box('Whiskey cabinet end',(4.56,1.75,z),(.64,3.0,.13),'Walnut_3',.014)
box('Whiskey base cabinet',(4.58,.48,-1.37),(.68,.90,3.51),'WalnutDeep',.012)
for z in [-2.71,-1.89,-1.07,-.25]:
    box('Cabinet raised door',(4.21,.47,z),(.045,.72,.71),'Walnut_2',.015)
    box('Cabinet recessed panel',(4.18,.47,z),(.025,.53,.51),'Walnut_0',.012)
    cyl('Cabinet brass knob',(4.137,.69,z+.23),.021,.024,'Brass',16,(0,math.pi/2,0))
for sy in [.97,1.54,2.11,2.69,3.23]:
    box('Whiskey cabinet shelf',(4.55,sy,-1.37),(.77,.065,3.51),'Walnut_2',.01)
    box('Whiskey shelf brass lip',(4.148,sy,-1.37),(.023,.015,3.42),'Brass',.003)
    if sy>1:
        box('Cabinet hidden light strip',(4.28,sy-.045,-1.37),(.022,.012,3.26),'LampGlow',.003)
for z in [-2.4,-.5]: light('WhiskeyCabinetGlow',(4.15,2.58,z),24,(1,.62,.27),.36)

def bottle(x0,base,z,h=.33,r=.05,index=0,orient=0):
    mat='BottleGreen' if index%5==0 else 'BottleAmber'
    cyl('Reserve bottle body',(x0,base+h*.31,z),r,h*.57,mat,20)
    cyl('Bottle sloped shoulder',(x0,base+h*.65,z),r,h*.14,mat,20,rad2=r*.42)
    cyl('Bottle neck',(x0,base+h*.81,z),r*.42,h*.21,mat,20)
    cyl('Bottle cork seal',(x0,base+h*.945,z),r*.44,h*.072,'BrassAged',20)
    # Paper wrap as thin band; product label facing into room on X wall.
    cyl('Reserve cream label',(x0,base+h*.35,z),r*1.008,h*.27,'Paper',20)
    box('Reserve label typography',(x0-r*1.013,base+h*.365,z),(.001,h*.03,r*1.10),'Ink',0)
    box('Reserve label gold divider',(x0-r*1.02,base+h*.30,z),(.002,h*.012,r*1.13),'BrassAged',0)

for row,base in enumerate([1.01,1.58,2.15,2.73]):
    for idx in range(16):
        z=-2.93+idx*.20+random.uniform(-.014,.014)
        with A.assembly(f'reserve-bottle-{row+1}-{idx+1:02d}', f'Reserve bottle {idx+1}, shelf {row+1}', (4.47,base,z), role='whiskey_bottle', parent_id='whiskey-cabinet', render_group='whiskey-cabinet'):
            bottle(4.47,base,z,random.uniform(.29,.43),random.uniform(.043,.058),idx+row)
# On cabinet, two heavy faceted decanters.
for index,z in enumerate([-.52,-.15]):
    with A.assembly(f'decanter-{index+1}', f'Crystal decanter {index+1}', (4.30,1.005,z), role='decanter', parent_id='whiskey-cabinet', render_group='whiskey-cabinet'):
        box('Faceted cut crystal decanter',(4.30,1.13,z),(.13,.25,.13),'Crystal',.026)
        box('Decanter whiskey core',(4.297,1.09,z),(.108,.14,.108),'Whiskey',.011)
        cyl('Decanter neck',(4.30,1.31,z),.035,.12,'Crystal',12)
        sphere('Decanter crystal stopper',(4.30,1.40,z),(.05,.055,.05),'Crystal',12,8)
text_mesh('Reserve cabinet plaque','HERMES RESERVE',(4.135,3.02,-1.37),.072,'Brass',(math.pi/2,0,-math.pi/2))

print('Building desk and reading lounge',flush=True)
A.activate('desk', 'Pedestal writing desk', (0,0,-2.5), role='desk', library=True)
A.anchor('desk_surface', (0,.7825,-2.5), size=[2.3,1.1], semantic_role='desk_surface', normal=[0,1,0])
# Bespoke desk. The central opening and screen aperture are deliberately clear.
box('Desk solid walnut top',(0,.745,-2.5),(2.30,.075,1.10),'Walnut_4',.025)
box('Desk brass perimeter front',(0,.727,-1.944),(2.24,.007,.007),'Brass',.002)
for x0 in [-.83,.83]:
    box('Desk pedestal',(x0,.383,-2.59),(.43,.68,.79),'WalnutDeep',.017)
    for sy in [.20,.41,.62]:
        box('Desk drawer front',(x0,sy,-2.169),(.391,.182,.043),'Walnut_2',.009)
        rod('Drawer brass pull',(x0-.081,sy+.015,-2.139),(x0+.081,sy+.015,-2.139),.010,'Brass')
    for z in [-2.89,-2.27]:cyl('Desk brass foot',(x0,.035,z),.06,.069,'BrassAged',16)
box('Desk modesty apron',(0,.49,-2.975),(1.67,.32,.045),'Walnut_2',.012)
box('Desk inset leather mat',(.02,.787,-2.205),(1.02,.008,.39),'ForestLeather',.018)
for x0 in [-.466,.506]:box('Writing mat fine brass border',(x0,.792,-2.205),(.002,.001,.34),'BrassAged',0)
build_monitor(A,box,cyl,rod,text_mesh)
build_keyboard(A,box,text_mesh)
build_computer(A,box,cyl,text_mesh)
A.activate('mouse', 'Wireless mouse', (.38,.792,-2.095), role='mouse', parent_id='desk', library=True)
sphere('Wireless mouse',(.38,.815,-2.095),(.039,.021,.061),'BlackSteel')
A.activate('notebook', 'Leather notebook and fountain pen', (.81,.788,-2.25), role='notebook', parent_id='desk', library=True)
box('Leather bound notebook',(.81,.81,-2.25),(.32,.043,.40),'OxbloodLeather',.007,rot=-.13)
box('Notebook page edge',(.811,.816,-2.249),(.306,.026,.384),'Paper',.002,rot=-.13)
box('Notebook top cover',(.81,.836,-2.25),(.32,.007,.40),'OxbloodLeather',.004,rot=-.13)
rod('Fountain pen',(.71,.85,-2.41),(.87,.85,-2.21),.006,'Brass')
# Ceramic espresso with visible dark coffee and brass saucer.
A.activate('espresso', 'Espresso cup and saucer', (.84,.788,-2.82), role='coffee_cup', parent_id='desk', library=True)
cyl('Coffee saucer',(.84,.794,-2.82),.096,.012,'BrassAged',28)
cyl('Ceramic espresso cup',(.84,.839,-2.82),.048,.084,'Bone',28,rad2=.058)
cyl('Coffee surface',(.84,.883,-2.82),.050,.004,'Charcoal',28)
for a in np.linspace(0,math.pi,12):
    sphere('Cup handle',(.90+math.sin(a)*.028,.84+math.cos(a)*.032,-2.82),(.008,.008,.008),'Bone',8,6)
# Banker lamp with layered brass body and a deep green shade.
A.activate('desk-lamp', 'Green banker lamp', (-.90,.7835,-2.82), role='desk_lamp', parent_id='desk', library=True)
cyl('Banker lamp foot',(-.90,.80,-2.82),.12,.033,'BrassAged',32)
rod('Banker lamp stem',(-.9,.80,-2.82),(-.9,1.25,-2.82),.016,'Brass')
rod('Banker shade crossbar',(-1.03,1.23,-2.82),(-.77,1.23,-2.82),.014,'Brass')
sphere('Banker green enamel shade',(-.90,1.27,-2.82),(.23,.09,.115),'ForestLeather')
box('Banker warm underside',(-.9,1.228,-2.82),(.37,.006,.14),'LampGlow',.013)
light('DeskLamp',(-.9,1.17,-2.78),28,(1,.70,.36),.16)

A.activate('reading-rug', 'Tabriz reading rug', (-2.25,.025,.76), role='rug')
box('Tabriz reading rug',(-2.25,.034,.76),(4.18,.019,3.38),'PersianRug',.015)
for side in [-1,1]:
    for j in range(88):box('Rug hand-knotted fringe',(-4.28+j*.046,.034,.76+side*1.75),(.017,.009,.13),'Cream',.001)
A.activate('coffee-table', 'Walnut coffee table', (-2.42,0,.85), role='coffee_table', library=True)
box('Coffee table polished walnut',(-2.42,.414,.85),(1.28,.070,.78),'Walnut_4',.027)
box('Coffee table lower shelf',(-2.42,.155,.85),(1.07,.036,.58),'Walnut_2',.012)
for dx in [-.48,.48]:
    for dz in [-.23,.23]:
        rod('Coffee table tapered leg',(-2.42+dx,.065,.85+dz),(-2.42+dx*.94,.40,.85+dz*.94),.027,'WalnutDeep')
        cyl('Coffee table brass ferrule',(-2.42+dx,.065,.85+dz),.029,.075,'BrassAged',16)
A.activate('art-volume', 'Coffee table art volume', (-2.62,.441,.85), role='book', parent_id='coffee-table', render_group='coffee-table')
box('Coffee table art volume',(-2.62,.466,.85),(.49,.050,.33),'BookWine',.006,rot=.10)
box('Art volume pages',(-2.62,.468,.85),(.465,.033,.316),'Paper',.002,rot=.10)
box('Art volume cover',(-2.62,.489,.85),(.49,.005,.33),'BookWine',.002,rot=.10)
A.activate('whiskey-tray', 'Whiskey tasting tray', (-2.04,.4515,.85), role='serving_tray', parent_id='coffee-table', render_group='coffee-table')
cyl('Whiskey tray',(-2.04,.462,.85),.20,.021,'BrassAged',32)
for z in [.77,.98]:
    cyl('Cut crystal rocks glass',(-2.08,.522,z),.050,.110,'Crystal',12)
    cyl('Whiskey in glass',(-2.08,.494,z),.045,.032,'Whiskey',12)

print('Building light fixtures and windows',flush=True)
# Aged-brass chandelier: fine chains, six silk shades, visible warm diffusers.
A.activate('chandelier', 'Six arm brass chandelier', (0,3.52,0), role='chandelier', library=True)
cyl('Chandelier ceiling canopy',(0,3.48,.0),.15,.08,'BrassAged',32)
rod('Chandelier central stem',(0,3.43,0),(0,2.73,0),.018,'Brass')
cyl('Chandelier central hub',(0,2.68,0),.15,.12,'BrassAged',32)
for idx in range(6):
    a=idx*math.tau/6;xx=math.cos(a)*.91;zz=math.sin(a)*.91
    rod('Chandelier curved arm inner',(0,2.69,0),(xx*.5,2.55,zz*.5),.013,'Brass')
    rod('Chandelier curved arm outer',(xx*.5,2.55,zz*.5),(xx,2.61,zz),.013,'Brass')
    rod('Chandelier lamp candle',(xx,2.61,zz),(xx,2.86,zz),.021,'BrassAged')
    cyl('Chandelier silk shade',(xx,2.92,zz),.19,.30,'WarmShade',32,rad2=.115)
    cyl('Chandelier brass shade rim',(xx,2.766,zz),.194,.012,'Brass',32)
    cyl('Chandelier warm diffuser',(xx,2.767,zz),.179,.006,'LampGlow',32)
light('Chandelier',(0,2.73,0),260,(1,.71,.41),1.0)

for side in [-1,1]:
    for index,z in enumerate([-4.17,2.30,4.6]):
        xx=side*4.76
        A.activate(('sconce-left-' if side<0 else 'sconce-right-')+str(index+1), ('Left' if side<0 else 'Right')+f' wall sconce {index+1}', (xx,2,z), role='wall_sconce')
        box('Sconce backplate',(xx,2.0,z),(.048,.32,.18),'BrassAged',.029)
        rod('Sconce arm',(xx,1.92,z),(side*4.50,1.93,z),.017,'Brass')
        cyl('Sconce candle cup',(side*4.49,1.99,z),.09,.04,'Brass',24)
        cyl('Sconce pleated silk shade',(side*4.49,2.16,z),.14,.30,'WarmShade',24,rad2=.080)
        cyl('Sconce warm diffuser',(side*4.49,2.009,z),.127,.006,'LampGlow',24)
        light('LibrarySconce' if z<0 else 'LoungeSconce',(side*4.39,2.13,z),50,(1,.64,.30),.23)

# Left wall night window: architectural glass and a subtle distant city texture.
A.activate('night-window', 'Bronze divided night window', (-4.75,1.15,0), role='window')
n=768; win=np.zeros((n,n,3),np.float32);win[:]=[.012,.025,.042]
rng=np.random.default_rng(130)
for j in range(40):
    xx=int(rng.uniform(0,n));ww=int(rng.uniform(8,39));ht=int(rng.uniform(130,480));win[:ht,xx:xx+ww]*=.45
    for iy in range(8,ht-8,13):
        for ix in range(xx+3,min(n,xx+ww-3),8):
            if rng.random()>.52:win[iy:iy+3,ix:ix+3]=[.35,.235,.13]
nighttex=image('night-city-window',win)
material('NightGlass',(1,1,1),.16,.10,tex=nighttex)
# Extra illumination from a cool window strengthens depth against warm lamps.
for z in [-.85,.85]:
    box('Night window walnut reveal',(-4.844,2.18,z),(.16,2.13,1.56),'WalnutDeep',.009)
    box('Night window glass',(-4.747,2.18,z),(.020,1.94,1.39),'NightGlass',.002)
    for dz in [-.72,0,.72]:box('Window bronze vertical mullion',(-4.72,2.18,z+dz),(.044,2.01,.040),'BrassAged',.004)
    for sy in [1.19,2.18,3.17]:box('Window bronze crossbar',(-4.72,sy,z),(.044,.036,1.49),'BrassAged',.003)
box('Window walnut sill',(-4.69,1.15,0),(.34,.084,3.37),'Walnut_3',.013)
material('CurtainTobacco',(.205,.130,.061),.93,normal=bpy.data.images['plaster-normal'])
A.activate('curtains', 'Tobacco linen drapery', (-4.57,3.26,0), role='curtains')
rod('Curtain brass pole',(-4.57,3.26,-1.99),(-4.57,3.26,1.99),.022,'BrassAged')
for z0 in [-1.73,1.73]:
    # Hanging cloth with actual longitudinal pleats.
    verts=[];faces=[]
    for iz in range(33):
        q=iz/32;zz=z0+(q-.5)*.52
        for ih in range(14):
            h=ih/13;xx=-4.49+math.sin(q*math.tau*5)*(.055+.023*(1-h))
            verts.append(G((xx,.15+h*3.05,zz+.018*math.sin(h*5)*math.sin(q*9))))
    for iz in range(32):
        for ih in range(13):a=iz*14+ih;faces.append((a,a+14,a+15,a+1))
    me=bpy.data.meshes.new('Curtain pleats');me.from_pydata(verts,[],faces);me.materials.append(M['CurtainTobacco']);ob=bpy.data.objects.new('Heavy tobacco linen drapery',me);bpy.context.collection.objects.link(ob);A.part(ob,role='curtain_cloth')
    for f in me.polygons:f.use_smooth=True
    for dz in np.linspace(-.23,.23,8):cyl('Curtain pole ring',(-4.53,3.26,z0+dz),.034,.013,'BrassAged',16,(math.pi/2,0,0))

# A quiet side console near the entry, with a sculptural brass armillary.
A.activate('entry-console', 'Entry console', (3.9,0,3.58), role='console_table', library=True)
box('Entry console top',(3.9,.92,3.58),(1.28,.06,.51),'Walnut_3',.015)
for dx in [-.53,.53]:
    for dz in [-.18,.18]:rod('Entry console leg',(3.9+dx,.06,3.58+dz),(3.9+dx,.89,3.58+dz),.022,'BrassAged')
A.activate('armillary', 'Brass armillary sphere', (3.93,.946,3.59), role='sculpture', parent_id='entry-console', library=True)
cyl('Armillary foot',(3.93,.975,3.59),.115,.058,'BlackSteel',24)
rod('Armillary pedestal',(3.93,.97,3.59),(3.93,1.10,3.59),.021,'Brass')
for angle in [0,.7,1.4]:
    bpy.ops.mesh.primitive_torus_add(major_radius=.19,minor_radius=.007,major_segments=48,minor_segments=8,location=G((3.93,1.29,3.59)),rotation=(math.pi/2,angle,0));ob=bpy.context.object;ob.name='Antique brass armillary ring';ob.data.materials.append(M['BrassAged']);A.part(ob,role='armillary_ring')
sphere('Armillary earth',(3.93,1.29,3.59),(.069,.069,.069),'BrassAged')

# Lighting used in the source still; native app uses corresponding manifest lights.
area('Warm entry fill',(1.1,3.1,4.6),(0,1.1,-1.4),350,(1,.77,.51),5)
area('Cool night window fill',(-4.55,2.1,0),(0,1.0,-1),150,(.30,.43,.63),2.8)
area('Ceiling bounce',(0,3.29,-3.2),(0,.1,-2.7),220,(1,.79,.53),4)

print('Preserving editable parts and preparing assembly exports',flush=True)
bpy.ops.object.camera_add(location=G((3.50,1.79,5.02)))
cam=bpy.context.object;cam.name='WhiskeyStudyArrival';cam.rotation_euler=(Vector(G((0,1.48,-2.05)))-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.lens=23
bpy.context.scene.camera=cam
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=24;scene.cycles.use_denoising=True
scene.cycles.max_bounces=6;scene.cycles.diffuse_bounces=3;scene.cycles.glossy_bounces=3
scene.render.resolution_x=1200;scene.render.resolution_y=800;scene.render.resolution_percentage=100
scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.075,.087,.11,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.20
scene.view_settings.view_transform='AgX';scene.view_settings.exposure=.7
scene.render.image_settings.file_format='PNG';scene.render.filepath=str(RENDER/'room-arrival.png')
for im in bpy.data.images:
    if im.source=='FILE' or im.name in [i.name for i in bpy.data.images if i.filepath]:
        try:im.pack()
        except Exception:pass
assemblies = A.export(ROOT)
triangles = assemblies['inventory']['triangles']
meshes = [o for o in bpy.context.scene.objects if o.type=='MESH']
manifest=dict(asset='app/assets/whiskey-room.glb',source='assets/room.blend',units='meters',coordinate_system='Godot Y-up; source Blender X=X,Y=-Z,Z=Y',bounds={'x':[-5.1,5.1],'y':[-.15,3.73],'z':[-6.1,6.1]},triangles=triangles,mesh_count=len(meshes),material_count=len(M),textures=[p.name for p in TEX.glob('*.png')],lights=LIGHTS,desk={'center':[0,.745,-2.5],'size':[2.3,.075,1.1],'surface_y':.7825},display={'center':[-.25,1.1,-2.36],'size':[1.15,.65]},hermes_clearance={'center':[1.65,0,-1.7],'radius':.45},chairs='Supplied independently by the object pipeline',notes=['Original deterministic modeled architecture and bitmap materials.','All visible meshes grouped by material to reduce draw calls.','Model contains no baked chairs or agent.','Physical objects use beveled mesh geometry; image textures are embedded in GLB.'])
manifest['source'] = 'assets/room-parts.blend'
manifest['assembly_manifest'] = 'app/office-assemblies.json'
manifest['notes'][1] = 'Parts preserved in source and libraries; runtime geometry batched per assembly/material.'
(ROOT/'room-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
if '--no-render' not in __import__('sys').argv:
    print('Rendering CPU preview',flush=True);bpy.ops.render.render(write_still=True)
print('COMPLETE',flush=True)
