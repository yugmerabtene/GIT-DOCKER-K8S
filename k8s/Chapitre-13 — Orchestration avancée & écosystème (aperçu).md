# Chapitre 13 — Orchestration avancée & écosystème (aperçu **très opérationnel**)

*(Kubernetes en tant que plateforme : contrôleurs/CRDs/opérateurs, réseau L3→L7 & **Gateway API**/maillages, stockage CSI & **Stateful**, scheduling & autoscaling **HPA/VPA/KEDA/CA/Karpenter**, sécurité par politiques (**PSA, RBAC, OPA/Gatekeeper, Kyverno**), supply-chain, observabilité, multi-cluster, GitOps & progressive delivery, edge & platform engineering. Chaque bloc inclut des **exemples prêts à coller**.)*

---

## 0) Objectifs

* Comprendre **l'architecture déclarative** (boucle de réconciliation) et étendre l'API avec **CRD/Operators**.
* Maîtriser le **réseau** du pod au trafic L7 : CNI, **NetworkPolicy**, **Gateway API**, **Service Mesh**.
* Gérer **données & état** : CSI dynamiques, **StatefulSet**, snapshots & sauvegardes.
* Optimiser le **placement** et l'**autoscaling** du Pod **et** des Nœuds (HPA/VPA/KEDA/CA/Karpenter).
* Appliquer des **politiques de sécurité** (PSA/RBAC/OPA/Kyverno) & supply chain (signatures).
* Opérer en production : **observabilité**, **multi-cluster**, **GitOps**, **progressive delivery**.

---

## 1) Architecture avancée : contrôleurs, CRDs & opérateurs

### 1.1 Modèle de réconciliation

> **Objectif** : Illustrer la boucle de réconciliation déclarative de Kubernetes : le contrôleur compare en permanence l'état désiré (Spec) avec l'état observé (Status) et agit pour converger.
> **Pre-requis** : Aucun — ce schéma est conceptuel et s'applique à tout contrôleur Kubernetes (built-in ou custom).

```
# ┌─────────────────────────────────────────────────────────────────────┐
# │  BOUCLE DE RECONCILIATION                                           │
# │                                                                     │
# │  [Spec (déclarative)]  ──→  [Controller/Operator]  ──→  [Status]   │
# │         ↑                                                ↓          │
# │   kubectl/apply                              agit (create/update/   │
# │   (état désiré)                               delete ressources)   │
# │                                                                     │
# │  Le contrôleur observe la Spec, compare à la Status,               │
# │  puis crée/modifie/supprime des ressources pour converger.         │
# └─────────────────────────────────────────────────────────────────────┘
```

> **Resultat attendu** :
> ```
> Schéma conceptuel — pas de sortie exécutable.
> Flux : Spec → Controller → Status → (relecture Spec) → Controller → ...
> ```
> **Verification** : Comprendre que tout objet K8s suit ce cycle ; `kubectl describe` montre la Status, `kubectl get -o yaml` montre la Spec.

### 1.2 Étendre l'API : créer un CRD (extrait)

> **Objectif** : Créer une CustomResourceDefinition (CRD) qui étend l'API Kubernetes avec un nouveau type de ressource `Widget` (groupe `example.io`), avec un schéma de validation OpenAPI v3 limitant le champ `size` à "s", "m" ou "l".
> **Pre-requis** : Cluster Kubernetes v1.16+ (API `apiextensions.k8s.io/v1` disponible). Accès `kubectl` avec droits cluster-admin pour créer des CRD.

```yaml
apiVersion: apiextensions.k8s.io/v1       # API stable pour les CRD (depuis K8s 1.16)
kind: CustomResourceDefinition             # Type : définition de ressource personnalisée
metadata: { name: widgets.example.io }     # Nom = <pluriel>.<groupe>
spec:
  group: example.io                        # Groupe API (ex: example.io/v1)
  names: { plural: widgets, singular: widget, kind: Widget }  # Noms de la ressource
  scope: Namespaced                        # Portée namespace (vs Cluster)
  versions:
  - name: v1                               # Version de l'API (ex: v1, v1beta1)
    served: true                           # Cette version est servie par l'API server
    storage: true                          # Stockée dans etcd (une seule = true)
    schema:
      openAPIV3Schema:                     # Schéma de validation (comme un schema JSON)
        type: object
        properties:
          spec:
            type: object
            properties:
              size: { type: string, enum: ["s","m","l"] }  # Validation : seulement s/m/l
```

> **Resultat attendu** :
> ```
> customresourcedefinition.apiextensions.k8s.io/widgets.example.io created
> ```
> **Verification** : `kubectl get crd widgets.example.io` → doit afficher la CRD. `kubectl api-resources | grep widget` → doit lister `widgets`. On peut ensuite créer des objets : `kubectl apply -f widget.yaml`.

> Un **Operator** (Kubebuilder/Operator-SDK/Helm Operator) observe `Widget` et reconcilie des ressources natives (Deployments/Jobs/Secrets…).

---

## 2) Réseau & trafic applicatif (L3→L7)

### 2.1 CNI & NetworkPolicy (Calico/Cilium)

**NetworkPolicy** de base (deny-all, allow ingress du namespace `frontend`) :

> **Objectif** : Mettre en place une stratégie réseau en deux étapes : (1) un deny-all par défaut qui bloque tout trafic entrant/sortant pour tous les pods du namespace `app`, (2) une exception qui autorise uniquement le trafic ingress depuis le namespace `frontend` vers les pods `app: api` sur le port 8080.
> **Pre-requis** : Un CNI supportant les NetworkPolicy installé (Calico, Cilium, ou autre). Le namespace `app` et le namespace `frontend` (avec le label `name: frontend`) doivent exister.

```yaml
# === Politique 1 : DENY-ALL ===
# Bloque TOUT le trafic ingress et egress pour tous les pods du namespace 'app'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: api-deny-by-default, namespace: app }
spec:
  podSelector: {}                 # Sélectionne TOUS les pods du namespace (sélecteur vide)
  policyTypes: [Ingress, Egress]  # Active le filtrage dans les deux directions
  ingress: []                     # Liste ingress vide = AUCUN trafic entrant autorisé
---
# === Politique 2 : ALLOW FRONTEND ===
# Autorise uniquement le namespace 'frontend' à accéder aux pods 'app: api' sur le port 8080
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: api-allow-frontend, namespace: app }
spec:
  podSelector: { matchLabels: { app: api } }  # Cible uniquement les pods avec label app=api
  ingress:
  - from:
    - namespaceSelector: { matchLabels: { name: frontend } }  # Source : ns label name=frontend
    ports: [{ port: 8080, protocol: TCP }]                     # Port TCP 8080 uniquement
```

> **Resultat attendu** :
> ```
> networkpolicy.networking.k8s.io/api-deny-by-default created
> networkpolicy.networking.k8s.io/api-allow-frontend created
> ```
> **Verification** : `kubectl -n app get networkpolicy` → lister les 2 politiques. Tester depuis un pod du namespace `frontend` : `curl http://api:8080` → OK (200). Tester depuis un autre namespace : timeout/refusé.

### 2.2 **Gateway API** (remplace/étend Ingress)

**HTTPRoute** avec réécriture & canary par header :

> **Objectif** : Configurer un routage HTTP avancé via la Gateway API : (1) règle par défaut avec répartition canary 90/10 entre `api-stable` et `api-canary`, (2) règle conditionnelle qui envoie 100% du trafic vers `api-canary` si le header `x-exp: beta` est présent.
> **Pre-requis** : Gateway API CRDs installées (`kubectl kustomize "github.com/kubernetes-sigs/gateway-api/config/crd?ref=v1.0.0" | kubectl apply -f -`). Une ressource `Gateway` nommée `public-gw` dans le namespace `networking`. Les Services `api-stable` et `api-canary` doivent exister dans le namespace `app`.

```yaml
apiVersion: gateway.networking.k8s.io/v1   # API stable Gateway API (GA depuis v1.0)
kind: HTTPRoute                             # Ressource de routage HTTP (remplace Ingress)
metadata: { name: api-route, namespace: app }
spec:
  parentRefs: [{ name: public-gw, namespace: networking }]   # Référence la Gateway L7 existante
  hostnames: ["api.example.com"]                             # Domaine routé par cette route
  rules:
  # --- Règle 1 : Trafic par défaut (path /) avec canary pondéré ---
  - matches:
    - path: { type: PathPrefix, value: "/" }                 # Matche tous les chemins sous /
    filters:
    - type: URLRewrite                                       # Filtre : réécriture d'URL
      urlRewrite: { path: { replacePrefixMatch: "/" } }      # Garde le prefix / (pas de changement)
    backendRefs:
    - name: api-stable  # Service v1                         # Backend stable
      port: 8080
      weight: 90                                             # 90% du trafic vers stable
    - name: api-canary  # Service v2                         # Backend canary
      port: 8080
      weight: 10                                             # 10% du trafic vers canary
  # --- Règle 2 : Trafic ciblé par header (100% canary) ---
  - matches:
    - headers: [{ name: "x-exp", value: "beta" }]            # Matche header x-exp=beta
    backendRefs: [{ name: api-canary, port: 8080 }]          # 100% vers canary
```

> **Resultat attendu** :
> ```
> httproute.gateway.networking.k8s.io/api-route created
> ```
> **Verification** : `kubectl get httproute -n app` → statut `Accepted=True, ResolvedRefs=True`. `curl -H "Host: api.example.com" http://<gateway-ip>/` → 90% stable, 10% canary. `curl -H "Host: api.example.com" -H "x-exp: beta" http://<gateway-ip>/` → 100% canary.

### 2.3 **Service Mesh** (Istio/Linkerd/Cilium Mesh)

* mTLS **maillé**, retries, circuit-breaking, timeouts, **traffic-shifting** & A/B.
* **Istio VirtualService** (timeout & retry) :

> **Objectif** : Configurer via Istio un VirtualService qui ajoute des retries (3 tentatives, 1s chacune) et un timeout global de 5s pour le service `api`. Le mTLS est géré automatiquement par le mesh.
> **Pre-requis** : Istio installé (via `istioctl install` ou l'opérateur). Le namespace `app` doit avoir le label `istio-injection=enabled` pour l'injection automatique du sidecar Envoy. Le Service `api` doit exister dans `app`.

```yaml
apiVersion: networking.istio.io/v1          # API Istio pour le contrôle du trafic
kind: VirtualService                         # Définit les règles de routage L7
metadata: { name: api, namespace: app }
spec:
  hosts: ["api.app.svc.cluster.local"]      # FQDN du service cible dans le mesh
  http:
  - route: [{ destination: { host: api } }] # Route tout le trafic vers le service 'api'
    retries: { attempts: 3, perTryTimeout: 1s }  # 3 tentatives, 1s max par tentative
    timeout: 5s                                  # Timeout global de la requête
```

> **Resultat attendu** :
> ```
> virtualservice.networking.istio.io/api created
> ```
> **Verification** : `kubectl get virtualservice -n app` → doit afficher `api`. Vérifier les métriques Istio : `kubectl -n istio-system exec deploy/istiod -- pilot-discovery request GET /debug/config_distribution`. Kiali (`istioctl dashboard kiali`) montre le graphe de trafic avec les retries.

> Mesh ≠ obligatoire : évaluer coût/perf/ops vs besoins (mutual TLS, observabilité L7…).

---

## 3) Données & stockage (CSI, Stateful, sauvegarde)

### 3.1 Provisionnement dynamique (CSI)

Classe de stockage (ex. Retain & expansion) :

> **Objectif** : Définir une StorageClass nommée `fast-retain` qui utilise un driver CSI, conserve les volumes après suppression du PVC (`Retain`), permet l'expansion à chaud des volumes, et attend qu'un pod réclame le volume avant de le provisionner (`WaitForFirstConsumer`).
> **Pre-requis** : Un driver CSI installé et fonctionnel (ex: `csi.example.com`). Le driver doit supporter l'expansion de volume et le mode `WaitForFirstConsumer`.

```yaml
apiVersion: storage.k8s.io/v1              # API StorageClass (stable)
kind: StorageClass                          # Définit une "classe" de stockage pour le provisionnement dynamique
metadata: { name: fast-retain }            # Nom référencé dans les PVC/StatefulSet
provisioner: csi.example.com               # Driver CSI qui crée les volumes (à remplacer par le vrai driver)
allowVolumeExpansion: true                 # Permet d'agrandir un PVC existant (kubectl patch pvc ...)
reclaimPolicy: Retain                      # Le PV n'est PAS supprimé quand le PVC est supprimé (vs Delete)
volumeBindingMode: WaitForFirstConsumer    # Le volume n'est créé qu'au premier pod qui le monte
                                           # → permet au scheduler de choisir le bon nœud/zone AVANT le provisioning
```

> **Resultat attendu** :
> ```
> storageclass.storage.k8s.io/fast-retain created
> ```
> **Verification** : `kubectl get storageclass fast-retain` → afficher la SC. `kubectl get sc` → vérifier `fast-retain` avec `Retain` et `WaitForFirstConsumer`.

### 3.2 **StatefulSet** (identité stable + headless Service)

> **Objectif** : Déployer un StatefulSet PostgreSQL à 3 réplicas avec : (1) un Service headless (`clusterIP: None`) pour donner une identité réseau stable à chaque pod (`db-0.db`, `db-1.db`, etc.), (2) des PersistentVolumeClaims créés automatiquement via `volumeClaimTemplates` (50Gi chacun, StorageClass `fast-retain`).
> **Pre-requis** : La StorageClass `fast-retain` doit exister (voir 3.1). Le namespace `app` doit exister. Un provisionneur de stockage fonctionnel pour créer les PV dynamiquement.

```yaml
# === Service headless : pas de ClusterIP, DNS direct vers les pods ===
apiVersion: v1
kind: Service
metadata: { name: db, namespace: app }
spec:
  clusterIP: None                        # Headless : pas de VIP, DNS retourne les IPs des pods
  selector: { app: db }                  # Cible les pods avec label app=db
  ports: [{ name: psql, port: 5432 }]    # Port PostgreSQL
---
# === StatefulSet : pods ordonnés, identité stable, stockage persistant ===
apiVersion: apps/v1
kind: StatefulSet
metadata: { name: db, namespace: app }
spec:
  serviceName: db                        # Service headless associé (pour le DNS stable)
  replicas: 3                            # 3 instances PostgreSQL
  selector: { matchLabels: { app: db } }
  template:
    metadata: { labels: { app: db } }
    spec:
      containers:
      - name: postgres
        image: postgres:16               # Image PostgreSQL 16
        volumeMounts: [{ name: data, mountPath: /var/lib/postgresql/data }]  # Monte le PV sur /var/lib/...
  volumeClaimTemplates:                  # Template de PVC : un PVC par réplica (db-data-db-0, db-data-db-1, ...)
  - metadata: { name: data }
    spec:
      accessModes: ["ReadWriteOnce"]     # Un seul nœud peut monter le volume en R/W
      storageClassName: fast-retain      # Utilise la StorageClass définie en 3.1
      resources: { requests: { storage: 50Gi } }  # 50 GiB par instance
```

> **Resultat attendu** :
> ```
> service/db created
> statefulset.apps/db created
> ```
> **Verification** : `kubectl -n app get sts db` → `READY 3/3`. `kubectl -n app get pvc` → 3 PVCs : `data-db-0`, `data-db-1`, `data-db-2` (chacun 50Gi, Bound). `kubectl -n app get pods` → `db-0`, `db-1`, `db-2` démarrés dans l'ordre. DNS test : `nslookup db-0.db.app.svc.cluster.local`.

### 3.3 Snapshots & sauvegarde

**VolumeSnapshot** (+ CRD installé par le driver CSI) :

> **Objectif** : Créer un snapshot (instantané) du volume persistant `data-db-0` (le PVC du premier pod PostgreSQL du StatefulSet). Le snapshot utilise la classe `csi-snap` définie par le driver CSI.
> **Pre-requis** : Les CRDs VolumeSnapshot doivent être installées (`kubectl apply -k "github.com/kubernetes-csi/external-snapshotter/client/config/crd"`). Un `VolumeSnapshotClass` nommé `csi-snap` doit exister. Le PVC `data-db-0` dans le namespace `app` doit être `Bound`. Le driver CSI doit supporter les snapshots.

```yaml
apiVersion: snapshot.storage.k8s.io/v1   # API VolumeSnapshot (nécessite les CRDs snapshot)
kind: VolumeSnapshot                      # Crée un instantané d'un PVC existant
metadata: { name: db-snap-2025-11-02, namespace: app }  # Nom du snapshot (convention : nom-date)
spec:
  volumeSnapshotClassName: csi-snap      # Classe de snapshot (définie par le driver CSI)
  source: { persistentVolumeClaimName: data-db-0 }  # PVC source à snapshoter
```

> **Resultat attendu** :
> ```
> volumesnapshot.snapshot.storage.k8s.io/db-snap-2025-11-02 created
> ```
> **Verification** : `kubectl -n app get volumesnapshot` → `READYTOUSE: true`. Le snapshot peut être utilisé pour restaurer : créer un nouveau PVC avec `dataSource: { kind: VolumeSnapshot, name: db-snap-2025-11-02 }`.

Sauvegarde/restauration **Velero** : sauvegarder ressources + PV (backend S3).

---

## 4) Scheduling & Autoscaling avancés

### 4.1 Placement (affinités, taints, spread, priorité)

> **Objectif** : Configurer le placement avancé d'un Deployment : (1) priorité haute avec préemption, (2) affinité nœud obligatoire vers les nœuds `memory-optimized`, (3) anti-affinité pod préférée pour répartir sur des hôtes différents, (4) contrainte de topology spread pour équilibrer sur les zones.
> **Pre-requis** : Des nœuds avec le label `node-type=memory-optimized` doivent exister. La PriorityClass `critical-app` doit être créée (`kubectl apply -f priorityclass.yaml`). Le cluster doit avoir au moins 2 zones de disponibilité.

```yaml
spec:
  priorityClassName: critical-app     # Classe de priorité (permet la préemption de pods moins prioritaires)
  affinity:
    nodeAffinity:
      # Le pod NE PEUT se placer que sur les nœuds labelisés memory-optimized
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: node-type
            operator: In
            values: ["memory-optimized"]
    podAntiAffinity:
      # Préférer (pas obligatoire) de ne pas co-localiser avec d'autres pods 'app: api'
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100                   # Poids maximum pour cette préférence
        podAffinityTerm:
          topologyKey: kubernetes.io/hostname  # Clé : un pod par nœud (hostname)
          labelSelector: { matchLabels: { app: api } }  # Anti-affinité avec les pods app=api
  topologySpreadConstraints:
  - maxSkew: 1                        # Différence max de 1 pod entre les zones
    topologyKey: topology.kubernetes.io/zone  # Répartition par zone de disponibilité
    whenUnsatisfiable: DoNotSchedule  # Bloquer le scheduling si impossible (vs ScheduleAnyway)
    labelSelector: { matchLabels: { app: api } }
```

> **Resultat attendu** :
> ```
> Les pods sont schedulés sur des nœuds memory-optimized, répartis sur plusieurs hôtes et zones.
> ```
> **Verification** : `kubectl get pods -o wide` → vérifier que les pods sont sur des nœuds `memory-optimized`, sur des hôtes différents et répartis entre zones. `kubectl describe pod <name>` → section Events montre les contraintes de scheduling appliquées.

> **Taints/Tolerations** pour réserver des nœuds spécialisés (GPU, grande RAM).

### 4.2 Autoscaling des **Pods**

* **HPA v2** (Resource/Pods/External), **VPA** (recommandations/auto), **KEDA** (events SQS/Kafka/Prom).
  Ex. **HPA** multi-métriques :

> **Objectif** : Créer un HorizontalPodAutoscaler v2 qui scale le Deployment `api` entre 3 et 20 réplicas en fonction de deux métriques : (1) CPU moyen à 60%, (2) requêtes HTTP par seconde (métrique custom `http_rps`) à 50 req/s par pod. Inclut des fenêtres de stabilisation pour éviter le flap (60s pour scaleUp, 300s pour scaleDown).
> **Pre-requis** : Metrics Server installé (`kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml`). Pour la métrique custom `http_rps`, un adaptateur Prometheus (prometheus-adapter) doit être déployé et exposer cette métrique via l'API `custom.metrics.k8s.io`. Le Deployment `api` doit exister dans `app`.

```yaml
apiVersion: autoscaling/v2              # API HPA v2 (supporte multi-métriques)
kind: HorizontalPodAutoscaler
metadata: { name: api-hpa, namespace: app }
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: api }  # Cible du scaling
  minReplicas: 3                        # Minimum 3 pods (haute disponibilité)
  maxReplicas: 20                       # Maximum 20 pods (limite de coût)
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60    # Attendre 60s avant de scaler UP (évite les pics temporaires)
    scaleDown:
      stabilizationWindowSeconds: 300   # Attendre 5min avant de scaler DOWN (évite les oscillations)
  metrics:
  # Métrique 1 : CPU moyen
  - type: Resource
    resource: { name: cpu, target: { type: Utilization, averageUtilization: 60 } }  # Cible : 60% CPU
  # Métrique 2 : Requêtes HTTP/s (métrique custom via prometheus-adapter)
  - type: Pods
    pods:
      metric: { name: http_rps }        # Nom de la métrique custom exposée par l'adapter
      target: { type: AverageValue, averageValue: "50" }  # Cible : 50 req/s PAR pod
```

> **Resultat attendu** :
> ```
> horizontalpodautoscaler.autoscaling/api-hpa created
> ```
> **Verification** : `kubectl get hpa api-hpa -n app` → afficher `TARGETS` (ex: `45%/30`), `MINPODS: 3`, `MAXPODS: 20`, `REPLICAS`. `kubectl describe hpa api-hpa -n app` → voir les événements de scaling. Générer de la charge : `kubectl run load --image=busybox -- sh -c "while true; do wget -q -O- http://api:8080; done"` et observer le scale-up.

### 4.3 Autoscaling des **nœuds**

* **Cluster Autoscaler (CA)** (clouds managés) ou **Karpenter** (provisionneur dynamique).
  Ex. **Karpenter** (extrait) :

> **Objectif** : Définir un NodePool Karpenter nommé `spot-general` qui provisionne dynamiquement des nœuds spot (amd64 ou arm64) avec consolidation automatique (supprime les nœuds vides). Les nœuds ont un taint `workload=batch:NoSchedule` pour n'accepter que les pods tolérants.
> **Pre-requis** : Karpenter installé (Helm chart `oci://public.ecr.aws/karpenter/karpenter`). Un `EC2NodeClass` (AWS) ou équivalent cloud doit être configuré. Le controller IAM doit avoir les permissions pour lancer/terminer des instances.

```yaml
apiVersion: karpenter.sh/v1beta1        # API Karpenter v1beta1
kind: NodePool                           # Définit un pool de nœuds à provisionner dynamiquement
metadata: { name: spot-general }
spec:
  disruption: { consolidationPolicy: WhenEmpty }  # Supprime les nœuds quand ils n'ont plus de pods
  template:
    spec:
      requirements:
      - key: "kubernetes.io/arch"        # Architecture CPU autorisée
        operator: In
        values: ["amd64","arm64"]        # Accepte x86_64 ET ARM (pour les instances Graviton par ex.)
      taints: [{ key: "workload", value: "batch", effect: NoSchedule }]  # Taint : seuls les pods
                                                                           # avec toleration matching
                                                                           # peuvent se placer ici
```

> **Resultat attendu** :
> ```
> nodepool.karpenter.sh/spot-general created
> ```
> **Verification** : `kubectl get nodepool` → `spot-general`. Créer un pod avec la toleration `workload=batch:NoSchedule` et observer : `kubectl get nodes` → un nouveau nœud apparaît après ~30s. Supprimer le pod → le nœud est consolidé après le délai configuré.

---

## 5) Sécurité par politiques (PSA, RBAC, OPA/Gatekeeper, Kyverno)

### 5.1 **Pod Security Admission** (baseline/restricted)

Labels de namespace :

> **Objectif** : Activer le Pod Security Admission (PSA) en mode `restricted` sur le namespace `app` : les pods qui ne respectent pas le profil de sécurité `restricted` (pas de privileged, pas de root, drop ALL capabilities, etc.) seront rejetés, audités et un warning sera émis.
> **Pre-requis** : Kubernetes v1.23+ (PSA en GA). Le namespace `app` doit exister. Les pods existants dans `app` doivent être compatibles avec le profil `restricted` (sinon ils seront rejetés au prochain redémarrage).

```bash
# Applique 3 niveaux PSA sur le namespace 'app' :
# enforce  = rejette les pods non-conformes au profil 'restricted'
kubectl label ns app pod-security.kubernetes.io/enforce=restricted \
  # audit    = log les pods non-conformes (dans les événements d'audit)
  pod-security.kubernetes.io/audit=restricted \
  # warn     = affiche un avertissement à l'utilisateur lors du kubectl apply
  pod-security.kubernetes.io/warn=restricted
```

> **Resultat attendu** :
> ```
> namespace/app labeled
> ```
> **Verification** : `kubectl get ns app --show-labels` → vérifier les 3 labels `pod-security.kubernetes.io/*`. Tester avec un pod non-conforme : `kubectl run test --image=nginx --privileged -n app` → doit être rejeté avec un message détaillant les violations.

### 5.2 **RBAC** minimaliste

> **Objectif** : Créer un rôle `viewer` dans le namespace `app` qui permet uniquement la lecture (get/list/watch) des pods et services, puis lier ce rôle à l'utilisateur `alice` via un RoleBinding.
> **Pre-requis** : L'utilisateur `alice` doit être configuré dans le kubeconfig ou via un mécanisme d'authentification (OIDC, certificats, etc.). Le namespace `app` doit exister.

```yaml
# === Role : permissions dans un namespace spécifique ===
apiVersion: rbac.authorization.k8s.io/v1
kind: Role                                  # Role = permissions scopées à un namespace
metadata: { name: viewer, namespace: app }
rules:
- apiGroups: [""]   # core API group (pods, services, configmaps, etc.)
  resources: ["pods","services"]            # Ressources autorisées
  verbs: ["get","list","watch"]             # Actions : lecture seule (pas create/update/delete)
---
# === RoleBinding : associe le Role à un sujet (User/Group/ServiceAccount) ===
kind: RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
metadata: { name: viewer-binding, namespace: app }
subjects: [{ kind: User, name: alice }]     # Sujet : l'utilisateur 'alice'
roleRef: { kind: Role, name: viewer, apiGroup: rbac.authorization.k8s.io }  # Référence le Role 'viewer'
```

> **Resultat attendu** :
> ```
> role.rbac.authorization.k8s.io/viewer created
> rolebinding.rbac.authorization.k8s.io/viewer-binding created
> ```
> **Verification** : `kubectl auth can-i list pods -n app --as=alice` → `yes`. `kubectl auth can-i delete pods -n app --as=alice` → `no`. `kubectl auth can-i get secrets -n app --as=alice` → `no`.

### 5.3 **Gatekeeper (OPA)** — interdire `:latest`

**ConstraintTemplate** (Rego résumé) + **Constraint** :

> **Objectif** : Déployer une politique Gatekeeper (OPA) en deux étapes : (1) un ConstraintTemplate qui définit la logique Rego pour détecter les images utilisant le tag `:latest`, (2) une Constraint qui active cette politique sur tout le cluster. Tout pod avec une image `*:latest` sera rejeté à l'admission.
> **Pre-requis** : Gatekeeper installé (`kubectl apply -f https://raw.githubusercontent.com/open-policy-agent/gatekeeper/master/deploy/gatekeeper.yaml`). Le namespace `gatekeeper-system` doit être actif.

```yaml
# === Étape 1 : ConstraintTemplate (définit le type de contrainte + logique Rego) ===
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate                   # Template : définit un nouveau type de contrainte
metadata: { name: k8sdenylatest }
spec:
  crd:
    spec:
      names: { kind: K8sDenyLatest }      # Nom du type de contrainte (sera utilisé en étape 2)
  targets:
  - target: admission.k8s.gatekeeper.sh   # Cible : webhook d'admission K8s
    rego: |                                # Politique écrite en Rego (langage OPA)
      package k8sdenylatest
      violation[{"msg": msg}] {            # Règle : génère une violation si ...
        c := input.review.object.spec.template.spec.containers[_]  # ... un container ...
        endswith(c.image, ":latest")       # ... a une image se terminant par ":latest"
        msg := sprintf("image %v uses :latest", [c.image])  # Message d'erreur
      }
---
# === Étape 2 : Constraint (active le template sur le cluster) ===
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sDenyLatest                        # Instance de la contrainte définie ci-dessus
metadata: { name: deny-latest }
spec: {}                                   # spec vide = s'applique à tout le cluster (pas de filtre)
```

> **Resultat attendu** :
> ```
> constrainttemplate.templates.gatekeeper.sh/k8sdenylatest created
> k8sdenylatest.constraints.gatekeeper.sh/deny-latest created
> ```
> **Verification** : `kubectl get constrainttemplate` → `k8sdenylatest`. `kubectl get k8sdenylatest` → `deny-latest`. Tester : `kubectl run test --image=nginx:latest` → rejeté avec `image nginx:latest uses :latest`. `kubectl run test --image=nginx:1.25` → accepté.

### 5.4 **Kyverno** — exiger signatures **Cosign**

> **Objectif** : Créer une ClusterPolicy Kyverno qui impose la vérification de signature Cosign pour toutes les images provenant de `ghcr.io/acme/*`. Tout pod dont l'image n'est pas signée avec la clé publique spécifiée sera rejeté (mode `Enforce`).
> **Pre-requis** : Kyverno installé (`kubectl create -f https://raw.githubusercontent.com/kyverno/kyverno/main/config/install.yaml`). Une paire de clés Cosign générée (`cosign generate-key-pair`). Les images `ghcr.io/acme/*` doivent être signées avec la clé privée correspondante (`cosign sign --key cosign.key <image>`).

```yaml
apiVersion: kyverno.io/v1                 # API Kyverno v1
kind: ClusterPolicy                        # Politique scope cluster (tous les namespaces)
metadata: { name: require-image-signature }
spec:
  validationFailureAction: Enforce        # Mode strict : rejette les pods non-conformes (vs Audit)
  webhookTimeoutSeconds: 10               # Timeout du webhook d'admission
  rules:
  - name: verify-signature
    match: { any: [{ resources: { kinds: ["Pod"] } }] }  # S'applique à tous les Pods
    verifyImages:                          # Vérification de signature d'image
    - imageReferences: ["ghcr.io/acme/*"] # Pattern d'images à vérifier
      attestors:
      - entries:
        - keys:
            publicKeys: |                  # Clé publique Cosign (remplacer par la vraie clé)
              -----BEGIN PUBLIC KEY-----
              ...
              -----END PUBLIC KEY-----
```

> **Resultat attendu** :
> ```
> clusterpolicy.kyverno.io/require-image-signature created
> ```
> **Verification** : `kubectl get clusterpolicy` → `require-image-signature` avec `VALIDATE ACTION: Enforce`, `READY: true`. Tester avec une image non-signée : `kubectl run test --image=ghcr.io/acme/app:unsigned` → rejeté. Avec une image signée : accepté.

---

## 6) Supply chain & distribution (rappel rapide)

* Images **pinées par digest**, **labels OCI**, **SBOM** (Syft), **scan** (Trivy), **signatures** (Cosign).
* Registre interne (Harbor/GHCR/GitLab), **immutabilité** des tags prod, **GC** & rétention.
* Politiques d'admission (Gatekeeper/Kyverno) couplées aux signatures.

---

## 7) Observabilité & SRE

### 7.1 Stack de référence

* **Prometheus Operator** / kube-prometheus-stack (metrics), **Grafana** (dashboards),
* **Loki** (logs), **Tempo/Jaeger** (traces), **Alertmanager** (alertes).
* **eBPF** (Cilium/Hubble) pour la visibilité réseau L3/L4/L7.

**PodMonitor** (exemple) :

> **Objectif** : Créer un PodMonitor (ressource du Prometheus Operator) qui découvre automatiquement les pods avec le label `app: api` dans le namespace `app` et scrape leurs métriques sur le port `metrics` (chemin `/metrics`, toutes les 15 secondes).
> **Pre-requis** : Le Prometheus Operator (ou kube-prometheus-stack) doit être installé. Le port `metrics` doit être nommé dans le spec du container (ex: `ports: [{ name: metrics, containerPort: 9090 }]`). Le PodMonitor doit être créé dans le namespace `monitoring` (ou là où Prometheus est configuré pour chercher).

```yaml
apiVersion: monitoring.coreos.com/v1     # API du Prometheus Operator
kind: PodMonitor                          # Découvre des pods et configure le scraping Prometheus
metadata: { name: api, namespace: monitoring }  # Dans le namespace de Prometheus
spec:
  namespaceSelector: { matchNames: ["app"] }  # Surveille les pods du namespace 'app'
  selector: { matchLabels: { app: api } }     # Filtre : uniquement les pods label app=api
  podMetricsEndpoints:
  - port: metrics                         # Nom du port dans le container (pas le numéro !)
    path: /metrics                        # Chemin HTTP pour les métriques Prometheus
    interval: 15s                         # Fréquence de scraping : toutes les 15 secondes
```

> **Resultat attendu** :
> ```
> podmonitor.monitoring.coreos.com/api created
> ```
> **Verification** : `kubectl get podmonitor -n monitoring` → `api`. Ouvrir Prometheus (`kubectl port-forward -n monitoring svc/prometheus-k8s 9090`) → Status → Service Discovery → vérifier que les targets `app` sont découvertes. Graph : `http_requests_total{namespace="app"}`.

### 7.2 Bonnes pratiques SRE

* **SLO/SLI** publiés, **burn-rate** alerts, **runbooks** liés (`runbook_url`).
* Tests de **restauration** réguliers (Velero), **game days**.

---

## 8) Multi-cluster, fédération & provisioning

* **Cluster API** (CAPI) : déclaratif pour créer/mettre à jour des clusters.
* **Submariner/MCS API** : maillage réseau et découverte de services inter-clusters.
* **Argo CD ApplicationSet** : déployer une app sur **N** clusters (pattern "clusters generator").
* **Velero** : sauvegardes inter-clusters (DR), **RPO/RTO** documentés.

**ApplicationSet** (extrait) :

> **Objectif** : Déployer automatiquement l'application `api` sur tous les clusters enregistrés dans Argo CD ayant le label `env: prod`, via un ApplicationSet avec le générateur `clusters`. Chaque cluster reçoit sa propre Application Argo CD avec sync automatique, prune et self-heal.
> **Pre-requis** : Argo CD installé avec le composant ApplicationSet activé. Les clusters cibles doivent être enregistrés dans Argo CD (`argocd cluster add <context>`) avec le label `env=prod`. Le dépôt Git `https://github.com/acme/infra.git` doit contenir le chemin `envs/prod/helm/api`.

```yaml
apiVersion: argoproj.io/v1alpha1         # API Argo CD (alpha mais stable en pratique)
kind: ApplicationSet                      # Déploie N Applications à partir de générateurs
metadata: { name: api-fleet, namespace: argocd }
spec:
  generators:
  # Générateur 'clusters' : itère sur tous les clusters enregistrés dans Argo CD
  # qui matchent le sélecteur (label env=prod)
  - clusters: { selector: { matchLabels: { env: prod } } }
  template:
    metadata: { name: 'api-{{name}}' }   # Nom dynamique : api-<nom-du-cluster>
    spec:
      source:
        repoURL: https://github.com/acme/infra.git     # Dépôt Git source
        path: envs/prod/helm/api                       # Chemin vers les manifests Helm/Kustomize
        targetRevision: main                           # Branche Git
      destination:
        server: '{{server}}'              # URL du cluster (injectée par le générateur)
        namespace: app                    # Namespace cible sur chaque cluster
      syncPolicy:
        automated:
          prune: true                     # Supprime les ressources qui ne sont plus dans Git
          selfHeal: true                  # Re-sync si quelqu'un modifie manuellement le cluster
```

> **Resultat attendu** :
> ```
> applicationset.argoproj.io/api-fleet created
> ```
> **Verification** : `kubectl get applicationset -n argocd` → `api-fleet`. `kubectl get applications -n argocd` → une Application par cluster prod (ex: `api-cluster-prod-eu`, `api-cluster-prod-us`). Interface Argo CD : vérifier le statut `Synced` et `Healthy` pour chaque application.

---

## 9) Progressive delivery (sans mesh) : **Argo Rollouts**

Canary par **Rollout** (pondération & checks) :

> **Objectif** : Déployer l'application `api` via un Rollout Argo (alternative au Deployment) avec une stratégie canary progressive : 10% du trafic pendant 60s, puis 25% pendant 120s, avant de basculer complètement. L'image est pinée par digest SHA256 pour la reproductibilité.
> **Pre-requis** : Argo Rollouts installé (`kubectl create namespace argo-rollouts && kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml`). Le plugin kubectl argo rollouts (`kubectl argo rollouts`). Le Service `api` doit exister.

```yaml
apiVersion: argoproj.io/v1alpha1         # API Argo Rollouts
kind: Rollout                             # Remplace Deployment pour la progressive delivery
metadata: { name: api, namespace: app }
spec:
  replicas: 5                            # 5 réplicas au total
  strategy:
    canary:                              # Stratégie canary (progressive)
      steps:
      - setWeight: 10                    # Étape 1 : envoyer 10% du trafic sur la nouvelle version
      - pause: { duration: 60 }          # Étape 2 : pause de 60s pour observer les métriques
      - setWeight: 25                    # Étape 3 : augmenter à 25% du trafic
      - pause: { duration: 120 }         # Étape 4 : pause de 120s pour valider
                                         # (après : promotion automatique à 100%)
  selector: { matchLabels: { app: api } }
  template:
    metadata: { labels: { app: api } }
    spec:
      containers:
      - name: api
        image: ghcr.io/acme/api@sha256:ABCD...  # Image pinée par digest (pas de tag mutable)
```

> **Resultat attendu** :
> ```
> rollout.argoproj.io/api created
> ```
> **Verification** : `kubectl argo rollouts get rollout api -n app` → afficher le statut avec les étapes canary. `kubectl argo rollouts status api -n app` → `Healthy`. Pendant le déploiement : `kubectl argo rollouts status api -n app --watch` → observer la progression des étapes. En cas d'erreur : `kubectl argo rollouts abort api -n app` puis `kubectl argo rollouts undo api -n app`.

---

## 10) Edge, serverless & data

* **Edge** : K3s/k0s/MicroK8s, GitOps **pull** (faible connectivité), **Rancher Fleet** ou **ArgoCD**.
* **Serverless** : **Knative** (autoscaling scale-to-zero, révisions).
* **Batch/Workflow** : Argo Workflows/Tekton, **Spark on K8s**.
* **Messaging** : opérateurs **Kafka** (Strimzi), **RabbitMQ** Operator, **Pulsar**.

---

## 11) Platform Engineering & IDP

* **Backstage** (portail développeurs), templates "golden path", scaffolding.
* **Policies shift-left** : lint/validate (kubeconform, conftest), **OPA** en CI.
* Environnements **éphémères** par PR (ApplicationSet/Preview Envs).

---

## 12) Aide-mémoire (commandes & contrôles)

> **Objectif** : Fournir un aide-mémoire des commandes `kubectl` essentielles pour vérifier l'état de toutes les fonctionnalités abordées dans ce chapitre : politiques de sécurité, réseau, autoscaling, stockage stateful et observabilité.
> **Pre-requis** : `kubectl` configuré avec un contexte actif sur un cluster. Les composants respectifs (Gatekeeper, Gateway API, HPA, Karpenter, StatefulSet, Prometheus Operator) doivent être installés pour que les commandes retournent des résultats.

```bash
# ============ POLITIQUES ============
# Active le profil de sécurité 'restricted' sur le namespace 'app' (PSA)
kubectl label ns app pod-security.kubernetes.io/enforce=restricted
# Liste les webhooks d'admission (Gatekeeper, Kyverno, PSA)
kubectl get validatingwebhookconfigurations
# Vérifie si les ressources Gateway API sont disponibles (CRDs installées)
kubectl api-resources | grep -i gateway

# ============ RÉSEAU ============
# Liste toutes les Gateways et HTTPRoutes sur tous les namespaces
kubectl get gateway,httproute -A
# Liste les NetworkPolicies dans le namespace 'app'
kubectl -n app get networkpolicy
# Test de connectivité réseau : curl depuis un pod netshoot vers le service api
kubectl -n app run -it net --image=nicolaka/netshoot --rm -- curl -sS http://api:8080/healthz

# ============ AUTOSCALING ============
# Liste tous les HPA du cluster et détaille le HPA 'api-hpa' dans 'app'
kubectl get hpa -A ; kubectl describe hpa api-hpa -n app
# Liste les NodePools et Provisioners Karpenter (si CRDs présentes, sinon silently ignore)
kubectl get nodepool,provisioner -A 2>/dev/null || true   # Karpenter selon CRD

# ============ STATEFUL & STOCKAGE ============
# Liste StatefulSets, Services et PVCs dans le namespace 'app'
kubectl -n app get sts,svc,pvc
# Liste les VolumeSnapshots dans 'app' (nécessite les CRDs snapshot)
kubectl -n app get volumesnapshot

# ============ OBSERVABILITÉ ============
# Liste les ressources Prometheus/Grafana/Alertmanager dans le namespace 'monitoring'
kubectl -n monitoring get prometheus,grafana,alertmanager
# Affiche les 200 dernières lignes de logs de CoreDNS (debug DNS)
kubectl -n kube-system logs deploy/coredns --tail=200
```

> **Resultat attendu** :
> ```
> # Politiques :
> namespace/app labeled
> NAME                                      WEBHOOKS   AGE
> gatekeeper-validating-webhook-configuration   1        5d
>
> # Réseau :
> NAME          CLASS    ADDRESS         PROGRAMMED   AGE
> public-gw     <none>   10.96.0.100     True         3d
> NAME        HOSTNAME              AGE
> api-route   api.example.com       2d
>
> # Autoscaling :
> NAMESPACE   NAME      REFERENCE        TARGETS         MINPODS   MAXPODS   REPLICAS
> app         api-hpa   Deployment/api   45%/60%, 30/50   3         20        5
>
> # Stateful :
> NAME   READY   AGE
> db     3/3     1d
>
> # Observabilité :
> NAME         VERSION   REPLICAS   READY   AGE
> prometheus   v2.48.0   2          2       10d
> ```
> **Verification** : Chaque commande doit retourner des résultats cohérents avec les ressources déployées. Les `TARGETS` du HPA montrent les valeurs actuelles vs cibles. Les webhooks listés correspondent aux politiques installées (Gatekeeper/Kyverno).

---

### Conclusion

Cet aperçu positionne Kubernetes comme **plateforme** : une API extensible opérée par politiques, outillée de **GitOps**, maillée de **réseau L7**, reliée à un **stockage de niveau entreprise**, dimensionnée par **autoscaling multi-couche**, sécurisée par **admission/supply-chain**, et observable de bout en bout.
On peut approfondir chaque sous-domaine à la demande (ex. "**Service Mesh en prod**", "**Karpenter + coût**", "**Kyverno policies catalog**", "**Argo Rollouts + analyses automatiques**", "**Multi-cluster Submariner**", etc.).