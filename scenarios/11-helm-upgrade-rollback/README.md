# 11. Helm upgrade fails: roll back first, then fix the values

> Verified on a kind cluster (Kubernetes v1.34.0) on 2026-10-20: **reproduced and fixed**. Failure visible after 0s; healthy 4s after applying the fix. All output below is real, captured by `scripts/run_scenario.py`.

## Try it
```bash
kubectl create namespace pb-11
helm upgrade --install catalog scenarios/11-helm-upgrade-rollback/chart -n pb-11 -f scenarios/11-helm-upgrade-rollback/values-v1.yaml --wait --timeout 120s
helm upgrade catalog scenarios/11-helm-upgrade-rollback/chart -n pb-11 -f scenarios/11-helm-upgrade-rollback/broken.yaml --wait --timeout 60s
# ...diagnose it yourself, then compare with the write-up below
```

Files: `broken.yaml`, `fixed.yaml`, `values-v1.yaml`, `chart/`

## Symptom
`helm upgrade --wait` times out and the release is marked failed. New pods are in ImagePullBackOff; the old ones still serve.

```console
$ helm upgrade --install catalog chart -n pb-11 -f values-v1.yaml --wait --timeout 120s
Release "catalog" does not exist. Installing it now.
NAME: catalog
LAST DEPLOYED: Tue Oct 20 20:02:22 2026
NAMESPACE: pb-11
STATUS: deployed
REVISION: 1
TEST SUITE: None

$ helm upgrade catalog chart -n pb-11 -f broken.yaml --wait --timeout 60s
Error: UPGRADE FAILED: context deadline exceeded
```

```console
$ helm -n pb-11 history catalog
REVISION	UPDATED                 	STATUS  	CHART        	APP VERSION	DESCRIPTION                                        
1       	Tue Oct 20 20:02:22 2026	deployed	catalog-0.1.0	1.27       	Install complete                                   
2       	Tue Oct 20 20:02:24 2026	failed  	catalog-0.1.0	1.27       	Upgrade "catalog" failed: context deadline exceeded

$ kubectl -n pb-11 get pods
NAME                       READY   STATUS         RESTARTS   AGE
catalog-55b4c487b8-6w92r   1/1     Running        0          62s
catalog-55b4c487b8-kprgz   1/1     Running        0          62s
catalog-6db9f5645b-b25vk   0/1     ErrImagePull   0          60s
```

## Diagnosis
Commands in the order I run them, with the real output:

```console
$ kubectl -n pb-11 get rs -o custom-columns=NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,IMAGE:.spec.template.spec.containers[0].image
NAME                 DESIRED   READY    IMAGE
catalog-55b4c487b8   2         2        nginx:1.27-alpine
catalog-6db9f5645b   1         <none>   nginx:1.28-alpne

$ kubectl -n pb-11 get events --field-selector reason=Failed -o custom-columns=MESSAGE:.message | cut -c1-220 | head -3
MESSAGE
Failed to pull image "nginx:1.28-alpne": rpc error: code = NotFound desc = failed to pull and unpack image "docker.io/library/nginx:1.28-alpne": failed to resolve reference "docker.io/library/nginx:1.28-alpne": docker.io
Error: ErrImagePull

$ helm -n pb-11 get values catalog
USER-SUPPLIED VALUES:
image:
  tag: 1.28-alpne
```

## Root cause
The upgrade changed the image tag to `1.28-alpne` (typo). New pods cannot pull it, so `--wait` times out and Helm marks revision 2 as failed. Because the Deployment uses `maxUnavailable: 0`, the old pods from revision 1 keep serving, but the release is now in a bad state and the next upgrade starts from it.

## Fix
First `helm rollback catalog 1` to get back to a known-good revision (it becomes revision 3), then fix the values and upgrade again (revision 4). Do not "fix forward" from a failed revision under pressure.

```diff
--- broken.yaml
+++ fixed.yaml
@@ -1,5 +1,3 @@
-# Release 2 (broken): someone bumped the tag to one that was never published.
-# helm upgrade --wait times out, the release is marked "failed",
-# and the old ReplicaSet keeps serving (maxUnavailable: 0).
+# Release 4 (fixed): the intended upgrade, with the correct tag.
 image:
-  tag: "1.28-alpne"
+  tag: "1.28-alpine"
```

Fix commands and output:

```console
$ helm -n pb-11 rollback catalog 1 --wait --timeout 120s
Rollback was a success! Happy Helming!

$ helm -n pb-11 history catalog
REVISION	UPDATED                 	STATUS    	CHART        	APP VERSION	DESCRIPTION                                        
1       	Tue Oct 20 20:02:22 2026	superseded	catalog-0.1.0	1.27       	Install complete                                   
2       	Tue Oct 20 20:02:24 2026	failed    	catalog-0.1.0	1.27       	Upgrade "catalog" failed: context deadline exceeded
3       	Tue Oct 20 20:03:24 2026	deployed  	catalog-0.1.0	1.27       	Rollback to 1

$ helm upgrade catalog chart -n pb-11 -f fixed.yaml --wait --timeout 120s
Release "catalog" has been upgraded. Happy Helming!
NAME: catalog
LAST DEPLOYED: Tue Oct 20 20:03:26 2026
NAMESPACE: pb-11
STATUS: deployed
REVISION: 4
TEST SUITE: None
```

After the fix:

```console
$ helm -n pb-11 history catalog
REVISION	UPDATED                 	STATUS    	CHART        	APP VERSION	DESCRIPTION                                        
1       	Tue Oct 20 20:02:22 2026	superseded	catalog-0.1.0	1.27       	Install complete                                   
2       	Tue Oct 20 20:02:24 2026	failed    	catalog-0.1.0	1.27       	Upgrade "catalog" failed: context deadline exceeded
3       	Tue Oct 20 20:03:24 2026	superseded	catalog-0.1.0	1.27       	Rollback to 1                                      
4       	Tue Oct 20 20:03:26 2026	deployed  	catalog-0.1.0	1.27       	Upgrade complete

$ kubectl -n pb-11 get pods -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,IMAGE:.spec.containers[0].image
NAME                       STATUS      IMAGE
catalog-55b4c487b8-kprgz   Succeeded   nginx:1.27-alpine
catalog-66675c7c79-f7ltd   Running     nginx:1.28-alpine
catalog-66675c7c79-s9gxp   Running     nginx:1.28-alpine
```

## Prevention
- Use `helm upgrade --atomic` (rolls back automatically on failure) in CI.
- Run `helm diff upgrade` (plugin) or `helm template | kubeconform` before upgrading.
- Keep `maxUnavailable: 0` so a bad rollout never takes the old pods down.
- Alerts `PodImagePullFailing`, `DeploymentReplicasMismatch`.

Alert rules that catch it (from [k8s-monitoring-stack](https://github.com/paulZYF/k8s-monitoring-stack)): [`PodImagePullFailing`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/PodImagePullFailing.md), [`DeploymentReplicasMismatch`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/DeploymentReplicasMismatch.md)

## Time to fix in the demo
4 seconds from applying the fix to healthy (measured by the runner; diagnosis time not included).
