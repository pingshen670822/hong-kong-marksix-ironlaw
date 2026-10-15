"""V10 immutable inputs, causal research, and atomic publication.

The sole public pointer is current -> releases/<content id>. All output/data/
ledger files are committed as one directory. No imported file is ever rewritten.
"""
from __future__ import annotations
import csv, hashlib, io, json, os, re, shutil, tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from v9.official_source import OfficialDraw, ENDPOINT, fetch_months, fetch_upcoming
from .model50 import replay
from v9.ledger import load_events as load_legacy

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
HKT = timezone(timedelta(hours=8))
VERSION = '10.1.0'
MAX_SOURCE_AGE = 86400
FIELDS = ['period','draw_date','n1','n2','n3','n4','n5','n6','special','source_id']
GENESIS = '0' * 64

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode()

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def stamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Timestamp must include a timezone')
    return result.astimezone(UTC)

def source_identity(source_id):
    match = re.fullmatch(r'(\d{4})(\d{1,3})N', source_id)
    if not match or not 1 <= int(match[2]) <= 999:
        raise ValueError('Invalid official source identity')
    return int(match[1]), int(match[2])

def validate(raw, manifest, now):
    if not isinstance(manifest, dict) or manifest.get('endpoint') != ENDPOINT:
        raise ValueError('Missing or invalid official provenance manifest')
    if digest(raw) != manifest.get('sha256') or manifest.get('legacy_data_used_for_model') is not False:
        raise ValueError('Official data hash/provenance mismatch')
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8')))
    if reader.fieldnames != FIELDS:
        raise ValueError('Unexpected data columns')
    draws = []
    years = {}
    for row in reader:
        when = date.fromisoformat(row['draw_date'])
        year, number = source_identity(row['source_id'])
        if when.isoformat() != row['draw_date'] or when > now.astimezone(HKT).date() or when.year < 2003:
            raise ValueError('Invalid/future draw date')
        if year != when.year or row['period'] != f'{year % 100:02d}/{number:03d}':
            raise ValueError('Date, period, source identity mismatch')
        main = tuple(int(row[f'n{i}']) for i in range(1,7)); special = int(row['special'])
        if len(set(main + (special,))) != 7 or any(n < 1 or n > 49 for n in main + (special,)) or main != tuple(sorted(main)):
            raise ValueError('Invalid seven distinct 1..49 balls')
        if draws and (when.isoformat() <= draws[-1].draw_date or row['period'] == draws[-1].period):
            raise ValueError('Duplicate/unordered draw')
        periods = years.setdefault(year, [])
        if number != len(periods) + 1:
            raise ValueError('Missing/duplicate/out-of-order yearly period')
        periods.append(number)
        draws.append(OfficialDraw(row['period'],row['draw_date'],main,special,row['source_id']))
    if not draws or list(years) != list(range(2003,int(draws[-1].draw_date[:4])+1)):
        raise ValueError('Missing history year')
    facts = {'count':len(draws),'first':draws[0].draw_date,'latest':draws[-1].draw_date,'latest_period':draws[-1].period}
    if any(manifest.get(k) != v for k,v in facts.items()):
        raise ValueError('Manifest row count/date/period mismatch')
    retrieved = stamp(manifest['retrieved_at_utc'])
    if retrieved > now + timedelta(minutes=5) or retrieved.astimezone(HKT).date().isoformat() < draws[-1].draw_date:
        raise ValueError('Manifest retrieval time is inconsistent')
    bootstrap = manifest.get('history_bootstrap')
    if not isinstance(bootstrap,dict) or bootstrap.get('mode') != 'full_official_bootstrap' or bootstrap.get('queried_months_from') != '2003-01':
        raise ValueError('Missing full-history provenance declaration')
    return draws, {'years':len(years),'consecutive_periods':True,'scope':'Internal sequence validation; source declaration retained, not an independent fresh full-history audit'}

def serialize(draws):
    out = io.StringIO(newline=''); writer=csv.writer(out,lineterminator='\n'); writer.writerow(FIELDS)
    for d in draws: writer.writerow([d.period,d.draw_date,*d.main,d.special,d.source_id])
    return out.getvalue().encode()

def verify_preserved(root):
    pins=json.loads((root/'baseline/preserved.json').read_text())
    for name, expected in pins.items():
        if digest((root/name).read_bytes()) != expected: raise ValueError('Imported baseline changed: '+name)
    load_legacy(root/'data/v9_forecast_events.jsonl')
    return pins

def source_snapshot(root):
    current=root/'current'
    directory=current if current.exists() else root/'data'
    names=('official.csv','manifest.json') if current.exists() else ('hkjc_verified_v9.csv','hkjc_verified_v9_manifest.json')
    return (directory/names[0]).read_bytes(), json.loads((directory/names[1]).read_text())

def refresh(draws, old_raw, manifest, now, fetcher=fetch_months):
    today=now.astimezone(HKT).date(); first= today.replace(day=1)-timedelta(days=183)
    start=(first.year,first.month); start_date=f'{first.year:04d}-{first.month:02d}-01'
    recent=fetcher(start,(today.year,today.month),workers=3)
    if not recent: raise ValueError('Official refresh is empty')
    old={d.period:d for d in draws}; incoming={d.period:d for d in recent}
    if len(incoming)!=len(recent): raise ValueError('Duplicate official refresh period')
    for d in draws:
        if d.draw_date >= start_date and incoming.get(d.period) != d:
            raise ValueError('Official refresh missing/revises existing result')
    for d in recent:
        if d.draw_date < start_date or d.draw_date > today.isoformat(): raise ValueError('Out-of-range official result')
        if d.period in old and old[d.period] != d: raise ValueError('Official result conflict')
        old[d.period]=d
    merged=sorted(old.values(),key=lambda d:d.draw_date)
    raw=old_raw if merged==draws else serialize(merged)
    new={**manifest,'count':len(merged),'first':merged[0].draw_date,'latest':merged[-1].draw_date,
         'latest_period':merged[-1].period,'sha256':digest(raw),'retrieved_at_utc':now.isoformat(),
         'evidence':{'mode':'v10_complete_recent_window','from':start_date,'through':today.isoformat(),'rows':len(recent)}}
    validate(raw,new,now)
    return raw,new

def target_evidence(upcoming, latest, now):
    unknown={'period':None,'date':None,'status':'unverified','source':None,'cutoff_policy':'Conservative: forecasts made on or after the target Hong Kong date are not scored'}
    if upcoming is None: return unknown
    if upcoming.get('source') != ENDPOINT or upcoming.get('status') != 'Defined': raise ValueError('Untrusted upcoming source')
    year,num=source_identity(upcoming['source_id']); when=date.fromisoformat(upcoming['date'])
    if when.year != year or when.isoformat() != upcoming['date'] or when.isoformat() <= latest.draw_date:
        raise ValueError('Upcoming identity/date inconsistent with latest result')
    latest_year,latest_num=source_identity(latest.source_id)
    if not ((year==latest_year and num==latest_num+1) or (year==latest_year+1 and num==1)):
        raise ValueError('Upcoming period is not immediately after latest result')
    return {**unknown,'period':f'{year%100:02d}/{num:03d}','date':when.isoformat(),'status':'official_announced','source':ENDPOINT}

def load_chain(raw):
    events=[]; previous=GENESIS; seals={}; settled=set()
    for line in raw.splitlines():
        if not line.strip(): raise ValueError('Blank ledger line')
        e=json.loads(line); body={k:v for k,v in e.items() if k!='hash'}
        if e.get('previous_hash') != previous or digest(canonical(body)) != e.get('hash'): raise ValueError('V10 chain broken')
        if e.get('kind')=='seal':
            if e['based_on_period'] in seals: raise ValueError('Duplicate basis seal')
            if sorted(e['ranking'])!=list(range(1,50)) or e['single'] != e['ranking'][0] or e['top9']!=e['ranking'][:9]: raise ValueError('Invalid sealed ranking')
            stamp(e['created_at_utc']); seals[e['based_on_period']]=e
        elif e.get('kind')=='settlement':
            if e['seal_hash'] in settled or not any(s['hash']==e['seal_hash'] for s in seals.values()): raise ValueError('Unknown/duplicate settlement')
            settled.add(e['seal_hash'])
        else: raise ValueError('Unknown ledger event')
        previous=e['hash']; events.append(e)
    return events

def audit_chain(events, draws, now):
    """Validate economic/temporal meaning, not only the cryptographic links."""
    by_period={d.period:i for i,d in enumerate(draws)}; seals={}
    for e in events:
        if e['kind']=='seal':
            index=by_period.get(e['based_on_period'])
            if index is None or e['based_on_date']!=draws[index].draw_date:
                raise ValueError('Seal basis does not match verified draw')
            created=stamp(e['created_at_utc'])
            if created>now or created.astimezone(HKT).date().isoformat()<draws[index].draw_date:
                raise ValueError('Seal creation date is inconsistent')
            if e['data_sha256']!=digest(serialize(draws[:index+1])):
                raise ValueError('Seal source prefix hash mismatch')
            if e.get('formal_single') is not None or e.get('purpose')!='research_only':
                raise ValueError('Unqualified formal selection in research ledger')
            if e.get('normal_baseline')!=6/49 or e.get('extra_baseline')!=1/49:
                raise ValueError('Incorrect sealed probability definition')
            if not re.fullmatch('[0-9a-f]{64}',e['code_sha256']): raise ValueError('Invalid sealed code identity')
            target=e['target']
            if target.get('period') is not None:
                target_evidence({'source':target.get('source'),'status':'Defined','source_id':f"20{target['period'][:2]}{int(target['period'][3:])}N",'date':target['date']},draws[index],created)
            elif target.get('date') is not None: raise ValueError('Target date without identity')
            seals[e['hash']]=e
        else:
            seal=seals[e['seal_hash']]; index=by_period[seal['based_on_period']]+1
            if index>=len(draws): raise ValueError('Settlement before official result')
            actual=draws[index]; eligible=stamp(seal['created_at_utc']).astimezone(HKT).date().isoformat()<actual.draw_date
            expected={'actual_period':actual.period,'actual_date':actual.draw_date,'actual_main':list(actual.main),'actual_special':actual.special,'eligible':eligible,'normal_hit':int(seal['single'] in actual.main) if eligible else None}
            if any(e.get(k)!=v for k,v in expected.items()): raise ValueError('Settlement meaning conflicts with official result')
            settled=stamp(e['settled_at_utc'])
            if settled>now or settled<stamp(seal['created_at_utc']) or settled.astimezone(HKT).date().isoformat()<actual.draw_date:
                raise ValueError('Settlement timestamp is inconsistent')
            if seal['target'].get('period') not in (None,actual.period) or seal['target'].get('date') not in (None,actual.draw_date):
                raise ValueError('Settlement changed the sealed target')
    return True

def ledger_update(raw, draws, model, target, sha, code_sha, now):
    events=load_chain(raw); added=[]
    def append(body):
        e={**body,'previous_hash':events[-1]['hash'] if events else GENESIS}; e['hash']=digest(canonical(e)); events.append(e); added.append(canonical(e)+b'\n'); return e
    by_period={d.period:i for i,d in enumerate(draws)}
    settlements={e['seal_hash'] for e in events if e['kind']=='settlement'}
    for seal in [e for e in events if e['kind']=='seal']:
        if seal['hash'] in settlements: continue
        index=by_period.get(seal['based_on_period'])
        if index is None: raise ValueError('Seal basis missing from dataset')
        if index+1>=len(draws): continue
        actual=draws[index+1]
        if seal['target']['period'] is not None and seal['target']['period']!=actual.period: raise ValueError('Sealed target/result mismatch')
        if seal['target']['date'] is not None and seal['target']['date']!=actual.draw_date: raise ValueError('Sealed target date changed; manual review required')
        eligible=stamp(seal['created_at_utc']).astimezone(HKT).date().isoformat()<actual.draw_date
        append({'kind':'settlement','seal_hash':seal['hash'],'settled_at_utc':now.isoformat(),'actual_period':actual.period,'actual_date':actual.draw_date,'actual_main':list(actual.main),'actual_special':actual.special,'eligible':eligible,'normal_hit':int(seal['single'] in actual.main) if eligible else None,'reason':None if eligible else 'Not proven before target Hong Kong calendar day'})
    seal=next((e for e in events if e['kind']=='seal' and e['based_on_period']==draws[-1].period),None)
    if seal is None:
        seal=append({'kind':'seal','created_at_utc':now.isoformat(),'based_on_period':draws[-1].period,'based_on_date':draws[-1].draw_date,'data_sha256':sha,'code_sha256':code_sha,'model':model['selected_model'],'single':model['single'],'top9':model['top9'],'ranking':model['rank'],'target':target,'formal_single':None,'purpose':'research_only','timing_status':'provisional_until_official_result_and_cutoff_audit','normal_baseline':6/49,'extra_baseline':1/49})
    if seal['data_sha256'] != sha: raise ValueError('Existing seal data hash differs for same basis')
    return raw+b''.join(added),events,seal

@contextmanager
def writer_lock(root):
    import fcntl
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.update.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield

def code_hash(root):
    files=sorted(list((root/'v10').glob('*.py'))+[root/'v9/model.py',root/'v9/official_source.py',root/'v9/ledger.py'])
    return digest(b''.join(str(p.relative_to(root)).encode()+b'\0'+p.read_bytes()+b'\0' for p in files))

def analyze(draws,manifest,coverage,model,events,seal,legacy,code_sha,now,mode,target):
    age=(now-stamp(manifest['retrieved_at_utc'])).total_seconds()
    status='fresh_verified' if mode=='online' and 0<=age<=MAX_SOURCE_AGE else 'snapshot' if age<=MAX_SOURCE_AGE else 'expired'
    scored=[e for e in events if e['kind']=='settlement' and e['eligible']]
    # Repetition is descriptive across imported/current seals, never performance pooling.
    by_basis={e['based_on_period']:e for e in legacy if e.get('kind')=='forecast'}
    by_basis.update({e['based_on_period']:e for e in events if e['kind']=='seal'})
    seals=sorted(by_basis.values(),key=lambda e:e['based_on_date']); run=0
    for s in reversed(seals):
        if s['single']!=seal['single']: break
        run+=1
    selected=model['models'][model['selected_model']]
    latest=draws[-1]
    oldsettled=[e for e in legacy if e.get('kind')=='settlement']
    return {'schema':'marksix_v10','version':VERSION,'generated_at':now.isoformat(),'code_sha256':code_sha,
        'data':{**{k:manifest[k] for k in ('sha256','count','first','latest','latest_period','retrieved_at_utc')},'coverage':coverage},
        'currentness':{'status':status,'age_seconds':age,'reason':'Official source checked during this run' if status=='fresh_verified' else 'Offline verified snapshot; latest official result is not freshly confirmed' if status=='snapshot' else 'Source receipt older than 24 hours'},
        'latest_draw':{'period':latest.period,'date':latest.draw_date,'main':list(latest.main),'special':latest.special},'target':target,
        'formal':{'single':None,'status':'unqualified','reason':'Research-only policy: no preregistered prospective validation establishes a predictive edge'},
        'research':{'model':model['selected_model'],'rank':model['rank'],'top9':model['top9'],'single':model['single'],'score_kind':model['score_kind'],'adjusted_p':model['evaluation_adjusted_p'],'candidate_count':model['candidate_count'],'catalog':model['catalog'],'model_results':model['models'],'selection_rule':model['rule'],'normal_baseline':6/49,'extra_baseline':1/49,'repeat_guard':{'repeated':run>1,'consecutive':run,'scope':'distinct basis draws across preserved V9 and V10 research seals; not performance pooling','warning':'Repeated research number is not extra confidence; formal selection remains blank'},'differs_from_seal':model['rank']!=seal['ranking'],'evaluation_window':[model['selected_replay_rows'][-120]['date'],model['selected_replay_rows'][-1]['date']]},
        'evidence':{**{k:selected[k] for k in ('development_rounds','development_hits','evaluation_rounds','evaluation_hits')},'prospective_rounds':len(scored),'prospective_hits':sum(e['normal_hit'] for e in scored),'qualification':'Not established; rolling historical holdout is exploratory, not independent prospective proof'},
        'seal':seal,'legacy':{'sha256':digest((ROOT/'data/v9_forecast_events.jsonl').read_bytes()),'events':len(legacy),'settlements':len(oldsettled),'hits':sum(e['single_hit'] for e in oldsettled),'caveat':'Imported V9 ledger retained unchanged; not V10 prospective performance. Local hash chains are tamper-evident, not independent timestamps.'}}

def verify_release(path):
    release=json.loads((path/'release.json').read_text())
    for name,sha in release['files'].items():
        if Path(name).name!=name or digest((path/name).read_bytes())!=sha: raise ValueError('Release checksum mismatch: '+name)
    a=json.loads((path/'latest_analysis.json').read_text()); version=json.loads((path/'version.json').read_text()); health=json.loads((path/'health_status.json').read_text())
    if not a['release_id']==version['hash']==release['release_id']==health['release_id']: raise ValueError('Mixed release metadata')
    if 'self_test_report.json' in release['files'] and (path/'self_test_report.json').read_bytes()!=(path/'health_status.json').read_bytes(): raise ValueError('Self-test and health status differ')
    original={k:v for k,v in a.items() if k!='release_id'}
    if digest(canonical(original))!=a['release_id']: raise ValueError('Analysis identity mismatch')
    for name in ('index.html','latest_battle_report.html'):
        if f'content="{a["release_id"]}"' not in (path/name).read_text(): raise ValueError('HTML version identity missing')
    events=load_chain((path/'forecast_events.jsonl').read_bytes())
    if not any(e==a['seal'] for e in events): raise ValueError('Displayed seal missing from ledger')
    draws,_=validate((path/'official.csv').read_bytes(),json.loads((path/'manifest.json').read_text()),stamp(a['generated_at']))
    audit_chain(events,draws,stamp(a['generated_at']))
    scored=[e for e in events if e['kind']=='settlement' and e['eligible']]
    if a['evidence']['prospective_rounds']!=len(scored) or a['evidence']['prospective_hits']!=sum(e['normal_hit'] for e in scored): raise ValueError('Report score differs from verified settlements')
    if a.get('version')=='10.1.0':
        research=a['research']; catalog=research['catalog']; results=research['model_results']
        if research['candidate_count']!=50 or len(catalog)!=50 or len(results)!=50 or {row['name'] for row in catalog}!=set(results):
            raise ValueError('Incomplete 50-rule research audit')
        if research['model'] not in results or results[research['model']]['current_first']!=research['single']:
            raise ValueError('Selected research rule and current ranking disagree')
        if any(row['name'] not in results or results[row['name']]['family']!=row['family'] or
               results[row['name']]['parameter']!=row['parameter'] or
               results[row['name']]['development_rounds']!=400 or
               results[row['name']]['evaluation_rounds']!=120 for row in catalog):
            raise ValueError('50-rule results do not match registered rules or validation windows')
    if a['formal']['single'] is not None: raise ValueError('Unqualified formal output')
    return a

def verify_model_computation(a, draws):
    """Recompute every research rule from the verified official rows.

    The release checker can inspect old immutable releases after code changes;
    this stronger check is used for the newly prepared current release before
    its Git commit and publication.
    """
    if a.get('version')!='10.1.0': return False
    calculated=replay(draws); research=a['research']; evidence=a['evidence']
    expected=(('candidate_count',calculated['candidate_count']),
              ('catalog',calculated['catalog']),('model_results',calculated['models']),
              ('model',calculated['selected_model']),('rank',calculated['rank']),
              ('top9',calculated['top9']),('single',calculated['single']),
              ('adjusted_p',calculated['evaluation_adjusted_p']),
              ('selection_rule',calculated['rule']))
    if any(research.get(key)!=value for key,value in expected):
        raise ValueError('Published 50-rule calculation differs from independent rerun')
    chosen=calculated['models'][calculated['selected_model']]
    if any(evidence.get(key)!=chosen[key] for key in
           ('development_rounds','development_hits','evaluation_rounds','evaluation_hits')):
        raise ValueError('Published research validation totals differ from independent rerun')
    return True

def run(root=ROOT, *, now=None, online=False, fetcher=fetch_months, upcoming_fetcher=fetch_upcoming, fail_at=None):
    now=now or datetime.now(UTC)
    if now.tzinfo is None: raise ValueError('Naive runtime')
    from .report import render
    with writer_lock(root):
        verify_preserved(root)
        if (root/'current').exists(): verify_release(root/'current')
        raw,manifest=source_snapshot(root); draws,coverage=validate(raw,manifest,now)
        upcoming=None
        if online:
            raw,manifest=refresh(draws,raw,manifest,now,fetcher); draws,coverage=validate(raw,manifest,now)
            upcoming=upcoming_fetcher() # Fail closed on source/network errors, never silently publish as live.
            if upcoming is None: raise ValueError('Official next-draw evidence unavailable; keeping last good release')
        target=target_evidence(upcoming,draws[-1],now)
        model=replay(draws); code_sha=code_hash(root)
        oldledger=(root/'current/forecast_events.jsonl').read_bytes() if (root/'current').exists() else b''
        audit_chain(load_chain(oldledger),draws,now)
        ledger,events,seal=ledger_update(oldledger,draws,model,target,manifest['sha256'],code_sha,now)
        audit_chain(events,draws,now)
        legacy=load_legacy(root/'data/v9_forecast_events.jsonl')
        a=analyze(draws,manifest,coverage,model,events,seal,legacy,code_sha,now,'online' if online else 'offline',target)
        a['legacy']['sha256']=digest((root/'data/v9_forecast_events.jsonl').read_bytes())
        a['release_id']=digest(canonical(a)); rid=a['release_id']
        health={'release_id':rid,'operational_passed':True,'source_live_checked':online,'currentness':a['currentness'],'formal_qualified':False,
                'prediction_gate_passed':False,'latest_period':draws[-1].period,'latest_date':draws[-1].draw_date,
                'status':'官方資料已核驗；正式預測未達資格' if online else '已驗證快照；尚未即時核對官方最新開獎'}
        files={'official.csv':raw,'manifest.json':canonical(manifest),'forecast_events.jsonl':ledger,'latest_analysis.json':canonical(a),
               'version.json':canonical({'schema':'marksix_v10','hash':rid,'updated_at':a['generated_at'],'latest_period':draws[-1].period,'latest_date':draws[-1].draw_date,'code_sha256':code_sha}),
               'health_status.json':canonical(health),'self_test_report.json':canonical(health)}
        html=render(a).encode(); files['index.html']=html; files['latest_battle_report.html']=html
        releases=root/'releases'; releases.mkdir(exist_ok=True)
        staging=Path(tempfile.mkdtemp(prefix='.staging-',dir=releases))
        try:
            for name,content in files.items():
                with (staging/name).open('wb') as stream: stream.write(content); stream.flush(); os.fsync(stream.fileno())
            with (staging/'release.json').open('wb') as stream:
                stream.write(canonical({'release_id':rid,'files':{n:digest(b) for n,b in files.items()}})); stream.flush(); os.fsync(stream.fileno())
            descriptor=os.open(staging,os.O_RDONLY); os.fsync(descriptor); os.close(descriptor)
            verify_release(staging)
            if fail_at=='before_commit': raise RuntimeError('Injected failure before commit')
            final=releases/rid
            if final.exists(): verify_release(final); shutil.rmtree(staging)
            else: os.replace(staging,final)
            descriptor=os.open(releases,os.O_RDONLY); os.fsync(descriptor); os.close(descriptor)
            temp=root/('.current-'+str(os.getpid())); temp.symlink_to(Path('releases')/rid)
            try:
                if fail_at=='before_pointer': raise RuntimeError('Injected failure before pointer')
                os.replace(temp,root/'current')
            finally:
                if temp.is_symlink(): temp.unlink()
            descriptor=os.open(root,os.O_RDONLY); os.fsync(descriptor); os.close(descriptor)
            return a
        finally:
            if staging.exists(): shutil.rmtree(staging)
