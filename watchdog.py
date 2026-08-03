from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

from engine import ROOT


def run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True)


def stale_after_two_hours() -> tuple[bool, str]:
    analysis=json.loads((ROOT/"reports"/"latest_analysis.json").read_text(encoding="utf-8"))
    now=datetime.now(timezone(timedelta(hours=8)))
    target=analysis["target_date"]
    latest=analysis["latest_draw"]["date"]
    overdue=(target<=now.date().isoformat() and latest<target and (now.hour>23 or (now.hour==23 and now.minute>=30)))
    return overdue,f"latest={latest}; target={target}; hk_time={now.isoformat(timespec='minutes')}"


def main() -> int:
    errors=[]
    for attempt in range(1,5):
        updated=run("update.py")
        verified=run("verify.py") if updated.returncode==0 else updated
        stale,detail=(False,"update failed") if updated.returncode else stale_after_two_hours()
        if updated.returncode==0 and verified.returncode==0 and not stale:
            print(json.dumps({"self_repair":"passed","attempt":attempt,"detail":detail},ensure_ascii=False))
            return 0
        errors.append({"attempt":attempt,"update":updated.stderr[-1000:],"verify":verified.stderr[-1000:],"stale":stale,"detail":detail})
        if attempt<4: time.sleep(30*attempt)
    print(json.dumps({"self_repair":"failed","errors":errors},ensure_ascii=False,indent=2))
    return 1


if __name__=="__main__":
    raise SystemExit(main())
