import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import scene_tool


class SceneToolTests(unittest.TestCase):
    def test_stale_scene_does_not_queue_an_action(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace=Path(folder)
            (workspace/'.hermes-office-context.json').write_text(json.dumps(dict(schema=1,running=True,instance='fixture',updated_at=time.time()-30)))
            with self.assertRaisesRegex(ValueError, 'fresh'):
                scene_tool.submit(workspace,'sphere','Ball','ff0000',.09)
            self.assertFalse((workspace/'.scene-commands').exists())

    def test_submit_waits_for_matching_live_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace=Path(folder)
            (workspace/'.hermes-office-context.json').write_text(json.dumps(dict(schema=1,running=True,instance='fixture',updated_at=time.time())))
            for name in ['.scene-commands','.scene-results']: (workspace/name).mkdir()
            observed=[]
            def scene_fixture():
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    paths=list((workspace/'.scene-commands').glob('*.json'))
                    if paths:
                        request=json.loads(paths[0].read_text())
                        observed.append(request)
                        receipt=workspace/'.scene-results'/paths[0].name
                        pending=receipt.with_suffix('.tmp')
                        pending.write_text(json.dumps(dict(status='done',id=request['id'],scene_instance='fixture',object_id=request['id'])))
                        pending.rename(receipt)
                        return
                    time.sleep(.01)
            worker=threading.Thread(target=scene_fixture)
            worker.start()
            try: result=scene_tool.submit(workspace,'sphere','Ball','ff0000',.09,timeout=3)
            finally: worker.join(4)
            self.assertEqual(result['status'],'done')
            self.assertEqual(observed[0]['instance'],'fixture')
            self.assertFalse(observed[0]['replace'])
            self.assertEqual(len(list((workspace/'.scene-commands').glob('*.json'))),1)

    def test_timeout_is_unconfirmed_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace=Path(folder)
            (workspace/'.hermes-office-context.json').write_text(json.dumps(dict(schema=1,running=True,instance='fixture',updated_at=time.time())))
            for name in ['.scene-commands','.scene-results']: (workspace/name).mkdir()
            result=scene_tool.submit(workspace,'sphere','Ball','ff0000',.09,timeout=0)
            self.assertEqual(result['status'],'unconfirmed')
            self.assertEqual(len(list((workspace/'.scene-commands').glob('*.json'))),1)


if __name__=='__main__': unittest.main()
