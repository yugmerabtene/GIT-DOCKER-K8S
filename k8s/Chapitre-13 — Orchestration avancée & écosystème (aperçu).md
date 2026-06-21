# Chapitre 13 — Orchestration avancée & écosystème (aperçu **très opérationnel**)

*(Kubernetes en tant que plateforme : contrôleurs/CRDs/opérateurs, réseau L3→L7 & **Gateway API**/maillages, stockage CSI & **Stateful**, scheduling & autoscaling **HPA/VPA/KEDA/CA/Karpenter**, sécurité par politiques (**PSA, RBAC, OPA/Gatekeeper, Kyverno**), supply-chain, observabilité, multi-cluster, GitOps & progressive delivery, edge & platform engineering. Chaque bloc inclut des **exemples prêts à coller**.)*

---

## 0) Objectifs

* Comprendre **l’architecture déclarative** (boucle de réconciliation) et étendre l’API avec **CRD/Operators**.
* Maîtriser le **réseau** du pod au trafic L7 : CNI, **NetworkPolicy**, **Gateway API**, **Service Mesh**.
* Gérer **données & état** : CSI dynamiques, **StatefulSet**, snapshots & sauvegardes.
* Optimiser le **placement** et l’**autoscaling** du Pod **et** des Nœuds (HPA/VPA/KEDA/CA/Karpenter).
* Appliquer des **politiques de sécurité** (PSA/RBAC/OPA/Kyverno) & supply chain (signatures).
* Opérer en production : **observabilité**, **multi-cluster**, **GitOps**, **progressive delivery**.

---

## 1) Architecture avancée : contrôleurs, CRDs & opérateurs

### 1.1 Modèle de réconciliation

```
[Spec (déclarative)] → [Controller/Operator] → [Status (observée)]
          ↑                                  ↓
        kubectl/apply                  agit (create/update/delete)
```

### 1.2 Étendre l’API : créer un CRD (extrait)

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata: { name: widgets.example.io }
spec:
  group: example.io
  names: { plural: widgets, singular: widget, kind: Widget }
  scope: Namespaced
  versions:
  - name: v1
    served: true
    storage: true
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec:
            type: object
            properties:
              size: { type: string, enum: ["s","m","l"] }
```

> Un **Operator** (Kubebuilder/Operator-SDK/Helm Operator) observe `Widget` et reconcilie des ressources natives (Deployments/Jobs/Secrets…).

---

## 2) Réseau & trafic applicatif (L3→L7)

### 2.1 CNI & NetworkPolicy (Calico/Cilium)

**NetworkPolicy** de base (deny-all, allow ingress du namespace `frontend`) :

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: api-deny-by-default, namespace: app }
spec:
  podSelector: {}                 # tous les pods du ns
  policyTypes: [Ingress, Egress]
  ingress: []                     # deny-all
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: api-allow-frontend, namespace: app }
spec:
  podSelector: { matchLabels: { app: api } }
  ingress:
  - from:
    - namespaceSelector: { matchLabels: { name: frontend } }
    ports: [{ port: 8080, protocol: TCP }]
```

### 2.2 **Gateway API** (remplace/étend Ingress)

**HTTPRoute** avec réécriture & canary par header :

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata: { name: api-route, namespace: app }
spec:
  parentRefs: [{ name: public-gw, namespace: networking }]   # Gateway L7 existante
  hostnames: ["api.example.com"]
  rules:
  - matches:
    - path: { type: PathPrefix, value: "/" }
    filters:
    - type: URLRewrite
      urlRewrite: { path: { replacePrefixMatch: "/" } }
    backendRefs:
    - name: api-stable  # Service v1
      port: 8080
      weight: 90
    - name: api-canary  # Service v2
      port: 8080
      weight: 10
  - matches:
    - headers: [{ name: "x-exp", value: "beta" }]             # trafic ciblé
    backendRefs: [{ name: api-canary, port: 8080 }]
```

### 2.3 **Service Mesh** (Istio/Linkerd/Cilium Mesh)

* mTLS **maillé**, retries, circuit-breaking, timeouts, **traffic-shifting** & A/B.
* **Istio VirtualService** (timeout & retry) :

```yaml
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata: { name: api, namespace: app }
spec:
  hosts: ["api.app.svc.cluster.local"]
  http:
  - route: [{ destination: { host: api } }]
    retries: { attempts: 3, perTryTimeout: 1s }
    timeout: 5s
```

> Mesh ≠ obligatoire : évaluer coût/perf/ops vs besoins (mutual TLS, observabilité L7…).

---

## 3) Données & stockage (CSI, Stateful, sauvegarde)

### 3.1 Provisionnement dynamique (CSI)

Classe de stockage (ex. Retain & expansion) :

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata: { name: fast-retain }
provisioner: csi.example.com
allowVolumeExpansion: true
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
```

### 3.2 **StatefulSet** (identité stable + headless Service)

```yaml
apiVersion: v1
kind: Service
metadata: { name: db, namespace: app }
spec:
  clusterIP: None                        # headless
  selector: { app: db }
  ports: [{ name: psql, port: 5432 }]
---
apiVersion: apps/v1
kind: StatefulSet
metadata: { name: db, namespace: app }
spec:
  serviceName: db
  replicas: 3
  selector: { matchLabels: { app: db } }
  template:
    metadata: { labels: { app: db } }
    spec:
      containers:
      - name: postgres
        image: postgres:16
        volumeMounts: [{ name: data, mountPath: /var/lib/postgresql/data }]
  volumeClaimTemplates:
  - metadata: { name: data }
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: fast-retain
      resources: { requests: { storage: 50Gi } }
```

### 3.3 Snapshots & sauvegarde

**VolumeSnapshot** (+ CRD installé par le driver CSI) :

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata: { name: db-snap-2025-11-02, namespace: app }
spec:
  volumeSnapshotClassName: csi-snap
  source: { persistentVolumeClaimName: data-db-0 }
```

Sauvegarde/restauration **Velero** : sauvegarder ressources + PV (backend S3).

---

## 4) Scheduling & Autoscaling avancés

### 4.1 Placement (affinités, taints, spread, priorité)

```yaml
spec:
  priorityClassName: critical-app     # priorité & préemption
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: node-type
            operator: In
            values: ["memory-optimized"]
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          topologyKey: kubernetes.io/hostname
          labelSelector: { matchLabels: { app: api } }
  topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule
    labelSelector: { matchLabels: { app: api } }
```

> **Taints/Tolerations** pour réserver des nœuds spécialisés (GPU, grande RAM).

### 4.2 Autoscaling des **Pods**

* **HPA v2** (Resource/Pods/External), **VPA** (recommandations/auto), **KEDA** (events SQS/Kafka/Prom).
  Ex. **HPA** multi-métriques :

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: { name: api-hpa, namespace: app }
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: api }
  minReplicas: 3
  maxReplicas: 20
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
  metrics:
  - type: Resource
    resource: { name: cpu, target: { type: Utilization, averageUtilization: 60 } }
  - type: Pods
    pods:
      metric: { name: http_rps }
      target: { type: AverageValue, averageValue: "50" }
```

### 4.3 Autoscaling des **nœuds**

* **Cluster Autoscaler (CA)** (clouds managés) ou **Karpenter** (provisionneur dynamique).
  Ex. **Karpenter** (extrait) :

```yaml
apiVersion: karpenter.sh/v1beta1
kind: NodePool
metadata: { name: spot-general }
spec:
  disruption: { consolidationPolicy: WhenEmpty }
  template:
    spec:
      requirements:
      - key: "kubernetes.io/arch"
        operator: In
        values: ["amd64","arm64"]
      taints: [{ key: "workload", value: "batch", effect: NoSchedule }]
```

---

## 5) Sécurité par politiques (PSA, RBAC, OPA/Gatekeeper, Kyverno)

### 5.1 **Pod Security Admission** (baseline/restricted)

Labels de namespace :

```bash
kubectl label ns app pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/audit=restricted \
  pod-security.kubernetes.io/warn=restricted
```

### 5.2 **RBAC** minimaliste

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: { name: viewer, namespace: app }
rules:
- apiGroups: [""]   # core
  resources: ["pods","services"]
  verbs: ["get","list","watch"]
---
kind: RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
metadata: { name: viewer-binding, namespace: app }
subjects: [{ kind: User, name: alice }]
roleRef: { kind: Role, name: viewer, apiGroup: rbac.authorization.k8s.io }
```

### 5.3 **Gatekeeper (OPA)** — interdire `:latest`

**ConstraintTemplate** (Rego résumé) + **Constraint** :

```yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata: { name: k8sdenylatest }
spec:
  crd:
    spec:
      names: { kind: K8sDenyLatest }
  targets:
  - target: admission.k8s.gatekeeper.sh
    rego: |
      package k8sdenylatest
      violation[{"msg": msg}] {
        c := input.review.object.spec.template.spec.containers[_]
        endswith(c.image, ":latest")
        msg := sprintf("image %v uses :latest", [c.image])
      }
---
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sDenyLatest
metadata: { name: deny-latest }
spec: {}
```

### 5.4 **Kyverno** — exiger signatures **Cosign**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: require-image-signature }
spec:
  validationFailureAction: Enforce
  webhookTimeoutSeconds: 10
  rules:
  - name: verify-signature
    match: { any: [{ resources: { kinds: ["Pod"] } }] }
    verifyImages:
    - imageReferences: ["ghcr.io/acme/*"]
      attestors:
      - entries:
        - keys:
            publicKeys: |
              -----BEGIN PUBLIC KEY-----
              ...
              -----END PUBLIC KEY-----
```

---

## 6) Supply chain & distribution (rappel rapide)

* Images **pinées par digest**, **labels OCI**, **SBOM** (Syft), **scan** (Trivy), **signatures** (Cosign).
* Registre interne (Harbor/GHCR/GitLab), **immutabilité** des tags prod, **GC** & rétention.
* Politiques d’admission (Gatekeeper/Kyverno) couplées aux signatures.

---

## 7) Observabilité & SRE

### 7.1 Stack de référence

* **Prometheus Operator** / kube-prometheus-stack (metrics), **Grafana** (dashboards),
* **Loki** (logs), **Tempo/Jaeger** (traces), **Alertmanager** (alertes).
* **eBPF** (Cilium/Hubble) pour la visibilité réseau L3/L4/L7.

**PodMonitor** (exemple) :

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata: { name: api, namespace: monitoring }
spec:
  namespaceSelector: { matchNames: ["app"] }
  selector: { matchLabels: { app: api } }
  podMetricsEndpoints: [{ port: metrics, path: /metrics, interval: 15s }]
```

### 7.2 Bonnes pratiques SRE

* **SLO/SLI** publiés, **burn-rate** alerts, **runbooks** liés (`runbook_url`).
* Tests de **restauration** réguliers (Velero), **game days**.

---

## 8) Multi-cluster, fédération & provisioning

* **Cluster API** (CAPI) : déclaratif pour créer/mettre à jour des clusters.
* **Submariner/MCS API** : maillage réseau et découverte de services inter-clusters.
* **Argo CD ApplicationSet** : déployer une app sur **N** clusters (pattern “clusters generator”).
* **Velero** : sauvegardes inter-clusters (DR), **RPO/RTO** documentés.

**ApplicationSet** (extrait) :

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata: { name: api-fleet, namespace: argocd }
spec:
  generators:
  - clusters: { selector: { matchLabels: { env: prod } } }
  template:
    metadata: { name: 'api-{{name}}' }
    spec:
      source: { repoURL: https://github.com/acme/infra.git, path: envs/prod/helm/api, targetRevision: main }
      destination: { server: '{{server}}', namespace: app }
      syncPolicy: { automated: { prune: true, selfHeal: true } }
```

---

## 9) Progressive delivery (sans mesh) : **Argo Rollouts**

Canary par **Rollout** (pondération & checks) :

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata: { name: api, namespace: app }
spec:
  replicas: 5
  strategy:
    canary:
      steps:
      - setWeight: 10
      - pause: { duration: 60 }    # observation métriques
      - setWeight: 25
      - pause: { duration: 120 }
  selector: { matchLabels: { app: api } }
  template:
    metadata: { labels: { app: api } }
    spec:
      containers:
      - name: api
        image: ghcr.io/acme/api@sha256:ABCD...
```

---

## 10) Edge, serverless & data

* **Edge** : K3s/k0s/MicroK8s, GitOps **pull** (faible connectivité), **Rancher Fleet** ou **ArgoCD**.
* **Serverless** : **Knative** (autoscaling scale-to-zero, révisions).
* **Batch/Workflow** : Argo Workflows/Tekton, **Spark on K8s**.
* **Messaging** : opérateurs **Kafka** (Strimzi), **RabbitMQ** Operator, **Pulsar**.

---

## 11) Platform Engineering & IDP

* **Backstage** (portail développeurs), templates “golden path”, scaffolding.
* **Policies shift-left** : lint/validate (kubeconform, conftest), **OPA** en CI.
* Environnements **éphémères** par PR (ApplicationSet/Preview Envs).

---

## 12) Aide-mémoire (commandes & contrôles)

```bash
# Politiques
kubectl label ns app pod-security.kubernetes.io/enforce=restricted
kubectl get validatingwebhookconfigurations
kubectl api-resources | grep -i gateway

# Réseau
kubectl get gateway,httproute -A
kubectl -n app get networkpolicy
kubectl -n app run -it net --image=nicolaka/netshoot --rm -- curl -sS http://api:8080/healthz

# Autoscaling
kubectl get hpa -A ; kubectl describe hpa api-hpa -n app
kubectl get nodepool,provisioner -A 2>/dev/null || true   # Karpenter selon CRD

# Stateful & stockage
kubectl -n app get sts,svc,pvc
kubectl -n app get volumesnapshot

# Observabilité
kubectl -n monitoring get prometheus,grafana,alertmanager
kubectl -n kube-system logs deploy/coredns --tail=200
```

---

### Conclusion

Cet aperçu positionne Kubernetes comme **plateforme** : une API extensible opérée par politiques, outillée de **GitOps**, maillée de **réseau L7**, reliée à un **stockage de niveau entreprise**, dimensionnée par **autoscaling multi-couche**, sécurisée par **admission/supply-chain**, et observable de bout en bout.
On peut approfondir chaque sous-domaine à la demande (ex. “**Service Mesh en prod**”, “**Karpenter + coût**”, “**Kyverno policies catalog**”, “**Argo Rollouts + analyses automatiques**”, “**Multi-cluster Submariner**”, etc.).
