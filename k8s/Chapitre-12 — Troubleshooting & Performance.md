# Chapitre 12 — Troubleshooting & Performance

*(méthode de triage, classes de pannes, diagnostics réseau/stockage/plan de contrôle, erreurs fréquentes `kubectl`/CNI/Ingress/PV, sécurité & policies, perf CPU/mémoire/réseau/disque, **runbooks prêts à l’emploi** et **commandes détaillées**)*

---

## 0) Objectifs

* Savoir **identifier** rapidement la classe de panne (image, scheduling, réseau, stockage, sécurité, CI/CD).
* Appliquer un **arbre de décision** clair (du plus simple au plus profond) avec **commandes canoniques**.
* Corréler **Events / Logs / Metrics / Traces** pour isoler la cause primaire.
* Mettre en œuvre des **correctifs** immédiats et des **préventions** durables.
* Optimiser la **performance** (CPU throttling, OOM, DNS, MTU, IOPS, GC images).

---

## 1) Triage express (5–10 minutes)

### 1.1 Golden signals & état global

```bash
kubectl get nodes -o wide
kubectl get pods -A -o wide --field-selector=status.phase!=Running
kubectl get events -A --sort-by=.lastTimestamp | tail -n 50
kubectl top nodes ; kubectl top pods -A
```

* **Regarder d’abord** : `NotReady`, `DiskPressure`, `MemoryPressure`, `NetworkUnavailable`, pics CPU/mémoire.

### 1.2 Cible (namespace/app) et chronologie

```bash
NS=app ; APP=api
kubectl -n $NS get deploy,sts,ds,svc,ingress,pdb -l app=$APP
kubectl -n $NS get pod -l app=$APP -o wide
kubectl -n $NS describe deploy/$APP | sed -n '/Conditions/,$p'
kubectl -n $NS get events --sort-by=.lastTimestamp | grep -E "$APP|$NS" | tail -n 30
```

### 1.3 Hypothèse initiale

* **Image / Pull** ? → `ErrImagePull` / `ImagePullBackOff`
* **Crash au boot** ? → `CrashLoopBackOff`
* **Jamais programmé** ? → `Pending` (ressources, affinités, taints, PV manquant)
* **Ready=false** ? → probes, réseau, DNS, endpoints
* **Nœud malade** ? → Pressures, kubelet, disque plein

---

## 2) Classes de pannes & runbooks rapides

### 2.1 Image / Registre

Symptômes : `ErrImagePull`, `ImagePullBackOff`, `manifest unknown`, `denied`.

```bash
kubectl -n $NS describe pod <pod> | sed -n '/Events/,$p'
kubectl -n $NS get secret -o name | grep dock | xargs -I{} kubectl -n $NS describe {}
```

Correctifs :

* Vérifier **tag/digest** exact, login registry, **allow-list** de l’admission.
* Si **Cosign/policy** : `cosign verify <image:tag>` ; vérifier **ClusterImagePolicy** (si Sigstore/Policy Controller).
* Réseau sortant bloqué (NetPol/proxy) → autoriser egress vers le registre.

### 2.2 Crash / Redémarrages

Symptômes : `CrashLoopBackOff`, `Error`, `OOMKilled`.

```bash
kubectl -n $NS logs <pod> --previous --tail=200
kubectl -n $NS get pod <pod> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}'
```

Correctifs :

* **Configuration manquante** (ENV/Secret/ConfigMap, port/probes).
* **OOMKilled** → augmenter `memory limit`, réduire caches, revoir GC (Java: `-XX:MaxRAMPercentage`).
* Démarrage long → ajouter **startupProbe** / augmenter `initialDelaySeconds`.

### 2.3 Scheduling / Pending

Symptômes : `Pending`, `0/… nodes are available…`

```bash
kubectl -n $NS describe pod <pod> | sed -n '/Events/,$p'
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"  taints:"}{.spec.taints}{"\n"}{end}'
```

Correctifs :

* **Requests** > capacité ; **nodeSelector/affinity** trop stricts ; **taints** sans **tolerations**.
* **PDB** trop exigeant (empêche rollouts) ; ajuster `minAvailable/maxUnavailable`.
* **PV manquant** (voir 2.5).

### 2.4 Réseau / DNS / Endpoints

Symptômes : Readiness KO, `Connection refused`, `i/o timeout`, `servfail`.

```bash
# Endpoints d’un Service
kubectl -n $NS get endpoints $APP -o wide
# DNS depuis un pod de debug
kubectl -n $NS run -it net --image=nicolaka/netshoot --rm -- \
  sh -lc 'dig A api.app.svc.cluster.local +search +time=2 && curl -sS http://api:8080/healthz'
# Probes d’un pod
kubectl -n $NS describe pod <pod> | sed -n '/Readiness/Liveness/,$p'
```

Correctifs :

* **Service selector** ne matche pas les Pods (labels incohérents) → corriger labels.
* **CoreDNS** saturé → activer **NodeLocal DNSCache**, augmenter cache/timeouts.
* **MTU** (CNI/overlay) → ajuster MTU (Calico/Cilium) ; vérifier `ping -M do -s`.

### 2.5 Stockage / PV & permissions

Symptômes : `PVC Pending`, `Read-only file system`, `permission denied`, `stale file handle`.

```bash
kubectl -n $NS get pvc,pv
kubectl -n $NS describe pvc <pvc>
kubectl -n $NS logs <pod> | grep -i "permission denied\|read-only"
```

Correctifs :

* **StorageClass** inexistante / `WaitForFirstConsumer` → attendre scheduling réel.
* **fsGroup**/UID/GID → ajouter `securityContext.fsGroup` ou `runAsUser: runAsGroup:`.
* NFS : monter `vers=4.1` + `noatime` ; re-créer PV si *stale handle* persistant.

### 2.6 Ingress / LB

Symptômes : 404/502/504, routage partiel.

````bash
kubectl -n $NS describe ingress
kubectl -n ingress-nginx logs deploy/ingress-nginx-controller --tail=200
``]
Correctifs :
- **Host/paths** incorrects ; Service/port name mismatch ; **canary annotations** résiduelles.
- Cloud LB non provisionné (annotations manquantes, quotas).

### 2.7 Sécurité / Policies
Symptômes : `Forbidden`, `denied by policy`, `seccomp`, `apparmor`, `selinux`.
```bash
kubectl auth can-i get pods -n $NS --as <sa>
kubectl -n $NS describe pod <pod> | sed -n '/Security Context/,$p'
````

Correctifs :

* RBAC : rôle/liaison manquante ; élargir minimalement.
* PodSecurity : capabilities interdites, `hostPath` non autorisé ; adapter la classe.
* Seccomp/AppArmor/SELinux : utiliser profils autorisés ; éviter `privileged`.

---

## 3) Outils de diagnostic incontournables

### 3.1 `kubectl debug` (ephemeral containers)

```bash
kubectl -n $NS debug pod/<pod> -it --image=nicolaka/netshoot --target=<container>
# shell dans le namespace réseau du container cible (sans redémarrer le pod)
```

### 3.2 `nsenter` / `crictl` (noeud)

```bash
# Sur le nœud (SSH)
crictl ps ; crictl logs <cid>
nsenter -t <pid> -n ss -tulpn
```

### 3.3 Réseau

```bash
kubectl -n $NS exec -it <pod> -- sh -lc 'ip a; ip route; ss -s; ss -tulpn'
kubectl -n $NS exec -it <pod> -- sh -lc 'curl -vS http://svc:8080/healthz'
```

### 3.4 Perf appli (instantané)

```bash
kubectl -n $NS logs <pod> --tail=200 | grep -E "ERROR|WARN|timeout|latency"
kubectl -n $NS top pod <pod>
```

---

## 4) Performance — modèles & remèdes

### 4.1 CPU throttling (CFS)

Symptômes : latence erratique, p95↑ sans utilisation CPU élevée dans `top`.

* Règle : **éviter** des **CPU limits** trop serrées pour workloads sensibles.
* Observabilité (Prometheus) :
  `rate(container_cpu_cfs_throttled_seconds_total[5m]) / rate(container_cpu_cfs_periods_total[5m])` → si > 0.2 soutenu ⇒ desserrer **limits** et ajuster **requests**.

### 4.2 Mémoire & OOM

* Analyser `OOMKilled`, **working set**, pics p95/p99 ; augmenter **limit** ou réduire footprint.
* Langages :

  * **Java** : `-XX:MaxRAMPercentage`, GC G1/Z ;
  * **Node** : `--max-old-space-size`;
  * **Python** : éviter grosses structures en mémoire, streaming.

### 4.3 DNS & connexions

* Activer **NodeLocal DNSCache** (latence & résilience).
* Vérifier **conntrack** (drops) ; augmenter `nf_conntrack_max` si saturation.

### 4.4 MTU & CNI

* MTU trop haute ⇒ fragmentation/pertes ; trop basse ⇒ overhead.
* Configurer MTU dans la CNI (Calico/Cilium) selon l’overlay ou VPN.

### 4.5 Disque / IOPS / FS

* Choisir **StorageClass** (gp3/io2, throughput) adaptée.
* Séparer **journaux** et **données** (DB).
* Mount options (NFS : `vers=4.1,noatime,nodiratime`).

### 4.6 Kubelet / évictions / GC

* Réserver CPU/Mem au système (`--system-reserved`, `--kube-reserved`).
* Éviter `DiskPressure` via **GC images**/containers (limiter couches).

---

## 5) Cas pratiques — runbooks détaillés

### 5.1 `Readiness probe failed`

**Diagnostics**

```bash
kubectl -n $NS describe pod <pod> | sed -n '/Readiness Probe/,$p'
kubectl -n $NS exec -it <pod> -- sh -lc 'curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/healthz'
```

**Actions**

* Corriger **path/port** ; augm. `initialDelaySeconds` ; ajouter **startupProbe** si boot long.
* Vérifier **Service**/Endpoints ; NetPol bloquant.

### 5.2 `Pending` (PV requis)

**Diagnostics**

```bash
kubectl -n $NS get pvc
kubectl -n $NS describe pvc <pvc>
kubectl get sc -o wide
```

**Actions**

* Créer/mapper **StorageClass** ; si `WaitForFirstConsumer`, patienter jusqu’au scheduling.
* Si permissions : `securityContext.fsGroup: 1000`.

### 5.3 `CrashLoopBackOff` après mise à jour

**Diagnostics**

```bash
kubectl -n $NS logs <pod> --previous --tail=200
kubectl -n $NS rollout history deploy/$APP
```

**Actions**

* Renvoyer **ancienne config** (rollback Helm) ; corriger variable manquante/secret.

### 5.4 `ImagePullBackOff`

**Diagnostics**

```bash
kubectl -n $NS describe pod <pod> | sed -n '/Events/,$p'
skopeo inspect docker://$IMG:$VER | jq -r .Digest
```

**Actions**

* Vérifier **secret** de pull, **policy** d’admission (signature/digest), egress.

### 5.5 Ingress 502/504

**Diagnostics**

```bash
kubectl -n ingress-nginx logs deploy/ingress-nginx-controller --tail=200
kubectl -n $NS get endpoints $APP
```

**Actions**

* Adapter timeouts Ingress ; corriger ports nommés (`name: http`), **readiness**.

---

## 6) Checklist “Performance saine”

* **Requests** partout ; **limits CPU** avec prudence ; **limits mémoire** protègent des emballements.
* **QoS** : workloads critiques en **Guaranteed** (requests==limits CPU+Mem).
* **Spreading**/anti-affinity ; **PDB** solide ; rollouts `maxUnavailable: 0`, `maxSurge > 0`.
* **HPA** sur métriques **métier** + fenêtres de stabilisation ; **VPA** en reco.
* **DNS** : NodeLocal cache ; **kube-proxy ipvs** si trafic fort.
* **MTU** correcte ; **conntrack** dimensionné.
* **Stockage** : SC adaptée (IOPS/throughput), mount options, RWX/RWO selon cas.
* **Kubelet** : réservations & **eviction thresholds** ; **GC** images.
* **Observabilité perf** : dashboards throttling/OOM/DNS/IOPS ; alertes actionnables.

---

## 7) Aide-mémoire (commandes utiles)

```bash
# État cluster / nœuds / events
kubectl get nodes -o wide
kubectl get events -A --sort-by=.lastTimestamp | tail -n 50

# Ressources & QoS
kubectl top nodes ; kubectl top pods -A
kubectl get pod <pod> -o jsonpath='{.status.qosClass}{"\n"}'

# Rollouts & images
kubectl -n app rollout status deploy/api
kubectl -n app rollout history deploy/api
kubectl -n app set image deploy/api api=repo@sha256:...

# Services / Endpoints / DNS
kubectl -n app get svc,ep
kubectl -n app run -it net --image=nicolaka/netshoot --rm -- sh -lc 'dig A api.app.svc.cluster.local; curl -sS http://api:8080/healthz'

# PV/PVC
kubectl -n app get pvc ; kubectl get sc -o wide
kubectl -n app describe pvc <pvc>

# Probes / logs / previous
kubectl -n app describe pod <pod> | sed -n '/Probe/,$p'
kubectl -n app logs <pod> --previous --tail=200

# kubelet / nœud (SSH)
journalctl -u kubelet --no-pager | tail -n 100
crictl ps ; crictl logs <cid>
```

---

## 8) Prévention (post-mortem → durcissement)

* **Runbooks** versionnés, liés aux alertes (annotation `runbook_url`).
* **Rules** admission : **pas de `:latest`**, **digest obligatoire**, **signature requise**, **registries autorisés**.
* **Tests de restauration** (PRA) & **game days** (pannes contrôlées).
* **SLO** publiés + **alertes burn-rate** ; **dashboards** standardisés.
* **Lint/validate** systématique (`kubeconform`, `helm lint`, `promtool`).

