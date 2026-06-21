# Chapitre 12 — Troubleshooting & Performance

*(méthode de triage, classes de pannes, diagnostics réseau/stockage/plan de contrôle, erreurs fréquentes `kubectl`/CNI/Ingress/PV, sécurité & policies, perf CPU/mémoire/réseau/disque, **runbooks prêts à l'emploi** et **commandes détaillées**)*

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

> **Objectif** : Obtenir en un coup d'œil l'état de santé global du cluster — nœuds, pods anormaux, événements récents et consommation de ressources.
> **Pré-requis** : Un cluster Kubernetes accessible avec `kubectl` configuré (contexte courant) et les droits de lecture sur les ressources cluster-wide.

```bash
# Liste tous les nœuds avec leurs adresses IP, version du kubelet et conditions (Ready, DiskPressure, etc.)
kubectl get nodes -o wide
# Liste tous les pods de tous les namespaces qui ne sont PAS en phase Running (Failed, Pending, Unknown, Succeeded)
kubectl get pods -A -o wide --field-selector=status.phase!=Running
# Récupère les 50 derniers événements du cluster, triés par timestamp décroissant
kubectl get events -A --sort-by=.lastTimestamp | tail -n 50
# Affiche la consommation CPU/Mémoire des nœuds ET de tous les pods (nécessite metrics-server)
kubectl top nodes ; kubectl top pods -A
```

> **Résultat attendu** :
> ```
> NAME     STATUS   ROLES    AGE   VERSION   INTERNAL-IP    OS-IMAGE            KERNEL-VERSION
> node-1   Ready    control  45d   v1.29.0   10.0.0.1       Ubuntu 22.04.3      5.15.0-91-generic
> node-2   Ready    worker   45d   v1.29.0   10.0.0.2       Ubuntu 22.04.3      5.15.0-91-generic
>
> NAMESPACE   NAME                  READY   STATUS    RESTARTS   AGE   IP           NODE
> kube-system   coredns-5d78c98-xx   0/1     Pending   0          2m    <none>       <none>
>
> LAST SEEN   TYPE      REASON             OBJECT                    MESSAGE
> 3m          Warning   FailedScheduling   pod/coredns-5d78c98-xx   0/2 nodes are available...
>
> NAME     CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
> node-1   250m         12%    1024Mi          26%
> ```
> **Vérification** : Confirmer qu'aucun nœud n'est `NotReady` / `DiskPressure` / `MemoryPressure`. Vérifier que le nombre de pods non-Running est cohérent. S'assurer que `metrics-server` répond (sinon `kubectl top` échoue).

* **Regarder d'abord** : `NotReady`, `DiskPressure`, `MemoryPressure`, `NetworkUnavailable`, pics CPU/mémoire.

### 1.2 Cible (namespace/app) et chronologie

> **Objectif** : Cibler le diagnostic sur un namespace et une application spécifiques — lister toutes les ressources associées, inspecter les conditions du Deployment et la chronologie des événements.
> **Pré-requis** : Les variables `NS` (namespace) et `APP` (nom de l'application/label) doivent être définies. L'application doit utiliser le label `app=$APP`.

```bash
# Définit le namespace et le nom de l'application cible
NS=app ; APP=api
# Liste toutes les ressources clés (Deployments, StatefulSets, DaemonSets, Services, Ingress, PDB) filtrées par label
kubectl -n $NS get deploy,sts,ds,svc,ingress,pdb -l app=$APP
# Affiche les pods correspondants avec leurs IPs, nœuds et statuts détaillés
kubectl -n $NS get pod -l app=$APP -o wide
# Extrait et affiche la section Conditions du Deployment (disponibilité, progression)
kubectl -n $NS describe deploy/$APP | sed -n '/Conditions/,$p'
# Récupère les 30 derniers événements du namespace filtrés sur l'application
kubectl -n $NS get events --sort-by=.lastTimestamp | grep -E "$APP|$NS" | tail -n 30
```

> **Résultat attendu** :
> ```
> NAME                  READY   UP-TO-DATE   AVAILABLE   AGE
> deployment.apps/api   3/3     3            3           10d
>
> NAME              TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)    AGE
> service/api       ClusterIP   10.96.45.12    <none>        8080/TCP   10d
>
> NAME                        READY   STATUS    RESTARTS   AGE   IP            NODE
> api-6b8d4f7c9-abc12         1/1     Running   0          2h    10.244.1.5    node-2
> api-6b8d4f7c9-def34         1/1     Running   1          2h    10.244.2.8    node-3
>
> Conditions:
>   Type           Status  Reason
>   ----           ------  ------
>   Available      True    MinimumReplicasAvailable
>   Progressing    True    NewReplicaSetAvailable
> ```
> **Vérification** : Confirmer que READY = UP-TO-DATE = AVAILABLE. Vérifier que les Conditions sont `True`. Examiner les événements pour détecter des warnings récents (FailedScheduling, Unhealthy, BackOff, etc.).

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

> **Objectif** : Identifier pourquoi le pull de l'image échoue — problème de credentials, image inexistante, ou blocage réseau/admission.
> **Pré-requis** : Le pod doit être dans un état `ErrImagePull` ou `ImagePullBackOff`. Variables `NS` définie.

```bash
# Affiche les événements du pod à partir de la section Events (message d'erreur exact du pull)
kubectl -n $NS describe pod <pod> | sed -n '/Events/,$p'
# Liste les secrets de type docker-registry et affiche leur contenu (vérifier la présence/validité des credentials)
kubectl -n $NS get secret -o name | grep dock | xargs -I{} kubectl -n $NS describe {}
```

> **Résultat attendu** :
> ```
> Events:
>   Type     Reason     Age   From               Message
>   ----     ------     ---   ----               -------
>   Normal   Pulling    2m    kubelet            Pulling image "registry.io/app:1.2.3"
>   Warning  Failed     1m    kubelet            Failed to pull image "registry.io/app:1.2.3":
>            rpc error: code = Unknown desc = Error response from daemon:
>            manifest for registry.io/app:1.2.3 not found: manifest unknown
>   Warning  Failed     1m    kubelet            Error: ErrImagePull
>
> Name         Type                             Data   Age
> regcred      kubernetes.io/dockerconfigjson   1      30d
> ```
> **Vérification** : Identifier le message exact (manifest unknown, denied, timeout). Confirmer que le secret `imagePullSecrets` existe et contient les bons credentials. Vérifier que le tag/digest est correct dans le spec du pod.

Correctifs :

* Vérifier **tag/digest** exact, login registry, **allow-list** de l'admission.
* Si **Cosign/policy** : `cosign verify <image:tag>` ; vérifier **ClusterImagePolicy** (si Sigstore/Policy Controller).
* Réseau sortant bloqué (NetPol/proxy) → autoriser egress vers le registre.

### 2.2 Crash / Redémarrages

Symptômes : `CrashLoopBackOff`, `Error`, `OOMKilled`.

> **Objectif** : Déterminer la cause du crash — erreur applicative, OOM, ou problème de configuration — en examinant les logs du conteneur précédent et la raison de terminaison.
> **Pré-requis** : Le pod doit avoir au moins un redémarrage (RESTARTS > 0). Variables `NS` définie.

```bash
# Affiche les logs du conteneur PRÉCÉDENT (avant le crash), les 200 dernières lignes
kubectl -n $NS logs <pod> --previous --tail=200
# Extrait la raison de terminaison du dernier arrêt (OOMKilled, Error, etc.)
kubectl -n $NS get pod <pod> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}'
```

> **Résultat attendu** :
> ```
> 2024-01-15T10:23:45Z INFO  Starting application...
> 2024-01-15T10:23:46Z ERROR Failed to connect to database: connection refused
> 2024-01-15T10:23:46Z FATAL Application exiting with code 1
>
> OOMKilled
> ```
> **Vérification** : Si `OOMKilled` → augmenter la memory limit. Si `Error` → examiner les logs pour identifier l'erreur (config manquante, DB inaccessible, etc.). Si `--previous` ne retourne rien, le conteneur n'a pas encore crashé.

Correctifs :

* **Configuration manquante** (ENV/Secret/ConfigMap, port/probes).
* **OOMKilled** → augmenter `memory limit`, réduire caches, revoir GC (Java: `-XX:MaxRAMPercentage`).
* Démarrage long → ajouter **startupProbe** / augmenter `initialDelaySeconds`.

### 2.3 Scheduling / Pending

Symptômes : `Pending`, `0/… nodes are available…`

> **Objectif** : Comprendre pourquoi le pod ne peut pas être schedulé — ressources insuffisantes, contraintes d'affinité/taints, ou PV manquant.
> **Pré-requis** : Le pod doit être en état `Pending`. Variables `NS` définie.

```bash
# Affiche les événements du pod — la section Events contient la raison exacte du Pending
kubectl -n $NS describe pod <pod> | sed -n '/Events/,$p'
# Liste tous les nœuds avec leurs taints pour vérifier les contraintes de scheduling
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"  taints:"}{.spec.taints}{"\n"}{end}'
```

> **Résultat attendu** :
> ```
> Events:
>   Type     Reason            Age   From               Message
>   ----     ------            ---   ----               -------
>   Warning  FailedScheduling  5m    default-scheduler  0/3 nodes are available:
>            1 Insufficient cpu, 2 node(s) had taint {node-role.kubernetes.io/control-plane: },
>            that the pod didn't tolerate.
>
> node-1  taints:[map[effect:NoSchedule key:node-role.kubernetes.io/control-plane]]
> node-2  taints:[]
> node-3  taints:[]
> ```
> **Vérification** : Identifier la raison exacte dans les Events (Insufficient cpu/memory, taint non tolérée, nodeSelector/affinity non satisfaite, PVC non bound). Comparer les requests du pod avec la capacité disponible des nœuds.

Correctifs :

* **Requests** > capacité ; **nodeSelector/affinity** trop stricts ; **taints** sans **tolerations**.
* **PDB** trop exigeant (empêche rollouts) ; ajuster `minAvailable/maxUnavailable`.
* **PV manquant** (voir 2.5).

### 2.4 Réseau / DNS / Endpoints

Symptômes : Readiness KO, `Connection refused`, `i/o timeout`, `servfail`.

> **Objectif** : Diagnostiquer les problèmes réseau — endpoints vides, résolution DNS défaillante, probes mal configurées ou MTU incorrecte.
> **Pré-requis** : Variables `NS` et `APP` définies. Le service et les pods doivent exister. Un pod de debug avec `nicolaka/netshoot` sera créé temporairement.

```bash
# Endpoints d'un Service — vérifie que des IPs de pods sont bien associées au Service
kubectl -n $NS get endpoints $APP -o wide
# DNS depuis un pod de debug — teste la résolution DNS et la connectivité HTTP vers le service
kubectl -n $NS run -it net --image=nicolaka/netshoot --rm -- \
  sh -lc 'dig A api.app.svc.cluster.local +search +time=2 && curl -sS http://api:8080/healthz'
# Probes d'un pod — extrait les sections Readiness/Liveness pour vérifier leur configuration
kubectl -n $NS describe pod <pod> | sed -n '/Readiness/Liveness/,$p'
```

> **Résultat attendu** :
> ```
> NAME   ENDPOINTS                          AGE
> api    10.244.1.5:8080,10.244.2.8:8080   10d
>
> ;; ANSWER SECTION:
> api.app.svc.cluster.local.  30  IN  A  10.96.45.12
>
> {"status":"ok"}
>
> Readiness:  http-get http://:8080/healthz delay=5s timeout=3s period=10s #success=1 #failure=3
> Liveness:   http-get http://:8080/healthz delay=15s timeout=3s period=20s #success=1 #failure=3
> ```
> **Vérification** : Si ENDPOINTS est vide → le selector du Service ne matche aucun pod. Si `dig` échoue → problème CoreDNS. Si `curl` échoue mais DNS OK → problème applicatif ou probe mal configurée.

Correctifs :

* **Service selector** ne matche pas les Pods (labels incohérents) → corriger labels.
* **CoreDNS** saturé → activer **NodeLocal DNSCache**, augmenter cache/timeouts.
* **MTU** (CNI/overlay) → ajuster MTU (Calico/Cilium) ; vérifier `ping -M do -s`.

### 2.5 Stockage / PV & permissions

Symptômes : `PVC Pending`, `Read-only file system`, `permission denied`, `stale file handle`.

> **Objectif** : Diagnostiquer les problèmes de stockage — PVC non bound, StorageClass manquante, ou erreurs de permissions sur le volume monté.
> **Pré-requis** : Variables `NS` définie. Le pod doit utiliser un PVC.

```bash
# Liste les PVC et PV du namespace pour vérifier leur état (Bound, Pending, Lost)
kubectl -n $NS get pvc,pv
# Décrit le PVC pour voir les événements (pourquoi il est Pending, quelle StorageClass est demandée)
kubectl -n $NS describe pvc <pvc>
# Recherche dans les logs du pod des erreurs de permission ou de filesystem read-only
kubectl -n $NS logs <pod> | grep -i "permission denied\|read-only"
```

> **Résultat attendu** :
> ```
> NAME                        STATUS   VOLUME          CAPACITY   ACCESS MODES   STORAGECLASS   AGE
> persistentvolumeclaim/data  Bound    pv-data-01      10Gi       RWO            standard       5d
>
> NAME                  CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM          STORAGECLASS   AGE
> persistentvolume/pv-data-01   10Gi   RWO   Retain   Bound   app/data   standard   5d
>
> Events:
>   Type    Reason         Age   From                         Message
>   ----    ------         ---   ----                         -------
>   Normal  Provisioning   2m    external-provisioner         Provisioning...
> ```
> **Vérification** : Si PVC est `Pending` → vérifier la StorageClass et le provisioner. Si `permission denied` dans les logs → ajouter `fsGroup` dans securityContext. Si `Read-only` → vérifier les mount options et les permissions du PV.

Correctifs :

* **StorageClass** inexistante / `WaitForFirstConsumer` → attendre scheduling réel.
* **fsGroup**/UID/GID → ajouter `securityContext.fsGroup` ou `runAsUser: runAsGroup:`.
* NFS : monter `vers=4.1` + `noatime` ; re-créer PV si *stale handle* persistant.

### 2.6 Ingress / LB

Symptômes : 404/502/504, routage partiel.

> **Objectif** : Diagnostiquer les erreurs Ingress/Load Balancer — mauvaise configuration des routes, ports nommés incorrects, ou contrôleur Ingress en erreur.
> **Pré-requis** : Un Ingress doit être configuré. Le contrôleur Ingress (nginx, traefik, etc.) doit être déployé dans le namespace `ingress-nginx`.

````bash
# Décrit l'Ingress pour vérifier les règles de routage, annotations et TLS
kubectl -n $NS describe ingress
# Affiche les 200 dernières lignes des logs du contrôleur Ingress nginx (erreurs upstream, 502, timeouts)
kubectl -n ingress-nginx logs deploy/ingress-nginx-controller --tail=200
``]
Correctifs :
- **Host/paths** incorrects ; Service/port name mismatch ; **canary annotations** résiduelles.
- Cloud LB non provisionné (annotations manquantes, quotas).

### 2.7 Sécurité / Policies
Symptômes : `Forbidden`, `denied by policy`, `seccomp`, `apparmor`, `selinux`.
> **Objectif** : Vérifier les permissions RBAC et les contraintes de sécurité appliquées au pod (PodSecurity, capabilities, profils seccomp/apparmor).
> **Pré-requis** : Variables `NS` définie. Connaître le ServiceAccount ou l'utilisateur à tester.

```bash
# Vérifie si le ServiceAccount (ou utilisateur) a le droit de lire les pods dans le namespace
kubectl auth can-i get pods -n $NS --as <sa>
# Extrait la section SecurityContext du pod (capabilities, fsGroup, runAsUser, seccomp, etc.)
kubectl -n $NS describe pod <pod> | sed -n '/Security Context/,$p'
````

> **Résultat attendu** :
> ```
> yes
>
> Security Context:
>   Run As User: 1000
>   Run As Group: 3000
>   FS Group: 2000
>   Capabilities:
>     drop: [ALL]
>     add: [NET_BIND_SERVICE]
>   Seccomp Profile: RuntimeDefault
> ```
> **Vérification** : Si `can-i` retourne `no` → créer un Role/RoleBinding approprié. Vérifier que les capabilities ajoutées sont autorisées par la PodSecurity Policy/Standard du namespace. Confirmer que les profils seccomp/apparmor sont autorisés.

Correctifs :

* RBAC : rôle/liaison manquante ; élargir minimalement.
* PodSecurity : capabilities interdites, `hostPath` non autorisé ; adapter la classe.
* Seccomp/AppArmor/SELinux : utiliser profils autorisés ; éviter `privileged`.

---

## 3) Outils de diagnostic incontournables

### 3.1 `kubectl debug` (ephemeral containers)

> **Objectif** : Injecter un conteneur éphémère (netshoot) dans un pod en cours d'exécution pour diagnostiquer le réseau, le filesystem ou les processus, sans redémarrer le pod cible.
> **Pré-requis** : Kubernetes 1.23+ (ephemeral containers en GA). L'image `nicolaka/netshoot` doit être accessible. Le `<container>` cible doit être spécifié si le pod a plusieurs conteneurs.

```bash
# Ouvre un shell interactif dans un conteneur éphémère, partagé dans le namespace réseau du conteneur cible
kubectl -n $NS debug pod/<pod> -it --image=nicolaka/netshoot --target=<container>
# shell dans le namespace réseau du container cible (sans redémarrer le pod)
```

> **Résultat attendu** :
> ```
> Targeting container "api" in pod "api-6b8d4f7c9-abc12"...
> Defaulting debug container name to debugger-xxxxx.
> If you don't see a command prompt, try pressing enter.
> / #
> ```
> **Vérification** : Une fois dans le shell, utiliser `ss -tulpn`, `curl`, `ip a`, `nslookup` pour diagnostiquer. Le conteneur éphémère disparaît à la sortie (pas de trace dans le spec du pod).

### 3.2 `nsenter` / `crictl` (noeud)

> **Objectif** : Diagnostiquer au niveau du nœud — inspecter les conteneurs via CRI et examiner le namespace réseau d'un processus spécifique.
> **Pré-requis** : Accès SSH au nœud. `crictl` doit être installé sur le nœud. Le PID du processus cible doit être connu (via `crictl inspect` ou `ps`).

```bash
# Sur le nœud (SSH)
# Liste tous les conteneurs en cours d'exécution via CRI (Container Runtime Interface)
crictl ps ; crictl logs <cid>
# Entre dans le namespace réseau d'un processus donné et liste les sockets TCP/UDP en écoute
nsenter -t <pid> -n ss -tulpn
```

> **Résultat attendu** :
> ```
> CONTAINER           IMAGE               CREATED             STATE      NAME
> a1b2c3d4e5f60      registry.io/api:1.2  2 hours ago         Running    api
> 7890abcdef12       registry.io/web:3.0  2 hours ago         Running    web
>
> 2024-01-15T10:23:45Z INFO  Listening on :8080
>
> Netid  State   Recv-Q  Send-Q  Local Address:Port   Peer Address:Port  Process
> tcp    LISTEN  0       128     0.0.0.0:8080         0.0.0.0:*          users:(("api",pid=12345,fd=3))
> tcp    LISTEN  0       128     0.0.0.0:9090         0.0.0.0:*          users:(("api",pid=12345,fd=7))
> ```
> **Vérification** : Confirmer que le conteneur tourne bien (`STATE = Running`). Vérifier que les ports attendus sont en écoute dans le namespace réseau correct. Les logs `crictl` montrent la sortie standard du conteneur.

### 3.3 Réseau

> **Objectif** : Inspecter la configuration réseau d'un pod (interfaces, routes, sockets) et tester la connectivité vers un service interne.
> **Pré-requis** : Le pod cible doit être en état Running. Variables `NS` définie.

```bash
# Exécute dans le pod : liste les interfaces IP, la table de routage, les stats sockets et les ports en écoute
kubectl -n $NS exec -it <pod> -- sh -lc 'ip a; ip route; ss -s; ss -tulpn'
# Teste la connectivité HTTP vers un service interne avec sortie verbose
kubectl -n $NS exec -it <pod> -- sh -lc 'curl -vS http://svc:8080/healthz'
```

> **Résultat attendu** :
> ```
> 1: lo: <LOOPBACK,UP> mtu 65536
>     inet 127.0.0.1/8 scope host lo
> 3: eth0@if10: <BROADCAST,MULTICAST,UP> mtu 1500
>     inet 10.244.1.5/24 scope global eth0
>
> default via 10.244.1.1 dev eth0
> 10.244.1.0/24 dev eth0 proto kernel scope link src 10.244.1.5
> 10.96.0.0/12 via 10.244.1.1 dev eth0
>
> TCP: 12 established, 5 timewait, 0 orphan
>
> *   Trying 10.96.45.12:8080...
> * Connected to svc (10.96.45.12) port 8080
> > GET /healthz HTTP/1.1
> < HTTP/1.1 200 OK
> {"status":"ok"}
> ```
> **Vérification** : Confirmer que l'IP du pod est dans le range du CNI. Vérifier que la route vers le Service CIDR (10.96.0.0/12) existe. Si `curl` échoue → tester avec l'IP directe du pod cible pour isoler (DNS vs réseau vs applicatif).

### 3.4 Perf appli (instantané)

> **Objectif** : Obtenir un instantané rapide des performances applicatives — erreurs/warnings dans les logs et consommation de ressources du pod.
> **Pré-requis** : Variables `NS` définie. Le pod doit être en état Running. `metrics-server` doit être déployé pour `kubectl top`.

```bash
# Recherche dans les 200 dernières lignes de logs les erreurs, warnings, timeouts et latences
kubectl -n $NS logs <pod> --tail=200 | grep -E "ERROR|WARN|timeout|latency"
# Affiche la consommation CPU et mémoire actuelle du pod
kubectl -n $NS top pod <pod>
```

> **Résultat attendu** :
> ```
> 2024-01-15T10:30:01Z ERROR  Database connection timeout after 5000ms
> 2024-01-15T10:30:05Z WARN   High latency detected: /api/users p99=2300ms
> 2024-01-15T10:30:10Z ERROR  Failed to process request: connection reset by peer
>
> NAME                   CPU(cores)   MEMORY(bytes)
> api-6b8d4f7c9-abc12   450m         512Mi
> ```
> **Vérification** : Si beaucoup de timeouts → problème de connectivité réseau ou de saturation de la base de données. Si CPU élevé → vérifier les limits/throttling. Si mémoire élevée → risque d'OOMKilled imminent.

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
* Configurer MTU dans la CNI (Calico/Cilium) selon l'overlay ou VPN.

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

> **Objectif** : Vérifier la configuration de la readiness probe et tester manuellement le endpoint de santé depuis l'intérieur du pod.
> **Pré-requis** : Le pod doit exister et être en état Running (mais Ready=false). Variables `NS` définie.

```bash
# Extrait la configuration complète de la Readiness Probe (path, port, délais, seuils)
kubectl -n $NS describe pod <pod> | sed -n '/Readiness Probe/,$p'
# Teste manuellement le endpoint de santé depuis le pod lui-même (boucle locale) avec le code HTTP retourné
kubectl -n $NS exec -it <pod> -- sh -lc 'curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/healthz'
```

> **Résultat attendu** :
> ```
> Readiness Probe:  http-get http://:8080/healthz delay=5s timeout=3s period=10s #success=1 #failure=3
>
> 200
> ```
> **Vérification** : Si le code HTTP est 200 mais le pod reste NotReady → le problème est un délai insuffisant (`initialDelaySeconds` trop court) ou un `timeout` trop agressif. Si le code est 500/503 → l'application signale qu'elle n'est pas prête (DB non connectée, cache non warmé).

**Actions**

* Corriger **path/port** ; augm. `initialDelaySeconds` ; ajouter **startupProbe** si boot long.
* Vérifier **Service**/Endpoints ; NetPol bloquant.

### 5.2 `Pending` (PV requis)

**Diagnostics**

> **Objectif** : Identifier pourquoi le PVC reste en Pending — StorageClass manquante, provisioner indisponible, ou quota dépassé.
> **Pré-requis** : Variables `NS` définie. Le pod doit requérir un PVC.

```bash
# Liste les PVC du namespace et leur état (Bound, Pending, Lost)
kubectl -n $NS get pvc
# Décrit le PVC pour voir les événements détaillés (erreur de provisioning, StorageClass introuvable)
kubectl -n $NS describe pvc <pvc>
# Liste les StorageClasses disponibles avec leur provisioner et paramètres
kubectl get sc -o wide
```

> **Résultat attendu** :
> ```
> NAME   STATUS    VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS   AGE
> data   Pending                                      fast-ssd       5m
>
> Events:
>   Type     Reason              Age   From                        Message
>   ----     ------              ---   ----                        -------
>   Warning  ProvisioningFailed  2m    persistentvolume-controller  storageclass "fast-ssd" not found
>
> NAME                 PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE      ALLOWVOLUMEEXPANSION   AGE
> standard (default)   k8s.io/minikube-hostpath  Delete       Immediate              false                  45d
> ```
> **Vérification** : Si la StorageClass demandée n'existe pas → la créer ou corriger le PVC. Si `WaitForFirstConsumer` → le PVC se bindra au scheduling du pod. Vérifier les quotas de stockage du namespace.

**Actions**

* Créer/mapper **StorageClass** ; si `WaitForFirstConsumer`, patienter jusqu'au scheduling.
* Si permissions : `securityContext.fsGroup: 1000`.

### 5.3 `CrashLoopBackOff` après mise à jour

**Diagnostics**

> **Objectif** : Examiner les logs du conteneur ayant crashé et vérifier l'historique des rollouts pour identifier le changement problématique.
> **Pré-requis** : Variables `NS` et `APP` définies. Le pod doit être en CrashLoopBackOff.

```bash
# Affiche les logs du conteneur précédent (celui qui a crashé) — les 200 dernières lignes
kubectl -n $NS logs <pod> --previous --tail=200
# Affiche l'historique des révisions du Deployment (pour identifier la version qui a introduit le crash)
kubectl -n $NS rollout history deploy/$APP
```

> **Résultat attendu** :
> ```
> 2024-01-15T11:00:01Z FATAL Missing required environment variable: DB_PASSWORD
> 2024-01-15T11:00:01Z ERROR Application failed to start: configuration invalid
>
> deployment.apps/api
> REVISION  CHANGE-CAUSE
> 1         Initial deployment
> 2         Update image to v1.3.0
> 3         Update image to v1.4.0
> ```
> **Vérification** : Si les logs montrent une variable manquante → vérifier les Secrets/ConfigMaps montés. Utiliser `rollout undo deploy/$APP --to-revision=N` pour revenir à la révision fonctionnelle précédente.

**Actions**

* Renvoyer **ancienne config** (rollback Helm) ; corriger variable manquante/secret.

### 5.4 `ImagePullBackOff`

**Diagnostics**

> **Objectif** : Identifier pourquoi l'image ne peut pas être pullée — vérifier les événements du pod et valider l'existence de l'image dans le registre.
> **Pré-requis** : Variables `NS`, `IMG` et `VER` définies. `skopeo` doit être installé localement.

```bash
# Affiche les événements du pod pour voir le message d'erreur exact du pull (auth, not found, timeout)
kubectl -n $NS describe pod <pod> | sed -n '/Events/,$p'
# Inspecte l'image dans le registre distant et affiche son digest (vérifie que l'image:tag existe bien)
skopeo inspect docker://$IMG:$VER | jq -r .Digest
```

> **Résultat attendu** :
> ```
> Events:
>   Type     Reason     Age   From               Message
>   ----     ------     ---   ----               -------
>   Warning  Failed     3m    kubelet            Failed to pull image "registry.io/app:1.5.0":
>            rpc error: code = Unknown desc = unauthorized: authentication required
>   Warning  Failed     3m    kubelet            Error: ImagePullBackOff
>
> sha256:a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef1234567890
> ```
> **Vérification** : Si `authentication required` → vérifier les `imagePullSecrets` dans le spec du pod. Si `manifest unknown` → le tag n'existe pas. Si `skopeo` retourne un digest → l'image existe, le problème est côté kubelet (credentials, réseau).

**Actions**

* Vérifier **secret** de pull, **policy** d'admission (signature/digest), egress.

### 5.5 Ingress 502/504

**Diagnostics**

> **Objectif** : Diagnostiquer les erreurs 502 (Bad Gateway) et 504 (Gateway Timeout) du contrôleur Ingress — upstream injoignable, ports mal nommés, ou timeouts trop courts.
> **Pré-requis** : Le contrôleur Ingress nginx doit être déployé dans `ingress-nginx`. Variables `NS` et `APP` définies.

```bash
# Affiche les 200 dernières lignes des logs du contrôleur Ingress (erreurs upstream, timeouts, 502)
kubectl -n ingress-nginx logs deploy/ingress-nginx-controller --tail=200
# Vérifie que le Service a des endpoints actifs (pods prêts à recevoir du trafic)
kubectl -n $NS get endpoints $APP
```

> **Résultat attendu** :
> ```
> 2024/01/15 11:30:45 [error] upstream timed out (110: Connection timed out) while connecting to upstream,
>   client: 10.0.0.1, server: api.example.com, request: "GET /healthz HTTP/1.1",
>   upstream: "http://10.244.1.5:8080/healthz"
>
> NAME   ENDPOINTS                          AGE
> api    10.244.1.5:8080,10.244.2.8:8080   10d
> ```
> **Vérification** : Si les logs montrent `upstream timed out` → les pods sont lents ou injoignables. Si ENDPOINTS est vide → le selector du Service ne matche aucun pod. Vérifier que le port nommé dans l'Ingress (`name: http`) correspond au port du Service.

**Actions**

* Adapter timeouts Ingress ; corriger ports nommés (`name: http`), **readiness**.

---

## 6) Checklist "Performance saine"

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

> **Objectif** : Regrouper les commandes les plus utilisées pour le dépannage quotidien — état cluster, ressources, rollouts, réseau, stockage, logs et diagnostic nœud.
> **Pré-requis** : `kubectl` configuré avec le bon contexte. `metrics-server` déployé pour les commandes `top`. Accès SSH au nœud pour les commandes kubelet/crictl. Les variables `NS` et `APP` doivent être adaptées.

```bash
# === État cluster / nœuds / events ===
# Liste tous les nœuds avec adresses IP, OS et conditions
kubectl get nodes -o wide
# Récupère les 50 derniers événements cluster-wide triés par timestamp
kubectl get events -A --sort-by=.lastTimestamp | tail -n 50

# === Ressources & QoS ===
# Affiche la consommation CPU/Mémoire des nœuds et de tous les pods
kubectl top nodes ; kubectl top pods -A
# Affiche la classe QoS du pod (Guaranteed, Burstable, BestEffort)
kubectl get pod <pod> -o jsonpath='{.status.qosClass}{"\n"}'

# === Rollouts & images ===
# Vérifie le statut du rollout en cours (attend la fin si --watch)
kubectl -n app rollout status deploy/api
# Affiche l'historique des révisions du Deployment
kubectl -n app rollout history deploy/api
# Met à jour l'image du conteneur vers un digest spécifique (immutable)
kubectl -n app set image deploy/api api=repo@sha256:...

# === Services / Endpoints / DNS ===
# Liste les Services et Endpoints du namespace app
kubectl -n app get svc,ep
# Crée un pod debug éphémère pour tester la résolution DNS et la connectivité HTTP
kubectl -n app run -it net --image=nicolaka/netshoot --rm -- sh -lc 'dig A api.app.svc.cluster.local; curl -sS http://api:8080/healthz'

# === PV/PVC ===
# Liste les PVC du namespace et les StorageClasses disponibles
kubectl -n app get pvc ; kubectl get sc -o wide
# Décrit un PVC pour voir son état, le PV lié et les événements
kubectl -n app describe pvc <pvc>

# === Probes / logs / previous ===
# Extrait la configuration des probes (Readiness, Liveness, Startup) du pod
kubectl -n app describe pod <pod> | sed -n '/Probe/,$p'
# Affiche les logs du conteneur précédent (avant crash) — 200 dernières lignes
kubectl -n app logs <pod> --previous --tail=200

# === kubelet / nœud (SSH) ===
# Affiche les 100 dernières lignes des logs du service kubelet (erreurs, warnings)
journalctl -u kubelet --no-pager | tail -n 100
# Liste les conteneurs CRI et affiche les logs d'un conteneur spécifique
crictl ps ; crictl logs <cid>
```

> **Résultat attendu** :
> ```
> NAME     STATUS   ROLES    AGE   VERSION
> node-1   Ready    control  45d   v1.29.0
> node-2   Ready    worker   45d   v1.29.0
>
> NAME                   CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
> api-6b8d4f7c9-abc12   250m         12%    512Mi           26%
>
> Guaranteed
>
> deployment.apps/api successfully rolled out
>
> NAME   TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)    AGE
> api    ClusterIP   10.96.45.12    <none>        8080/TCP   10d
>
> NAME   ENDPOINTS                          AGE
> api    10.244.1.5:8080,10.244.2.8:8080   10d
>
> Readiness:  http-get http://:8080/healthz delay=5s timeout=3s period=10s
> ```
> **Vérification** : Chaque commande doit retourner des données cohérentes. `kubectl top` doit fonctionner (sinon installer metrics-server). Les Endpoints doivent contenir des IPs de pods Ready. Le rollout status doit afficher `successfully rolled out`.

---

## 8) Prévention (post-mortem → durcissement)

* **Runbooks** versionnés, liés aux alertes (annotation `runbook_url`).
* **Rules** admission : **pas de `:latest`**, **digest obligatoire**, **signature requise**, **registries autorisés**.
* **Tests de restauration** (PRA) & **game days** (pannes contrôlées).
* **SLO** publiés + **alertes burn-rate** ; **dashboards** standardisés.
* **Lint/validate** systématique (`kubeconform`, `helm lint`, `promtool`).
