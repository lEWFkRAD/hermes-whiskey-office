"""Circular walnut projection furniture; optics are switched on by the app."""
import math

def build(api):
    A=api['A']; cyl=api['cyl']; ring=api['ring']; box=api['box']
    x,z=-.25,-.35
    A.activate('hologram-podium','Circular walnut hologram podium',(x,0,z),library=True)
    cyl('Recessed shadow foot',(x,.035,z),.43,.07,'AudioGraphite',n=96)
    cyl('Walnut stepped plinth',(x,.102,z),.54,.065,'WalnutDeep',r2=.52,n=96)
    ring('Lower brass reveal',(x,.136,z),.51,.008,'BrassAged')
    cyl('Walnut drum',(x,.355,z),.445,.44,'Walnut_4',r2=.47,n=96)
    for i in range(56):
        angle=i*math.tau/56
        cyl('Rounded vertical walnut flute',(x+.462*math.cos(angle),.36,z+.462*math.sin(angle)),.015,.41,'Walnut_4',n=10)
    ring('Upper brass reveal',(x,.582,z),.485,.009,'BrassAged')
    cyl('Rounded circular walnut crown',(x,.618,z),.58,.065,'Walnut_4',n=128)
    ring('Inset brass aperture',(x,.653,z),.43,.007,'BrassAged')
    cyl('Smoked projection well',(x,.653,z),.417,.007,'AudioGraphite',n=96)
    for i in range(12):
        angle=i*math.tau/12
        cyl('Optical emitter lens',(x+.39*math.cos(angle),.66,z+.39*math.sin(angle)),.011,.007,'AudioCeramic',n=12)
