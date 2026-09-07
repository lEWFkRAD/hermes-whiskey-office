from pathlib import Path
import tempfile
import unittest
from check_locks import check

class LockTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.spec=self.root/'requirements.in';self.lock=self.root/'requirements.lock'
        self.lock.write_text('some-lib==1.5\n')

    def test_matching_range_and_normalized_name(self):
        self.spec.write_text('some_lib[extra]>=1,<2\n');check(self.spec,self.lock)

    def test_stale_lock_rejected(self):
        self.spec.write_text('some-lib>=2,<3\n')
        with self.assertRaises(ValueError):check(self.spec,self.lock)

    def test_missing_dependency_rejected(self):
        self.spec.write_text('another-lib==1\n')
        with self.assertRaises(ValueError):check(self.spec,self.lock)

    def test_included_input_is_checked(self):
        (self.root/'base.in').write_text('some-lib>=2\n')
        self.spec.write_text('-r base.in\n')
        with self.assertRaises(ValueError):check(self.spec,self.lock)

if __name__=='__main__':unittest.main()
