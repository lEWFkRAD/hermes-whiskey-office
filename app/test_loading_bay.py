import tempfile
from pathlib import Path
import unittest
from loading_bay import Bay

class BayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.bay=Bay(self.root/'bay')
        self.source=self.root/'draft.txt';self.source.write_text('original')
    def tearDown(self):self.bay.close();self.tmp.cleanup()
    def test_survives_restart_and_retains_original(self):
        item=self.bay.put(self.source);self.source.write_text('changed')
        self.bay.close();self.bay=Bay(self.root/'bay')
        checkout=self.bay.checkout(item['artifact'],'shatner')
        self.assertEqual(Path(checkout['path']).read_text(),'original')
    def test_competing_returns_preserve_both(self):
        item=self.bay.put(self.source)
        a=self.bay.checkout(item['artifact'],'forge');b=self.bay.checkout(item['artifact'],'onyx')
        Path(a['path']).write_text('first');Path(b['path']).write_text('second')
        first=self.bay.put_back(a['lease']);second=self.bay.put_back(b['lease'])
        self.assertFalse(first['conflict']);self.assertTrue(second['conflict'])
        self.assertEqual(self.bay.rows()[0]['head'],first['revision'])
        self.assertEqual(Path(second['path']).read_text(),'second')
        self.assertEqual(len(self.bay.history(item['artifact'])),3)
        with self.assertRaises(ValueError):self.bay.put_back(a['lease'])
    def test_path_and_machine_validation(self):
        item=self.bay.put(self.source)
        with self.assertRaises(ValueError):self.bay.checkout(item['artifact'],'../../escape')
        with self.assertRaises(ValueError):self.bay.checkout('../../escape','forge')
    def test_integrity_failure_does_not_checkout(self):
        item=self.bay.put(self.source);obj=self.bay.root/'objects'/item['sha256'];obj.chmod(0o600);obj.write_text('corrupt')
        with self.assertRaises(ValueError):self.bay.checkout(item['artifact'],'forge')
    def test_editable_shelf_cannot_change_original(self):
        item=self.bay.put(self.source);shelf=next((self.bay.root/'Shelf').iterdir());shelf.chmod(0o600);shelf.write_text('oops')
        self.assertEqual(Path(self.bay.checkout(item['artifact'],'onyx')['path']).read_text(),'original')
    def test_symlink_rejected(self):
        link=self.root/'link'
        try:link.symlink_to(self.source)
        except OSError:self.skipTest('Symlink creation unavailable')
        with self.assertRaises(ValueError):self.bay.put(link)
    def test_parallel_return_race(self):
        from concurrent.futures import ThreadPoolExecutor
        item=self.bay.put(self.source)
        leases=[self.bay.checkout(item['artifact'],m)['lease'] for m in ['forge','onyx']]
        def finish(lease):
            bay=Bay(self.bay.root)
            try:return bay.put_back(lease)
            finally:bay.close()
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(finish,leases))
        self.assertEqual(sum(r['head_advanced'] for r in results),1)
        self.assertEqual(len(self.bay.history(item['artifact'])),3)

if __name__=='__main__':unittest.main()
