# 04. Pending: PersistentVolumeClaim not bound (wrong StorageClass)

> Verified on a kind cluster (Kubernetes v1.34.0) on 2026-10-20: **reproduced and fixed**. Failure visible after 0s; healthy 8s after applying the fix. All output below is real, captured by `scripts/run_scenario.py`.

## Try it
```bash
kubectl create namespace pb-04
kubectl -n pb-04 apply -f scenarios/04-pvc-wrong-storageclass/broken.yaml
# ...diagnose it yourself, then compare with the write-up below
```

Files: `broken.yaml`, `fixed.yaml`

## Symptom
The pod is Pending, and the PVC is Pending too.


```console
$ kubectl -n pb-04 get pods,pvc
NAME                           READY   STATUS    RESTARTS   AGE
pod/uploader-cdf64f7d9-gf5wn   0/1     Pending   0          0s

NAME                            STATUS    VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS   VOLUMEATTRIBUTESCLASS   AGE
persistentvolumeclaim/uploads   Pending                                      fast-ssd       <unset>                 0s
```

## Diagnosis
Commands in the order I run them, with the real output:

```console
$ kubectl -n pb-04 describe pod -l app=uploader | sed -n '/Events:/,$p'
Events:
  Type     Reason            Age   From               Message
  ----     ------            ----  ----               -------
  Warning  FailedScheduling  0s    default-scheduler  0/1 nodes are available: pod has unbound immediate PersistentVolumeClaims. not found

$ kubectl -n pb-04 describe pvc uploads | sed -n '/StorageClass:/p;/Events:/,$p'
StorageClass:  fast-ssd
Events:
  Type     Reason              Age   From                         Message
  ----     ------              ----  ----                         -------
  Warning  ProvisioningFailed  0s    persistentvolume-controller  storageclass.storage.k8s.io "fast-ssd" not found

$ kubectl get storageclass
NAME                 PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE      ALLOWVOLUMEEXPANSION   AGE
standard (default)   rancher.io/local-path   Delete          WaitForFirstConsumer   false                  25m
```

## Root cause
The PVC asks for `storageClassName: fast-ssd`, which does not exist in this cluster, so no provisioner ever creates a volume and the PVC stays Pending. The pod waits for its volume.

## Fix
Use an existing class (`kubectl get storageclass`; on kind it is `standard`). `storageClassName` cannot be changed on an existing PVC, so delete and recreate it. On a PVC that already holds data, back the data up first.

```diff
--- broken.yaml
+++ fixed.yaml
@@ -4,5 +4,5 @@
   name: uploads
 spec:
-  storageClassName: fast-ssd   # does not exist in this cluster
+  storageClassName: standard   # the class that exists (kubectl get storageclass)
   accessModes: [ReadWriteOnce]
   resources:
```

Fix commands and output:

```console
$ kubectl -n pb-04 delete deploy uploader --wait=true
deployment.apps "uploader" deleted from pb-04 namespace

$ kubectl -n pb-04 delete pvc uploads --wait=true
persistentvolumeclaim "uploads" deleted from pb-04 namespace

$ kubectl -n pb-04 apply -f fixed.yaml
persistentvolumeclaim/uploads created
deployment.apps/uploader created
```

After the fix:

```console
$ kubectl -n pb-04 get pods,pvc
NAME                           READY   STATUS    RESTARTS   AGE
pod/uploader-cdf64f7d9-jtxvr   1/1     Running   0          8s

NAME                            STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   VOLUMEATTRIBUTESCLASS   AGE
persistentvolumeclaim/uploads   Bound    pvc-6daf822c-776c-403b-9263-4766317df841   1Gi        RWO            standard       <unset>                 8s

$ kubectl -n pb-04 exec deploy/uploader -- cat /data/health
ok
```

## Prevention
- Keep the StorageClass name in Helm values per environment, not hard-coded.
- Mark one class as default so PVCs without a class still bind.
- Alert `PodNotReady`; PVC alerts (`PVCAlmostFull`, `PVCFull`) take over once it is bound.

Alert rules that catch it (from [k8s-monitoring-stack](https://github.com/paulZYF/k8s-monitoring-stack)): [`PodNotReady`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/PodNotReady.md)

## Time to fix in the demo
8 seconds from applying the fix to healthy (measured by the runner; diagnosis time not included).
