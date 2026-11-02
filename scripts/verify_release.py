"""Run the real local release gate after dependency installation.
python -m pip install -e ".[train,dev]"
cd frontend && npm ci && cd ..
python scripts/verify_release.py
"""
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import os

root = Path(__file__).resolve().parents[1]
npm = shutil.which("npm")
checks = [
    ("performance-contract", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_performance.py"], root),
    ("core", [sys.executable, "scripts/check_core.py"], root),
    ("pytest", [sys.executable, "-m", "pytest", "-q"], root),
    ("frontend-contract", ["node", "--test", "frontend/tests/validation.test.mjs", "frontend/tests/depthSemantics.test.mjs"], root),
    ("frontend-build", [npm or "npm", "run", "build"], root/"frontend"),
]
results = []
for name, command, cwd in checks:
    try:
        r = subprocess.run(command, cwd=cwd, text=True, capture_output=True,
                           shell=os.name=="nt" and name=="frontend-build")
        result = {"name":name,"returncode":r.returncode,"output":r.stdout+r.stderr}
    except OSError as exc:
        result = {"name":name,"returncode":1,"output":str(exc)}
    print(name, "PASS" if result["returncode"]==0 else "FAIL")
    print(result["output"])
    results.append(result)
report={"checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"checks":results}
(root/"docs/LOCAL_VERIFICATION.json").write_text(json.dumps(report,indent=2))
sys.exit(0 if all(r["returncode"]==0 for r in results) else 1)
