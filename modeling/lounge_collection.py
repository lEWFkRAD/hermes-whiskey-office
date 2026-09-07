"""Editable plants, occasional tables, cut crystal and precision turntables."""
import math
import random
from mathutils import Vector

def build(api):
    A=api['A'];mat=api['mat'];box=api['box'];cyl=api['cyl'];rod=api['rod'];ball=api['ball'];ring=api['ring'];leaf=api['leaf']
    rng=random.Random(90666)
    for spec in [
        ('TurntableSilver',(.53,.57,.59),.25,.94),('VinylBlack',(.012,.015,.018),.24,.1),
        ('VinylGroove',(.026,.03,.035),.36,.1),('LabelOchre',(.62,.31,.06),.88),
        ('LabelTeal',(.045,.21,.19),.85),('LinenLamp',(.76,.62,.43),.87,0,1,.6),
        ('SoftBulb',(1,.64,.28),.5,0,1,1.8),('GlazedOlive',(.17,.22,.13),.28),
        ('GlazedCream',(.58,.53,.42),.45),('Clay',(.30,.135,.071),.9),
        ('CutCrystal',(.68,.83,.84),.09,0,.16),('CrystalEdge',(.4,.53,.54),.19,.2),
        ('WhiskeyAmber',(.32,.105,.012),.21,.04),('PaleStone',(.47,.44,.37),.76),
    ]:mat(*spec)

    def table(identifier,x,z,height,radius,stone=False):
        A.activate(identifier,'Occasional table', (x,0,z),library=True)
        cyl('Round honed top',(x,height-.025,z),radius,.05,'PaleStone' if stone else 'Walnut_4',n=64)
        ring('Brass tabletop reveal',(x,height-.042,z),radius-.002,.004,'BrassAged')
        cyl('Splayed pedestal foot',(x,.035,z),radius*.58,.06,'WalnutDeep',r2=radius*.46,n=40)
        cyl('Tapered pedestal',(x,height*.45,z),radius*.12,height*.82-.035,'BrassAged',r2=radius*.075,n=24)
        return (x,height,z)

    def plant(identifier,p,size=1,palm=False,owner=None):
        x,y,z=p
        A.activate(identifier,'Indoor palm' if palm else 'Broad-leaf indoor plant',p,parent_id=owner or 'office',render_group=owner,library=owner is None)
        pot_h=.28*size;pot_r=.20*size
        cyl('Thrown ceramic planter',(x,y+pot_h/2,z),pot_r*.73,pot_h,'GlazedOlive' if palm else 'GlazedCream',r2=pot_r,n=40)
        ring('Planter rounded lip',(x,y+pot_h,z),pot_r,.008*size,'GlazedOlive' if palm else 'GlazedCream')
        cyl('Dark potting mix',(x,y+pot_h+.001*size,z),pot_r*.92,.006*size,'Soil',n=32)
        if palm:
            for frond in range(9):
                angle=frond*2.399;length=size*rng.uniform(.7,1.05)
                base=Vector((x,y+pot_h,z));previous=base
                for segment in range(1,7):
                    t=segment/6
                    tip=base+Vector((math.cos(angle)*length*.66*t*t,length*(1.36*t-.58*t*t),math.sin(angle)*length*.66*t*t))
                    rod('Arching palm rachis',previous,tip,.003*size,'Stem')
                    if segment>1:
                        width=length*.22*math.sin(math.pi*t*.8)
                        for side in [-1,1]:
                            side_angle=angle+side*1.05
                            end=tip+Vector((math.cos(side_angle)*width,-.035*size,math.sin(side_angle)*width))
                            leaf('Palm leaflet',tip,end,width*.24,'LeafJade' if frond%3 else 'LeafForest')
                    previous=tip
        else:
            for shoot in range(4):
                angle=shoot*2.399;start=Vector((x,y+pot_h,z))
                tip=start+Vector((math.cos(angle)*.12*size,size*rng.uniform(.53,.99),math.sin(angle)*.12*size))
                rod('Woody botanical stem',start,tip,.005*size,'Driftwood')
                for j in range(5):
                    base=start+(tip-start)*(.26+j*.16);theta=angle+j*1.8
                    reach=size*rng.uniform(.20,.35)
                    end=base+Vector((math.cos(theta)*reach,.08*size,math.sin(theta)*reach))
                    leaf('Folded broad leaf',base,end,reach*.31,['LeafForest','LeafJade','LeafLime'][(j+shoot)%3])

    def lamp(identifier,p,height=.47):
        x,y,z=p;A.activate(identifier,'Soft linen table lamp',p,library=True)
        cyl('Weighted bronze lamp base',(x,y+.018,z),.09,.036,'BrassAged',n=40)
        rod('Lamp stem',(x,y+.03,z),(x,y+height-.15,z),.009,'Brass')
        # Open frustum mesh gives the shade a thin fabric shell, not a solid cone.
        import bpy
        G=api['G'];finish=api['finish'];n=48;r=.14;top=.085;bottom=y+height-.20
        verts=[G((x+math.cos(i*math.tau/n)*rad,sy,z+math.sin(i*math.tau/n)*rad)) for sy,rad in [(bottom,r),(y+height,top)] for i in range(n)]
        faces=[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
        me=bpy.data.meshes.new('Linen shade');me.from_pydata(verts,[],faces);ob=bpy.data.objects.new('Linen shade',me);bpy.context.collection.objects.link(ob);finish(ob,'Open woven shade','LinenLamp')
        for sy,rad in [(bottom,r),(y+height,top)]:ring('Rolled shade edge',(x,sy,z),rad,.002,'GlazedCream')
        ball('Frosted bulb',(x,y+height-.13,z),(.026,.042,.026),'SoftBulb')

    def decanter(identifier,p,round_body=False):
        x,y,z=p;A.activate(identifier,'Faceted crystal whiskey decanter',p,library=True)
        if round_body:
            cyl('Octagonal crystal body',(x,y+.105,z),.083,.20,'CutCrystal',r2=.065,n=8)
            cyl('Visible amber whiskey',(x,y+.075,z),.070,.125,'WhiskeyAmber',r2=.064,n=8)
            for i in range(8):
                a=i*math.tau/8
                rod('Cut crystal edge',(x+math.cos(a)*.080,y+.02,z+math.sin(a)*.080),(x+math.cos(a)*.067,y+.195,z+math.sin(a)*.067),.001,'CrystalEdge')
        else:
            box('Square crystal body',(x,y+.105,z),(.13,.19,.13),'CutCrystal',.014)
            box('Amber spirit',(x,y+.075,z),(.105,.12,.105),'WhiskeyAmber',.01)
            for dx in [-.054,0,.054]:
                for dz in [-.065,.065]:rod('Vertical cut flute',(x+dx,y+.028,z+dz),(x+dx,y+.175,z+dz),.0015,'CrystalEdge')
        cyl('Decanter shoulder',(x,y+.215,z),.059,.048,'CutCrystal',r2=.021,n=12)
        cyl('Long glass neck',(x,y+.261,z),.022,.047,'CutCrystal',n=16)
        ring('Neck brass collar',(x,y+.281,z),.022,.002,'BrassAged')
        cyl('Faceted stopper',(x,y+.306,z),.031,.039,'CutCrystal',r2=.021,n=8)
        for dx,dz in [(.15,.07),(.06,.17)]:
            cyl('Heavy tumbler foot',(x+dx,y+.007,z+dz),.032,.014,'CutCrystal',n=16)
            cyl('Tumbler glass',(x+dx,y+.045,z+dz),.033,.078,'CutCrystal',r2=.037,n=16)
            cyl('Tumbler whiskey',(x+dx,y+.022,z+dz),.028,.023,'WhiskeyAmber',n=16)

    tables=[('window-drinks-table',-3.90,2.75,.65,.34,False),
            ('lounge-lamp-table',-3.82,-1.22,.69,.29,False),
            ('rear-drinks-table',2.98,-3.85,.77,.38,True),
            ('bar-drinks-table',3.24,-.38,.72,.34,False),
            ('nesting-table-tall',-.90,4.04,.53,.43,True),
            ('nesting-table-low',-.28,4.19,.43,.28,False)]
    for identifier,x,z,h,r,s in tables:table(identifier,x,z,h,r,s)
    decanter('window-decanter',(-3.97,.65,2.71),True)
    decanter('rear-decanter',(2.88,.77,-3.90))
    decanter('bar-decanter',(3.16,.72,-.45),True)
    decanter('nesting-decanter',(-1.02,.53,4.0))
    lamp('lounge-linen-lamp',(-3.82,.69,-1.22))
    lamp('rear-linen-lamp',(3.11,.77,-3.99),.43)
    lamp('nesting-linen-lamp',(-.28,.43,4.19),.40)
    plant('window-palm',(-3.75,0,4.40),1.25,True)
    plant('library-broadleaf',(4.15,0,-4.45),1.15)
    plant('desk-side-broadleaf',(-2.10,0,-4.3),1.1)
    plant('front-palm',(2.35,0,4.73),1.25,True)
    plant('library-top-plant',(-3.1,2.89,-5.50),.46)
    plant('reserve-top-plant',(4.48,2.87,-.2),.43)
    plant('entry-table-plant',(4.33,.95,3.58),.43)
    plant('low-table-plant',(-.90,.53,4.18),.36)

    # Right-wall record console faces the room, next to the whiskey cabinet.
    def P(u,y,v=0):return(4.34-v,y,1.78+u)
    A.activate('vinyl-console','Walnut vinyl console',P(0,0),library=True)
    box('Floating walnut counter',P(0,.90),(.64,.075,1.74),'Walnut_4',.018)
    box('Lower record shelf',P(0,.20),(.54,.055,1.64),'Walnut_4',.01)
    box('Cabinet back',P(0,.54,-.25),(.025,.64,1.63),'WalnutDeep',.004)
    for u in [-.82,0,.82]:box('Open cabinet divider',P(u,.54),(.55,.66,.034),'WalnutDeep',.007)
    for u in [-.69,.69]:
        for v in [-.20,.20]:cyl('Console brass foot',P(u,.092,v),.024,.18,'BrassAged')
    for side in [-1,1]:
        for i in range(19):
            u=side*.39+(i-9)*.014
            box('Individual record sleeve',P(u,.395,.04),(.31,.33,.011),['LabelOchre','LabelTeal','AudioPaper','IvoryLetter','WalnutDeep'][i%5],.001)
            box('Record spine title',P(u,.44,.199),(.001,.06,.006),'IvoryLetter',0)

    def turntable(identifier,u,label_material,silver):
        A.activate(identifier,'Precision belt-drive turntable',P(u,.94),library=True)
        def T(a,b,c):return P(u+a,.938+b,c)
        for du in [-.22,.22]:
            for v in [-.17,.17]:
                cyl('Adjustable isolation foot',T(du,.02,v),.034,.04,'AudioRubber',n=24)
                ring('Foot brass trim',T(du,.034,v),.033,.003,'Brass')
        box('Deep walnut plinth',T(0,.068,0),(.43,.070,.54),'Walnut_4',.016)
        box('Machined top plate',T(0,.109,0),(.40,.008,.51),'TurntableSilver' if silver else 'AudioGraphite',.005)
        center=T(-.067,.13,.012)
        cyl('Bearing platter',center,.165,.03,'TurntableSilver',n=96)
        for h in [-.010,0,.010]:ring('Platter machined edge',(center[0],center[1]+h,center[2]),.165,.0016,'BrassAged')
        record=T(-.067,.147,.012)
        cyl('Vinyl record',record,.153,.003,'VinylBlack',n=96)
        for i in range(23):ring('Concentric vinyl groove',(record[0],record[1]+.002,record[2]),.053+i*.0042,.00032,'VinylGroove')
        cyl('Printed center label',T(-.067,.150,.012),.047,.001,'LabelOchre' if silver else label_material,n=64)
        ring('Label border',T(-.067,.151,.012),.043,.0008,'IvoryLetter')
        cyl('Brass record clamp',T(-.067,.161,.012),.020,.020,'Brass',r2=.016,n=32)
        cyl('Polished spindle',T(-.067,.176,.012),.003,.015,'TurntableSilver',n=16)
        # Independent motor pulley and drive belt, with a real tonearm assembly.
        cyl('Motor pod',T(-.213,.125,-.143),.027,.031,'AudioGraphite',n=32)
        cyl('Brass motor pulley',T(-.213,.150,-.143),.011,.023,'Brass',n=24)
        rod('Visible drive belt',T(-.220,.144,-.144),T(-.109,.144,-.152),.0013,'AudioRubber')
        pivot=T(.177,.16,-.132)
        cyl('Arm bearing tower',pivot,.025,.081,'BrassAged',n=32)
        ring('Gimbal bearing',T(.177,.204,-.132),.024,.004,'TurntableSilver',axis=(0,0,1))
        rod('Carbon tonearm',T(.177,.199,-.132),T(.043,.176,.094),.005,'AudioGraphite')
        rod('Counterweight shaft',T(.177,.200,-.132),T(.188,.208,-.184),.003,'TurntableSilver')
        cyl('Balanced counterweight',T(.188,.208,-.177),.017,.028,'TurntableSilver',axis=(1,0,0))
        box('Cartridge headshell',T(.043,.174,.108),(.036,.01,.022),'BrassAged',.002)
        box('Moving coil cartridge',T(.043,.165,.108),(.020,.011,.016),label_material,.001)
        rod('Stylus cantilever',T(.043,.162,.108),T(.035,.151,.111),.0008,'TurntableSilver')
        cyl('Speed selector',T(.220,.119,.150),.015,.012,'Brass',n=24)
        cyl('Power indicator',T(.183,.115,.164),.003,.003,'SoftBulb',n=12)
        for du in [-.23,.23]:
            for v in [-.177,.177]:cyl('Recessed mounting screw',T(du,.116,v),.003,.002,'TurntableSilver',n=8)
    turntable('turntable-reference',-.43,'LabelOchre',True)
    turntable('turntable-studio',.43,'LabelTeal',False)
