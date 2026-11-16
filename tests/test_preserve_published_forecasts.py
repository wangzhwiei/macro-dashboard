import unittest
from scripts.preserve_published_forecasts import preserve

class PreserveTests(unittest.TestCase):
    def test_release_keeps_prediction_but_updates_actual(self):
        old={'history':{'x':[{'date':'2026-10-31','forecast':1.1,'actual':None,'officialRounding':1.1}]}}
        new={'history':{'x':[{'date':'2026-10-31','forecast':2.2,'actual':3.3}]}}
        self.assertEqual(preserve(old,new),1)
        self.assertEqual(new['history']['x'][0]['forecast'],1.1)
        self.assertEqual(new['history']['x'][0]['actual'],3.3)
        self.assertEqual(new['history']['x'][0]['forecastKind'],'confirmed_nowcast')

    def test_unreleased_predictions_can_update(self):
        old={'history':{'x':[{'date':'2026-11-30','forecast':1.1}]}}
        new={'history':{'x':[{'date':'2026-11-30','forecast':2.2,'actual':None}]}}
        self.assertEqual(preserve(old,new),0)
        self.assertEqual(new['history']['x'][0]['forecast'],2.2)

    def test_retrospective_flag_survives(self):
        row={'date':'2026-09-30','forecast':1.1,'actual':2.0,'forecastKind':'retrospective_reconstruction'}
        old={'history':{'x':[row]}}
        new={'history':{'x':[dict(row,forecast=4.0,actual=2.1)]}}
        preserve(old,new)
        self.assertEqual(new['history']['x'][0]['forecastKind'],'retrospective_reconstruction')
