#!/usr/bin/env bash
# Offline checks: YAML lint, Kubernetes schema validation (kubeconform), Helm lint for scenario 11,
# and that every scenario.yaml loads with the fields the runner needs. No cluster needed.
set -euo pipefail
cd "$(dirname "$0")/.."
K8S_VERSION="${K8S_VERSION:-1.34.0}"
echo ">> yamllint"
yamllint -c .yamllint.yaml .
echo ">> kubeconform (broken.yaml / fixed.yaml)"
kubeconform -strict -summary -kubernetes-version "$K8S_VERSION" \
  $(ls scenarios/*/broken.yaml scenarios/*/fixed.yaml | grep -v 11-helm-upgrade-rollback)
echo ">> helm lint + kubeconform (scenario 11 chart with each values file)"
C=scenarios/11-helm-upgrade-rollback
helm lint "$C/chart" >/dev/null
for v in values-v1.yaml broken.yaml fixed.yaml; do
  helm template catalog "$C/chart" -f "$C/$v" | kubeconform -strict -summary -kubernetes-version "$K8S_VERSION" -
done
echo ">> scenario.yaml structure"
python3 - <<'PY'
import pathlib, sys, yaml
need = ["title", "symptom_text", "broken_when", "symptom", "diagnose", "healthy_when", "verify",
        "root_cause", "fix_text", "prevention"]
bad = 0
for f in sorted(pathlib.Path("scenarios").glob("*/scenario.yaml")):
    m = yaml.safe_load(f.read_text())
    for k in need:
        if k not in m:
            print(f"{f}: missing {k}"); bad += 1
    for k in ("setup", "break", "symptom", "diagnose", "fix", "verify", "teardown", "prevention"):
        for c in m.get(k, []) or []:
            if not isinstance(c, str):
                print(f"{f}: {k} entry is not a string (quote it): {c!r}"); bad += 1
print(f"{len(list(pathlib.Path('scenarios').glob('*/scenario.yaml')))} scenario files checked, {bad} problems")
sys.exit(1 if bad else 0)
PY
