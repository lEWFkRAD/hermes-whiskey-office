"""Explicit real-desktop acceptance. No prompt, mic, camera or approval is sent."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent

def tested_inputs(env):
    result={'sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['desktop_bridge.py','run-hermes-desktop.sh','run-hermes-tui.sh','office_workspace.py','smoke_desktop_bridge.py','hermes_navigation.py']}}
    lock=ROOT/'desktop-plugins-lock.json'
    if lock.exists():
        result['sha256'][lock.name]=hashlib.sha256(lock.read_bytes()).hexdigest()
        from runtime_guard import check_plugins
        result['desktop_plugins']=check_plugins(ROOT, result)
    backend=Path(env.get('HERMES_OFFICE_BACKEND_ROOT', str(Path.home()/'.hermes/hermes-agent')))
    git_env={key:value for key,value in env.items() if not key.startswith('GIT_')}
    git_env['GIT_OPTIONAL_LOCKS']='0'
    revision=subprocess.run(['git','-C',str(backend),'rev-parse','HEAD'],env=git_env,capture_output=True,text=True,check=True,timeout=10).stdout.strip()
    result['backend_runtime']=dict(root=str(backend),source_commit=revision,python_path=str(backend/'venv/bin/python'))
    receipt_path=Path.home()/'.local/share/hermes-whiskey-office/vendor/hermes-v2026.8.31-build-receipt.json'
    build=json.loads(receipt_path.read_text())
    if build.get('status')!='built': raise RuntimeError('Pinned desktop build is not ready')
    binary=Path(build['binary'])
    asar=binary.parent/'resources/app.asar'
    result['desktop_build']=dict(receipt_path=str(receipt_path), receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(), source_commit=build['source_commit'], binary=str(binary), binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), app_asar=str(asar), app_asar_sha256=hashlib.sha256(asar.read_bytes()).hexdigest())
    return result


def main():
    directory=ROOT/('desktop-acceptance-'+str(time.time_ns()))
    directory.mkdir(mode=0o700)
    ipc=directory/'ipc'
    env=os.environ.copy()
    env['HERMES_OFFICE_DATA_DIR']=str(directory/'data')
    env['HERMES_OFFICE_ACCEPTANCE_RUN']='1'
    argv=[sys.executable,str(ROOT/'desktop_bridge.py'),'--ipc-dir',str(ipc),'--command',json.dumps(['bash',str(ROOT/'run-hermes-desktop.sh')])]
    result={'directory':str(directory),'passed':False,'model_prompts_sent':0,'microphone_used':False}
    result['checks']={}
    before=tested_inputs(env)
    serial=0
    def command(kind, **params):
        nonlocal serial
        serial+=1
        state=json.loads((ipc/'status.json').read_text())
        identifier='smoke-%08d'%serial
        value=dict(protocol_version=1,instance_id=state['instance_id'],created_at_unix=time.time(),id=identifier,type=kind,**params)
        temporary=ipc/'commands'/('cmd-%08d.tmp'%serial)
        temporary.write_text(json.dumps(value))
        temporary.replace(temporary.with_suffix('.json'))
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            state=json.loads((ipc/'status.json').read_text())
            last=state.get('last_command',{})
            if last.get('id')==identifier:
                if last.get('status')!='done': raise RuntimeError(last.get('error','Command failed'))
                return last
            time.sleep(.05)
        raise RuntimeError('Input acknowledgement timed out')
    def chord(*keys):
        for key in keys: command('key',keysym=key,pressed=True)
        for key in reversed(keys): command('key',keysym=key,pressed=False)
    def capture(name):
        time.sleep(1)
        shutil.copyfile(ipc/'frame.png',directory/(name+'.png'))
    with (directory/'helper.log').open('wb') as log:
        child=subprocess.Popen(argv,env=env,stdout=log,stderr=log,start_new_session=True)
        try:
            start=time.monotonic()
            while time.monotonic()-start<35:
                if (ipc/'status.json').exists():
                    try: result['status']=json.loads((ipc/'status.json').read_text())
                    except ValueError: pass
                if result.get('status',{}).get('connected'):
                    time.sleep(8)
                    result['status']=json.loads((ipc/'status.json').read_text())
                    shutil.copyfile(ipc/'frame.png',directory/'desktop.png')
                    result['passed']=result['status']['connected'] and time.time()-result['status']['updated_at_unix']<4
                    result['checks']['startup']=result['passed']
                    command('pointer_button',x=650,y=752,button=1,pressed=True)
                    command('pointer_button',x=650,y=752,button=1,pressed=False)
                    command('text',text='Office input verification — unsent draft.')
                    capture('typed-draft')
                    result['checks']['pointer_and_text_acknowledged']=True
                    # Always exercise attachment using a synthetic fixture; never
                    # depend on a private screenshot from the original machine.
                    from PIL import Image, ImageDraw
                    fixture=Image.new('RGB',(640,360),'#153b45')
                    ImageDraw.Draw(fixture).text((30,150),'SYNTHETIC OFFICE ACCEPTANCE - UNSENT',fill='white')
                    fixture.save(ipc/'captures/office-check.png')
                    command('clipboard_image',image_name='office-check.png')
                    capture('image-attachment')
                    result['checks']['image_paste_acknowledged']=True
                    chord('Control_L','Shift_L','h')
                    capture('hud')
                    chord('Control_L','Shift_L','h')
                    command('launch_tui')
                    time.sleep(3)
                    capture('tui')
                    result['checks']['tui_launch_acknowledged']=True
                    command('focus_desktop')
                    capture('returned-desktop')
                    result['navigation']={}
                    for destination in ['tools','skills','mcp','plugins','settings','artifacts','new_session','approvals']:
                        try:
                            result['navigation'][destination]=command('navigate_hermes',destination=destination)
                            result['checks']['navigate_'+destination]=True
                        except RuntimeError as exc:
                            result['navigation'][destination]={'error':str(exc)}
                            result['checks']['navigate_'+destination]=False
                        capture('nav-'+destination)
                    result['passed']=result['passed'] and all(result['checks'].values())
                    result['requires_visual_review']=True
                    break
                if child.poll() is not None: break
                time.sleep(.2)
            result['helper_running']=child.poll() is None
        except Exception as exc:
            result['passed']=False
            result['error']=str(exc)
        finally:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try: child.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGKILL)
                    child.wait(timeout=3)
            result['helper_exit']=child.returncode
    result['helper_log']=(directory/'helper.log').read_text(errors='replace')[-7000:]
    result['checked_at']=time.time()
    result.update(before)
    try:
        result['checks']['tested_inputs_unchanged']=before==tested_inputs(env)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        result['checks']['tested_inputs_unchanged']=False
    result['passed']=result['passed'] and result['checks']['tested_inputs_unchanged']
    (ROOT/'desktop-acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)
    return 0 if result['passed'] else 1

if __name__=='__main__': raise SystemExit(main())
