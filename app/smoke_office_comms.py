"""Explicit real Desktop -> middleware -> Hermes -> reply acceptance.

Creates a labeled test conversation. Never records a microphone or sends to contacts.
The scene metadata fixture is identified as a test; response is read only for this
new test session. No existing conversation text is read or altered.
"""
import json,os,sqlite3,subprocess,sys,time,uuid,shutil,wave
from pathlib import Path
from office_launcher import stop_owned
ROOT=Path(__file__).resolve().parent

def main():
    directory=ROOT/('desktop-acceptance-comms-'+str(time.time_ns()));directory.mkdir(mode=0o700)
    data=directory/'data';workspace=data/'workspace';workspace.mkdir(parents=True)
    ipc=directory/'ipc';env=os.environ.copy();env.update(HERMES_OFFICE_DATA_DIR=str(data),HERMES_OFFICE_ACCEPTANCE_RUN='1')
    nonce=uuid.uuid4().hex[:8];label='Copper test cube '+nonce
    report={'started_at':time.time(),'passed':False,'physical_microphone':False,'synthetic_scene':True,'label':label,'checks':{}}
    def scene():
        state={'schema':1,'running':True,'workspace':str(workspace),'updated_at':time.time(),'instance':nonce,'sequence':1,
            'windows':[{'id':'hermes','title':'Hermes acceptance','connected':True,'position_m':[0,1.6,-1.3],'active':True}],
            'mode':'desktop acceptance fixture','viewer_position_m':[0,1.6,0],'viewer_forward':[0,0,-1],'podium':label,'render_status':'test fixture ready'}
        file=workspace/'.hermes-office-context.json';temporary=file.with_suffix('.tmp');temporary.write_text(json.dumps(state));temporary.replace(file)
    def pump(seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:scene();time.sleep(.2)
    serial=0
    def command(kind,**params):
        nonlocal serial
        serial+=1;status=json.loads((ipc/'status.json').read_text());identifier='comms-'+str(serial)
        value=dict(protocol_version=1,instance_id=status['instance_id'],created_at_unix=time.time(),id=identifier,type=kind,**params)
        file=ipc/'commands'/(identifier+'.json');tmp=file.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.replace(file)
        for _ in range(35):
            pump(.2);last=json.loads((ipc/'status.json').read_text()).get('last_command',{})
            if last.get('id')==identifier:
                if last.get('status')!='done':raise RuntimeError(str(last.get('error')))
                return last
        raise RuntimeError('Input acknowledgement timed out')
    def enter():
        command('key',keysym='Return',pressed=True);command('key',keysym='Return',pressed=False)
    def response(session=None,after=0):
        with sqlite3.connect('file:'+str(Path.home()/'.hermes/state.db')+'?mode=ro',uri=True) as db:
            if not session:
                row=db.execute("SELECT session_id, content FROM messages WHERE role='user' AND timestamp>=? AND content LIKE ? ORDER BY id DESC LIMIT 1",(report['started_at'],'%Office communication acceptance '+nonce+'%')).fetchone()
                if not row:return None,None
                session=row[0];report['checks']['context_in_real_user_message']=label in row[1]
            row=db.execute("SELECT id,content FROM messages WHERE session_id=? AND role='assistant' AND id>? ORDER BY id DESC LIMIT 1",(session,after)).fetchone()
            return session,row
    scene()
    # Chromium's documented fake-media input supplies only this generated WAV.
    # No physical microphone or camera is opened by the acceptance process.
    speech=directory/'speech.wav';sample=directory/'input.wav'
    subprocess.run(['espeak-ng','-w',str(speech),'Office voice verification. Please tell me the label of the object on the podium.'],check=True)
    with wave.open(str(speech),'rb') as audio:
        params=audio.getparams();frames=audio.readframes(audio.getnframes())
    with wave.open(str(sample),'wb') as audio:
        audio.setparams(params);silence=b'\0'*(params.framerate*params.nchannels*params.sampwidth)
        audio.writeframes(silence*2+frames+silence*5)
    launch=['bash',str(ROOT/'run-hermes-desktop.sh'),'--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream','--use-file-for-fake-audio-capture='+str(sample)+'%noloop','--mute-audio']
    with (directory/'helper.log').open('wb') as log:
        process=subprocess.Popen([sys.executable,str(ROOT/'desktop_bridge.py'),'--ipc-dir',str(ipc),'--command',json.dumps(launch)],env=env,stdout=log,stderr=log,start_new_session=True)
        try:
            for _ in range(120):
                pump(.25)
                if (ipc/'status.json').exists() and json.loads((ipc/'status.json').read_text()).get('connected'):break
            pump(8)
            command('navigate_hermes',destination='new_session');pump(2)
            command('pointer_button',x=600,y=750,button=1,pressed=True);command('pointer_button',x=600,y=750,button=1,pressed=False)
            command('text',text='Office communication acceptance '+nonce+'. Please reply with only the label of the object on the podium in the supplied office context. This is a harmless test fixture; no tools or changes are needed.')
            pump(1);enter()
            session=None;row=None
            for _ in range(150):
                pump(1);session,row=response(session)
                if row:break
            report['session_id']=session
            report['reply']=str(row[1])[:1500] if row else ''
            report['checks']['scene_grounded_reply']=label in report['reply']
            shutil.copyfile(ipc/'frame.png',directory/'context-reply.png')
            if report['checks']['scene_grounded_reply']:
                last_id=row[0]
                pump(2)
                report['voice_start']=command('navigate_hermes',destination='voice')
                for _ in range(75):
                    pump(1);_,spoken=response(session,last_id)
                    if spoken:break
                report['voice_reply']=str(spoken[1])[:1200] if spoken else ''
                report['checks']['synthetic_voice_to_scene_grounded_reply']=label in report['voice_reply']
                shutil.copyfile(ipc/'frame.png',directory/'voice-reply.png')
            # This does not start recording. End is safe/idempotent when idle.
            report['voice_end']=command('navigate_hermes',destination='end_voice')
            report['checks']['voice_end_reachable']=True
            if report['checks']['scene_grounded_reply']:
                command('launch_tui');pump(5)
                expected=label
                command('text',text='TUI communication acceptance '+nonce+'. What is on the office podium right now? Read the fresh local .hermes-office-context.json in this workspace as described by AGENTS.md. Reply only with its podium label. This is a read-only synthetic scene test; make no changes.')
                pump(1);enter()
                tui_reply=''
                for _ in range(80):
                    pump(1)
                    with sqlite3.connect('file:'+str(Path.home()/'.hermes/state.db')+'?mode=ro',uri=True) as db:
                        found=db.execute("SELECT session_id FROM messages WHERE role='user' AND timestamp>=? AND content LIKE ? ORDER BY id DESC LIMIT 1",(report['started_at'],'%TUI communication acceptance '+nonce+'%')).fetchone()
                        if found:
                            found=db.execute("SELECT content FROM messages WHERE role='assistant' AND session_id=? ORDER BY id DESC LIMIT 1",(found[0],)).fetchone()
                            if found and found[0]:
                                tui_reply=str(found[0])
                                if expected in tui_reply:break
                report['tui_reply']=tui_reply[:1200]
                report['checks']['tui_text_reply']=expected in tui_reply
                report['checks']['tui_scene_grounded_reply']=expected in tui_reply
                shutil.copyfile(ipc/'frame.png',directory/'tui-reply.png')
            report['passed']=all(report['checks'].values())
        except Exception as e:report['error']=str(e)[:500]
        finally:stop_owned(process)
    report['directory']=str(directory);report['finished_at']=time.time()
    (ROOT/'comms-desktop-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
