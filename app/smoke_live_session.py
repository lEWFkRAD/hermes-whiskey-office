"""Explicit live acceptance: two text turns + optional generated-office image.

Unlike check_compatibility.py, this intentionally calls the configured Hermes
model and creates one clearly named ACP verification conversation. No tools,
microphone, playback, or messaging platforms are requested. Never auto-run it.
"""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from office_bridge import OfficeBridge

ROOT = Path(__file__).resolve().parent


def wait_for(bridge, condition, timeout=120):
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        bridge.tick()
        if bridge.state['permissions']:
            raise RuntimeError('The verification requested a tool approval; no option was approved.')
        if condition(): return
        if bridge.state['connection']['status'] in {'offline','incompatible'}:
            raise RuntimeError(bridge.state['connection']['reason'])
        time.sleep(.03)
    raise RuntimeError('Live verification timed out.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live',action='store_true',required=True)
    parser.add_argument('--image',type=Path)
    args=parser.parse_args()
    report={'started_at':time.time(),'passed':False,'steps':[],'model_prompts_sent':0,'microphone_used':False,'permissions_approved':False}
    with tempfile.TemporaryDirectory(prefix='hermes-office-acceptance-') as temp:
        directory=Path(temp)
        bridge=OfficeBridge(directory/'ipc',directory/'workspace',directory/'cache',['bash',str(ROOT/'run-hermes-acp.sh')],voice_command=[])
        def command(name,params):
            cid='acceptance-'+str(len(report['steps']))+'-'+str(time.monotonic_ns())
            bridge.execute_command({'protocol_version':1,'instance_id':bridge.instance_id,'id':cid,'method':name,'params':params})
            if bridge.state['last_command']['status'] not in {'accepted','completed'}:
                raise RuntimeError(bridge.state['last_command']['error'])
        def turn(text,image_name=None):
            params={'text':text}
            if image_name: params['image_name']=image_name
            command('message.send',params)
            report['model_prompts_sent']+=1
            wait_for(bridge,lambda:not bridge.state['busy'],180)
            if bridge.state['last_command']['status']=='failed' or bridge.state['error']:
                raise RuntimeError(bridge.state['error'] or bridge.state['last_command']['error'])
            messages=bridge.state['messages']
            response=next((m['content'] for m in reversed(messages) if m['role']=='assistant'),'')
            if not response.strip() or any(error in response.lower() for error in ['api call failed', 'connection error.', 'account balance is too low']):
                raise RuntimeError('Model did not complete the verification: '+response[:500])
            return response
        try:
            bridge.start_child()
            wait_for(bridge,lambda:bridge.state['connection']['status']=='ready',40)
            report['connection']=bridge.state['connection']
            command('session.new',{})
            wait_for(bridge,lambda:bridge.loaded_session is not None and not bridge.state['busy'])
            report['session_id']=bridge.loaded_session
            report['steps'].append({'name':'create_session','passed':True})
            token='amber-'+str(time.time_ns())[-9:]
            reply=turn('Office compatibility check. Do not call any tools or change anything. Remember this exact temporary check word for this conversation: '+token+'. Reply with only that word.')
            report['steps'].append({'name':'text_turn','passed':token in reply,'response':reply[:500]})
            if token not in reply:
                raise RuntimeError('First text turn failed; remaining model checks were not sent.')
            reply=turn('What exact temporary check word did I just give you? Reply with only that word. Do not call tools.')
            report['steps'].append({'name':'same_session_context','passed':token in reply,'response':reply[:500]})
            if token not in reply:
                raise RuntimeError('Conversation context check failed; image check was not sent.')
            if args.image:
                target=directory/'ipc/captures/office-acceptance.png'
                shutil.copyfile(args.image,target)
                reply=turn('This is a generated image of our virtual office, shared as an integration test. Without using tools, briefly describe the visible furniture and room colors. Do not claim access to physical cameras.',target.name)
                report['steps'].append({'name':'shared_virtual_image','passed':bool(reply.strip()),'response':reply[:1800],'requires_visual_review':True})
            report['passed']=all(step['passed'] for step in report['steps'])
        except Exception as exc:
            report['error']=str(exc)[:1500]
        finally:
            bridge.stop_voice(force=True)
            bridge.stop_child()
    (ROOT/'live-acceptance.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
