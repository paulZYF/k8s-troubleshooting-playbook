#!/usr/bin/env python3
"""Render docs/demo.gif and docs/summary.png from the recorded runs (scenarios/*/output/run.json).

The GIF is a replay of the real commands and output that run_scenario.py recorded; nothing is
typed by hand. Needs Pillow:  pip install pillow
  python3 scripts/render_docs.py            # demo of scenario 05
  python3 scripts/render_docs.py 01         # demo of another scenario
"""
import json
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCEN = ROOT / "scenarios"
DOCS = ROOT / "docs"
FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
              "/System/Library/Fonts/Menlo.ttc", "C:/Windows/Fonts/consola.ttf"]
W, H, PAD, SIZE, LINE = 1000, 560, 16, 15, 19
BG, FG, DIM, CMD, OK, BAD, BAR = "#1e1f22", "#d4d4d4", "#8a8f98", "#7cc4ff", "#7fd88f", "#ff7b72", "#2b2d31"
PHASE_LABEL = {"break": "1. Apply the broken manifest", "symptom": "2. Symptom", "diagnose": "3. Diagnose",
               "fix": "4. Apply the fix", "verify": "5. Verify"}


def font():
    for p in FONT_PATHS:
        if pathlib.Path(p).exists():
            return ImageFont.truetype(p, SIZE)
    return ImageFont.load_default()


F = font()
MAXCOL = int((W - 2 * PAD) / F.getlength("M")) - 2


def wrap(text):
    out = []
    for ln in text.splitlines() or [""]:
        while len(ln) > MAXCOL:
            out.append(ln[:MAXCOL])
            ln = "  " + ln[MAXCOL:]
        out.append(ln)
    return out


def frame(title, lines):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 30], fill=BAR)
    d.text((PAD, 7), title, font=F, fill=FG)
    rows = (H - 40 - PAD) // LINE
    y = 40
    for color, text in lines[-rows:]:
        d.text((PAD, y), text, font=F, fill=color)
        y += LINE
    return img


def demo(num):
    d = next(p for p in sorted(SCEN.iterdir()) if p.name.startswith(num))
    run = json.loads((d / "output" / "run.json").read_text())
    title = f"k8s-troubleshooting-playbook  {d.name}  (replay of a recorded run on kind {run['kubectl']})"
    frames, durations, buf, phase = [], [], [], None
    for s in run["steps"]:
        if not s.get("show", True):
            continue
        if s["phase"] != phase:
            phase = s["phase"]
            buf = [(DIM, f"# {PHASE_LABEL.get(phase, phase)}")]
        cmd = s["cmd"].replace("$NS", run["namespace"]).replace("$DIR/", f"scenarios/{d.name}/")
        buf.append((CMD, f"$ {wrap(cmd)[0]}"))
        buf += [(CMD, c) for c in wrap(cmd)[1:]]
        frames.append(frame(title, buf)); durations.append(900)
        buf += [(FG, ln) for ln in wrap(s["output"])] + [(FG, "")]
        frames.append(frame(title, buf)); durations.append(2600)
    status = run["fixed"] and run["broken_detected"]
    buf += [(OK if status else BAD, f"# {'fixed' if status else 'NOT fixed'}: healthy {run['recovery_s']:.0f}s after applying the fix")]
    frames.append(frame(title, buf)); durations.append(4000)
    out = DOCS / "demo.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print("wrote", out.relative_to(ROOT), len(frames), "frames")


def summary():
    rows = []
    for d in sorted(p for p in SCEN.iterdir() if (p / "scenario.yaml").exists()):
        f = d / "output" / "run.json"
        if not f.exists():
            rows.append((BAD, f"  NOT RUN  {d.name}"))
            continue
        r = json.loads(f.read_text())
        ok = r["fixed"] and r["broken_detected"]
        detail = (f"broken after {r['broken_after_s']:>5.0f}s   healthy {r['recovery_s']:>4.0f}s after fix"
                  if ok else ("broken state NOT reproduced" if not r["broken_detected"] else "fix did not get healthy"))
        rows.append((OK if ok else BAD, f"  {'PASS' if ok else 'FAIL'}  {d.name:<36} {detail}   ({r['started'][:10]})"))
    passed = sum(1 for c, _ in rows if c == OK)
    lines = [(CMD, "$ python3 scripts/run_scenario.py all"), (FG, ""), (FG, "SUMMARY"), *rows, (FG, ""),
             (FG, f"{passed}/{len(rows)} scenarios reproduced and fixed on a kind cluster")]
    global H
    H = 40 + PAD + LINE * (len(lines) + 1)
    img = frame("k8s-troubleshooting-playbook  run_scenario.py summary (from the recorded runs)", lines)
    img.save(DOCS / "summary.png")
    print("wrote docs/summary.png", f"{passed}/{len(rows)} passed")


if __name__ == "__main__":
    DOCS.mkdir(exist_ok=True)
    demo(sys.argv[1] if len(sys.argv) > 1 else "05")
    summary()
