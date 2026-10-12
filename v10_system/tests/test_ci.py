import json, shutil, tempfile, unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from v10 import ci, core

class PipelineMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.repo=Path(self.temp.name);self.root=self.repo/'v10_system';self.root.mkdir()
        for name in ('data','baseline','v9','v10'):
            shutil.copytree(core.ROOT/name,self.root/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        rid=(core.ROOT/'CURRENT').read_text().strip();(self.root/'CURRENT').write_text(rid+'\n')
        shutil.copytree(core.ROOT/'releases'/rid,self.root/'releases'/rid)
        for name in ('reports','docs','site'):
            (self.repo/name).mkdir();(self.repo/name/'old').write_text('last good '+name)
    def tearDown(self):self.temp.cleanup()
    def test_restore_ordinary_pointer_and_idempotent(self):
        expected=(self.root/'CURRENT').read_text().strip()
        self.assertEqual(ci.restore_current(self.root),expected);self.assertTrue((self.root/'current').is_symlink());self.assertEqual(ci.restore_current(self.root),expected)
    def test_bad_current_pointer_rejected(self):
        (self.root/'CURRENT').write_text('../../outside')
        with self.assertRaises(ValueError):ci.restore_current(self.root)
    def test_rollback_every_mirror_and_pointer(self):
        expected=(self.root/'CURRENT').read_bytes()
        for position in ('reports','docs','site'):
            with self.assertRaises(RuntimeError):ci.publish_worktree(self.repo,self.root,updater=lambda:None,fail_after=position)
            self.assertEqual((self.root/'CURRENT').read_bytes(),expected)
            for name in ('reports','docs','site'):self.assertEqual((self.repo/name/'old').read_text(),'last good '+name)
            core.verify_release(self.root/'current')
    def test_failed_update_never_rewrites_outputs(self):
        def fail():raise OSError('official endpoint failure')
        with self.assertRaises(OSError):ci.publish_worktree(self.repo,self.root,updater=fail)
        for name in ('reports','docs','site'):self.assertTrue((self.repo/name/'old').exists())
    def test_successful_materialization_uses_single_identity_and_no_publication(self):
        pins=core.verify_preserved(self.root)
        result=ci.publish_worktree(self.repo,self.root,updater=lambda:None)
        self.assertFalse(result['published']);self.assertTrue(result['prepared_for_git_commit']);self.assertEqual(pins,core.verify_preserved(self.root))
        a=ci.validate_outputs(self.repo,self.root);self.assertEqual(result['release_id'],a['release_id'])
        legacy=json.loads((self.repo/'reports/latest_analysis.json').read_text());self.assertEqual(legacy['engine_schema'],'marksix_v10');self.assertEqual(legacy['schema'],'marksix_official_v9')
    def test_repeated_materialization_and_guards(self):
        ci.publish_worktree(self.repo,self.root,updater=lambda:None);a=ci.validate_outputs(self.repo,self.root)
        result=ci.publish_worktree(self.repo,self.root,updater=lambda:None);self.assertEqual(result['release_id'],a['release_id'])
        recent=core.stamp(a['generated_at'])+timedelta(minutes=1);self.assertFalse(ci.should_repair('schedule',self.root,recent));self.assertTrue(ci.should_repair('schedule',self.root,recent+timedelta(hours=2)));self.assertTrue(ci.should_repair('workflow_run',self.root,recent))
    def test_workflows_do_not_expand_permissions_or_run_v9(self):
        for name in ('update.yml','cloud-self-repair.yml'):
            text=(core.ROOT.parent/'.github/workflows'/name).read_text()
            self.assertIn('  contents: write',text);self.assertNotIn('pages: write',text);self.assertNotIn('id-token:',text);self.assertNotIn('python -m v9.',text);self.assertIn('v10_system/CURRENT v10_system/releases reports site docs',text)
            self.assertNotIn('git add data',text);self.assertNotIn('cloud_failure_status.json',text)
    def test_original_repo_data_untouched(self):
        (self.repo/'data').mkdir();(self.repo/'data/v9_forecast_events.jsonl').write_bytes(b'original ledger marker\n')
        ci.publish_worktree(self.repo,self.root,updater=lambda:None)
        self.assertEqual((self.repo/'data/v9_forecast_events.jsonl').read_bytes(),b'original ledger marker\n')
