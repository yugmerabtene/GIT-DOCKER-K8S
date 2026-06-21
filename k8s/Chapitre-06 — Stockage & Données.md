# Chapitre 6 — Stockage & Données

*(volumes éphémères, PV/PVC, StorageClass & provisioning dynamique, modes d'accès, StatefulSets, snapshots & clones CSI, redimensionnement, permissions & sécurité, sauvegarde/restauration, runbooks de debug — avec explications **commande par commande**)*

---

## 1) Objectifs d'apprentissage

* Distinguer **volumes éphémères** (cycle de vie = Pod) et **persistants** (PV/PVC).
* Maîtriser **PV/PVC/StorageClass** : modes d'accès (**RWO/ROX/RWX**), **VolumeMode** (Filesystem/Block), **reclaimPolicy**, **bindingMode**.
* Utiliser le **provisioning dynamique** (CSI), les **snapshots**/**clones**, et le **redimensionnement**.
* Comprendre la **sécurité** des montages (UID/GID, `fsGroup`, SELinux, `subPath`, `mountOptions`).
* Savoir **diagnostiquer** (PVC Pending, Multi-attach, Read-only FS) et appliquer des **bonnes pratiques**.

---

## 2) Panorama (carte mentale)

> **Objectif** : Visualiser la hiérarchie des volumes dans Kubernetes — des volumes éphémères attachés aux Pods jusqu'aux volumes persistants liés via des PV/PVC et provisionnés par des drivers CSI.
> **Pre-requis** : Aucun, ce schéma est une vue d'ensemble conceptuelle.

```
# Arbre des volumes Kubernetes :
# [Pod] utilise spec.volumes qui peut contenir :
#   - Volumes éphémères : emptyDir, configMap, secret, downwardAPI, projected
#     → détruits avec le Pod
#   - hostPath : montage depuis le système de fichiers de l'hôte (⚠ risqué en prod)
#   - PVC : lien vers un volume persistant
#
# Chaîne de provisioning persistant :
#   PVC ←binding (1:1)→ PV ←provisioner (CSI driver)→ Backend réel (EBS, Ceph, NFS, EFS…)
#
# Snapshots & Clones :
#   VolumeSnapshotClass (config) + VolumeSnapshot (instantané) → nouveau PVC (restore ou clone)
[Pod] ──spec.volumes──> 
  - emptyDir / configMap / secret / downwardAPI / projected (éphémères)
  - hostPath (⚠ prod)
  - PVC (persistant via PV fourni par StorageClass/CSI)

[Persistant] PVC ←binding→ PV ←provisioner→ Backend (CSI: EBS, Ceph, NFS, EFS, …)

Snapshots/Clones: VolumeSnapshotClass + VolumeSnapshot → PVC (restore/clone)
```

> **Résultat attendu** :
> ```
> Compréhension visuelle : chaque Pod peut avoir 0..N volumes.
> Les volumes persistants suivent la chaîne : PVC → PV → Backend via un driver CSI.
> ```
> **Vérification** : Retenir que le PVC est la "demande" et le PV est la "ressource" — le binding est automatique si compatibilité.

---

## 3) Volumes **éphémères** (cycle de vie = Pod)

### 3.1 `emptyDir`

* Créé au démarrage du **Pod**, détruit à sa suppression.
* Options : `medium: Memory` (tmpfs), `sizeLimit`.

> **Objectif** : Créer un volume temporaire en mémoire (tmpfs) de 256Mi, partagé entre les conteneurs du Pod, idéal pour un cache ou des données temporaires.
> **Pre-requis** : Un Pod existant ou un manifeste de Pod prêt à être déployé.

```yaml
volumes:
- name: cache                          # Nom du volume, référencé par les conteneurs
  emptyDir: { medium: Memory, sizeLimit: 256Mi }  # medium: Memory → tmpfs (RAM), limité à 256Mi
containers:
- name: app                            # Conteneur applicatif
  volumeMounts: [ { name: cache, mountPath: /tmp/cache } ]  # Monte le volume dans /tmp/cache
```

> **Résultat attendu** :
> ```
> Le Pod démarre avec un répertoire /tmp/cache en mémoire (tmpfs), limité à 256Mi.
> Les données sont perdues à la suppression du Pod.
> ```
> **Vérification** : `kubectl exec <pod> -- df -hT /tmp/cache` doit afficher `tmpfs` avec une taille de 256Mi.

**Quand** : caches, scratch, données temporaires.

### 3.2 `configMap` / `secret` / `downwardAPI` / `projected`

* **configMap** : fichiers de config ; **secret** : *tmpfs*, monté en mémoire ; **downwardAPI** : metadata (labels/annotations) rendues en fichiers ; **projected** : fusion de sources.

> **Objectif** : Monter trois types de volumes éphémères dans un Pod : une ConfigMap (fichier de configuration), un Secret (identifiants sensibles en mémoire), et les metadata du Pod via downwardAPI (labels exposés comme fichier).
> **Pre-requis** : La ConfigMap `app-config` et le Secret `db-credentials` doivent exister dans le même namespace.

```yaml
volumes:
- name: cfg                            # Volume pour la ConfigMap
  configMap: { name: app-config }      # Référence la ConfigMap "app-config" du namespace
- name: creds                          # Volume pour le Secret
  secret: { secretName: db-credentials }  # Référence le Secret "db-credentials" (monté en tmpfs)
- name: meta                           # Volume pour les metadata du Pod
  downwardAPI:
    items:
    - path: labels                     # Fichier qui contiendra les labels
      fieldRef: { fieldPath: metadata.labels }  # Injecte les labels du Pod dans ce fichier
```

> **Résultat attendu** :
> ```
# /etc/cfg/          → contient les clés/valeurs de la ConfigMap "app-config"
# /etc/creds/        → contient les clés/valeurs du Secret "db-credentials" (en base64 décodé)
# /etc/meta/labels   → contient les labels du Pod au format clé=valeur
> ```
> **Vérification** : `kubectl exec <pod> -- ls /etc/cfg /etc/creds /etc/meta` et `cat /etc/meta/labels`.

**Bonnes pratiques** : pour secrets, éviter d'écrire sur disque ; monter en lecture seule.

### 3.3 `hostPath` (⚠️ prudence)

* Monte un chemin **de l'hôte** dans le Pod (couplage fort, risques sécurité).
* Usage **lab/daemon** uniquement (ex. agents logs). **Éviter en prod** pour les données applicatives.

### 3.4 Éphémères "génériques" (PVC inline) & Inline CSI

* **Generic ephemeral volumes** : un **PVC** est créé/supprimé **avec le Pod**.
* **Inline CSI** : certains drivers autorisent un volume CSI **directement dans le Pod** (sans PVC).

---

## 4) Volumes **persistants** : **PV** / **PVC**

### 4.1 Concepts

* **PV** (*PersistentVolume*) : ressource cluster, capacité + classe + mode d'accès.
* **PVC** (*PersistentVolumeClaim*) : **demande** de stockage par un **namespace**.
* **Binding** : PVC ↔ PV si compatibilité (capacité, StorageClass, modes d'accès).

### 4.2 Modes d'accès

* **RWO** (ReadWriteOnce) : lecture/écriture par **un** nœud à la fois (disque attaché).
* **ROX** (ReadOnlyMany) : lecture par **plusieurs** nœuds.
* **RWX** (ReadWriteMany) : lecture/écriture par **plusieurs** nœuds (NFS/CephFS/EFS…).

### 4.3 VolumeMode

* **Filesystem** (par défaut) : le driver formate/monte un FS.
* **Block** : **bloc brut** (pas de FS) présenté au conteneur (besoins spécifiques).

### 4.4 Commandes d'inspection (explications incluses)

> **Objectif** : Inspecter l'état du stockage dans le cluster — StorageClass, PV, PVC — pour vérifier le provisioning et le binding.
> **Pre-requis** : `kubectl` configuré avec un contexte valide vers un cluster Kubernetes.

```bash
kubectl get sc -o wide
# Liste les StorageClass avec détails : provisioner (driver CSI), reclaimPolicy (Delete/Retain),
# bindingMode (Immediate/WaitForFirstConsumer), allowExpansion (true/false)

kubectl get pv
# Affiche tous les PersistentVolumes du cluster :
# CAPACITY (taille), ACCESS MODES (RWO/ROX/RWX), RECLAIM POLICY,
# STATUS (Available/Bound/Released/Failed), STORAGECLASS, AGE

kubectl get pvc -A
# Liste tous les PersistentVolumeClaims de tous les namespaces (-A = --all-namespaces)
# Utile pour avoir une vue globale des demandes de stockage

kubectl describe pvc <name> -n <ns>
# Affiche les détails complets d'un PVC + les Events associés :
# très utile pour diagnostiquer : "waiting for first consumer",
# erreurs de driver CSI, problèmes de topologie, quotas dépassés, etc.
```

> **Résultat attendu** :
> ```
> $ kubectl get sc -o wide
> NAME     PROVISIONER          RECLAIMPOLICY   BINDINGMODE        ALLOWEXPANSION
> fast     csi.example.com      Delete          WaitForFirstConsumer  true
>
> $ kubectl get pv
> NAME    CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   STORAGECLASS
> pv-01   10Gi       RWO            Delete           Bound    fast
>
> $ kubectl get pvc -A
> NAMESPACE   NAME    STATUS   VOLUME   CAPACITY   STORAGECLASS
> default     data    Bound    pv-01    10Gi       fast
> ```
> **Vérification** : S'assurer que les PV sont en statut `Bound` et que les StorageClass ont le bon `provisioner`.

---

## 5) **StorageClass** & provisioning **dynamique** (CSI)

### 5.1 StorageClass — champs clés

> **Objectif** : Définir une StorageClass nommée "fast" qui utilise un driver CSI pour provisionner dynamiquement des volumes SSD, avec suppression automatique du PV quand le PVC est supprimé, et binding retardé au premier Pod consommateur.
> **Pre-requis** : Le driver CSI `csi.example.com` doit être installé dans le cluster.

```yaml
apiVersion: storage.k8s.io/v1          # API stable pour les StorageClass
kind: StorageClass
metadata: { name: fast }               # Nom de la classe, référencé par les PVC
provisioner: csi.example.com           # Driver CSI qui crée les volumes (ex: ebs.csi.aws.com)
parameters:                            # Paramètres spécifiques au driver CSI
  type: ssd                            # Ex: type de disque (ssd, gp3, io2, etc.)
reclaimPolicy: Delete                  # Delete = PV supprimé quand PVC supprimé ; Retain = conservé
allowVolumeExpansion: true             # Autorise le redimensionnement (kubectl patch pvc)
volumeBindingMode: WaitForFirstConsumer # Attend le Pod avant de créer le PV → bon placement topologique
# allowedTopologies:                   # (Optionnel) Restreint les zones/régions/nœuds
# - matchLabelExpressions:             # Ex: limiter aux zones eu-west-1a et eu-west-1b
#   - key: topology.kubernetes.io/zone
#     values: ["eu-west-1a","eu-west-1b"]
```

> **Résultat attendu** :
> ```
> $ kubectl get sc fast -o wide
> NAME   PROVISIONER           RECLAIMPOLICY   BINDINGMODE              ALLOWEXPANSION
> fast   csi.example.com       Delete          WaitForFirstConsumer     true
> ```
> **Vérification** : `kubectl get sc` doit lister "fast" avec le bon provisioner et les bonnes options.

* **reclaimPolicy**

  * **Delete** : PV supprimé quand PVC supprimé.
  * **Retain** : PV reste (données à gérer manuellement).
* **volumeBindingMode**

  * **Immediate** : le PV est créé/lié **immédiatement**.
  * **WaitForFirstConsumer** : attend que **le Pod** cible le PVC → permet un **placement topologique correct** (zone/host) pour éviter les cross-zones.

**Trouver la StorageClass par défaut**

> **Objectif** : Identifier quelle StorageClass est marquée comme "par défaut" dans le cluster (utilisée automatiquement quand un PVC ne spécifie pas de `storageClassName`).
> **Pre-requis** : `kubectl` configuré avec accès au cluster.

```bash
kubectl get sc -o jsonpath='{range .items[*]}{.metadata.name}{" => default="}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\n"}{end}'
# Parcourt toutes les StorageClass et affiche leur annotation "is-default-class"
# La classe avec "true" est celle utilisée par défaut pour les PVC sans storageClassName
```

> **Résultat attendu** :
> ```
> fast => default=true
> standard => default=false
> ```
> **Vérification** : Au moins une StorageClass devrait avoir `default=true` (sinon les PVC doivent en spécifier une).

### 5.2 Provisioning dynamique (PVC → PV automatique)

> **Objectif** : Créer une demande de stockage (PVC) de 10Gi en mode ReadWriteOnce, qui déclenchera automatiquement la création d'un PV via la StorageClass "fast".
> **Pre-requis** : La StorageClass `fast` doit exister dans le cluster.

```yaml
apiVersion: v1                          # API core pour les PVC
kind: PersistentVolumeClaim             # Demande de stockage
metadata: { name: data }                # Nom du PVC, référencé par les Pods
spec:
  accessModes: [ ReadWriteOnce ]        # RWO : un seul nœud peut écrire
  storageClassName: fast                # Utilise la StorageClass "fast" (sinon, classe par défaut)
  resources:
    requests: { storage: 10Gi }         # Demande 10Gi de stockage
  volumeMode: Filesystem                # Mode par défaut : le driver formate un FS (vs Block)
```

> **Résultat attendu** :
> ```
> $ kubectl get pvc data
> NAME   STATUS   VOLUME    CAPACITY   ACCESS MODES   STORAGECLASS
> data   Bound    pvc-abc   10Gi       RWO            fast
> ```
> **Vérification** : Le PVC passe de `Pending` à `Bound` une fois le PV provisionné par le driver CSI.

**Commandes**

> **Objectif** : Appliquer le PVC, vérifier son statut et diagnostiquer d'éventuels problèmes de binding.
> **Pre-requis** : Le fichier `pvc.yaml` contient le manifeste du PVC ci-dessus.

```bash
kubectl apply -f pvc.yaml               # Crée ou met à jour le PVC dans le cluster
kubectl get pvc data -o wide            # Affiche le PVC avec détails (VOLUME, CAPACITY, etc.)
kubectl describe pvc data               # Détails + Events : diagnostic si "Pending"
# "Bound" => le PV a été provisionné avec succès
# "Pending" => vérifier les Events : provisioner absent ? quotas dépassés ? topologie incompatible ?
```

> **Résultat attendu** :
> ```
> $ kubectl apply -f pvc.yaml
> persistentvolumeclaim/data created
>
> $ kubectl get pvc data -o wide
> NAME   STATUS   VOLUME         CAPACITY   ACCESS MODES   STORAGECLASS   AGE
> data   Bound    pvc-a1b2c3     10Gi       RWO            fast           5s
>
> $ kubectl describe pvc data
> Events:
>   Normal  Provisioning    CSI driver provisionne le volume
>   Normal  SuccessfulProvisioning  Volume provisionné avec succès
> ```
> **Vérification** : Le STATUS doit être `Bound`. Si `Pending`, lire les Events pour identifier la cause.

### 5.3 Monter un PVC dans un Pod

> **Objectif** : Créer un Pod qui monte le PVC "data" et écrit un fichier test dans le volume pour vérifier que le montage fonctionne.
> **Pre-requis** : Le PVC `data` doit exister et être en statut `Bound`.

```yaml
spec:
  volumes: [ { name: data, persistentVolumeClaim: { claimName: data } } ]  # Déclare le volume depuis le PVC
  containers:
  - name: app
    image: busybox:1.36                    # Image légère pour le test
    volumeMounts: [ { name: data, mountPath: /data } ]  # Monte le PVC dans /data
    command: ["sh","-c","echo hello > /data/test && sleep 3600"]  # Écrit dans le volume puis attend
```

> **Résultat attendu** :
> ```
> Le Pod démarre, monte le PVC "data" sur /data, écrit "hello" dans /data/test.
> Le fichier persiste tant que le PVC existe (même si le Pod est supprimé).
> ```
> **Vérification** : `kubectl exec <pod> -- cat /data/test` doit afficher `hello`.

**Vérifier depuis le Pod**

> **Objectif** : Vérifier depuis l'intérieur du Pod que le volume est correctement monté, son type de filesystem, sa taille, ses permissions et son contenu.
> **Pre-requis** : Le Pod doit être en statut `Running`.

```bash
kubectl exec -it <pod> -- sh -lc "df -hT /data && ls -l /data && cat /data/test"
# df -hT /data : affiche le type de filesystem (ext4, xfs…) et la taille montée
# ls -l /data   : vérifie les permissions (propriétaire, groupe, droits)
# cat /data/test : affiche le contenu écrit (doit contenir "hello")
```

> **Résultat attendu** :
> ```
> Filesystem     Type   Size  Used Avail Use% Mounted on
> /dev/sdb       ext4   9.8G   24K  9.8G   1% /data
> total 4
> -rw-r--r-- 1 root root 6 Jun 21 10:00 test
> hello
> ```
> **Vérification** : `df -hT` montre un vrai filesystem (pas tmpfs), la taille correspond à ~10Gi, et `cat` affiche le contenu écrit.

---

## 6) **StatefulSet** & `volumeClaimTemplates`

* **StatefulSet** crée **1 PVC par réplique** (identité stable).

> **Objectif** : Déployer un StatefulSet de 3 répliques PostgreSQL, chacune avec son propre PVC de 20Gi (identité stable : data-db-0, data-db-1, data-db-2), adressables via un Service headless.
> **Pre-requis** : La StorageClass `fast` doit exister. Le Service headless `db-headless` doit être créé au préalable.

```yaml
apiVersion: apps/v1                     # API pour les StatefulSets
kind: StatefulSet
metadata: { name: db }                  # Nom du StatefulSet
spec:
  serviceName: db-headless              # Service headless requis pour l'adressage DNS stable (db-0.db-headless)
  replicas: 3                           # 3 répliques → 3 Pods : db-0, db-1, db-2
  selector: { matchLabels: { app: db } }  # Sélectionne les Pods avec label app=db
  template:
    metadata: { labels: { app: db } }   # Label appliqué à chaque Pod
    spec:
      containers:
      - name: postgres
        image: postgres:16              # Image PostgreSQL 16
        volumeMounts: [ { name: data, mountPath: /var/lib/postgresql/data } ]  # Données PG dans le volume
  volumeClaimTemplates:                 # Template de PVC : un PVC créé par réplique
  - metadata: { name: data }            # Nom de base du PVC (sera suffixé : data-db-0, data-db-1, …)
    spec:
      accessModes: [ ReadWriteOnce ]    # Chaque PVC est exclusif à son Pod
      storageClassName: fast            # Utilise la StorageClass "fast"
      resources: { requests: { storage: 20Gi } }  # 20Gi par réplique
```

> **Résultat attendu** :
> ```
> $ kubectl get pods
> NAME   READY   STATUS    RESTARTS   AGE
> db-0   1/1     Running   0          30s
> db-1   1/1     Running   0          20s
> db-2   1/1     Running   0          10s
>
> $ kubectl get pvc
> NAME        STATUS   VOLUME         CAPACITY   STORAGECLASS
> data-db-0   Bound    pvc-aaa        20Gi       fast
> data-db-1   Bound    pvc-bbb        20Gi       fast
> data-db-2   Bound    pvc-ccc        20Gi       fast
> ```
> **Vérification** : 3 Pods (db-0, db-1, db-2) Running, chacun avec son PVC dédié (data-db-0, data-db-1, data-db-2).

Chaque Pod (`db-0`, `db-1`, `db-2`) a **son PVC** (`data-db-0`, …).

---

## 7) **RWX** (ReadWriteMany) & partages

* **Besoin d'accès simultané en lecture/écriture depuis plusieurs nœuds** :

  * **NFS** (simple, perfs variables ; driver CSI NFS).
  * **CephFS** (performant, distribué).
  * **EFS** (AWS), **Azure Files**, etc.
* **RWO** (disques attachés : EBS, PD, Azure Disk, RBD) → **un seul nœud à la fois**.

---

## 8) **Snapshots** & **clones** (CSI)

### 8.1 CRDs snapshot

* `VolumeSnapshotClass` : indique le **driver** & la stratégie.
* `VolumeSnapshot` : **point dans le temps** d'un volume existant.
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
* Driver CSI : doit supporter l'expand.
* **Augmenter** uniquement (réduction non supportée).

### 9.2 Procédure

> **Objectif** : Redimensionner un PVC de 10Gi à 20Gi sans interruption de service (expand en ligne), puis vérifier que le filesystem est étendu.
> **Pre-requis** : La StorageClass doit avoir `allowVolumeExpansion: true`. Le driver CSI doit supporter l'expand.

```bash
kubectl get pvc data -o yaml | grep storage:
# Affiche la taille actuelle demandée : spec.resources.requests.storage: 10Gi
# Permet de vérifier la valeur avant modification

kubectl patch pvc data -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'
# Modifie la demande de stockage de 10Gi à 20Gi (patch JSON)
# Le contrôleur CSI va agrandir le volume backend, puis le kubelet étend le filesystem

kubectl describe pvc data
# Vérifier les Conditions :
#   FileSystemResizePending → le kubelet est en train d'étendre le filesystem
#   Une fois terminé, la condition disparaît et la nouvelle taille est effective
# Un redémarrage du Pod peut être nécessaire selon le driver CSI utilisé
```

> **Résultat attendu** :
> ```
> $ kubectl get pvc data -o yaml | grep storage:
>     storage: 10Gi
>
> $ kubectl patch pvc data -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'
> persistentvolumeclaim/data patched
>
> $ kubectl describe pvc data
> Conditions:
>   Type                Status
>   FileSystemResizePending  True
>   ...
> # Après quelques secondes :
>   Capacity: 20Gi (plus de condition FileSystemResizePending)
> ```
> **Vérification** : Le PVC affiche 20Gi et la condition `FileSystemResizePending` disparaît. `df -hT` dans le Pod confirme la nouvelle taille.

---

## 10) Permissions & sécurité des montages

### 10.1 `securityContext` (Pod/Container)

* **UID/GID** : `runAsUser`, `runAsGroup`, `fsGroup`.
* **fsGroup** : applique un **chgrp** récursif sur les volumes montés (selon `fsGroupChangePolicy`).
* **SELinux** (si activé) : `seLinuxOptions` (type/level).

> **Objectif** : Configurer le contexte de sécurité du Pod pour que les volumes montés appartiennent au groupe 1000, permettant à un conteneur non-root d'y écrire. `OnRootMismatch` évite un chown récursif coûteux si les permissions sont déjà correctes.
> **Pre-requis** : Un Pod avec des volumes montés. L'image du conteneur doit tourner avec un UID non-root (ex: 1000).

```yaml
spec:
  securityContext:
    runAsUser: 1000                    # Tous les conteneurs tournent en tant qu'UID 1000
    runAsGroup: 1000                   # Groupe principal = 1000
    fsGroup: 1000                      # Applique chgrp -R 1000 sur les volumes montés
    fsGroupChangePolicy: "OnRootMismatch"  # Ne fait le chown que si la racine du volume appartient à root
                                           # "Always" (défaut) : toujours faire le chown récursif
```

> **Résultat attendu** :
> ```
> Les volumes montés dans le Pod appartiennent à root:1000 avec permissions g+rw.
> Le conteneur (UID 1000, GID 1000) peut lire et écrire dans les volumes.
> ```
> **Vérification** : `kubectl exec <pod> -- ls -ld /data` doit montrer `drwxrwsr-x ... 1000` (le 's' indique le setgid via fsGroup).

**Quand** : l'image n'est pas root et le FS monté appartient à `root:root`.

### 10.2 `mountOptions` (StorageClass/PV)

* Ex. NFS : `vers=4.1`, `rsize/wsize`, `noatime`.
* **À configurer côté StorageClass** ou **PV** (selon driver).

### 10.3 `subPath` / `subPathExpr`

* Monter **un sous-répertoire** du volume.
* **Attention** : erreurs de chemins → "file not found" ; risques si app s'attend à la racine.

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

> **Objectif** : Limiter la consommation de stockage dans un namespace à 200Gi maximum et 20 PVC au total, pour éviter qu'une équipe ne monopolise les ressources du cluster.
> **Pre-requis** : Avoir les droits d'administration sur le namespace cible.

```yaml
apiVersion: v1                          # API core pour les ResourceQuotas
kind: ResourceQuota
metadata: { name: storage-quota }       # Nom du quota
spec:
  hard:
    requests.storage: "200Gi"           # Limite totale de stockage demandé (somme de tous les PVC)
    persistentvolumeclaims: "20"        # Nombre maximum de PVC dans ce namespace
```

> **Résultat attendu** :
> ```
> $ kubectl describe resourcequota storage-quota
> Name:       storage-quota
> Resource    Used   Hard
> --------    ----   ----
> persistentvolumeclaims  2    20
> requests.storage         15Gi  200Gi
> ```
> **Vérification** : Toute nouvelle demande de PVC dépassant ces limites sera rejetée avec une erreur "exceeded quota".

### 12.2 LimitRange (éphemères)

* Encadrer `ephemeral-storage` des **containers** pour éviter le remplissage des disques.

---

## 13) Diagnostics — **runbooks**

### Cas A — **PVC Pending** (ne se lie pas)

**Symptômes** : `STATUS: Pending`
**Commandes**

> **Objectif** : Diagnostiquer pourquoi un PVC reste en statut `Pending` — identifier si le problème vient du provisioner, de la topologie, des quotas ou de la StorageClass.
> **Pre-requis** : Un PVC en statut `Pending` dans le cluster.

```bash
kubectl describe pvc data
# Lire les Events en bas de la sortie :
# "no persistent volumes available" → pas de PV compatible (si provisioning statique)
# "waiting for first consumer" → WaitForFirstConsumer, normal tant qu'aucun Pod ne consomme le PVC
# "no compatible topology" → contraintes topologiques non satisfaites
# "provisioner not found" → le driver CSI n'est pas installé ou ne répond pas

kubectl get sc -o wide
# Vérifier que la StorageClass référencée par le PVC existe et a le bon provisioner,
# le bon bindingMode, et allowExpansion si nécessaire

kubectl get events -n <ns> --sort-by=.lastTimestamp | tail -n 20
# Affiche les 20 derniers events du namespace triés par timestamp
# Utile pour voir les erreurs récentes du provisioner CSI ou du scheduler
```

> **Résultat attendu** :
> ```
> $ kubectl describe pvc data
> Events:
>   Warning  ProvisioningFailed  provisioner csi.example.com: waiting for first consumer
>   # OU
>   Warning  ProvisioningFailed  no persistent volumes available for this claim
> ```
> **Vérification** : Identifier le message exact dans les Events pour appliquer le correctif correspondant.

**Correctifs** :

* Installer/activer le **driver CSI** ;
* Utiliser la **StorageClass par défaut** ou en préciser une existante ;
* Si `WaitForFirstConsumer`, **créer le Pod** qui consomme le PVC ;
* Problèmes de **topologie** (zones) → adapter `allowedTopologies` ou le placement du Pod.

---

### Cas B — **Pod bloqué "ContainerCreating"** (montage échoue)

**Commandes**

> **Objectif** : Diagnostiquer pourquoi un Pod reste bloqué en statut `ContainerCreating` à cause d'un échec de montage de volume — identifier l'erreur exacte (claimName incorrect, permissions, driver CSI).
> **Pre-requis** : Un Pod bloqué en statut `ContainerCreating`.

```bash
kubectl describe pod <name>
# Lire les Events :
# "MountVolume.SetUp failed" → problème de configuration du volume (claimName, namespace)
# "permission denied" → problème de permissions (fsGroup, SELinux)
# "not found" → le PVC référencé n'existe pas ou est dans un autre namespace

journalctl -u kubelet -f
# Logs en temps réel du kubelet (si accès SSH à l'hôte)
# Montre les erreurs détaillées du montage : driver CSI, attach/detach, permissions
```

> **Résultat attendu** :
> ```
> $ kubectl describe pod writer
> Events:
>   Warning  FailedMount  MountVolume.SetUp failed for volume "data" :
>     persistentvolumeclaim "data" not found
>   # OU
>   Warning  FailedMount  Unable to attach or mount volumes: permission denied
> ```
> **Vérification** : Le message d'erreur dans les Events indique la cause exacte (PVC manquant, permissions, driver).

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

**Symptômes** : Events "**Multi-Attach error**".
**Causes** : disque RWO déjà monté sur un autre nœud.
**Fix** : s'assurer qu'un seul Pod utilise le PVC RWO à un instant donné ; drain correct.

---

### Cas E — **PV en "Released"/"Terminating"** (nettoyage compliqué)

**À faire** :

* Si `Retain` : recycler manuellement (détacher, nettoyer, recréer PV).
* Vérifier **finalizers** ; supprimer avec parcimonie si fuite de contrôleur.

---

## 14) Mini-labs guidés (rapides)

> Comme convenu, les **bundles complets** de manifests seront donnés **à la fin**.
> Ici, juste les **extraits** nécessaires pour pratiquer immédiatement.

### Lab 1 — `emptyDir` + vérification

> **Objectif** : Lancer un Pod basique avec busybox pour préparer un test de volume éphémère — le Pod crée un répertoire /cache et attend.
> **Pre-requis** : Un cluster Kubernetes accessible via kubectl.

```bash
kubectl run t1 --image=busybox:1.36 --restart=Never -- \
  sh -lc 'mkdir -p /cache && sleep 3600'
# Crée un Pod nommé "t1" avec l'image busybox
# --restart=Never : crée un Pod (pas un Deployment)
# Le Pod crée /cache puis dort 3600s (1h) pour rester actif
# (on y reviendra avec un YAML complet dans le bundle final)
```

> **Résultat attendu** :
> ```
> $ kubectl run t1 --image=busybox:1.36 --restart=Never -- sh -lc 'mkdir -p /cache && sleep 3600'
> pod/t1 created
>
> $ kubectl get pod t1
> NAME   READY   STATUS    RESTARTS   AGE
> t1     1/1     Running   0          5s
> ```
> **Vérification** : Le Pod doit être en statut `Running`. On pourra ensuite y entrer avec `kubectl exec -it t1 -- sh`.

*(Idée : montrer `emptyDir` via manifest — fourni plus tard — puis `exec` et écrire dans /cache.)*

### Lab 2 — PVC RWO avec StorageClass par défaut

> **Objectif** : Trouver la StorageClass par défaut du cluster, créer un PVC de 5Gi qui sera automatiquement provisionné, puis vérifier que le binding est effectif.
> **Pre-requis** : Un cluster Kubernetes avec au moins une StorageClass configurée.

```bash
# 1) Trouver la StorageClass par défaut
kubectl get sc -o jsonpath='{range .items[*]}{.metadata.name}{" => default="}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\n"}{end}'
# Parcourt toutes les StorageClass et affiche leur annotation is-default-class
# Celle avec "true" sera utilisée automatiquement par le PVC

# 2) Créer un PVC (extrait)
cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: data }
spec:
  accessModes: [ ReadWriteOnce ]       # Un seul nœud peut écrire
  resources: { requests: { storage: 5Gi } }  # Demande 5Gi (pas de storageClassName → classe par défaut)
YAML
# Le heredoc (cat <<'YAML') envoie le manifeste directement à kubectl apply -f -

# 3) Vérifier le binding
kubectl get pvc data -o wide           # Affiche le PVC avec le volume lié
kubectl describe pvc data              # Détails + Events pour confirmer le provisioning
```

> **Résultat attendu** :
> ```
> $ kubectl get sc -o jsonpath=...
> standard => default=true
>
> $ cat <<'YAML' | kubectl apply -f -
> persistentvolumeclaim/data created
>
> $ kubectl get pvc data -o wide
> NAME   STATUS   VOLUME         CAPACITY   ACCESS MODES   STORAGECLASS   AGE
> data   Bound    pvc-xyz789     5Gi        RWO            standard       3s
>
> $ kubectl describe pvc data
> Events:
>   Normal  Provisioning          CSI driver provisionne
>   Normal  SuccessfulProvisioning  Volume prêt
> ```
> **Vérification** : Le PVC `data` est en statut `Bound` avec un VOLUME auto-généré et la STORAGECLASS par défaut.

### Lab 3 — Pod qui consomme le PVC + test d'écriture

> **Objectif** : Créer un Pod qui monte le PVC "data", écrit un fichier "ping" dans le volume, puis vérifier depuis le Pod que le montage est fonctionnel (filesystem, permissions, contenu).
> **Pre-requis** : Le PVC `data` doit exister et être en statut `Bound`.

```bash
cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata: { name: writer }
spec:
  volumes: [ { name: data, persistentVolumeClaim: { claimName: data } } ]  # Monte le PVC "data"
  containers:
  - name: app
    image: busybox:1.36                    # Image légère pour le test
    volumeMounts: [ { name: data, mountPath: /data } ]  # Volume accessible dans /data
    command: ["sh","-c","echo OK > /data/ping && sleep 3600"]  # Écrit "OK" dans /data/ping puis attend
YAML
# Le Pod crée le fichier /data/ping avec le contenu "OK" sur le volume persistant

kubectl exec -it writer -- sh -lc "df -hT /data && ls -l /data && cat /data/ping"
# df -hT /data : type de FS + taille du volume monté
# ls -l /data  : liste les fichiers et permissions dans /data
# cat /data/ping : affiche le contenu du fichier écrit (doit être "OK")
```

> **Résultat attendu** :
> ```
> $ cat <<'YAML' | kubectl apply -f -
> pod/writer created
>
> $ kubectl exec -it writer -- sh -lc "df -hT /data && ls -l /data && cat /data/ping"
> Filesystem     Type   Size  Used Avail Use% Mounted on
> /dev/sdb       ext4   4.8G   24K  4.8G   1% /data
> total 4
> -rw-r--r-- 1 root root 3 Jun 21 10:05 ping
> OK
> ```
> **Vérification** : `df -hT` montre un filesystem monté sur /data, `ls -l` montre le fichier `ping`, et `cat` affiche `OK`.

---

## 15) Bonnes pratiques (condensé)

* **Toujours** expliciter **StorageClass** (ou vérifier la **par défaut**).
* **RWO ≠ multi-nœuds** : un seul nœud à la fois ; pour RWX, utilisez NFS/CephFS/EFS.
* **WaitForFirstConsumer** recommandé en cloud multizone.
* **Pas de hostPath** pour les données app (sauf cas très contrôlés).
* **`fsGroup`/UID** cohérents avec l'image ; éviter root si possible.
* **Snapshots réguliers** + **backup** (Velero/restic) ; tester **restore**.
* **Quotas** par namespace ; surveiller la **capacité** et les **IOPS** côté backend.
* Documenter **MTU**/**topologie**/**classes** ; versionner vos manifests.

---

## 16) Aide-mémoire (cheat-sheet commandes)

> **Objectif** : Récapitulatif de toutes les commandes essentielles pour inspecter, diagnostiquer et gérer le stockage dans Kubernetes — à garder sous la main.
> **Pre-requis** : `kubectl` configuré avec un contexte valide vers un cluster Kubernetes.

```bash
# === Lister/inspecter ===
kubectl get sc -o wide
# Liste les StorageClass : provisioner, reclaimPolicy, bindingMode, allowExpansion

kubectl get pv
# Liste les PersistentVolumes : capacité, modes d'accès, reclaim policy, statut, storageclass

kubectl get pvc -A
# Liste tous les PVC de tous les namespaces : statut, volume lié, capacité, storageclass

kubectl describe pvc <name> -n <ns>
# Détails complets d'un PVC + Events (indispensable pour le diagnostic)

kubectl get events -n <ns> --sort-by=.lastTimestamp | tail -n 30
# 30 derniers events du namespace, triés par timestamp (utile pour voir les erreurs récentes)

# === Trouver la StorageClass par défaut ===
kubectl get sc -o jsonpath='{range .items[*]}{.metadata.name}{" => default="}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\n"}{end}'
# Affiche chaque StorageClass avec son annotation is-default-class (true/false)

# === Redimensionner un PVC (expand) ===
kubectl patch pvc data -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'
# Augmente la demande de stockage du PVC "data" à 20Gi (le volume backend sera agrandi)

kubectl describe pvc data
# Vérifie les Conditions : FileSystemResizePending pendant l'extension du FS

# === Dans un Pod (vérifier montage) ===
kubectl exec -it <pod> -- sh -lc "df -hT /data && mount | grep /data && id && ls -l /data"
# df -hT : type de FS + taille ; mount : options de montage ; id : UID/GID courant ; ls -l : permissions

# === Debug kubelet (si accès hôte) ===
journalctl -u kubelet -f
# Logs en temps réel du kubelet : erreurs de montage, attach/detach, driver CSI
```

> **Résultat attendu** :
> ```
> Toutes les commandes ci-dessus fonctionnent sur un cluster Kubernetes opérationnel.
> Elles permettent de couvrir 90% des cas de diagnostic liés au stockage.
> ```
> **Vérification** : Tester chaque commande une par une pour s'assurer que le cluster répond correctement et que les informations affichées sont cohérentes avec l'état attendu.
