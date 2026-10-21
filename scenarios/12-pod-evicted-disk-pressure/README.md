# 12. Pods evicted: ephemeral storage (disk) limit exceeded

> Verified on a kind cluster (Kubernetes v1.34.0) on 2026-10-20: **reproduced and fixed**. Failure visible after 21s; healthy 46s after applying the fix. All output below is real, captured by `scripts/run_scenario.py`.

## Try it
```bash
kubectl create namespace pb-12
kubectl -n pb-12 apply -f scenarios/12-pod-evicted-disk-pressure/broken.yaml
# ...diagnose it yourself, then compare with the write-up below
```

Files: `broken.yaml`, `fixed.yaml`

## Symptom
Pods show `Evicted` (STATUS Failed) and are replaced again and again.


```console
$ kubectl -n pb-12 get pods
NAME                          READY   STATUS    RESTARTS   AGE
log-writer-5f8596c6f4-rkxfg   1/1     Running   0          3s
log-writer-5f8596c6f4-zzqjn   0/1     Error     0          22s
```

## Diagnosis
Commands in the order I run them, with the real output:

```console
$ kubectl -n pb-12 get pods -l app=log-writer -o jsonpath='{range .items[?(@.status.reason=="Evicted")]}{.metadata.name}{"  "}{.status.message}{"\n"}{end}' | head -2
log-writer-5f8596c6f4-zzqjn  Pod ephemeral local storage usage exceeds the total limit of containers 100Mi.

$ kubectl -n pb-12 get events --field-selector reason=Evicted -o custom-columns=REASON:.reason,MESSAGE:.message | head -3
REASON    MESSAGE
Evicted   Pod ephemeral local storage usage exceeds the total limit of containers 100Mi.

$ kubectl describe node | grep -E 'DiskPressure|MemoryPressure|PIDPressure'
  MemoryPressure   False   Tue, 20 Oct 2026 19:59:17 -0700   Tue, 20 Oct 2026 19:27:04 -0700   KubeletHasSufficientMemory   kubelet has sufficient memory available
  DiskPressure     False   Tue, 20 Oct 2026 19:59:17 -0700   Tue, 20 Oct 2026 19:27:04 -0700   KubeletHasNoDiskPressure     kubelet has no disk pressure
  PIDPressure      False   Tue, 20 Oct 2026 19:59:17 -0700   Tue, 20 Oct 2026 19:27:04 -0700   KubeletHasSufficientPID      kubelet has sufficient PID available
  Normal  NodeHasNoDiskPressure    32m   kubelet          Node playbook-control-plane status is now: NodeHasNoDiskPressure

$ kubectl -n pb-12 get deploy log-writer -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}'
{"limits":{"ephemeral-storage":"100Mi","memory":"32Mi"},"requests":{"cpu":"10m","ephemeral-storage":"50Mi","memory":"16Mi"}}
```

## Root cause
The container writes a new 20 MB file every 2 seconds and never deletes old ones. Its `ephemeral-storage` limit is 100Mi, so the kubelet evicts the pod once usage passes the limit. The Deployment creates a new pod, which fills up again. Without a limit the same app would fill the node disk, the node would report `DiskPressure`, and the kubelet would evict *other* pods too.

## Fix
Fix the app to rotate its files, and write to a size-limited `emptyDir`. Delete the old Evicted pod objects; they do not go away by themselves.

```diff
--- broken.yaml
+++ fixed.yaml
@@ -15,7 +15,11 @@
         - name: app
           image: busybox:1.36
-          # writes a debug dump to the container filesystem every 2 s and never cleans up
-          command: ["sh", "-c", "i=0; while true; do dd if=/dev/zero of=/tmp/dump-$i bs=1M count=20 2>/dev/null; i=$((i+1)); sleep 2; done"]
+          # keep only the latest dump (rotate), on a size-limited emptyDir
+          command: ["sh", "-c", "while true; do dd if=/dev/zero of=/scratch/dump.tmp bs=1M count=20 2>/dev/null; mv /scratch/dump.tmp /scratch/dump; sleep 2; done"]
+          volumeMounts: [{name: scratch, mountPath: /scratch}]
           resources:
             requests: {cpu: 10m, memory: 16Mi, ephemeral-storage: 50Mi}
             limits: {memory: 32Mi, ephemeral-storage: 100Mi}
+      volumes:
+        - name: scratch
+          emptyDir: {sizeLimit: 80Mi}
```

Fix commands and output:

```console
$ kubectl -n pb-12 apply -f fixed.yaml
deployment.apps/log-writer configured

$ kubectl -n pb-12 rollout status deploy/log-writer --timeout=120s
Waiting for deployment "log-writer" rollout to finish: 1 old replicas are pending termination...
Waiting for deployment "log-writer" rollout to finish: 1 old replicas are pending termination...
deployment "log-writer" successfully rolled out

$ kubectl -n pb-12 delete pods --field-selector=status.phase=Failed
pod "log-writer-5f8596c6f4-zzqjn" deleted from pb-12 namespace
```

After the fix:

```console
$ kubectl -n pb-12 get pods
NAME                         READY   STATUS    RESTARTS   AGE
log-writer-b7886b9f4-wpdnl   1/1     Running   0          46s

$ kubectl -n pb-12 exec deploy/log-writer -- du -sh /scratch
20.0M	/scratch
```

## Prevention
- Set `ephemeral-storage` requests/limits so one noisy pod cannot fill a node.
- Log to stdout and let the runtime rotate logs.
- Alerts `NodeDiskAlmostFull` (node disk) and `KubeNodeNotReady` (if the node goes NotReady).

Alert rules that catch it (from [k8s-monitoring-stack](https://github.com/paulZYF/k8s-monitoring-stack)): [`NodeDiskAlmostFull`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/NodeDiskAlmostFull.md), [`KubeNodeNotReady`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/KubeNodeNotReady.md)

## Time to fix in the demo
46 seconds from applying the fix to healthy (measured by the runner; diagnosis time not included).
