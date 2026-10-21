# 02. ImagePullBackOff: wrong image tag

> Verified on a kind cluster (Kubernetes v1.34.0) on 2026-10-20: **reproduced and fixed**. Failure visible after 3s; healthy 2s after applying the fix. All output below is real, captured by `scripts/run_scenario.py`.

## Try it
```bash
kubectl create namespace pb-02
kubectl -n pb-02 apply -f scenarios/02-imagepullbackoff/broken.yaml
# ...diagnose it yourself, then compare with the write-up below
```

Files: `broken.yaml`, `fixed.yaml`

## Symptom
The pod stays in ErrImagePull / ImagePullBackOff and never starts.


```console
$ kubectl -n pb-02 get pods
NAME                  READY   STATUS         RESTARTS   AGE
web-f4995468b-t2cxm   0/1     ErrImagePull   0          3s
```

## Diagnosis
Commands in the order I run them, with the real output:

```console
$ kubectl -n pb-02 describe pod -l app=web | sed -n '/Events:/,$p'
Events:
  Type     Reason     Age   From               Message
  ----     ------     ----  ----               -------
  Normal   Scheduled  3s    default-scheduler  Successfully assigned pb-02/web-f4995468b-t2cxm to playbook-control-plane
  Normal   Pulling    3s    kubelet            spec.containers{nginx}: Pulling image "nginx:1.27.99-alpine"
  Warning  Failed     2s    kubelet            spec.containers{nginx}: Failed to pull image "nginx:1.27.99-alpine": rpc error: code = NotFound desc = failed to pull and unpack image "docker.io/library/nginx:1.27.99-alpine": failed to resolve reference "docker.io/library/nginx:1.27.99-alpine": docker.io/library/nginx:1.27.99-alpine: not found
  Warning  Failed     2s    kubelet            spec.containers{nginx}: Error: ErrImagePull
  Normal   BackOff    2s    kubelet            spec.containers{nginx}: Back-off pulling image "nginx:1.27.99-alpine"
  Warning  Failed     2s    kubelet            spec.containers{nginx}: Error: ImagePullBackOff

$ kubectl -n pb-02 get deploy web -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
nginx:1.27.99-alpine
```

## Root cause
The tag `nginx:1.27.99-alpine` does not exist in the registry, so the kubelet gets "not found" and backs off. The same symptom appears with a private image and no `imagePullSecrets` (the event then says "unauthorized" or "pull access denied" instead of "not found").

## Fix
Use a tag that exists (`nginx:1.27-alpine`). For private registries, create a `docker-registry` Secret and add it under `imagePullSecrets`.

```diff
--- broken.yaml
+++ fixed.yaml
@@ -14,5 +14,5 @@
       containers:
         - name: nginx
-          image: nginx:1.27.99-alpine   # this tag was never published
+          image: nginx:1.27-alpine
           ports: [{containerPort: 80}]
           resources:
```

After the fix:

```console
$ kubectl -n pb-02 get pods
NAME                   READY   STATUS        RESTARTS   AGE
web-54d59cb594-nrcnd   1/1     Running       0          2s
web-f4995468b-t2cxm    0/1     Terminating   0          5s

$ kubectl -n pb-02 get deploy web -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
nginx:1.27-alpine
```

## Prevention
- Pin images by tag that CI has just pushed (or by digest), never type tags by hand.
- Check the event text first; "not found" and "unauthorized" have different fixes.
- Alert `PodImagePullFailing` (warning, 10m).

Alert rules that catch it (from [k8s-monitoring-stack](https://github.com/paulZYF/k8s-monitoring-stack)): [`PodImagePullFailing`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/PodImagePullFailing.md)

## Time to fix in the demo
2 seconds from applying the fix to healthy (measured by the runner; diagnosis time not included).
