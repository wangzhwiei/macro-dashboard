import copy
import unittest
from scripts.verify_cloud_result import validate

class CloudAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.d={'indicators':[{'id':'a','unit':'%','updatedAt':'2026-11-15'}]}
        self.f={'history':{'x':[{'date':'2026-10-31','actual':None,'forecast':2.1}]}}
        self.q={'summary':{'provider_code_collisions':0},'errors':[]}
    def test_unchanged_passes(self):
        self.assertEqual([],validate(self.d,self.d,self.f,self.f,self.q))
    def test_date_regression_fails(self):
        new=copy.deepcopy(self.d);new['indicators'][0]['updatedAt']='2026-10-01'
        self.assertTrue(validate(self.d,new,self.f,self.f,self.q))
    def test_released_forecast_may_not_be_rewritten(self):
        new=copy.deepcopy(self.f);new['history']['x'][0].update(actual=3,forecast=3)
        self.assertTrue(validate(self.d,self.d,self.f,new,self.q))
    def test_unreleased_forecast_can_update(self):
        new=copy.deepcopy(self.f);new['history']['x'][0]['forecast']=3
        self.assertEqual([],validate(self.d,self.d,self.f,new,self.q))
    def test_new_source_warning_blocks(self):
        new=copy.deepcopy(self.d);new['indicators'][0]['dataQuality']=[{'code':'a','status':'warning'}]
        self.assertTrue(validate(self.d,new,self.f,self.f,self.q))
