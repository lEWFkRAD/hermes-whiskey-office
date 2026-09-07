import os,time,json
from pathlib import Path
from desktop_bridge import PrivateDesktop,InputController
ROOT=Path(__file__).resolve().parent
directory=ROOT/('desktop-acceptance-tui-'+str(time.time_ns()));directory.mkdir(mode=0o700)
os.environ.update(HERMES_OFFICE_DATA_DIR=str(directory/'data'),HERMES_OFFICE_ACCEPTANCE_RUN='1')
desktop=PrivateDesktop(directory,['bash',str(ROOT/'run-hermes-desktop.sh')])
def pump(n):
 end=time.monotonic()+n
 while time.monotonic()<end:desktop.pump();desktop.flush();time.sleep(.01)
try:
 desktop.start();pump(9);desktop.launch_tui();pump(4)
 original=desktop.selection_request
 def selection(item):
  print('SELECTION',desktop.display.get_atom_name(item.selection),desktop.display.get_atom_name(item.target),flush=True);original(item)
 desktop.selection_request=selection
 focused=desktop.display.get_input_focus().focus
 print('TUI PROCESS',desktop.tui.poll(),'FOCUS',focused.id,'CLASS',focused.get_wm_class(),flush=True)
 print('ROOT WINDOWS',[(w.id,w.get_wm_class()) for w in desktop.root.query_tree().children],flush=True)
 desktop.move(300,300);desktop.button(1,True);desktop.button(1,False);pump(.5)
 desktop.clipboard(b'TUI paste verification draft', 'UTF8_STRING');pump(2)
 print('AFTER CTRL SHIFT V',desktop.paste_finished,flush=True)
 desktop.key('Control_L',True);desktop.key('Shift_L',True);desktop.key('v',True);desktop.key('v',False);desktop.key('Shift_L',False);desktop.key('Control_L',False);pump(1)
 desktop.key('a',True);desktop.key('a',False);pump(.5)
 desktop.key('Shift_L',True);desktop.key('Insert',True);desktop.key('Insert',False);desktop.key('Shift_L',False);pump(2)
 desktop.ImageGrab.grab(xdisplay=desktop.display_name).save(directory/'paste.png')
 print('PASTE',desktop.paste_active,desktop.paste_finished,'DIRECTORY',str(directory),flush=True)
finally:desktop.close()
