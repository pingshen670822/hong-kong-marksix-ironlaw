from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

from engine import ROOT


def run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True)

def write_status(payload: dict) -> None:
    text=json.dumps(payload,ensure_ascii=False,indent=2)
    for name in ("reports","site","docs"):
        path=ROOT/name/"repair_status.json"
        path.parent.mkdir(exist_ok=True)
        tmp=path.with_suffix(".tmp")
        tmp.write_text(text,encoding="utf-8")
        tmp.replace(path)


def stale_after_two_hours() -> tuple[bool, str]:
    analysis=json.loads((ROOT/"reports"/"latest_analysis.json").read_text(encoding="utf-8"))
    now=datetime.now(timezone(timedelta(hours=8)))
    target=analysis["target_date"]
    latest=analysis["latest_draw"]["date"]
    overdue=(target<=now.date().isoformat() and latest<target and (now.hour>23 or (now.hour==23 and now.minute>=30)))
    return overdue,f"latest={latest}; target={target}; hk_time={now.isoformat(timespec='minutes')}"


def main() -> int:
    from v9.watchdog import main as official_v9_watchdog
    return official_v9_watchdog()
    errors=[]
    for attempt in range(1,5):
        updated=run("update.py")
        verified=run("verify.py") if updated.returncode==0 else updated
        healthy=run("health_check.py") if verified.returncode==0 else verified
        stale,detail=(False,"update failed") if updated.returncode else stale_after_two_hours()
        if updated.returncode==0 and verified.returncode==0 and healthy.returncode==0 and not stale:
            payload={"self_repair":"passed","attempt":attempt,"checked_at":datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),"detail":detail}
            write_status(payload)
            print(json.dumps(payload,ensure_ascii=False))
            return 0
        errors.append({"attempt":attempt,"update":(updated.stdout+updated.stderr)[-1600:],"verify":(verified.stdout+verified.stderr)[-1600:],"health":(healthy.stdout+healthy.stderr)[-1600:],"stale":stale,"detail":detail})
        write_status({"self_repair":"retrying","attempt":attempt,"checked_at":datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),"errors":errors[-1:]})
        if attempt<4: time.sleep(30*attempt)
    payload={"self_repair":"failed","checked_at":datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),"errors":errors}
    write_status(payload)
    print(json.dumps(payload,ensure_ascii=False,indent=2))
    return 1


if __name__=="__main__":
    from v9.watchdog import main as official_v9_watchdog
    raise SystemExit(official_v9_watchdog())
