import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine,update

class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.draws=engine.load_draws()
    def test_history_integrity(self):
        self.assertGreaterEqual(len(self.draws),4300)
        self.assertEqual(len({d.period for d in self.draws}),len(self.draws))
        self.assertEqual(self.draws,sorted(self.draws,key=lambda d:d.draw_date))
        self.assertGreater(self.draws[-1].draw_date,self.draws[-2].draw_date)
    def test_models(self):
        m=engine.model_suite(self.draws[:500])
        self.assertTrue({"lagged_drag","interval_cycle","lag_trace"}.issubset(m))
        self.assertEqual(len(m),14)
        self.assertTrue(all(len(x)==49 for x in m.values()))
        self.assertTrue(all(abs(x.sum()-6)<1e-6 for x in m.values()))
    def test_next_draw(self): self.assertEqual(engine.next_draw("2026-07-14"),"2026-07-16")
    def test_prize_divisions(self):
        d=engine.Draw("x","2026-01-01",(1,2,3,4,5,6),7)
        self.assertEqual(engine.prize_division([1,2,3,4,5,6],d),"一獎")
        self.assertEqual(engine.prize_division([1,2,3,4,5,7],d),"二獎")
        self.assertEqual(engine.prize_division([1,2,3,7,8,9],d),"六獎")
        self.assertEqual(engine.prize_division([1,2,3,8,9,10],d),"七獎")
    def test_sets(self):
        import numpy as np
        sets=engine.build_sets(np.linspace(.05,.2,49))
        self.assertEqual(len(sets),8)
        self.assertTrue(all(len(set(x))==6 for x in sets))
    def test_live_single_audit_deduplicates_target_draw(self):
        result={"packs":{"最強單支":[31]},"release_gate":{"passed":True},"backtest":{"main":{"confidence_audit":{"super_consensus":True,"checks":{}}}}}
        def settled(based_on,number,actual):
            return {"status":"settled","target_date":"2026-08-22","based_on_date":based_on,"based_on_period":based_on,"packs":{"最強單支":[number]},"actual":{"main":actual}}
        history=[settled("2026-08-18",7,[7,8,9,10,11,12]),settled("2026-08-20",31,[31,32,33,34,35,36])]
        audit=update.apply_live_single_audit(result,history)
        self.assertEqual(audit["settled_snapshots"],2)
        self.assertEqual(audit["independent_draws"],1)
        self.assertEqual(audit["duplicate_snapshots_excluded"],1)
        self.assertEqual(audit["hits"],1)
        self.assertFalse(result["release_gate"]["passed"])
        self.assertFalse(result["backtest"]["main"]["confidence_audit"]["super_consensus"])
    def test_consecutive_single_requires_cross_period_model_support(self):
        confidence={"super_consensus":False,"checks":{},"score_gap_to_second":.01,"model_top9_support":8,"weighted_support_pct":72.0}
        result={"latest_draw":{"period":"26/106","date":"2026-10-06"},"target_date":"2026-10-08","packs":{"最強單支":[31]},"release_gate":{"passed":False,"model_passed":True,"live_single_passed":False},"backtest":{"main":{"names":[str(x) for x in range(9)],"confidence_audit":confidence}}}
        history=[
            {"status":"settled","based_on_period":"26/105","based_on_date":"2026-10-03","target_date":"2026-10-06","packs":{"最強單支":[31]},"actual":{"main":[9,29,31,34,36,41]}},
            {"status":"pending","based_on_period":"26/106","based_on_date":"2026-10-06","target_date":"2026-10-08","packs":{"最強單支":[31]}},
        ]
        audit=update.apply_consecutive_single_audit(result,history)
        self.assertTrue(audit["is_consecutive"])
        self.assertEqual(audit["streak"],2)
        self.assertTrue(audit["reasonable_repeat_passed"])
        self.assertFalse(audit["strong_recommendation_passed"])
        self.assertTrue(audit["previous_result_hit"])
if __name__=="__main__": unittest.main()
