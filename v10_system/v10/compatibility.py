"""Explicit legacy transport projection for the existing V9 page's read-only loader.

This is not the V10 canonical analysis; the engine_schema remains marksix_v10.
No upload, commit, browser navigation or hosting change is performed here.
"""
import argparse, json, os, shutil, tempfile
from pathlib import Path
from .core import ROOT,HKT,canonical,digest,stamp,verify_release

def export_legacy(destination):
    source=(ROOT/'current').resolve(); a=verify_release(source); destination=Path(destination).resolve()
    if destination.exists(): raise ValueError('Existing destination is never overwritten')
    destination.parent.mkdir(parents=True,exist_ok=True)
    timestamp=stamp(a['generated_at']).astimezone(HKT).isoformat()
    version={'schema':'marksix_official_v9','engine_schema':'marksix_v10','transport':'v9_loader_compatibility_only','hash':a['release_id'],'updated_at':timestamp,'latest_period':a['latest_draw']['period'],'latest_date':a['latest_draw']['date']}
    projected={**a,'schema':'marksix_official_v9','engine_schema':'marksix_v10','transport':'v9_loader_compatibility_only','canonical_generated_at':a['generated_at'],'generated_at':timestamp,'canonical_analysis_sha256':digest((source/'latest_analysis.json').read_bytes())}
    health={'operational_passed':True,'formal_qualified':False,'engine_schema':'marksix_v10','latest_period':a['latest_draw']['period'],'latest_date':a['latest_draw']['date'],'release_id':a['release_id'],'currentness':a['currentness']}
    files={'version.json':canonical(version),'latest_analysis.json':canonical(projected),'self_test_report.json':canonical(health),'index.html':(source/'index.html').read_bytes(),'latest_battle_report.html':(source/'index.html').read_bytes(),'canonical_v10_analysis.json':(source/'latest_analysis.json').read_bytes()}
    for marker in [a['release_id'],a['latest_draw']['period']]:
        if f'content="{marker}"'.encode() not in files['index.html']: raise ValueError('Legacy HTML identity mismatch')
    files['compatibility_manifest.json']=canonical({'release_id':a['release_id'],'engine_schema':'marksix_v10','files':{n:digest(b) for n,b in files.items()}})
    staging=Path(tempfile.mkdtemp(prefix='.compat-',dir=destination.parent))
    try:
        for name,raw in files.items(): (staging/name).write_bytes(raw)
        os.replace(staging,destination)
    finally:
        if staging.exists(): shutil.rmtree(staging)
    return {'directory':str(destination),'release_id':a['release_id'],'published':False,'warning':'Legacy-loader compatibility projection, not a primary-site redeployment'}

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('destination'); args=p.parse_args()
    print(json.dumps(export_legacy(args.destination),indent=2))
