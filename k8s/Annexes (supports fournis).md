# Annexes (supports fournis)

## 1) Glossaire Kubernetes (sélection essentielle)

* **Cluster** : ensemble nœuds + plan de contrôle (API Server, etcd, Scheduler, Controller-Manager).
* **Nœud (Node)** : machine (VM/physique) qui exécute les Pods (kubelet, runtime, kube-proxy).
* **Espace de noms (Namespace)** : partition logique d'isolement et de quotas.
* **Pod** : plus petite unité déployable ; 1..N conteneurs partageant réseau/IPC/volumes.
* **Container** : processus isolé packagé par une image OCI.
* **Image** : artefact OCI immuable (référence par digest `@sha256:...` recommandée).
* **Label / Annotation** : paires clé/valeur (sélection/organisation vs métadonnées non-indexées).
* **Selector** : requête sur labels (Services, Deployments, Policies, etc.).
* **Taint/Toleration** : mécanisme d'exclusion/réservation de nœuds.
* **Affinity/Anti-Affinity** : contraintes de placement (avec `topologyKey`).
* **QoS** : `Guaranteed`, `Burstable`, `BestEffort` selon requests/limits CPU/Mem.
* **Deployment** : contrôleur déclaratif pour Pods stateless (gère ReplicaSet & rollouts).
* **ReplicaSet** : maintient un nombre de Pods identiques (utilisé par Deployment).
* **StatefulSet** : Pods à identité stable + stockage persistant ordonné.
* **DaemonSet** : un Pod par nœud (logs/monitoring/agents).
* **Job / CronJob** : exécution finie / planifiée.
* **Service** : accès stable aux Pods (types : ClusterIP, NodePort, LoadBalancer, Headless).
* **EndpointSlice** : liste scalable des endpoints d'un Service.
* **Ingress** : exposition HTTP/HTTPS (L7) via un contrôleur (NGINX, Traefik…).
* **Gateway API** : évolution d'Ingress (objets Gateway/Route, fonctionnalités L7 avancées).
* **ConfigMap / Secret** : configuration non sensible / sensible.
* **Volume / PVC / PV / StorageClass** : stockage persistant, provisionnement CSI.
* **VolumeSnapshot** : snapshot de PV (via driver CSI).
* **CNI** : plugin réseau (Calico, Cilium…).
* **NetworkPolicy** : pare-feu L3/L4 inter-Pods (deny/allow).
* **RBAC** : droits (Role/ClusterRole) + liaisons (RoleBinding/ClusterRoleBinding).
* **ServiceAccount** : identité des Pods vis-à-vis de l'API ; token monté (désactivable).
* **PSA** : Pod Security Admission (niveaux `baseline`/`restricted`).
* **Admission (Validating/Mutating)** : garde-fous (OPA Gatekeeper, Kyverno, Sigstore).
* **Probes** : `liveness` (auto-heal), `readiness` (gating trafic), `startup` (grâce au boot).
* **HPA / VPA / KEDA** : autoscaling horizontal, vertical, par événements externes.
* **PDB** : PodDisruptionBudget (disponibilité lors d'évictions/rollouts).
* **PriorityClass** : priorité/preemption de Pods.
* **kube-proxy** : routage Service (iptables/ipvs).
* **Metrics Server** : source CPU/Mem pour `kubectl top` et HPA.

---

## 2) Cheat-sheet `kubectl` (opérations courantes)

### Base & affichage

> **Objectif** : Commandes de base pour vérifier la connexion au cluster, naviguer entre contextes, et afficher les ressources principales.
> **Pre-requis** : `kubectl` installé et configuré ; un fichier kubeconfig valide (`~/.kube/config`) ; accès à un cluster K8s.

```bash
# Affiche les versions du client kubectl et du serveur API (format court)
kubectl version --short                 # versions client/serveur
# Liste tous les contextes définis dans le kubeconfig (le courant est marqué *)
kubectl config get-contexts             # contextes Kubeconfig
# Bascule vers un contexte spécifique (change de cluster/namespace)
kubectl config use-context <ctx>        # bascule de contexte
# Liste tous les namespaces du cluster
kubectl get ns                          # namespaces
# Affiche Pods, Services et Deployments de tous les namespaces avec détails (IP, nœud)
kubectl get pod,svc,deploy -A -o wide   # vue rapide multi-ns
# Affiche toutes les ressources usuelles d'un namespace donné
kubectl get all -n <ns>                 # ressources usuelles d'un ns
# Affiche les détails complets d'un Pod + ses événements récents
kubectl describe pod/<name> -n <ns>     # détails + Events
# Affiche la documentation complète du schéma d'un champ Deployment (récursif)
kubectl explain deployment.spec.strategy --recursive  # documentation schéma
```

> **Résultat attendu** :
> ```
> Client Version: v1.28.0
> Server Version: v1.28.0
>
> NAME              CLUSTER    AUTHINFO         NAMESPACE
> * dev-cluster     dev        dev-admin        default
>   prod-cluster    prod       prod-admin       default
>
> NAME         STATUS   AGE
> default      Active   45d
> kube-system  Active   45d
> app          Active   30d
> ```
> **Vérification** : Les versions client/serveur doivent être compatibles (skew max ±1 minor version). Le contexte courant est marqué par `*`.

### Sélection & formats

> **Objectif** : Utiliser des sélecteurs (labels, champs) et des formats de sortie personnalisés (jsonpath) pour filtrer et extraire des informations précises.
> **Pre-requis** : `kubectl` configuré ; des Pods existants dans le namespace cible avec des labels définis.

```bash
# Sélectionne les Pods portant le label app=api dans le namespace donné
kubectl get pods -n <ns> -l app=api
# Sélectionne les Pods dont la phase N'EST PAS "Running" (ex: Pending, Failed)
kubectl get pods --field-selector=status.phase!=Running
# Extrait la classe QoS de tous les Pods via jsonpath (format personnalisé)
kubectl get pods -o jsonpath='{.items[*].status.qosClass}{"\n"}'
# Liste les 50 événements les plus récents du cluster, triés par timestamp
kubectl get events -A --sort-by=.lastTimestamp | tail -n 50
```

> **Résultat attendu** :
> ```
> NAME    READY   STATUS    RESTARTS   AGE   LABELS
> api-0   1/1     Running   0          2h    app=api
>
> Burstable BestEffort Guaranteed
>
> LAST SEEN   TYPE     REASON    OBJECT              MESSAGE
> 2m          Normal   Pulled    pod/api-0           Successfully pulled image
> 5m          Warning  BackOff   pod/worker-xyz      Back-off restarting failed
> ```
> **Vérification** : Les filtres doivent retourner uniquement les ressources correspondantes. Le jsonpath doit afficher une liste de classes QoS.

### Appliquer / valider / supprimer

> **Objectif** : Appliquer, visualiser le diff, ou supprimer des ressources K8s à partir de fichiers YAML ou de overlays Kustomize.
> **Pre-requis** : Des fichiers YAML valides (`deploy.yaml`) ou un répertoire Kustomize (`kustomize/overlays/prod`) ; droits d'écriture sur le namespace cible.

```bash
# Affiche les différences entre l'état actuel et le fichier (sans appliquer)
kubectl diff -f deploy.yaml                       # diff déclaratif
# Applique le fichier YAML (crée ou met à jour les ressources)
kubectl apply -f deploy.yaml                      # appliquer
# Supprime les ressources définies dans le fichier YAML
kubectl delete -f deploy.yaml                     # supprimer
# Applique un overlay Kustomize pour l'environnement de production
kubectl apply -k kustomize/overlays/prod          # Kustomize
```

> **Résultat attendu** :
> ```
> # diff :
> (aucune sortie si rien n'a changé, sinon diff unifié)
>
> # apply :
> deployment.apps/api configured
> service/api unchanged
>
> # apply -k :
> deployment.apps/api configured
> service/api configured
> configmap/api-config-abc123 created
> ```
> **Vérification** : `kubectl diff` ne doit montrer que les changements intentionnels. `kubectl apply` doit retourner le statut de chaque ressource (created/configured/unchanged).

### Rollout & scale

> **Objectif** : Gérer les déploiements : vérifier le statut, consulter l'historique, annuler un rollout, scaler le nombre de réplicas, ou changer l'image.
> **Pre-requis** : Un Deployment `api` existant dans le namespace `app` ; droits de modification sur le Deployment.

```bash
# Attend et affiche le statut du rollout (termine quand tous les Pods sont Ready)
kubectl rollout status deploy/api -n app
# Affiche l'historique des révisions du Deployment
kubectl rollout history deploy/api -n app
# Annule le dernier rollout et revient à la révision précédente
kubectl rollout undo deploy/api -n app
# Met à jour le nombre de réplicas à 5 (scale horizontal)
kubectl scale deploy/api -n app --replicas=5
# Change l'image du conteneur 'api' pour une version spécifique (par digest)
kubectl set image deploy/api api=repo@sha256:... -n app
```

> **Résultat attendu** :
> ```
# rollout status :
> deployment "api" successfully rolled out
>
> # rollout history :
> REVISION  CHANGE-CAUSE
> 1         Initial deploy
> 2         Update image to v1.4.2
> 3         Scale to 5 replicas
>
> # scale :
> deployment.apps/api scaled
>
> # set image :
> deployment.apps/api image updated
> ```
> **Vérification** : `kubectl rollout status` doit terminer avec "successfully rolled out". `kubectl get pods -n app` doit montrer le nombre de réplicas attendu.

### Logs / Exec / Port-forward

> **Objectif** : Accéder aux logs des conteneurs, ouvrir un shell interactif dans un Pod, ou créer un tunnel port-forward pour accéder à un service du cluster en local.
> **Pre-requis** : Un Pod en cours d'exécution dans le namespace `app` ; droits d'accès aux logs et exec sur le Pod.

```bash
# Affiche les 200 dernières lignes de logs du conteneur principal
kubectl logs pod/<name> -n app --tail=200
# Affiche les logs du conteneur précédent (après un crash/redémarrage)
kubectl logs pod/<name> -n app --previous         # crash précédent
# Ouvre un shell interactif (sh) dans le conteneur
kubectl exec -it pod/<name> -n app -- sh          # shell
# Redirige le port 8080 local vers le port 8080 du Service api dans le cluster
kubectl port-forward svc/api -n app 8080:8080     # local→cluster
```

> **Résultat attendu** :
> ```
> # logs :
> 2025-06-21T10:00:00Z INFO  Server started on :8080
> 2025-06-21T10:00:01Z INFO  Connected to database
> ...
>
> # exec :
> / $   (shell du conteneur)
>
> # port-forward :
> Forwarding from 127.0.0.1:8080 -> 8080
> Forwarding from [::1]:8080 -> 8080
> ```
> **Vérification** : Les logs doivent s'afficher en continu ou les N dernières lignes. `port-forward` : accéder à `http://localhost:8080` depuis le navigateur doit atteindre le service du cluster.

### Ressources & nœuds

> **Objectif** : Monitorer l'utilisation des ressources (CPU/Mémoire) et gérer la maintenance des nœuds (cordon, drain, uncordon).
> **Pre-requis** : Metrics Server installé sur le cluster (`kubectl top` fonctionne) ; droits admin pour les opérations sur les nœuds.

```bash
# Affiche l'utilisation CPU/Mémoire des nœuds et de tous les Pods
kubectl top nodes ; kubectl top pods -A
# Marque le nœud comme non-planifiable (plus de nouveaux Pods)
kubectl cordon <node> ; \
# Évacue tous les Pods du nœud (pour maintenance)
# --ignore-daemonsets : ne supprime pas les DaemonSets (inévitables par nœud)
# --delete-emptydir-data : supprime les volumes emptyDir (données perdues)
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
# Remet le nœud en service (re-planifiable)
kubectl uncordon <node>
```

> **Résultat attendu** :
> ```
> # top nodes :
> NAME     CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
> node-1   250m         12%    1024Mi          32%
> node-2   180m         9%     896Mi           28%
>
> # cordon :
> node/node-1 cordoned
>
> # drain :
> node/node-1 drained
>
> # uncordon :
> node/node-1 uncordoned
> ```
> **Vérification** : Après `cordon`, le nœud affiche `SchedulingDisabled`. Après `drain`, plus aucun Pod (sauf DaemonSets) ne tourne sur le nœud. Après `uncordon`, les nouveaux Pods peuvent être planifiés.

### Secrets / ConfigMap

> **Objectif** : Créer des Secrets et ConfigMaps depuis des valeurs littérales en ligne de commande, pour injecter configuration et données sensibles dans les Pods.
> **Pre-requis** : Namespace `app` existant ; droits de création de Secrets/ConfigMaps dans ce namespace.

```bash
# Crée un Secret générique avec des paires clé=valeur littérales
# Les valeurs sont encodées en base64 automatiquement par kubectl
kubectl create secret generic db-creds -n app \
  --from-literal=DB_USER=app --from-literal=DB_PASS='s3cret!'
# Crée une ConfigMap (données non sensibles) avec des paires clé=valeur
kubectl create configmap api-config -n app --from-literal=APP_ENV=prod
```

> **Résultat attendu** :
> ```
> secret/db-creds created
> configmap/api-config created
> ```
> **Vérification** : `kubectl get secret db-creds -n app -o yaml` doit montrer les données en base64. `kubectl get configmap api-config -n app -o yaml` doit montrer les données en clair. `kubectl describe secret db-creds -n app` affiche les clés sans les valeurs.

---

## 3) Modèles YAML (prêts à copier)

### 3.1 Deployment (stateless) + Probes + Ressources

> **Objectif** : Déployer une application stateless avec 3 réplicas, des probes de santé (readiness/liveness), des limites de ressources, et des bonnes pratiques de sécurité (non-root, seccomp, pas de token SA).
> **Pre-requis** : Namespace `app` existant ; ConfigMap `api-config` créée ; Secret `db-creds` créé ; l'image `ghcr.io/org/api@sha256:...` accessible.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api                      # nom du Deployment
  namespace: app                 # namespace cible
  labels: { app: api, tier: backend }  # labels pour identification et sélection
spec:
  replicas: 3                    # nombre de Pods souhaités
  revisionHistoryLimit: 5        # conserve 5 révisions pour rollback (par défaut 10)
  strategy:
    type: RollingUpdate          # mise à jour progressive (vs Recreate)
    rollingUpdate:
      maxSurge: 25%              # max Pods supplémentaires pendant le rollout (au-dessus de replicas)
      maxUnavailable: 0          # aucun Pod indisponible pendant le rollout (zéro downtime)
  selector:
    matchLabels: { app: api }   # sélectionne les Pods avec ce label
  template:                      # template du Pod (spec des Pods créés)
    metadata:
      labels: { app: api, tier: backend }  # labels appliqués aux Pods
    spec:
      automountServiceAccountToken: false  # désactive le montage auto du token SA (sécurité)
      securityContext:
        runAsNonRoot: true                  # exige un utilisateur non-root
        seccompProfile: { type: RuntimeDefault }  # profil seccomp par défaut du runtime
      containers:
      - name: api                            # nom du conteneur
        image: ghcr.io/org/api@sha256:REPLACER_ME  # image par digest (immuable) — remplacer le digest
        imagePullPolicy: IfNotPresent        # pull seulement si l'image n'est pas en local
        ports: [ { name: http, containerPort: 8080 } ]  # port exposé (nommé pour référence)
        envFrom:
          - configMapRef: { name: api-config }  # injecte toutes les clés de la ConfigMap comme env vars
        env:
          - name: DB_USER
            valueFrom: { secretKeyRef: { name: db-creds, key: DB_USER } }  # injecte DB_USER depuis le Secret
          - name: DB_PASS
            valueFrom: { secretKeyRef: { name: db-creds, key: DB_PASS } }  # injecte DB_PASS depuis le Secret
        resources:
          requests: { cpu: "200m", memory: "256Mi" }  # ressources minimales garanties (scheduling)
          limits:   { cpu: "1",    memory: "512Mi" }   # ressources maximales (au-delà = throttle/OOM kill)
        readinessProbe:
          httpGet: { path: /healthz, port: http }  # vérifie /healthz pour accepter du trafic
          periodSeconds: 5                          # vérifie toutes les 5 secondes
        livenessProbe:
          httpGet: { path: /livez, port: http }    # vérifie /livez pour détecter les crashes
          initialDelaySeconds: 15                   # attend 15s avant la première vérification
          periodSeconds: 10                         # vérifie toutes les 10 secondes
```

> **Résultat attendu** :
> ```
> deployment.apps/api created
>
> kubectl get deploy api -n app:
> NAME   READY   UP-TO-DATE   AVAILABLE   AGE
> api    3/3     3            3           30s
>
> kubectl get pods -n app:
> NAME                   READY   STATUS    RESTARTS   AGE
> api-6d4f5b6c7-abc12   1/1     Running   0          30s
> api-6d4f5b6c7-def34   1/1     Running   0          30s
> api-6d4f5b6c7-ghi56   1/1     Running   0          30s
> ```
> **Vérification** : Les 3 Pods doivent être `Running` et `READY 1/1`. `kubectl describe pod` doit montrer les probes et les resource requests/limits. `curl http://<pod-ip>:8080/healthz` doit retourner 200.

### 3.2 Service (ClusterIP) + Headless (si besoin)

> **Objectif** : Créer un Service ClusterIP pour exposer l'API en interne au cluster, et un Service Headless (clusterIP: None) pour la découverte DNS granulaire (chaque Pod a son propre enregistrement DNS).
> **Pre-requis** : Des Pods avec le label `app: api` existants dans le namespace `app`.

```yaml
# === Service ClusterIP (standard) ===
# Expose les Pods via une IP virtuelle unique (load-balancing interne)
apiVersion: v1
kind: Service
metadata:
  name: api                    # nom du Service (utilisé pour le DNS: api.app.svc.cluster.local)
  namespace: app
  labels: { app: api }
spec:
  type: ClusterIP              # type par défaut : accessible uniquement dans le cluster
  selector: { app: api }      # sélectionne les Pods cible via le label
  ports:
    - name: http               # nom du port (référençable dans Ingress, etc.)
      port: 8080               # port exposé par le Service
      targetPort: http         # port cible sur le Pod (référence au port nommé "http")
---
# === Service Headless (découverte DNS granulaire) ===
# clusterIP: None → pas d'IP virtuelle ; DNS retourne directement les IPs des Pods
# Utile pour StatefulSets ou discovery personnalisé (ex: clients qui gèrent le load-balancing)
apiVersion: v1
kind: Service
metadata: { name: api-headless, namespace: app, labels: { app: api } }
spec:
  clusterIP: None              # headless : pas de ClusterIP, DNS direct vers les Pods
  selector: { app: api }      # mêmes Pods cible que le Service standard
  ports: [ { name: http, port: 8080, targetPort: http } ]
```

> **Résultat attendu** :
> ```
> service/api created
> service/api-headless created
>
> kubectl get svc -n app:
> NAME           TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)    AGE
> api            ClusterIP   10.96.45.123   <none>        8080/TCP   5s
> api-headless   ClusterIP   None           <none>        8080/TCP   5s
> ```
> **Vérification** : `nslookup api.app.svc.cluster.local` doit retourner le ClusterIP. `nslookup api-headless.app.svc.cluster.local` doit retourner les IPs de chaque Pod.

### 3.3 Ingress (NGINX)

> **Objectif** : Exposer le service API en HTTP/HTTPS depuis l'extérieur du cluster via un Ingress NGINX, avec terminaison TLS et annotations de configuration (taille body, timeout).
> **Pre-requis** : Contrôleur Ingress NGINX installé sur le cluster ; le Service `api` existant sur le port 8080 ; le Secret `api-tls` contenant le certificat TLS ; le DNS `api.example.com` pointant vers l'IP du contrôleur Ingress.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api                      # nom de l'Ingress
  namespace: app
  annotations:
    # Taille max du corps de requête acceptée (évite les erreurs 413)
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    # Timeout de lecture du backend (secondes)
    nginx.ingress.kubernetes.io/proxy-read-timeout: "30"
spec:
  ingressClassName: nginx        # classe d'Ingress (identifie le contrôleur NGINX)
  rules:
    - host: api.example.com      # nom de domaine routé
      http:
        paths:
          - path: /              # chemin (ici, tout le domaine)
            pathType: Prefix     # type de matching (Prefix, Exact, ImplementationSpecific)
            backend:
              service:
                name: api        # nom du Service cible
                port: { number: 8080 }  # port du Service cible
  tls:
    - hosts: [ api.example.com ]       # domaines couverts par le certificat
      secretName: api-tls              # Secret contenant le certificat TLS (cert + key)
```

> **Résultat attendu** :
> ```
> ingress.networking.k8s.io/api created
>
> kubectl get ingress -n app:
> NAME   CLASS   HOSTS               ADDRESS        PORTS     AGE
> api    nginx   api.example.com     203.0.113.50   80, 443   10s
> ```
> **Vérification** : `curl -k https://api.example.com` doit retourner une réponse de l'API. `kubectl describe ingress api -n app` doit montrer les règles TLS et le backend.

### 3.4 PVC + StorageClass

> **Objectif** : Définir une StorageClass pour le provisionnement dynamique de volumes persistants (avec politique de rétention et binding différé), puis créer un PersistentVolumeClaim qui demande 10Gi de stockage.
> **Pre-requis** : Un driver CSI installé sur le cluster (`csi.example.com`) ; droits de création de StorageClass (admin) ; droits de création de PVC dans le namespace `app`.

```yaml
# === StorageClass : définit comment les volumes sont provisionnés ===
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata: { name: fast-retain }    # nom de la StorageClass
provisioner: csi.example.com       # driver CSI qui provisionne les volumes
allowVolumeExpansion: true         # permet l'extension à chaud des volumes (resize)
reclaimPolicy: Retain              # conserve le PV après suppression du PVC (vs Delete)
volumeBindingMode: WaitForFirstConsumer  # attend qu'un Pod utilise le PVC avant de provisionner
                                       # (évite le binding prématuré sur un mauvais nœud/zone)
---
# === PersistentVolumeClaim : demande de stockage ===
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-api                   # nom du PVC (référencé dans les Pods)
  namespace: app
spec:
  accessModes: ["ReadWriteOnce"]   # monté en lecture/écriture par un seul nœud
  storageClassName: fast-retain    # utilise la StorageClass définie ci-dessus
  resources:
    requests: { storage: 10Gi }    # demande 10 Gio d'espace stockage
```

> **Résultat attendu** :
> ```
> storageclass.storage.k8s.io/fast-retain created
> persistentvolumeclaim/data-api created
>
> kubectl get pvc -n app:
> NAME       STATUS    VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS    AGE
> data-api   Pending                                      fast-retain     5s
> # (Pending car WaitForFirstConsumer — sera Bound quand un Pod l'utilisera)
> ```
> **Vérification** : `kubectl get sc` doit lister `fast-retain`. Le PVC sera `Pending` jusqu'à ce qu'un Pod le consomme, puis passera à `Bound`.

### 3.5 StatefulSet (avec Service headless)

> **Objectif** : Déployer une base de données PostgreSQL en StatefulSet avec 3 réplicas, chaque Pod ayant une identité stable (db-0, db-1, db-2) et son propre volume persistant via volumeClaimTemplates.
> **Pre-requis** : Le Service headless `db` (ci-dessous) ; la StorageClass `fast-retain` existante ; l'image `postgres:16` accessible.

```yaml
# === Service Headless requis par le StatefulSet ===
# Le StatefulSet utilise ce Service pour la découverte DNS stable des Pods
# Chaque Pod aura un DNS : db-0.db.app.svc.cluster.local, db-1.db..., etc.
apiVersion: v1
kind: Service
metadata: { name: db, namespace: app }
spec:
  clusterIP: None                # headless : DNS direct vers chaque Pod
  selector: { app: db }         # sélectionne les Pods du StatefulSet
  ports: [ { name: psql, port: 5432 } ]  # port PostgreSQL
---
# === StatefulSet : Pods à identité stable + stockage persistant ===
apiVersion: apps/v1
kind: StatefulSet
metadata: { name: db, namespace: app }
spec:
  serviceName: db                # nom du Service headless (obligatoire pour StatefulSet)
  replicas: 3                    # 3 instances PostgreSQL (db-0, db-1, db-2)
  selector: { matchLabels: { app: db } }
  template:
    metadata: { labels: { app: db } }
    spec:
      containers:
      - name: postgres
        image: postgres:16               # image PostgreSQL 16
        ports: [ { name: psql, containerPort: 5432 } ]
        volumeMounts:
        - name: data                     # nom du volume (lié au volumeClaimTemplate)
          mountPath: /var/lib/postgresql/data  # chemin de données PostgreSQL
  volumeClaimTemplates:                  # crée un PVC par réplica (data-db-0, data-db-1, etc.)
  - metadata: { name: data }
    spec:
      accessModes: ["ReadWriteOnce"]     # chaque volume est monté par un seul Pod
      storageClassName: fast-retain      # StorageClass pour le provisionnement
      resources: { requests: { storage: 50Gi } }  # 50Gi par instance
```

> **Résultat attendu** :
> ```
> service/db created
> statefulset.apps/db created
>
> kubectl get sts -n app:
> NAME   READY   AGE
> db     3/3     45s
>
> kubectl get pods -n app:
> NAME    READY   STATUS    RESTARTS   AGE
> db-0    1/1     Running   0          45s
> db-1    1/1     Running   0          30s
> db-2    1/1     Running   0          15s
>
> kubectl get pvc -n app:
> NAME         STATUS   VOLUME         CAPACITY   STORAGECLASS
> data-db-0    Bound    pvc-abc123     50Gi       fast-retain
> data-db-1    Bound    pvc-def456     50Gi       fast-retain
> data-db-2    Bound    pvc-ghi789     50Gi       fast-retain
> ```
> **Vérification** : Chaque Pod doit avoir un nom stable (db-0, db-1, db-2). `nslookup db-0.db.app.svc.cluster.local` doit résoudre. Chaque Pod doit avoir son propre PVC lié.

### 3.6 NetworkPolicy (deny-all + allow front→api)

> **Objectif** : Appliquer le principe "deny-all" dans le namespace `app` (tout le trafic est bloqué par défaut), puis créer une règle explicite autorisant uniquement le namespace `frontend` à accéder à l'API sur le port 8080.
> **Pre-requis** : Un CNI supportant les NetworkPolicy installé (Calico, Cilium, etc.) ; le namespace `app` avec des Pods `app: api` ; le namespace `frontend` avec le label `name: frontend`.

```yaml
# === Policy 1 : Deny-All (bloque tout le trafic entrant et sortant) ===
# Par défaut : tout bloquer dans le ns "app"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: default-deny, namespace: app }
spec:
  podSelector: {}                # s'applique à tous les Pods du namespace
  policyTypes: [Ingress, Egress] # bloque à la fois le trafic entrant ET sortant
                                 # aucune règle ingress/egress = tout est refusé

---
# === Policy 2 : Allow front→api (autorise le frontend à joindre l'API) ===
# Autoriser le frontend (ns=frontend) à joindre l'API sur 8080
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: allow-frontend-to-api, namespace: app }
spec:
  podSelector:
    matchLabels: { app: api }   # s'applique uniquement aux Pods API
  ingress:
  - from:
    - namespaceSelector:
        matchLabels: { name: frontend }  # source autorisée : namespace avec label name=frontend
    ports: [ { protocol: TCP, port: 8080 } ]  # uniquement sur le port TCP 8080
```

> **Résultat attendu** :
> ```
> networkpolicy.networking.k8s.io/default-deny created
> networkpolicy.networking.k8s.io/allow-frontend-to-api created
>
> kubectl get networkpolicy -n app:
> NAME                    POD-SELECTOR   AGE
> allow-frontend-to-api   app=api        5s
> default-deny            <none>         5s
> ```
> **Vérification** : Depuis un Pod du namespace `frontend`, `curl http://api.app.svc:8080` doit fonctionner. Depuis un Pod d'un autre namespace (ex: `backend`), la connexion doit être bloquée (timeout). Tester avec `kubectl exec` depuis différents namespaces.

---

## 4) Checklists (sécurité, release, incident)

### 4.1 Sécurité (avant mise en prod)

* [ ] **Images** : base pinée par **digest** ; **pas de `:latest`** ; labels OCI complets.
* [ ] **User** : `runAsNonRoot`, UID dédié ; `readOnlyRootFilesystem` si possible.
* [ ] **Capabilities** : `drop: ["ALL"]` puis ajouter au besoin (pas de `NET_ADMIN`/`SYS_ADMIN` par défaut).
* [ ] **Seccomp/AppArmor/SELinux** : `seccompProfile: RuntimeDefault` (ou profil strict).
* [ ] **ServiceAccount** : minimal ; `automountServiceAccountToken: false` si inutile.
* [ ] **Secrets** : montés en **fichiers** ; rotation documentée ; jamais en clair dans l'image.
* [ ] **Réseau** : `NetworkPolicy` deny-all + règles explicites ; egress contrôlé.
* [ ] **Ressources** : requests/limits posés ; PDB présent ; probes correctes.
* [ ] **Supply-chain** : SBOM générée ; **Trivy** bloquant ; **Cosign** signature ; policies d'admission (digest + signature).
* [ ] **Audit** : logs cluster/registre centralisés ; traces d'accès & de changement.

### 4.2 Release (qualité & traçabilité)

* [ ] **Versionning** SemVer ; release tag `vX.Y.Z`.
* [ ] **CI** : build multi-arch, tests unit/int, scan, SBOM, signature passés.
* [ ] **Artefact** : digest enregistré ; chart Helm validé (`helm lint`, `kubeconform`).
* [ ] **Stratégie** : Rolling (`maxUnavailable=0`) ou Blue-Green/Canary documentée.
* [ ] **Migrations** : hooks Helm `pre-install/upgrade` idempotents.
* [ ] **Observabilité** : dashboards, alertes, logs/trace prêts ; smoke test post-deploy.
* [ ] **Rollback** : procédure testée (`helm rollback` ou GitOps revert).
* [ ] **CHANGELOG** : notes livrées + risques connus.

### 4.3 Incident (triage & réponse)

* [ ] **Détection** : alerte → classer severité ; assigner responsable (astreinte).
* [ ] **Triage 5–10 min** : `kubectl get events -A`, `top`, état ns/app, endpoints/probes.
* [ ] **Classes** : Image/Pull, Crash/OOM, Pending/Scheduling, Réseau/DNS, PV/Permissions, Ingress/LB, Policies.
* [ ] **Confinement** : réduire trafic (canary→0), basculer Service (blue→green), rollback.
* [ ] **Collecte preuves** : logs (`--previous`), events, manifest rendu, horodatage NTP.
* [ ] **Communication** : statut interne/externe, ticketing, time-line.
* [ ] **Remédiation** : correctif, tests, remise en service contrôlée.
* [ ] **Post-mortem** : cause racine, actions durables (policies, tests, alertes), échéances suivies.
