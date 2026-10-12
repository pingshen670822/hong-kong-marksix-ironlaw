import argparse, json
from .core import ROOT, run, verify_release
p=argparse.ArgumentParser(description='V10 fail-closed Mark Six research pipeline')
p.add_argument('command',choices=['build','update','verify'],nargs='?',default='build')
a=p.parse_args()
r=verify_release(ROOT/'current') if a.command=='verify' else run(online=a.command=='update')
print(json.dumps({'release':r['release_id'],'period':r['latest_draw']['period'],'source':r['currentness']['status'],'formal_single':r['formal']['single'],'research_single':r['research']['single']},ensure_ascii=False,indent=2))
