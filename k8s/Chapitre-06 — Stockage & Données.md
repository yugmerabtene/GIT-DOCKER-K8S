# Chapitre 6 — Stockage & Données

*(volumes éphémères, PV/PVC, StorageClass & provisioning dynamique, modes d’accès, StatefulSets, snapshots & clones CSI, redimensionnement, permissions & sécurité, sauvegarde/restauration, runbooks de debug — avec explications **commande par commande**)*

---

## 1) Objectifs d’apprentissage

* Distinguer **volumes éphémères** (cycle de vie = Pod) et **persistants** (PV/PVC).
* Maîtriser **PV/PVC/StorageClass** : modes d’accès (**RWO/ROX/RWX**), **VolumeMode** (Filesystem/Block), **reclaimPolicy**, **bindingMode**.
* Utiliser le **provisioning dynamique** (CSI), les **snapshots**/**clones**, et le **redimensionnement**.
* Comprendre la **sécurité** des montages (UID/GID, `fsGroup`, SELinux, `subPath`, `mountOptions`).
* Savoir **diagnostiquer** (PVC Pending, Multi-attach, Read-only FS) et appliquer des **bonnes pratiques**.

---

## 2) Panorama (carte mentale)

```
[Pod] ──spec.volumes──> 
  - emptyDir / configMap / secret / downwardAPI / projected (éphémères)
  - hostPath (⚠ prod)
  - PVC (persistant via PV fourni par StorageClass/CSI)

[Persistant] PVC ←binding→ PV ←provisioner→ Backend (CSI: EBS, Ceph, NFS, EFS, …)

Snapshots/Clones: VolumeSnapshotClass + VolumeSnapshot → PVC (restore/clone)
```

---

## 3) Volumes **éphémères** (cycle de vie = Pod)

### 3.1 `emptyDir`

* Créé au démarrage du **Pod**, détruit à sa suppression.
* Options : `medium: Memory` (tmpfs), `sizeLimit`.

```yaml
volumes:
- name: cache
  emptyDir: { medium: Memory, sizeLimit: 256Mi }
containers:
- name: app
  volumeMounts: [ { name: cache, mountPath: /tmp/cache } ]
```

**Quand** : caches, scratch, données temporaires.

### 3.2 `configMap` / `secret` / `downwardAPI` / `projected`

* **configMap** : fichiers de config ; **secret** : *tmpfs*, monté en mémoire ; **downwardAPI** : metadata (labels/annotations) rendues en fichiers ; **projected** : fusion de sources.

```yaml
volumes:
- name: cfg
  configMap: { name: app-config }
- name: creds
  secret: { secretName: db-credentials }
- name: meta
  downwardAPI:
    items:
    - path: labels
      fieldRef: { fieldPath: metadata.labels }
```

**Bonnes pratiques** : pour secrets, éviter d’écrire sur disque ; monter en lecture seule.

### 3.3 `hostPath` (⚠️ prudence)

* Monte un chemin **de l’hôte** dans le Pod (couplage fort, risques sécurité).
* Usage **lab/daemon** uniquement (ex. agents logs). **Éviter en prod** pour les données applicatives.

### 3.4 Éphémères “génériques” (PVC inline) & Inline CSI

* **Generic ephemeral volumes** : un **PVC** est créé/supprimé **avec le Pod**.
* **Inline CSI** : certains drivers autorisent un volume CSI **directement dans le Pod** (sans PVC).

---

## 4) Volumes **persistants** : **PV** / **PVC**

### 4.1 Concepts

* **PV** (*PersistentVolume*) : ressource cluster, capacité + classe + mode d’accès.
* **PVC** (*PersistentVolumeClaim*) : **demande** de stockage par un **namespace**.
* **Binding** : PVC ↔ PV si compatibilité (capacité, StorageClass, modes d’accès).

### 4.2 Modes d’accès

* **RWO** (ReadWriteOnce) : lecture/écriture par **un** nœud à la fois (disque attaché).
* **ROX** (ReadOnlyMany) : lecture par **plusieurs** nœuds.
* **RWX** (ReadWriteMany) : lecture/écriture par **plusieurs** nœuds (NFS/CephFS/EFS…).

### 4.3 VolumeMode

* **Filesystem** (par défaut) : le driver formate/monte un FS.
* **Block** : **bloc brut** (pas de FS) présenté au conteneur (besoins spécifiques).

### 4.4 Commandes d’inspection (explications incluses)

```bash
kubectl get sc -o wide
# Liste les StorageClass ; -o wide : provisioner, reclaimPolicy, bindingMode, allowExpansion

kubectl get pv
# PV au niveau cluster : CAPACITY, ACCESS MODES, RECLAIM POLICY, STATUS, STORAGECLASS, AGE

kubectl get pvc -A
# Liste tous les PVC de tous les namespaces

kubectl describe pvc <name> -n <ns>
# Détails + Events : très utile pour voir "waiting for first consumer", erreurs de driver, etc.
```

---

## 5) **StorageClass** & provisioning **dynamique** (CSI)

### 5.1 StorageClass — champs clés

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata: { name: fast }
provisioner: csi.example.com          # driver CSI
parameters:                            # spécifiques au driver (type, iops, fsType, ...)
  type: ssd
reclaimPolicy: Delete                  # Delete | Retain (Recycle obsolète)
allowVolumeExpansion: true             # redimensionnement possible
volumeBindingMode: WaitForFirstConsumer # vs Immediate
# allowedTopologies:                   # contraindre zones/regions/nodes
# - matchLabelExpressions:
#   - key: topology.kubernetes.io/zone
#     values: ["eu-west-1a","eu-west-1b"]
```

* **reclaimPolicy**

  * **Delete** : PV supprimé quand PVC supprimé.
  * **Retain** : PV reste (données à gérer manuellement).
* **volumeBindingMode**

  * **Immediate** : le PV est créé/lié **immédiatement**.
  * **WaitForFirstConsumer** : attend que **le Pod** cible le PVC → permet un **placement topologique correct** (zone/host) pour éviter les cross-zones.

**Trouver la StorageClass par défaut**

```bash
kubectl get sc -o jsonpath='{range .items[*]}{.metadata.name}{" => default="}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\n"}{end}'
```

### 5.2 Provisioning dynamique (PVC → PV automatique)

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: data }
spec:
  accessModes: [ ReadWriteOnce ]
  storageClassName: fast          # sinon utilise la classe par défaut
  resources:
    requests: { storage: 10Gi }
  volumeMode: Filesystem
```

**Commandes**

```bash
kubectl apply -f pvc.yaml
kubectl get pvc data -o wide
kubectl describe pvc data
# "Bound" => OK ; "Pending" => voir Events (provisioner absent ? quotas ? topologie ?)
```

### 5.3 Monter un PVC dans un Pod

```yaml
spec:
  volumes: [ { name: data, persistentVolumeClaim: { claimName: data } } ]
  containers:
  - name: app
    image: busybox:1.36
    volumeMounts: [ { name: data, mountPath: /data } ]
    command: ["sh","-c","echo hello > /data/test && sleep 3600"]
```

**Vérifier depuis le Pod**

```bash
kubectl exec -it <pod> -- sh -lc "df -hT /data && ls -l /data && cat /data/test"
# df -hT : type de FS + taille ; ls -l : permissions ; cat : contenu écrit
```

---

## 6) **StatefulSet** & `volumeClaimTemplates`

* **StatefulSet** crée **1 PVC par réplique** (identité stable).

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata: { name: db }
spec:
  serviceName: db-headless     # Service headless pour l’adressage stable
  replicas: 3
  selector: { matchLabels: { app: db } }
  template:
    metadata: { labels: { app: db } }
    spec:
      containers:
      - name: postgres
        image: postgres:16
        volumeMounts: [ { name: data, mountPath: /var/lib/postgresql/data } ]
  volumeClaimTemplates:
  - metadata: { name: data }
    spec:
      accessModes: [ ReadWriteOnce ]
      storageClassName: fast
      resources: { requests: { storage: 20Gi } }
```

Chaque Pod (`db-0`, `db-1`, `db-2`) a **son PVC** (`data-db-0`, …).

---

## 7) **RWX** (ReadWriteMany) & partages

* **Besoin d’accès simultané en lecture/écriture depuis plusieurs nœuds** :

  * **NFS** (simple, perfs variables ; driver CSI NFS).
  * **CephFS** (performant, distribué).
  * **EFS** (AWS), **Azure Files**, etc.
* **RWO** (disques attachés : EBS, PD, Azure Disk, RBD) → **un seul nœud à la fois**.

---

## 8) **Snapshots** & **clones** (CSI)

### 8.1 CRDs snapshot

* `VolumeSnapshotClass` : indique le **driver** & la stratégie.
* `VolumeSnapshot` : **point dans le temps** d’un volume existant.
* **Restore** : créer un **PVC** depuis un snapshot.

**Flux** : PVC source → **VolumeSnapshot** → PVC restore.

*(Les manifests complets seront fournis en bundle à la fin du cours.)*

### 8.2 Clonage

* Beaucoup de drivers CSI supportent le **clone** direct : **PVC → PVC**.
* Spécifier `dataSource` dans le nouveau PVC (type `PersistentVolumeClaim`).

---

## 9) **Redimensionnement** (expand)

### 9.1 Conditions

* StorageClass : `allowVolumeExpansion: true`.
* Driver CSI : doit supporter l’expand.
* **Augmenter** uniquement (réduction non supportée).

### 9.2 Procédure

```bash
kubectl get pvc data -o yaml | grep storage:
# spec.resources.requests.storage: 10Gi

kubectl patch pvc data -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'
# Augmente la demande

kubectl describe pvc data
# Conditions: FileSystemResizePending → kubelet étendra le FS
# Un redémarrage du Pod peut être nécessaire selon le driver
```

---

## 10) Permissions & sécurité des montages

### 10.1 `securityContext` (Pod/Container)

* **UID/GID** : `runAsUser`, `runAsGroup`, `fsGroup`.
* **fsGroup** : applique un **chgrp** récursif sur les volumes montés (selon `fsGroupChangePolicy`).
* **SELinux** (si activé) : `seLinuxOptions` (type/level).

```yaml
spec:
  securityContext:
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
    fsGroupChangePolicy: "OnRootMismatch"   # "Always" par défaut
```

**Quand** : l’image n’est pas root et le FS monté appartient à `root:root`.

### 10.2 `mountOptions` (StorageClass/PV)

* Ex. NFS : `vers=4.1`, `rsize/wsize`, `noatime`.
* **À configurer côté StorageClass** ou **PV** (selon driver).

### 10.3 `subPath` / `subPathExpr`

* Monter **un sous-répertoire** du volume.
* **Attention** : erreurs de chemins → “file not found” ; risques si app s’attend à la racine.

---

## 11) Sauvegarde / Restauration

### 11.1 Stratégie

* **3-2-1** : 3 copies, 2 supports, 1 offsite.
* **RPO/RTO** définis (objectifs de reprise).
* Combiner **exports bases** (logiques) + **snapshots CSI** (bloc).

### 11.2 Outils

* **Velero** : sauvegarde **objets K8s** + **snapshots** (intégration CSI) ; **restic** pour fichiers.
* **Database operators** (Postgres/MySQL) : souvent intégrés avec backup/restore.

---

## 12) Quotas & politiques

### 12.1 ResourceQuota

* Limiter **storage** total et nombre de **PVC** par namespace.

```yaml
apiVersion: v1
kind: ResourceQuota
metadata: { name: storage-quota }
spec:
  hard:
    requests.storage: "200Gi"
    persistentvolumeclaims: "20"
```

### 12.2 LimitRange (éphemères)

* Encadrer `ephemeral-storage` des **containers** pour éviter le remplissage des disques.

---

## 13) Diagnostics — **runbooks**

### Cas A — **PVC Pending** (ne se lie pas)

**Symptômes** : `STATUS: Pending`
**Commandes**

```bash
kubectl describe pvc data
# Lire les Events: "no persistent volumes available", "waiting for first consumer", "no compatible topology", "provisioner not found"

kubectl get sc -o wide
# Vérifier provisioner, bindingMode, allowExpansion

kubectl get events -n <ns> --sort-by=.lastTimestamp | tail -n 20
```

**Correctifs** :

* Installer/activer le **driver CSI** ;
* Utiliser la **StorageClass par défaut** ou en préciser une existante ;
* Si `WaitForFirstConsumer`, **créer le Pod** qui consomme le PVC ;
* Problèmes de **topologie** (zones) → adapter `allowedTopologies` ou le placement du Pod.

---

### Cas B — **Pod bloqué “ContainerCreating”** (montage échoue)

**Commandes**

```bash
kubectl describe pod <name>
# Events: "MountVolume.SetUp failed", "permission denied", "not found"

journalctl -u kubelet -f
# Logs kubelet (si accès hôte)
```

**Correctifs** :

* Corriger **claimName** ; vérifier **namespace** ;
* Permissions → ajuster `runAsUser` / `fsGroup` ;
* Driver CSI : vérifier le **daemonset** du driver.

---

### Cas C — **Read-only file system** dans le conteneur

**Causes** : volume monté en RO, FS corrompu, `fsGroup` manquant, `seLinux` bloquant.
**À faire** : `mount | grep /data`, `dmesg`, ajuster `securityContext` (UID/GID/SELinux), remonter RW.

---

### Cas D — **Multi-attach** (volume attaché à 2 nœuds)

**Symptômes** : Events “**Multi-Attach error**”.
**Causes** : disque RWO déjà monté sur un autre nœud.
**Fix** : s’assurer qu’un seul Pod utilise le PVC RWO à un instant donné ; drain correct.

---

### Cas E — **PV en “Released”/“Terminating”** (nettoyage compliqué)

**À faire** :

* Si `Retain` : recycler manuellement (détacher, nettoyer, recréer PV).
* Vérifier **finalizers** ; supprimer avec parcimonie si fuite de contrôleur.

---

## 14) Mini-labs guidés (rapides)

> Comme convenu, les **bundles complets** de manifests seront donnés **à la fin**.
> Ici, juste les **extraits** nécessaires pour pratiquer immédiatement.

### Lab 1 — `emptyDir` + vérification

```bash
kubectl run t1 --image=busybox:1.36 --restart=Never -- \
  sh -lc 'mkdir -p /cache && sleep 3600'
# (on y reviendra avec un YAML complet dans le bundle final)
```

*(Idée : montrer `emptyDir` via manifest — fourni plus tard — puis `exec` et écrire dans /cache.)*

### Lab 2 — PVC RWO avec StorageClass par défaut

```bash
# 1) Trouver la StorageClass par défaut
kubectl get sc -o jsonpath='{range .items[*]}{.metadata.name}{" => default="}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\n"}{end}'

# 2) Créer un PVC (extrait)
cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: data }
spec:
  accessModes: [ ReadWriteOnce ]
  resources: { requests: { storage: 5Gi } }
YAML

# 3) Vérifier le binding
kubectl get pvc data -o wide
kubectl describe pvc data
```

### Lab 3 — Pod qui consomme le PVC + test d’écriture

```bash
cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata: { name: writer }
spec:
  volumes: [ { name: data, persistentVolumeClaim: { claimName: data } } ]
  containers:
  - name: app
    image: busybox:1.36
    volumeMounts: [ { name: data, mountPath: /data } ]
    command: ["sh","-c","echo OK > /data/ping && sleep 3600"]
YAML

kubectl exec -it writer -- sh -lc "df -hT /data && ls -l /data && cat /data/ping"
```

---

## 15) Bonnes pratiques (condensé)

* **Toujours** expliciter **StorageClass** (ou vérifier la **par défaut**).
* **RWO ≠ multi-nœuds** : un seul nœud à la fois ; pour RWX, utilisez NFS/CephFS/EFS.
* **WaitForFirstConsumer** recommandé en cloud multizone.
* **Pas de hostPath** pour les données app (sauf cas très contrôlés).
* **`fsGroup`/UID** cohérents avec l’image ; éviter root si possible.
* **Snapshots réguliers** + **backup** (Velero/restic) ; tester **restore**.
* **Quotas** par namespace ; surveiller la **capacité** et les **IOPS** côté backend.
* Documenter **MTU**/**topologie**/**classes** ; versionner vos manifests.

---

## 16) Aide-mémoire (cheat-sheet commandes)

```bash
# Lister/inspecter
kubectl get sc -o wide
kubectl get pv
kubectl get pvc -A
kubectl describe pvc <name> -n <ns>
kubectl get events -n <ns> --sort-by=.lastTimestamp | tail -n 30

# Trouver la StorageClass par défaut
kubectl get sc -o jsonpath='{range .items[*]}{.metadata.name}{" => default="}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\n"}{end}'

# Redimensionner un PVC (expand)
kubectl patch pvc data -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'
kubectl describe pvc data

# Dans un Pod (vérifier montage)
kubectl exec -it <pod> -- sh -lc "df -hT /data && mount | grep /data && id && ls -l /data"

# Debug kubelet (si accès hôte)
journalctl -u kubelet -f
```

