# Chapitre 8 — Sécurité & Politiques

*(AuthN/AuthZ & RBAC, ServiceAccounts, Pod Security Admission (PSA), politiques d’admission (Kyverno/Gatekeeper & ValidatingAdmissionPolicy), NetworkPolicies, quotas/LimitRanges, politiques d’images (Cosign), durcissement runtime (seccomp/AppArmor/SELinux), Audit API, runbooks. **Explications champ-par-champ** & **commandes détaillées**.)*

---

## 0) Préambule (méthode)

Pour chaque mécanisme de sécurité : 1) **Concept** → 2) **YAML** commenté → 3) **Commandes** & flags → 4) **Pièges** & diagnostics → 5) **Runbook** de correction.

---

## 1) Objectifs

* Mettre en place un **contrôle d’accès** robuste : **authentification** (certs/OIDC), **RBAC** minimaliste, **ServiceAccounts** dédiés.
* Appliquer des **garde-fous** : **Pod Security Admission (PSA)** + **politiques d’admission** (Kyverno/Gatekeeper, ValidatingAdmissionPolicy).
* Isoler **réseau** & **ressources** : **NetworkPolicies** défaut-deny + règles, **ResourceQuota/LimitRange**.
* Sécuriser la **supply-chain** : **scanner**, **signer** (Cosign), **vérifier** les images à l’admission (autoriser registres, interdire `:latest`, exiger digests).
* Durcir l’**exécution** : `securityContext` (non-root, RO rootfs), **seccomp/AppArmor/SELinux**, capabilities minimales.
* Activer la **traçabilité** : **Audit Policy** de l’API server, logs exploitables.

---

## 2) Carte des flux de contrôle

```
[AuthN utilisateurs / apps]
  → RBAC (Roles & Bindings)
    → Admission (PSA + Policies) 
      → Scheduler → Kubelet (runtime durci)
[Réseau]  CNI + NetworkPolicies
[Images]  Scan + Signature (Cosign) + Vérif à l’admission
[Audit]   API Audit Policy + SIEM
```

---

## 3) AuthN/OIDC & **RBAC**

### 3.1 ServiceAccount (SA) **dédié** (et pas de token auto)

```yaml
apiVersion: v1
kind: ServiceAccount
metadata: { name: app-sa, namespace: demo }
automountServiceAccountToken: false      # évite un token API inutile dans le Pod
```

### 3.2 RBAC minimal (namespace-scoped)

```yaml
# Rôle : lecture de ConfigMaps uniquement
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: { name: read-cm, namespace: demo }
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get","list","watch"]

---
# Liaison de rôle vers le SA
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: { name: rb-read-cm, namespace: demo }
subjects:
- kind: ServiceAccount
  name: app-sa
  namespace: demo
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: read-cm
```

**Vérifs & diagnostics**

```bash
# Simuler l’identité du SA (impersonation)
kubectl auth can-i get configmaps \
  --as=system:serviceaccount:demo:app-sa -n demo           # doit répondre yes
kubectl auth can-i get secrets \
  --as=system:serviceaccount:demo:app-sa -n demo           # doit répondre no

# Lister RBAC du namespace
kubectl get role,rolebinding -n demo -o wide
```

> **Pièges** : `ClusterRoleBinding` accordant trop de droits à *tous* les SA ; privilégier **Role/RoleBinding** dans un **namespace**.

---

## 4) **Pod Security Admission (PSA)** — baseline/risk/restricted

### 4.1 Activer PSA par **labels** sur le namespace

```bash
kubectl label ns prod \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/enforce-version=latest \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/audit=restricted --overwrite
```

* **enforce** : bloque les Pods non conformes au profil `restricted`.
* **warn/audit** : génère des messages sans blocage (phase d’adoption).

### 4.2 Effets clés du profil `restricted`

* **Interdits** : `privileged`, `hostNetwork/PID/IPC` (sauf cas très cadrés), montages **hostPath** non sûrs.
* **Exigés** : `runAsNonRoot: true`, **seccomp** `RuntimeDefault`, **capabilities** minimales, **readOnlyRootFilesystem** recommandé.

**Pod durci (extrait)**

```yaml
spec:
  automountServiceAccountToken: false
  securityContext:
    seccompProfile: { type: RuntimeDefault }
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
  containers:
  - name: app
    image: ghcr.io/acme/app:1.2.3
    securityContext:
      readOnlyRootFilesystem: true
      allowPrivilegeEscalation: false
      capabilities: { drop: ["ALL"] }
```

**Diagnostics**

```bash
kubectl -n prod get events --sort-by=.lastTimestamp | tail -n 20
kubectl describe ns prod | sed -n '/pod-security/p'
```

---

## 5) **Politiques d’admission** (Kyverno / Gatekeeper / Native CEL)

### 5.1 Kyverno — simple & lisible (validate/mutate/verifyImages)

**Interdire `hostPath` & conteneurs privilégiés**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: disallow-hostpath-privileged }
spec:
  validationFailureAction: Enforce
  rules:
  - name: no-hostpath
    match: { resources: { kinds: ["Pod"] } }
    validate:
      message: "hostPath interdit."
      pattern:
        spec:
          =(volumes):
            - X(hostPath): "null"
  - name: no-privileged
    match: { resources: { kinds: ["Pod"] } }
    validate:
      message: "Conteneurs privilégiés interdits."
      pattern:
        spec:
          containers:
          - =(securityContext):
              =(privileged): "false"
              =(allowPrivilegeEscalation): false
```

**Exiger seccomp & rootfs en lecture seule**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: require-seccomp-ro }
spec:
  validationFailureAction: Enforce
  rules:
  - name: require-seccomp
    match: { resources: { kinds: ["Pod"] } }
    validate:
      message: "Seccomp RuntimeDefault requis."
      pattern:
        spec:
          securityContext:
            seccompProfile: { type: "RuntimeDefault" }
  - name: ro-rootfs
    match: { resources: { kinds: ["Pod"] } }
    validate:
      message: "readOnlyRootFilesystem requis."
      pattern:
        spec:
          containers:
          - securityContext:
              readOnlyRootFilesystem: true
```

**Autoriser seulement certains registres + refuser `:latest`**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: allowed-registries-no-latest }
spec:
  validationFailureAction: Enforce
  rules:
  - name: only-ghcr-acme
    match: { resources: { kinds: ["Pod"] } }
    validate:
      message: "Seules les images ghcr.io/acme/* sont autorisées."
      pattern:
        spec:
          containers:
          - image: "ghcr.io/acme/*"
  - name: no-latest
    match: { resources: { kinds: ["Pod"] } }
    validate:
      message: "Tag :latest interdit. Utilisez un tag versionné ou un digest."
      deny:
        conditions:
        - key: "{{ images.containers[*].tag }}"
          operator: AnyIn
          value: ["latest", "dev", "stable"]
```

**Vérifier **signatures Cosign** (bloquer si non signées)**

```yaml
apiVersion: kyverno.io/v2
kind: ClusterPolicy
metadata: { name: verify-images }
spec:
  validationFailureAction: Enforce
  rules:
  - name: signed-by-acme
    match: { resources: { kinds: ["Pod"] } }
    verifyImages:
    - imageReferences: ["ghcr.io/acme/*"]
      attestors:
      - entries:
        - keys:
            publicKeys: |
              -----BEGIN PUBLIC KEY-----
              ...votre clef cosign...
              -----END PUBLIC KEY-----
```

**Commandes**

```bash
kubectl get cpol                       # ClusterPolicies Kyverno
kubectl get policyreport -A            # Rapports de conformité
kubectl describe cpol verify-images
```

### 5.2 Gatekeeper (OPA) — puissant & déclaratif (exemple minimal)

**ConstraintTemplate** (interdire hostNetwork)

```yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata: { name: k8sdenynethost }
spec:
  crd:
    spec:
      names:
        kind: K8sDenyNetHost
  targets:
  - target: admission.k8s.gatekeeper.sh
    rego: |
      package k8sdenynethost
      violation[{"msg": msg}] {
        input.review.kind.kind == "Pod"
        input.review.object.spec.hostNetwork == true
        msg := "hostNetwork interdit"
      }
```

**Constraint**

```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sDenyNetHost
metadata: { name: deny-hostnetwork }
spec: {}
```

### 5.3 ValidatingAdmissionPolicy (native, **CEL**)

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata: { name: require-nonroot }
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE","UPDATE"]
      resources: ["pods"]
  validations:
  - expression: "object.spec.securityContext.runAsNonRoot == true"
    message: "runAsNonRoot: true est requis."
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata: { name: require-nonroot-binding }
spec:
  policyName: require-nonroot
  validationActions: ["Deny"]
```

---

## 6) **NetworkPolicies** — défaut-deny + ouvertures ciblées

**Tout bloquer (Ingress & Egress)**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: default-deny-all, namespace: demo }
spec:
  podSelector: {}
  policyTypes: ["Ingress","Egress"]
```

**Autoriser web → api (Ingress)**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: allow-web-to-api, namespace: demo }
spec:
  podSelector: { matchLabels: { app.kubernetes.io/name: api } }
  ingress:
  - from:
    - podSelector: { matchLabels: { app.kubernetes.io/name: web } }
    ports: [ { protocol: TCP, port: 8080 } ]
```

**Autoriser egress DNS + DB**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: allow-egress-dns-db, namespace: demo }
spec:
  podSelector: { matchLabels: { app.kubernetes.io/name: api } }
  policyTypes: ["Egress"]
  egress:
  - to:
    - namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: kube-system } }
    ports: [ { protocol: UDP, port: 53 }, { protocol: TCP, port: 53 } ]
  - to:
    - podSelector: { matchLabels: { app.kubernetes.io/name: db } }
    ports: [ { protocol: TCP, port: 5432 } ]
```

**Commandes**

```bash
kubectl get netpol -n demo
kubectl describe netpol default-deny-all -n demo
```

> *Nécessite un CNI compatible NetPol (Calico/Cilium, …).*

---

## 7) **ResourceQuota** & **LimitRange** — éviter l’abus de ressources

**ResourceQuota**

```yaml
apiVersion: v1
kind: ResourceQuota
metadata: { name: rq, namespace: demo }
spec:
  hard:
    pods: "50"
    requests.cpu: "10"
    requests.memory: "20Gi"
    limits.cpu: "20"
    limits.memory: "40Gi"
    persistentvolumeclaims: "20"
    requests.storage: "200Gi"
```

**LimitRange (défauts/bornes par conteneur)**

```yaml
apiVersion: v1
kind: LimitRange
metadata: { name: lr, namespace: demo }
spec:
  limits:
  - type: Container
    defaultRequest: { cpu: "100m", memory: "128Mi" }
    default:        { cpu: "500m", memory: "512Mi" }
    max:            { cpu: "2",    memory: "2Gi" }
```

---

## 8) **Politiques d’images** (supply-chain)

### 8.1 Signature & vérification (Cosign)

```bash
# Signer (clé)
cosign sign --key cosign.key ghcr.io/acme/app:1.2.3

# Vérifier (CI/CD ou admission)
cosign verify --key cosign.pub ghcr.io/acme/app:1.2.3
```

### 8.2 Admission : **allow-list** registres, **interdire `:latest`**, **exiger digest**

* Kyverno `allowed-registries-no-latest` (ci-dessus).
* Variante : bloquer si image **sans digest** (`image: repo@sha256:...` préféré).

Exemple (exiger un **digest** sur toutes les images) :

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: require-digest }
spec:
  validationFailureAction: Enforce
  rules:
  - name: image-must-use-digest
    match: { resources: { kinds: ["Pod"] } }
    validate:
      message: "Les images doivent être référencées par digest (repo@sha256:...)."
      pattern:
        spec:
          containers:
          - image: "*@sha256:*"
```

---

## 9) Durcissement **runtime** (securityContext, seccomp, AppArmor, SELinux)

**Principes**

* **Non-root**, `readOnlyRootFilesystem`, **drop ALL capabilities**, **seccomp RuntimeDefault**.
* **Pas** de `hostPath`/`hostNetwork/PID/IPC` (sauf cas hyper cadrés).
* SA dédié, `automountServiceAccountToken: false`.

**Commandes de lecture/contrôle**

```bash
kubectl explain pod.spec.securityContext
kubectl explain pod.spec.containers.securityContext
kubectl get pod <p> -o yaml | yq '.spec.securityContext, .spec.containers[].securityContext'
```

---

## 10) **Audit de l’API server** — traçabilité sécurité

**Extrait de Policy (cible secrets & opérations sensibles)**

```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
- level: Metadata
  resources:
  - group: ""
    resources: ["pods","configmaps","secrets"]
- level: RequestResponse
  verbs: ["create","update","patch","delete","get","list","watch"]
  resources:
  - group: ""
    resources: ["secrets"]
```

**Drapeaux API server**

* `--audit-policy-file=/etc/kubernetes/audit-policy.yaml`
* `--audit-log-path=/var/log/kubernetes/audit.log`

Acheminer vers **SIEM** (ELK/Loki), corréler avec **Falco**.

---

## 11) Mini-labs (rapides)

### Lab A — Activer PSA + refuser un Pod non conforme

```bash
kubectl create ns secure && \
kubectl label ns secure pod-security.kubernetes.io/enforce=restricted --overwrite
kubectl -n secure run bad --image=alpine --overrides='{"spec":{"securityContext":{"runAsNonRoot":false}}}'
# Attendu : admission denied (PSA)
kubectl -n secure get events --sort-by=.lastTimestamp | tail -n 20
```

### Lab B — RBAC minimal + tests `kubectl auth can-i`

```bash
kubectl create ns demo
# (appliquer Role + RoleBinding + SA comme plus haut)
kubectl auth can-i list configmaps --as=system:serviceaccount:demo:app-sa -n demo  # yes
kubectl auth can-i get secrets     --as=system:serviceaccount:demo:app-sa -n demo  # no
```

### Lab C — NetPol défaut-deny + ouverture ciblée

```bash
# Appliquer default-deny-all puis allow-web-to-api et allow-egress-dns-db
kubectl -n demo get netpol
# Tester la connectivité depuis un pod netshoot
kubectl -n demo run -it test --image=nicolaka/netshoot --rm --restart=Never -- sh
```

### Lab D — Kyverno : bloquer `:latest`

```bash
# Appliquer la policy no-latest, puis:
kubectl -n demo run u1 --image=ghcr.io/acme/app:latest --restart=Never
# Attendu : denied
kubectl get events --sort-by=.lastTimestamp | tail -n 30
```

---

## 12) Runbooks (dépannage)

### 12.1 “**Refus PSA**”

```bash
kubectl -n <ns> get events --sort-by=.lastTimestamp | tail -n 20
kubectl describe ns <ns> | sed -n '/pod-security/p'
# Corriger securityContext (non-root, seccomp...), ou utiliser warn/audit en transition.
```

### 12.2 “**Denied par Kyverno/Gatekeeper**”

```bash
kubectl get events --sort-by=.lastTimestamp | tail -n 30
kubectl get cpol -A ; kubectl get policyreport -A
kubectl describe cpol allowed-registries-no-latest
# Adapter manifest selon message 'validate' de la policy.
```

### 12.3 “**RBAC : accès refusé**”

```bash
kubectl auth can-i get secrets --as=system:serviceaccount:demo:app-sa -n demo
kubectl get role,rolebinding -n demo -o wide
# Ajouter un Role ciblé ; éviter ClusterRoleBinding global.
```

### 12.4 “**Trafic bloqué (NetPol)**”

```bash
kubectl get netpol -n demo
kubectl describe netpol <name> -n demo
# Ajouter la règle manquante (DNS/DB/front), valider ports/protocoles exacts.
```

### 12.5 “**Image non signée / `:latest` interdit**”

* Lire l’event d’admission.
* **Signer** (Cosign) ou pousser une **version taggée**/digest.
* Re-déployer et **vérifier** avec `cosign verify`.

---

## 13) Bonnes pratiques (check-list)

* **Namespaces** par appli/env ; **PSA `restricted`** par défaut (warn/audit en montée de version).
* **RBAC minimal**, SA dédiés, `automountServiceAccountToken: false`.
* **securityContext** strict (non-root, RO rootfs, seccomp RuntimeDefault, drop ALL caps).
* **NetworkPolicies** : **défaut-deny** + ouvertures nécessaires (DNS/DB/monitoring).
* **Images** : scanner en CI, **signer** (Cosign), **vérifier à l’admission** ; interdire `:latest`, exiger **digest**.
* **Quotas/LimitRanges** : éviter l’abus de ressources ; PDB (disponibilité) si besoin.
* **Audit** activé (API) + logs expédiés au **SIEM** ; corrélation avec **Falco**.

---

## 14) Aide-mémoire (commandes)

```bash
# RBAC
kubectl auth can-i get configmaps --as=system:serviceaccount:demo:app-sa -n demo
kubectl get role,rolebinding -n demo -o wide

# PSA
kubectl label ns demo pod-security.kubernetes.io/enforce=restricted --overwrite
kubectl describe ns demo | sed -n '/pod-security/p'

# Kyverno / Gatekeeper
kubectl get cpol ; kubectl get policyreport -A
kubectl get constrainttemplates.constraints.gatekeeper.sh
kubectl get constraints -A

# ValidatingAdmissionPolicy
kubectl get validatingadmissionpolicy,validatingadmissionpolicybinding

# NetworkPolicies
kubectl get netpol -n demo
kubectl describe netpol default-deny-all -n demo

# Quotas & Limits
kubectl get resourcequota,limitrange -n demo
kubectl describe resourcequota rq -n demo

# Cosign (local)
cosign verify --key cosign.pub ghcr.io/acme/app:1.2.3

# Audit (API server)
ps aux | grep kube-apiserver | grep -- '--audit'
```
