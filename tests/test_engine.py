import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine

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
if __name__=="__main__": unittest.main()
