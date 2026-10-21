#!/usr/bin/env python3
"""Run one scenario end to end on the current kubectl context and record real output.

  python3 scripts/run_scenario.py 05-oomkilled     # or: 05
  python3 scripts/run_scenario.py all

Steps: create namespace pb-NN -> apply broken -> wait until the failure is visible ->
run the diagnosis commands -> apply the fix -> wait until healthy -> record -> delete namespace.
Output goes to scenarios/<name>/output/run.json (used by build_readmes.py).
"""
import json
import os
import pathlib
import subprocess
import sys
import time

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCEN = ROOT / "scenarios"


def sh(cmd, env, timeout=120):
    try:
        p = subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, (out + f"\n(timed out after {timeout}s)").strip()
    return p.returncode, (p.stdout + p.stderr).rstrip()


def wait_for(cmd, env, timeout):
    start = time.time()
    while time.time() - start < timeout:
        rc, out = sh(cmd, env)
        if rc == 0:
            return True, round(time.time() - start, 1)
        time.sleep(3)
    return False, round(time.time() - start, 1)


def run(name):
    d = SCEN / name
    meta = yaml.safe_load((d / "scenario.yaml").read_text())
    for key in ("setup", "break", "symptom", "diagnose", "fix", "verify", "teardown"):
        bad = [c for c in meta.get(key, []) if not isinstance(c, str)]
        if bad:
            sys.exit(f"{name}/scenario.yaml: '{key}' has a non-string entry (quote it): {bad[0]!r}")
    ns = "pb-" + name[:2]
    env = dict(os.environ, NS=ns, DIR=str(d))
    print(f"=== {name}: {meta['title']}")
    record = {"scenario": name, "namespace": ns, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "kubectl": sh("kubectl version -o json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"serverVersion\"][\"gitVersion\"])'", env)[1],
              "steps": []}

    def step(kind, cmd, show=True):
        # setup may install things (e.g. ingress-nginx) and pull images, so it gets more time
        rc, out = sh(cmd, env, timeout=600 if kind == "setup" else meta.get("cmd_timeout", 180))
        record["steps"].append({"phase": kind, "cmd": cmd, "rc": rc, "output": out, "show": show})
        print(f"[{kind}] $ {cmd}\n{out}\n")
        return rc, out

    sh(f"kubectl delete namespace {ns} --ignore-not-found --wait=true", env, timeout=300)
    sh(f"kubectl create namespace {ns}", env)
    for cmd in meta.get("setup", []):
        step("setup", cmd, show=False)
    for cmd in meta.get("break", [f"kubectl -n {ns} apply -f $DIR/broken.yaml"]):
        step("break", cmd)
    ok, waited = wait_for(meta["broken_when"], env, meta.get("broken_timeout", 180))
    record["broken_detected"] = ok
    record["broken_after_s"] = waited
    if not ok:
        print("!! broken state was not reached")
    for cmd in meta["symptom"]:
        step("symptom", cmd)
    for cmd in meta["diagnose"]:
        step("diagnose", cmd)
    t0 = time.time()
    for cmd in meta.get("fix", [f"kubectl -n {ns} apply -f $DIR/fixed.yaml"]):
        step("fix", cmd)
    ok, _ = wait_for(meta["healthy_when"], env, meta.get("fix_timeout", 240))
    record["fixed"] = ok
    record["recovery_s"] = round(time.time() - t0, 1)
    for cmd in meta["verify"]:
        step("verify", cmd)
    if not os.environ.get("KEEP"):
        for cmd in meta.get("teardown", []):
            sh(cmd, env, timeout=300)
        sh(f"kubectl delete namespace {ns} --wait=false", env)
    record["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    (d / "output").mkdir(exist_ok=True)
    (d / "output" / "run.json").write_text(json.dumps(record, indent=2) + "\n")
    status = "FIXED" if record["fixed"] and record["broken_detected"] else "FAILED"
    print(f"=== {name}: broken seen after {record['broken_after_s']}s, {status} in {record['recovery_s']}s")
    return status == "FIXED"


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = sorted(p.name for p in SCEN.iterdir() if (p / "scenario.yaml").exists())
    if arg != "all":
        names = [n for n in names if n == arg or n.startswith(arg + "-")]
    results = {n: run(n) for n in names}
    print("\nSUMMARY")
    for n, r in results.items():
        print(f"  {'PASS' if r else 'FAIL'}  {n}")
    sys.exit(0 if all(results.values()) else 1)
