"""Real draft-only dictation and capture-cadence acceptance with generated audio."""
import json, os, shutil, sqlite3, subprocess, sys, time, wave
from pathlib import Path
from office_launcher import stop_owned

ROOT = Path(__file__).resolve().parent

def main():
    folder = ROOT / ('desktop-acceptance-ux-' + str(time.time_ns()))
    folder.mkdir(mode=0o700)
    (folder/'data/workspace').mkdir(parents=True)
    ipc = folder / 'ipc'
    env = dict(os.environ, HERMES_OFFICE_DATA_DIR=str(folder/'data'), HERMES_OFFICE_ACCEPTANCE_RUN='1')
    speech = folder/'speech.wav'; sample = folder/'input.wav'
    phrase = 'Draft only verification. The amber book belongs on the shared desk.'
    subprocess.run(['espeak-ng','-w',str(speech),phrase], check=True)
    with wave.open(str(speech),'rb') as wav:
        params=wav.getparams(); frames=wav.readframes(wav.getnframes())
    with wave.open(str(sample),'wb') as wav:
        wav.setparams(params); silence=b'\0'*(params.framerate*params.nchannels*params.sampwidth)
        wav.writeframes(silence*2+frames+silence*5)
    launch=['bash',str(ROOT/'run-hermes-desktop.sh'),'--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream','--use-file-for-fake-audio-capture='+str(sample)+'%noloop','--mute-audio']
    report={'started_at':time.time(),'passed':False,'physical_microphone':False,'test_phrase':phrase}
    serial=0
    def status(): return json.loads((ipc/'status.json').read_text())
    def command(kind, **fields):
        nonlocal serial
        serial+=1; identifier='ux-'+str(serial)
        value=dict(protocol_version=1,instance_id=status()['instance_id'],id=identifier,type=kind,created_at_unix=time.time(),**fields)
        target=ipc/'commands'/(identifier+'.json'); tmp=target.with_suffix('.tmp'); tmp.write_text(json.dumps(value)); tmp.replace(target)
        for _ in range(80):
            time.sleep(.1); last=status().get('last_command',{})
            if last.get('id')==identifier:
                if last.get('status')!='done': raise RuntimeError(str(last))
                return last
        raise RuntimeError('No command acknowledgement')
    with (folder/'helper.log').open('wb') as log:
        process=subprocess.Popen([sys.executable,str(ROOT/'desktop_bridge.py'),'--ipc-dir',str(ipc),'--command',json.dumps(launch)],env=env,stdout=log,stderr=log,start_new_session=True)
        try:
            for _ in range(160):
                time.sleep(.25)
                if process.poll() is not None: raise RuntimeError('Private Desktop exited: '+str(status().get('error','unknown')))
                if (ipc/'status.json').exists() and status().get('connected'): break
            time.sleep(7)
            command('navigate_hermes',destination='new_session'); time.sleep(2)
            report['dictate']=command('navigate_hermes',destination='dictate')
            time.sleep(9)
            report['stop']=command('navigate_hermes',destination='end_voice')
            time.sleep(8)
            shutil.copyfile(ipc/'frame.png',folder/'dictation-draft.png')
            with sqlite3.connect('file:'+str(Path.home()/'.hermes/state.db')+'?mode=ro',uri=True) as db:
                count=db.execute("SELECT count(*) FROM messages WHERE role='user' AND timestamp>=?",(report['started_at'],)).fetchone()[0]
            report['no_test_message_submitted']=count==0
            # Sample status publications, not frame IDs: unchanged pixels are intentionally skipped.
            stamps=[]; costs=[]; end=time.monotonic()+3
            while time.monotonic()<end:
                row=status(); stamp=row['updated_at_unix']
                if not stamps or stamp!=stamps[-1]: stamps.append(stamp); costs.append(row.get('capture_ms',0))
                time.sleep(.003)
            report['capture_poll_hz']=(len(stamps)-1)/(stamps[-1]-stamps[0])
            report['capture_ms_p95']=sorted(costs)[int(len(costs)*.95)]
            report['passed']=report['no_test_message_submitted'] and report['capture_poll_hz']>20
            report['draft_visual_review_required']=True
        except Exception as exc:
            report['error']=str(exc)
        finally:
            stop_owned(process)
    report['finished_at']=time.time(); report['directory']=str(folder)
    (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (ROOT/'ux-input-acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1

if __name__=='__main__': raise SystemExit(main())
