import copy, csv, io, json, shutil, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from v10 import core
from v9.model import replay, binomial_tail, candidate_scores, rank, as_matrix

NOW=datetime(2026,10,12,3,45,tzinfo=timezone.utc)
class V10Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=(core.ROOT/'data/hkjc_verified_v9.csv').read_bytes()
        cls.manifest=json.loads((core.ROOT/'data/hkjc_verified_v9_manifest.json').read_text())
        cls.draws,_=core.validate(cls.raw,cls.manifest,NOW)
        cls.model=replay(cls.draws)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        for directory in ('data','baseline','v10','v9'): shutil.copytree(core.ROOT/directory,self.root/directory)
    def tearDown(self): self.temp.cleanup()
    def build(self,**kwargs):
        with patch.object(core,'replay',return_value=copy.deepcopy(self.model)):
            return core.run(self.root,now=NOW,**kwargs)
    def test_original_pins_preserved(self):
        before=core.verify_preserved(self.root); self.build(); self.assertEqual(before,core.verify_preserved(self.root))
    def test_missing_manifest_rejected(self):
        with self.assertRaises(ValueError): core.validate(self.raw,{},NOW)
    def test_manifest_metadata_rejected(self):
        for k,v in [('count',3),('latest','2026-10-09'),('latest_period','26/107'),('endpoint','https://fake.example')]:
            m={**self.manifest,k:v}
            with self.assertRaises(ValueError): core.validate(self.raw,m,NOW)
    def test_manifest_future_time_rejected(self):
        with self.assertRaises(ValueError): core.validate(self.raw,{**self.manifest,'retrieved_at_utc':(NOW+timedelta(hours=1)).isoformat()},NOW)
    def test_gap_rejected_even_with_updated_hash_count(self):
        lines=self.raw.splitlines(keepends=True); raw=b''.join(lines[:100]+lines[101:]); m={**self.manifest,'sha256':core.digest(raw),'count':3323}
        with self.assertRaises(ValueError): core.validate(raw,m,NOW)
    def test_invalid_date_identity_and_balls_rejected(self):
        for old,new in [(b'2003-01-02',b'2003-02-30'),(b'2003001N',b'2003999N')]:
            raw=self.raw.replace(old,new,1); m={**self.manifest,'sha256':core.digest(raw)}
            with self.assertRaises(ValueError): core.validate(raw,m,NOW)
    def test_id_formats(self):
        self.assertEqual(core.source_identity('2003001N'),(2003,1)); self.assertEqual(core.source_identity('20251N'),(2025,1))
        for s in ['2025101Ngarbage','2025101','202500N','20251Z']:
            with self.assertRaises(ValueError): core.source_identity(s)
    def test_reproducible_causal_model(self):
        import numpy as np
        matrix=as_matrix(self.draws)
        first=candidate_scores(matrix[:-1]); altered=matrix.copy(); altered[-1]=0
        other=candidate_scores(altered[:-1])
        for key in first: np.testing.assert_array_equal(first[key],other[key])
        self.assertEqual(self.model['single'],7); self.assertEqual(self.model['models']['bayes_60']['evaluation_hits'],23)
        self.assertAlmostEqual(binomial_tail(120,23)*5,self.model['evaluation_adjusted_p'],7)
        self.assertFalse(self.model['statistical_edge_passed'])
    def test_normal_extra_baselines_and_formal_blank(self):
        a=self.build(); self.assertEqual(a['research']['normal_baseline'],6/49); self.assertEqual(a['research']['extra_baseline'],1/49); self.assertIsNone(a['formal']['single']); self.assertEqual(a['currentness']['status'],'snapshot')
    def test_idempotent_seal(self):
        a=self.build(); raw=(self.root/'current/forecast_events.jsonl').read_bytes(); b=self.build()
        self.assertEqual(raw,(self.root/'current/forecast_events.jsonl').read_bytes()); self.assertEqual(a['release_id'],b['release_id'])
    def test_changed_model_does_not_replace_seal(self):
        a=self.build(); m=copy.deepcopy(self.model); m['rank']=list(reversed(m['rank'])); m['single']=m['rank'][0]; m['top9']=m['rank'][:9]
        with patch.object(core,'replay',return_value=m): b=core.run(self.root,now=NOW+timedelta(seconds=1))
        self.assertEqual(a['seal'],b['seal']); self.assertTrue(b['research']['differs_from_seal']); self.assertIsNone(b['formal']['single'])
    def test_partial_update_failure_preserves_release_and_ledger(self):
        self.build(); before=(self.root/'current').readlink(); old=(self.root/'current/forecast_events.jsonl').read_bytes()
        for where in ['before_commit','before_pointer']:
            with patch.object(core,'replay',return_value=self.model),self.assertRaises(RuntimeError): core.run(self.root,now=NOW+timedelta(seconds=2),fail_at=where)
            self.assertEqual(before,(self.root/'current').readlink()); self.assertEqual(old,(self.root/'current/forecast_events.jsonl').read_bytes()); core.verify_release(self.root/'current')
    def test_failed_source_keeps_last_good(self):
        self.build(); before=(self.root/'current').readlink()
        def bad(*args,**kwargs): raise OSError('network offline')
        with self.assertRaises(OSError): self.build(online=True,fetcher=bad)
        self.assertEqual(before,(self.root/'current').readlink())
    def test_truncated_source_rejected(self):
        def truncated(*args,**kwargs): return self.draws[-5:]
        with self.assertRaises(ValueError): self.build(online=True,fetcher=truncated,upcoming_fetcher=lambda:None)
        self.assertFalse((self.root/'current').exists())
    def test_real_online_path_with_fixture_and_target(self):
        def official(first,last,workers): return [d for d in self.draws if d.draw_date>=f'{first[0]:04d}-{first[1]:02d}-01']
        upcoming={'source':core.ENDPOINT,'status':'Defined','source_id':'2026109N','date':'2026-10-13'}
        a=self.build(online=True,fetcher=official,upcoming_fetcher=lambda:upcoming)
        self.assertEqual(a['currentness']['status'],'fresh_verified'); self.assertEqual(a['target']['period'],'26/109'); self.assertEqual(a['target']['date'],'2026-10-13')
    def test_target_mismatch_rejected(self):
        for source_id,when in [('2026110N','2026-10-13'),('2026109N','2026-10-09'),('2025109N','2026-10-13')]:
            with self.assertRaises(ValueError): core.target_evidence({'source':core.ENDPOINT,'status':'Defined','source_id':source_id,'date':when},self.draws[-1],NOW)
    def test_expired_source_report(self):
        with patch.object(core,'replay',return_value=self.model): a=core.run(self.root,now=NOW+timedelta(days=2))
        self.assertEqual(a['currentness']['status'],'expired'); self.assertIsNone(a['formal']['single'])
    def test_corrupted_release_rejected(self):
        self.build(); (self.root/'current/latest_analysis.json').write_text('{}')
        with self.assertRaises(ValueError): core.verify_release(self.root/'current')
        with self.assertRaises(ValueError): self.build()
    def test_ledger_tamper_rejected(self):
        a=self.build(); raw=(self.root/'current/forecast_events.jsonl').read_bytes().replace(b'"single":7',b'"single":8')
        with self.assertRaises(ValueError): core.load_chain(raw)
    def test_hkt_same_day_settlement_is_excluded_and_idempotent(self):
        prior=self.draws[:-1]; target=core.target_evidence(None,prior[-1],NOW); seal_time=datetime(2026,10,9,17,tzinfo=timezone.utc)
        raw,_,s=core.ledger_update(b'',prior,self.model,target,'a'*64,'b'*64,seal_time)
        raw2,events,_=core.ledger_update(raw,self.draws,self.model,target,'c'*64,'b'*64,NOW)
        settled=[e for e in events if e['kind']=='settlement']; self.assertEqual(len(settled),1); self.assertFalse(settled[0]['eligible']); self.assertIsNone(settled[0]['normal_hit'])
        raw3,_,_=core.ledger_update(raw2,self.draws,self.model,target,'c'*64,'b'*64,NOW)
        self.assertEqual(raw2,raw3)
    def test_pre_hkt_day_settlement_scored_honestly(self):
        prior=self.draws[:-1]; target=core.target_evidence(None,prior[-1],NOW)
        raw,_,s=core.ledger_update(b'',prior,self.model,target,'a'*64,'b'*64,datetime(2026,10,8,12,tzinfo=timezone.utc))
        _,events,_=core.ledger_update(raw,self.draws,self.model,target,'c'*64,'b'*64,NOW)
        e=[e for e in events if e['kind']=='settlement'][0]; self.assertTrue(e['eligible']); self.assertEqual(e['normal_hit'],int(s['single'] in self.draws[-1].main))
    def test_legacy_not_counted_as_v10_performance(self):
        a=self.build(); self.assertEqual(a['evidence']['prospective_rounds'],0); self.assertGreater(a['legacy']['events'],0)
    def test_release_all_files_and_embedded_identity(self):
        a=self.build(); verified=core.verify_release(self.root/'current'); self.assertEqual(a,verified)
        html=(self.root/'current/latest_battle_report.html').read_text(); self.assertIn(a['release_id'],html); self.assertIn('marksix-report-version',html)

if __name__=='__main__': unittest.main()

class LegacyProjectionTests(unittest.TestCase):
    def test_projection_is_explicit_and_matches_existing_loader_contract(self):
        from v10 import compatibility
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'legacy'
            result=compatibility.export_legacy(target)
            v=json.loads((target/'version.json').read_text()); a=json.loads((target/'latest_analysis.json').read_text()); h=json.loads((target/'self_test_report.json').read_text())
            self.assertEqual(v['schema'],'marksix_official_v9'); self.assertEqual(a['schema'],v['schema']); self.assertEqual(a['engine_schema'],'marksix_v10')
            self.assertEqual(v['updated_at'],a['generated_at']); self.assertEqual(core.stamp(v['updated_at']),core.stamp(a['canonical_generated_at']))
            self.assertEqual(v['latest_period'],a['latest_draw']['period']); self.assertEqual(v['latest_date'],a['latest_draw']['date']); self.assertTrue(h['operational_passed']); self.assertEqual(h['latest_period'],v['latest_period'])
            self.assertFalse(h['prediction_gate_passed']); self.assertFalse(h['formal_qualified']); self.assertIn('正式預測未達資格',h['status'])
            html=(target/'index.html').read_text(); self.assertIn(f'content="{v["hash"]}"',html); self.assertIn(f'content="{v["latest_period"]}"',html); self.assertFalse(result['published'])
            self.assertEqual(core.digest((target/'canonical_v10_analysis.json').read_bytes()),a['canonical_analysis_sha256'])
