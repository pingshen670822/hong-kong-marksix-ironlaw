"""Existing contents-write pipeline integration, with no deployment permission expansion.

Only prepares local Git worktree files. A coherent Git commit is the public
transaction boundary; this module does not commit, push, or invoke hosting APIs.
"""
import argparse, json, os, re, shutil, tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .core import ROOT, run, verify_release, verify_model_computation, validate, stamp, digest, canonical, HKT

def restore_current(root=ROOT):
    text=(root/'CURRENT').read_text().strip()
    if not re.fullmatch('[0-9a-f]{64}',text): raise ValueError('Invalid tracked CURRENT release ID')
    if (root/'current').exists():
        if not (root/'current').is_symlink() or (root/'current').resolve()!=(root/'releases'/text).resolve():
            raise ValueError('Local current does not match tracked CURRENT')
    else:
        link=root/'.restore-current'; link.symlink_to(Path('releases')/text); os.replace(link,root/'current')
    verify_release(root/'current')
    return text

def legacy_files(source):
    a=verify_release(source); timestamp=stamp(a['generated_at']).astimezone(HKT).isoformat()
    version={'schema':'marksix_official_v9','engine_schema':'marksix_v10','transport':'v9_loader_compatibility_only','hash':a['release_id'],'updated_at':timestamp,'latest_period':a['latest_draw']['period'],'latest_date':a['latest_draw']['date']}
    projected={**a,'schema':'marksix_official_v9','engine_schema':'marksix_v10','transport':'v9_loader_compatibility_only','canonical_generated_at':a['generated_at'],'generated_at':timestamp,'canonical_analysis_sha256':digest((source/'latest_analysis.json').read_bytes())}
    health={'operational_passed':True,'prediction_gate_passed':False,'status':'官方資料已核驗；正式預測未達資格','formal_qualified':False,'engine_schema':'marksix_v10','latest_period':a['latest_draw']['period'],'latest_date':a['latest_draw']['date'],'release_id':a['release_id'],'currentness':a['currentness']}
    files={'version.json':canonical(version),'latest_analysis.json':canonical(projected),'self_test_report.json':canonical(health),'health_status.json':canonical(health),'index.html':(source/'index.html').read_bytes(),'latest_battle_report.html':(source/'index.html').read_bytes(),'canonical_v10_analysis.json':(source/'latest_analysis.json').read_bytes()}
    files['compatibility_manifest.json']=canonical({'release_id':a['release_id'],'engine_schema':'marksix_v10','files':{n:digest(b) for n,b in files.items()}})
    return files

def validate_outputs(repo, root=ROOT):
    a=verify_release(root/'current'); expected=a['release_id']
    for name in ('docs','site'):
        if verify_release(repo/name)['release_id']!=expected: raise ValueError('Native output differs from current release')
    directory=repo/'reports'; manifest=json.loads((directory/'compatibility_manifest.json').read_text())
    if manifest['release_id']!=expected: raise ValueError('Legacy output differs from current release')
    for name,sha in manifest['files'].items():
        if Path(name).name!=name or digest((directory/name).read_bytes())!=sha: raise ValueError('Legacy output file checksum mismatch')
    v=json.loads((directory/'version.json').read_text()); p=json.loads((directory/'latest_analysis.json').read_text()); h=json.loads((directory/'self_test_report.json').read_text())
    if v['schema']!='marksix_official_v9' or p['schema']!=v['schema'] or p['engine_schema']!='marksix_v10': raise ValueError('Invalid explicit compatibility schema')
    if v['hash']!=expected or h['release_id']!=expected or v['updated_at']!=p['generated_at'] or v['latest_period']!=p['latest_draw']['period'] or h['latest_period']!=v['latest_period'] or not h['operational_passed'] or h['prediction_gate_passed'] or h['formal_qualified']: raise ValueError('Mixed compatibility metadata')
    if (directory/'index.html').read_bytes()!=(root/'current/index.html').read_bytes(): raise ValueError('Compatibility HTML is not canonical report')
    return a

def publish_worktree(repo, root=ROOT, *, updater=None, fail_after=None):
    """Rollback local pointer and all output mirrors on any preparation failure."""
    import fcntl
    repo=Path(repo); root=Path(root)
    with (root/'.ci.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        old_id=restore_current(root); old_text=(root/'CURRENT').read_bytes()
        staging=Path(tempfile.mkdtemp(prefix='.v10-publish-',dir=repo)); replaced=[]; moved=[]
        try:
            (updater or (lambda:run(root,online=True)))()
            a=verify_release(root/'current'); new_id=a['release_id']
            for name in ('docs','site'):
                shutil.copytree((root/'current').resolve(),staging/name)
                verify_release(staging/name)
            (staging/'reports').mkdir()
            for name,raw in legacy_files(root/'current').items(): (staging/'reports'/name).write_bytes(raw)
            for name in ('reports','docs','site'):
                target=repo/name
                if target.exists(): os.replace(target,staging/(name+'.previous')); moved.append(name)
                os.replace(staging/name,target); replaced.append(name)
                if fail_after==name: raise RuntimeError('Injected publication failure after '+name)
            validate_outputs(repo,root)
            temporary=root/'.CURRENT.next'; temporary.write_text(new_id+'\n'); os.replace(temporary,root/'CURRENT')
            return {'release_id':new_id,'prepared_for_git_commit':True,'published':False,'formal_single':a['formal']['single'],'target':a['target']}
        except BaseException:
            for name in reversed(replaced):
                if (repo/name).exists(): shutil.rmtree(repo/name)
            for name in reversed(moved): os.replace(staging/(name+'.previous'),repo/name)
            old_link=root/'.rollback-current'; old_link.symlink_to(Path('releases')/old_id); os.replace(old_link,root/'current')
            temp=root/'.rollback-CURRENT'; temp.write_bytes(old_text); os.replace(temp,root/'CURRENT')
            raise
        finally:
            shutil.rmtree(staging)

def should_repair(event,root=ROOT,now=None):
    if event!='schedule': return True
    try:
        restore_current(root); a=verify_release(root/'current'); age=((now or datetime.now(timezone.utc))-stamp(a['generated_at'])).total_seconds()
        return not (0<=age<=75*60 and a['currentness']['status']=='fresh_verified')
    except (OSError,ValueError,KeyError,TypeError): return True

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('command',choices=['init','update','verify','guard','build']);args=p.parse_args(argv)
    if args.command=='init': result={'release_id':restore_current()}
    elif args.command=='guard':
        value=should_repair(os.environ.get('EVENT_NAME','workflow_dispatch')); result={'run_repair':value}
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('run_repair='+str(value).lower()+'\n')
    elif args.command=='update': result=publish_worktree(ROOT.parent)
    elif args.command=='build':
        restore_current(); result=publish_worktree(ROOT.parent,updater=lambda:run())
    else:
        restore_current(); a=validate_outputs(ROOT.parent)
        raw=(ROOT/'current/official.csv').read_bytes(); manifest=json.loads((ROOT/'current/manifest.json').read_text())
        draws,_=validate(raw,manifest,stamp(a['generated_at']))
        result={'release_id':a['release_id'],'verified':True,
                'fifty_rules_recomputed':verify_model_computation(a,draws)}
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0
