#!/usr/bin/env python3
"""Build scenarios/*/README.md from scenario.yaml + the real output in output/run.json,
and the scenario index table in README.md (between the INDEX markers)."""
import difflib
import json
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCEN = ROOT / "scenarios"
MON = "https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook"


def block(steps, phase, ns):
    out = []
    for s in steps:
        if s["phase"] != phase or not s.get("show", True):
            continue
        cmd = s["cmd"].replace("$NS", ns).replace("$DIR/", "")
        out.append(f"$ {cmd}\n{s['output']}".rstrip())
    return "```console\n" + "\n\n".join(out) + "\n```" if out else ""


def diff(d):
    la = (d / "broken.yaml").read_text().splitlines(keepends=True)
    lb = (d / "fixed.yaml").read_text().splitlines(keepends=True)
    txt = "".join(difflib.unified_diff(la, lb, "broken.yaml", "fixed.yaml", n=2))
    return "```diff\n" + txt.rstrip() + "\n```"


index = []
for d in sorted(p for p in SCEN.iterdir() if (p / "scenario.yaml").exists()):
    m = yaml.safe_load((d / "scenario.yaml").read_text())
    run_file = d / "output" / "run.json"
    run = json.loads(run_file.read_text()) if run_file.exists() else None
    verified = bool(run and run["fixed"] and run["broken_detected"])
    ns = f"pb-{d.name[:2]}"
    files = sorted(p.name for p in d.iterdir() if p.is_file() and p.suffix == ".yaml" and p.name != "scenario.yaml")
    md = [f"# {d.name[:2]}. {m['title']}", ""]
    if verified:
        md += [f"> Verified on a kind cluster (Kubernetes {run['kubectl']}) on {run['started'][:10]}: **reproduced and fixed**. "
               f"Failure visible after {run['broken_after_s']:.0f}s; healthy {run['recovery_s']:.0f}s after applying the fix. "
               "All output below is real, captured by `scripts/run_scenario.py`.", ""]
    else:
        reason = m.get("not_verified_reason", "It has not been run yet.")
        md += [f"> **Not verified.** {reason} The manifests and the write-up below are provided, "
               "but there is no recorded output for this scenario.", ""]
        run = None  # never show output from a run that did not reproduce the problem
    md += ["## Try it", "```bash", f"kubectl create namespace {ns}"]
    if "break" in m:
        md += [c.replace("$NS", ns).replace("$DIR/", f"scenarios/{d.name}/") for c in m["break"]]
    else:
        md += [f"kubectl -n {ns} apply -f scenarios/{d.name}/broken.yaml"]
    md += ["# ...diagnose it yourself, then compare with the write-up below", "```", "",
           f"Files: {', '.join(f'`{f}`' for f in files)}" + (", `chart/`" if (d / 'chart').exists() else ""), "",
           "## Symptom", m["symptom_text"], ""]
    if run:
        md += [block(run["steps"], "break", ns) if "break" in m else "", "", block(run["steps"], "symptom", ns), "",
               "## Diagnosis", "Commands in the order I run them, with the real output:", "",
               block(run["steps"], "diagnose", ns), ""]
    md += ["## Root cause", m["root_cause"], "", "## Fix", m["fix_text"], "", diff(d), ""]
    if run:
        if "fix" in m:
            md += ["Fix commands and output:", "", block(run["steps"], "fix", ns), ""]
        md += ["After the fix:", "", block(run["steps"], "verify", ns), ""]
    md += ["## Prevention", *[f"- {p}" for p in m["prevention"]]]
    if m.get("alerts"):
        md += ["", "Alert rules that catch it (from [k8s-monitoring-stack](https://github.com/paulZYF/k8s-monitoring-stack)): "
               + ", ".join(f"[`{a}`]({MON}/{a}.md)" for a in m["alerts"])]
    if run:
        md += ["", "## Time to fix in the demo",
               f"{run['recovery_s']:.0f} seconds from applying the fix to healthy (measured by the runner; "
               "diagnosis time not included)."]
    (d / "README.md").write_text("\n".join(x for x in md if x is not None).replace("\n\n\n", "\n\n") + "\n")
    index.append(f"| [{d.name[:2]}]({'scenarios/' + d.name}/README.md) | {m['title']} | "
                 f"{m['root_cause'].split('. ')[0].replace('|', '/')}. | {'yes' if verified else 'no'} |")

readme = ROOT / "README.md"
table = "\n".join(["| # | Scenario | Root cause (short) | Verified on kind |", "|---|---|---|---|", *index])
txt = readme.read_text()
txt = re.sub(r"<!-- INDEX -->.*<!-- /INDEX -->", f"<!-- INDEX -->\n{table}\n<!-- /INDEX -->", txt, flags=re.S)
readme.write_text(txt)
print(f"built {len(index)} scenario READMEs")
