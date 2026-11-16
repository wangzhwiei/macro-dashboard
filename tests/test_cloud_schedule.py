import unittest
from scripts.cloud_schedule_gate import should_run
class ScheduleTests(unittest.TestCase):
    def test_staging_always_denied(self):
        self.assertFalse(should_run({'phase':'staging'},'workflow_dispatch',9))
    def test_disabled_schedule_does_not_block_manual(self):
        c={'phase':'production','schedule':{'enabled':False,'hourShanghai':9}}
        self.assertFalse(should_run(c,'schedule',9))
        self.assertTrue(should_run(c,'workflow_dispatch',9))
    def test_schedule_only_selected_hour(self):
        c={'phase':'production','schedule':{'enabled':True,'hourShanghai':9}}
        self.assertTrue(should_run(c,'schedule',9))
        self.assertFalse(should_run(c,'schedule',10))
