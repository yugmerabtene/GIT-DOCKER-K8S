# Chapitre 8 — Sécurité & Politiques

*(AuthN/AuthZ & RBAC, ServiceAccounts, Pod Security Admission (PSA), politiques d'admission (Kyverno/Gatekeeper & ValidatingAdmissionPolicy), NetworkPolicies, quotas/LimitRanges, politiques d'images (Cosign), durcissement runtime (seccomp/AppArmor/SELinux), Audit API, runbooks. **Explications champ-par-champ** & **commandes détaillées**.)*

---

## 0) Préambule (méthode)

Pour chaque mécanisme de sécurité : 1) **Concept** → 2) **YAML** commenté → 3) **Commandes** & flags → 4) **Pièges** & diagnostics → 5) **Runbook** de correction.

---

## 1) Objectifs

* Mettre en place un **contrôle d'accès** robuste : **authentification** (certs/OIDC), **RBAC** minimaliste, **ServiceAccounts** dédiés.
* Appliquer des **garde-fous** : **Pod Security Admission (PSA)** + **politiques d'admission** (Kyverno/Gatekeeper, ValidatingAdmissionPolicy).
* Isoler **réseau** & **ressources** : **NetworkPolicies** défaut-deny + règles, **ResourceQuota/LimitRange**.
* Sécuriser la **supply-chain** : **scanner**, **signer** (Cosign), **vérifier** les images à l'admission (autoriser registres, interdire `:latest`, exiger digests).
* Durcir l'**exécution** : `securityContext` (non-root, RO rootfs), **seccomp/AppArmor/SELinux**, capabilities minimales.
* Activer la **traçabilité** : **Audit Policy** de l'API server, logs exploitables.

---

## 2) Carte des flux de contrôle

> **Objectif** : Visualiser le chemin complet d'une requête dans Kubernetes, de l'authentification jusqu'à l'exécution, en passant par les contrôles de sécurité (RBAC, admission, réseau, audit).
> **Pre-requis** : Aucun — ce schéma est informatif.

```
# Flux complet d'une requête Kubernetes avec les points de contrôle sécurité
[AuthN utilisateurs / apps]          # 1. Authentification (certs TLS, OIDC, tokens)
  → RBAC (Roles & Bindings)          # 2. Autorisation : vérifie les droits de l'identité
    → Admission (PSA + Policies)     # 3. Admission : PSA + Kyverno/Gatekeeper/CEL valident le manifest
      → Scheduler → Kubelet (runtime durci)  # 4. Orchestration + exécution avec securityContext
[Réseau]  CNI + NetworkPolicies      # 5. Isolation réseau via le CNI (Calico/Cilium)
[Images]  Scan + Signature (Cosign) + Vérif à l'admission  # 6. Supply-chain : images signées/scannées
[Audit]   API Audit Policy + SIEM    # 7. Traçabilité : logs d'audit envoyés au SIEM
```

> **Résultat attendu** :
> ```
> Schéma conceptuel — pas de sortie exécutable.
> ```
> **Vérification** : Comprendre que chaque couche (AuthN → RBAC → Admission → Runtime → Réseau → Images → Audit) est un maillon indépendant de la chaîne de sécurité.

---

## 3) AuthN/OIDC & **RBAC**

### 3.1 ServiceAccount (SA) **dédié** (et pas de token auto)

> **Objectif** : Créer un ServiceAccount dédié à une application dans le namespace `demo`, en désactivant le montage automatique du token API pour réduire la surface d'attaque.
> **Pre-requis** : Un namespace `demo` doit exister (`kubectl create ns demo`).

```yaml
apiVersion: v1                          # API core de Kubernetes
kind: ServiceAccount                    # Ressource : compte de service pour les Pods
metadata:
  name: app-sa                          # Nom du ServiceAccount
  namespace: demo                       # Namespace dans lequel il est créé
automountServiceAccountToken: false     # Empêche le montage auto du token API dans le Pod
                                        # → un Pod compromis ne peut pas accéder à l'API K8s par défaut
```

> **Résultat attendu** :
> ```
> serviceaccount/app-sa created
> ```
> **Vérification** : `kubectl get sa app-sa -n demo` — le SA existe. Vérifier dans un Pod utilisant ce SA que `/var/run/secrets/kubernetes.io/serviceaccount/token` n'existe pas.

### 3.2 RBAC minimal (namespace-scoped)

> **Objectif** : Définir un rôle RBAC limité à la lecture des ConfigMaps dans le namespace `demo`, puis le lier au ServiceAccount `app-sa`. Principe du moindre privilège.
> **Pre-requis** : Le namespace `demo` et le ServiceAccount `app-sa` doivent exister.

```yaml
# Rôle : lecture de ConfigMaps uniquement
apiVersion: rbac.authorization.k8s.io/v1   # API RBAC (groupe rbac.authorization.k8s.io)
kind: Role                                 # Role = permissions scopees à un namespace
metadata:
  name: read-cm                            # Nom du rôle
  namespace: demo                          # Namespace du rôle
rules:
- apiGroups: [""]                          # Groupe API vide = API core (v1)
  resources: ["configmaps"]                # Ressource ciblée : les ConfigMaps
  verbs: ["get","list","watch"]            # Opérations autorisées : lecture seule

---
# Liaison de rôle vers le SA
apiVersion: rbac.authorization.k8s.io/v1   # API RBAC
kind: RoleBinding                          # Lie un Role à un sujet (ici un SA)
metadata:
  name: rb-read-cm                         # Nom du RoleBinding
  namespace: demo                          # Namespace (doit correspondre au Role)
subjects:
- kind: ServiceAccount                     # Type de sujet
  name: app-sa                             # Nom du SA cible
  namespace: demo                          # Namespace du SA
roleRef:
  apiGroup: rbac.authorization.k8s.io      # Groupe API du rôle référencé
  kind: Role                               # Type : Role (pas ClusterRole)
  name: read-cm                            # Nom du Role à lier
```

> **Résultat attendu** :
> ```
> role.rbac.authorization.k8s.io/read-cm created
> rolebinding.rbac.authorization.k8s.io/rb-read-cm created
> ```
> **Vérification** : `kubectl get role,rolebinding -n demo` — le Role et le RoleBinding sont présents.

**Vérifs & diagnostics**

> **Objectif** : Vérifier que le RBAC fonctionne correctement : le SA `app-sa` doit pouvoir lire les ConfigMaps mais PAS les Secrets.
> **Pre-requis** : Le Role `read-cm` et le RoleBinding `rb-read-cm` doivent être appliqués. Le SA `app-sa` doit exister.

```bash
# Simuler l'identité du SA (impersonation)
# --as= permet de tester les permissions sans avoir réellement le token du SA
kubectl auth can-i get configmaps \
  --as=system:serviceaccount:demo:app-sa -n demo           # doit répondre yes
kubectl auth can-i get secrets \
  --as=system:serviceaccount:demo:app-sa -n demo           # doit répondre no

# Lister RBAC du namespace
# Affiche tous les Roles et RoleBindings avec détails (colonnes supplémentaires)
kubectl get role,rolebinding -n demo -o wide
```

> **Résultat attendu** :
> ```
> yes
> no
> NAME                                       CREATED AT
> role.rbac.authorization.k8s.io/read-cm     2024-01-15T10:00:00Z
>
> NAME                                              ROLE              AGE
> rolebinding.rbac.authorization.k8s.io/rb-read-cm  Role/read-cm      1m
> ```
> **Vérification** : La première commande répond `yes`, la seconde `no`. Le RoleBinding pointe bien vers `Role/read-cm`.

> **Pièges** : `ClusterRoleBinding` accordant trop de droits à *tous* les SA ; privilégier **Role/RoleBinding** dans un **namespace**.

---

## 4) **Pod Security Admission (PSA)** — baseline/risk/restricted

### 4.1 Activer PSA par **labels** sur le namespace

> **Objectif** : Activer le profil de sécurité `restricted` (le plus strict) sur le namespace `prod` via les labels PSA. Cela bloque, avertit et audite les Pods non conformes.
> **Pre-requis** : Kubernetes 1.23+ (PSA en GA). Le namespace `prod` doit exister.

```bash
# Applique les labels PSA au namespace 'prod'
# --overwrite permet de remplacer les labels existants s'il y en a
kubectl label ns prod \
  pod-security.kubernetes.io/enforce=restricted \
  # enforce=restricted → bloque tout Pod non conforme au profil 'restricted'
  pod-security.kubernetes.io/enforce-version=latest \
  # enforce-version=latest → applique la dernière version du profil PSA
  pod-security.kubernetes.io/warn=restricted \
  # warn=restricted → affiche un avertissement à l'utilisateur lors du kubectl apply
  pod-security.kubernetes.io/audit=restricted --overwrite
  # audit=restricted → enregistre les violations dans les événements d'audit API
```

> **Résultat attendu** :
> ```
> namespace/prod labeled
> ```
> **Vérification** : `kubectl get ns prod --show-labels | grep pod-security` — les 4 labels PSA sont présents.

* **enforce** : bloque les Pods non conformes au profil `restricted`.
* **warn/audit** : génère des messages sans blocage (phase d'adoption).

### 4.2 Effets clés du profil `restricted`

* **Interdits** : `privileged`, `hostNetwork/PID/IPC` (sauf cas très cadrés), montages **hostPath** non sûrs.
* **Exigés** : `runAsNonRoot: true`, **seccomp** `RuntimeDefault`, **capabilities** minimales, **readOnlyRootFilesystem** recommandé.

**Pod durci (extrait)**

> **Objectif** : Définir un Pod conforme au profil PSA `restricted` avec tous les durcissements de sécurité : non-root, filesystem en lecture seule, seccomp, pas d'escalade de privilèges, toutes les capabilities supprimées.
> **Pre-requis** : Le namespace doit avoir PSA activé en mode `restricted`. L'image `ghcr.io/acme/app:1.2.3` doit exister et être accessible.

```yaml
spec:
  automountServiceAccountToken: false     # Pas de token API monté dans le Pod
  securityContext:                        # Contexte de sécurité au niveau du Pod
    seccompProfile: { type: RuntimeDefault }  # Profil seccomp par défaut du runtime (containerd/CRI-O)
    runAsNonRoot: true                    # Interdit de lancer le conteneur en root (UID 0)
    runAsUser: 10001                      # UID explicite (non-root)
    runAsGroup: 10001                     # GID explicite
    fsGroup: 10001                        # GID pour les volumes montés
  containers:
  - name: app                             # Nom du conteneur
    image: ghcr.io/acme/app:1.2.3         # Image avec tag versionné (pas :latest)
    securityContext:                      # Contexte de sécurité au niveau du conteneur
      readOnlyRootFilesystem: true        # Filesystem racine en lecture seule
      allowPrivilegeEscalation: false     # Interdit setuid/setgid et autres mécanismes d'escalade
      capabilities: { drop: ["ALL"] }     # Supprime TOUTES les capabilities Linux
```

> **Résultat attendu** :
> ```
> pod/app-durci created
> ```
> **Vérification** : `kubectl get pod app-durci -n prod` — le Pod est Running. `kubectl describe pod` ne montre aucune violation PSA.

**Diagnostics**

> **Objectif** : Inspecter les événements et les labels PSA du namespace pour diagnostiquer d'éventuelles violations de sécurité.
> **Pre-requis** : Le namespace `prod` doit avoir PSA activé. Des Pods doivent avoir été créés (ou rejetés).

```bash
# Afficher les 20 derniers événements triés par timestamp
# Permet de voir les rejets PSA ou les avertissements récents
kubectl -n prod get events --sort-by=.lastTimestamp | tail -n 20

# Extraire les lignes contenant 'pod-security' de la description du namespace
# Montre les labels PSA actifs et les violations enregistrées
kubectl describe ns prod | sed -n '/pod-security/p'
```

> **Résultat attendu** :
> ```
> LAST SEEN   TYPE      REASON              OBJECT              MESSAGE
> 2m          Warning   FailedCreate        job/bad-job         Error creating: pods "..." is forbidden: violates PodSecurity "restricted:latest": ...
> 1m          Normal    Scheduled           pod/app-durci       Successfully assigned prod/app-durci to node01
>
> pod-security.kubernetes.io/enforce=restricted
> pod-security.kubernetes.io/enforce-version=latest
> pod-security.kubernetes.io/warn=restricted
> pod-security.kubernetes.io/audit=restricted
> ```
> **Vérification** : Les événements montrent soit des rejets (FailedCreate avec message PSA), soit des créations réussies. Les labels PSA sont bien listés dans la description du namespace.

---

## 5) **Politiques d'admission** (Kyverno / Gatekeeper / Native CEL)

### 5.1 Kyverno — simple & lisible (validate/mutate/verifyImages)

**Interdire `hostPath` & conteneurs privilégiés**

> **Objectif** : Créer une ClusterPolicy Kyverno qui interdit les volumes `hostPath` (accès au filesystem de l'hôte) et les conteneurs privilégiés (accès total au système hôte).
> **Pre-requis** : Kyverno doit être installé dans le cluster (`kubectl get pods -n kyverno`).

```yaml
apiVersion: kyverno.io/v1                 # API Kyverno v1
kind: ClusterPolicy                       # Policy au niveau cluster (pas un namespace)
metadata:
  name: disallow-hostpath-privileged      # Nom de la policy
spec:
  validationFailureAction: Enforce        # Mode Enforce = bloque les violations (vs Audit = log seulement)
  rules:
  - name: no-hostpath                     # Nom de la règle
    match: { resources: { kinds: ["Pod"] } }  # S'applique à toutes les ressources de type Pod
    validate:
      message: "hostPath interdit."       # Message affiché en cas de violation
      pattern:
        spec:
          =(volumes):                     # Le '=' signifie 'optionnel' — si volumes existe...
            - X(hostPath): "null"         # Le 'X' signifie 'interdit' — hostPath ne doit PAS être présent
  - name: no-privileged                   # Deuxième règle
    match: { resources: { kinds: ["Pod"] } }  # S'applique aux Pods
    validate:
      message: "Conteneurs privilégiés interdits."
      pattern:
        spec:
          containers:
          - =(securityContext):           # Si securityContext est défini...
              =(privileged): "false"      # ... alors privileged doit être "false" (chaîne)
              =(allowPrivilegeEscalation): false  # et allowPrivilegeEscalation doit être false (booléen)
```

> **Résultat attendu** :
> ```
> clusterpolicy.kyverno.io/disallow-hostpath-privileged created
> ```
> **Vérification** : `kubectl get cpol disallow-hostpath-privileged` — statut READY. Tester avec un Pod utilisant `hostPath` → doit être rejeté.

**Exiger seccomp & rootfs en lecture seule**

> **Objectif** : Créer une ClusterPolicy Kyverno qui exige un profil seccomp `RuntimeDefault` au niveau du Pod et un filesystem racine en lecture seule pour chaque conteneur.
> **Pre-requis** : Kyverno installé dans le cluster.

```yaml
apiVersion: kyverno.io/v1                 # API Kyverno v1
kind: ClusterPolicy                       # Policy cluster-wide
metadata:
  name: require-seccomp-ro                # Nom de la policy
spec:
  validationFailureAction: Enforce        # Bloque les violations
  rules:
  - name: require-seccomp                 # Règle 1 : exige seccomp
    match: { resources: { kinds: ["Pod"] } }  # Cible les Pods
    validate:
      message: "Seccomp RuntimeDefault requis."
      pattern:
        spec:
          securityContext:                # Contexte de sécurité du Pod
            seccompProfile: { type: "RuntimeDefault" }  # Exige le profil seccomp par défaut du runtime
  - name: ro-rootfs                       # Règle 2 : filesystem en lecture seule
    match: { resources: { kinds: ["Pod"] } }  # Cible les Pods
    validate:
      message: "readOnlyRootFilesystem requis."
      pattern:
        spec:
          containers:
          - securityContext:
              readOnlyRootFilesystem: true  # Chaque conteneur doit avoir le FS racine en lecture seule
```

> **Résultat attendu** :
> ```
> clusterpolicy.kyverno.io/require-seccomp-ro created
> ```
> **Vérification** : `kubectl get cpol require-seccomp-ro` — statut READY. Un Pod sans `seccompProfile` ou sans `readOnlyRootFilesystem: true` sera rejeté.

**Autoriser seulement certains registres + refuser `:latest`**

> **Objectif** : Restreindre les images autorisées au registre `ghcr.io/acme/*` et interdire les tags non versionnés (`:latest`, `:dev`, `:stable`) pour garantir la traçabilité des images.
> **Pre-requis** : Kyverno installé dans le cluster.

```yaml
apiVersion: kyverno.io/v1                 # API Kyverno v1
kind: ClusterPolicy                       # Policy cluster-wide
metadata:
  name: allowed-registries-no-latest      # Nom de la policy
spec:
  validationFailureAction: Enforce        # Bloque les violations
  rules:
  - name: only-ghcr-acme                  # Règle 1 : registre autorisé
    match: { resources: { kinds: ["Pod"] } }  # Cible les Pods
    validate:
      message: "Seules les images ghcr.io/acme/* sont autorisées."
      pattern:
        spec:
          containers:
          - image: "ghcr.io/acme/*"       # Pattern glob : seules les images de ce registre sont acceptées
  - name: no-latest                       # Règle 2 : interdiction des tags non versionnés
    match: { resources: { kinds: ["Pod"] } }  # Cible les Pods
    validate:
      message: "Tag :latest interdit. Utilisez un tag versionné ou un digest."
      deny:                               # Action de déni conditionnel
        conditions:
        - key: "{{ images.containers[*].tag }}"  # Variable Kyverno : extrait tous les tags des images
          operator: AnyIn                 # Si AU MOINS UN tag est dans la liste...
          value: ["latest", "dev", "stable"]     # ... alors le Pod est refusé
```

> **Résultat attendu** :
> ```
> clusterpolicy.kyverno.io/allowed-registries-no-latest created
> ```
> **Vérification** : `kubectl run test --image=nginx:latest` → rejeté. `kubectl run test --image=ghcr.io/acme/app:1.2.3` → accepté.

**Vérifier **signatures Cosign** (bloquer si non signées)**

> **Objectif** : Créer une ClusterPolicy Kyverno v2 qui vérifie la signature Cosign des images `ghcr.io/acme/*` et bloque le déploiement si la signature est absente ou invalide.
> **Pre-requis** : Kyverno v1.9+ installé. Une paire de clés Cosign doit avoir été générée (`cosign generate-key-pair`). La clé publique doit être insérée dans le champ `publicKeys`.

```yaml
apiVersion: kyverno.io/v2                 # API Kyverno v2 (nécessaire pour verifyImages)
kind: ClusterPolicy                       # Policy cluster-wide
metadata:
  name: verify-images                     # Nom de la policy
spec:
  validationFailureAction: Enforce        # Bloque les images non signées
  rules:
  - name: signed-by-acme                  # Nom de la règle
    match: { resources: { kinds: ["Pod"] } }  # Cible les Pods
    verifyImages:                         # Section spécifique à la vérification d'images signées
    - imageReferences: ["ghcr.io/acme/*"]  # Applique la vérif aux images de ce registre
      attestors:                          # Définit qui est autorisé à signer
      - entries:
        - keys:
            publicKeys: |                 # Clé publique Cosign (PEM) utilisée pour vérifier la signature
              -----BEGIN PUBLIC KEY-----
              ...votre clef cosign...
              -----END PUBLIC KEY-----
```

> **Résultat attendu** :
> ```
> clusterpolicy.kyverno.io/verify-images created
> ```
> **Vérification** : Déployer une image non signée → rejetée. Signer avec `cosign sign --key cosign.key` puis redéployer → acceptée.

**Commandes**

> **Objectif** : Consulter l'état des ClusterPolicies Kyverno et les rapports de conformité pour vérifier que les politiques sont actives et efficaces.
> **Pre-requis** : Kyverno installé et au moins une ClusterPolicy appliquée.

```bash
kubectl get cpol                       # Liste toutes les ClusterPolicies Kyverno (statut READY)
kubectl get policyreport -A            # Liste les rapports de conformité par namespace
                                       # Montre les résultats pass/fail pour chaque règle
kubectl describe cpol verify-images    # Détails de la policy 'verify-images'
                                       # Affiche les règles, le statut, les compteurs de violations
```

> **Résultat attendu** :
> ```
> NAME                               READY   AGE   MESSAGE
> disallow-hostpath-privileged       true    5m    Ready
> require-seccomp-ro                 true    5m    Ready
> allowed-registries-no-latest       true    5m    Ready
> verify-images                      true    5m    Ready
>
> NAMESPACE   NAME                                          PASS   FAIL   WARN   ERROR   SKIP   AGE
> demo        cpol-require-seccomp-ro                       3      1      0      0       0      5m
>
> Name:         verify-images
> ...
> ```
> **Vérification** : Toutes les policies doivent être `READY=true`. Les policyreports montrent le ratio pass/fail des ressources évaluées.

### 5.2 Gatekeeper (OPA) — puissant & déclaratif (exemple minimal)

**ConstraintTemplate** (interdire hostNetwork)

> **Objectif** : Définir un ConstraintTemplate Gatekeeper (basé sur OPA/Rego) qui crée un type de contrainte personnalisé `K8sDenyNetHost` pour interdire l'utilisation de `hostNetwork` dans les Pods.
> **Pre-requis** : Gatekeeper doit être installé (`kubectl get pods -n gatekeeper-system`).

```yaml
apiVersion: templates.gatekeeper.sh/v1    # API Gatekeeper pour les templates
kind: ConstraintTemplate                  # Définit un type de contrainte réutilisable
metadata:
  name: k8sdenynethost                    # Nom du template (doit être en minuscules)
spec:
  crd:
    spec:
      names:
        kind: K8sDenyNetHost              # Nom du CRD qui sera créé (CamelCase)
  targets:
  - target: admission.k8s.gatekeeper.sh   # Cible : webhook d'admission Gatekeeper
    rego: |                               # Code Rego (langage de politique OPA)
      package k8sdenynethost              # Package Rego (doit correspondre au nom du template)
      violation[{"msg": msg}] {           # Règle 'violation' : si cette règle matche, le Pod est rejeté
        input.review.kind.kind == "Pod"   # Vérifie que la ressource est un Pod
        input.review.object.spec.hostNetwork == true  # Vérifie si hostNetwork est activé
        msg := "hostNetwork interdit"     # Message d'erreur retourné
      }
```

> **Résultat attendu** :
> ```
> constrainttemplate.templates.gatekeeper.sh/k8sdenynethost created
> ```
> **Vérification** : `kubectl get constrainttemplate` — le template est créé. Le CRD `k8sdenynethosts.constraints.gatekeeper.sh` est disponible.

**Constraint**

> **Objectif** : Instancier la contrainte `K8sDenyNetHost` définie par le ConstraintTemplate ci-dessus. Une fois créée, tout Pod avec `hostNetwork: true` sera rejeté.
> **Pre-requis** : Le ConstraintTemplate `k8sdenynethost` doit être appliqué et le CRD correspondant doit être disponible.

```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1  # API Gatekeeper pour les contraintes
kind: K8sDenyNetHost                           # Kind défini par le ConstraintTemplate
metadata:
  name: deny-hostnetwork                       # Nom de l'instance de contrainte
spec: {}                                       # Pas de paramètres supplémentaires (s'applique à tout le cluster)
                                               # On pourrait ajouter match/ exclusion ici
```

> **Résultat attendu** :
> ```
> k8sdenynethost.constraints.gatekeeper.sh/deny-hostnetwork created
> ```
> **Vérification** : `kubectl get k8sdenynethost` — la contrainte est active. Tester avec un Pod ayant `hostNetwork: true` → rejeté.

### 5.3 ValidatingAdmissionPolicy (native, **CEL**)

> **Objectif** : Utiliser la fonctionnalité native Kubernetes (1.28+) ValidatingAdmissionPolicy avec le langage CEL (Common Expression Language) pour exiger `runAsNonRoot: true` sur tous les Pods, sans dépendance à un outil tiers.
> **Pre-requis** : Kubernetes 1.28+ avec la feature gate `ValidatingAdmissionPolicy` activée.

```yaml
apiVersion: admissionregistration.k8s.io/v1  # API native d'admission Kubernetes
kind: ValidatingAdmissionPolicy              # Politique d'admission native (CEL)
metadata:
  name: require-nonroot                      # Nom de la politique
spec:
  failurePolicy: Fail                        # Si la politique ne peut pas être évaluée → rejeter
  matchConstraints:
    resourceRules:
    - apiGroups: [""]                        # API core (v1)
      apiVersions: ["v1"]                    # Version v1
      operations: ["CREATE","UPDATE"]        # S'applique à la création et la mise à jour
      resources: ["pods"]                    # Cible : les Pods
  validations:
  - expression: "object.spec.securityContext.runAsNonRoot == true"  # Expression CEL : vérifie runAsNonRoot
    message: "runAsNonRoot: true est requis."  # Message d'erreur si l'expression est fausse
---
apiVersion: admissionregistration.k8s.io/v1  # API native d'admission
kind: ValidatingAdmissionPolicyBinding       # Lie la politique à des actions concrètes
metadata:
  name: require-nonroot-binding              # Nom du binding
spec:
  policyName: require-nonroot                # Référence la policy définie ci-dessus
  validationActions: ["Deny"]                # Action : rejeter (vs Audit = log seulement, Warn = avertissement)
```

> **Résultat attendu** :
> ```
> validatingadmissionpolicy.admissionregistration.k8s.io/require-nonroot created
> validatingadmissionpolicybinding.admissionregistration.k8s.io/require-nonroot-binding created
> ```
> **Vérification** : `kubectl get validatingadmissionpolicy` — la policy est listée. Créer un Pod sans `runAsNonRoot: true` → rejeté avec le message défini.

---

## 6) **NetworkPolicies** — défaut-deny + ouvertures ciblées

**Tout bloquer (Ingress & Egress)**

> **Objectif** : Créer une NetworkPolicy "default-deny" qui bloque tout le trafic entrant (Ingress) et sortant (Egress) pour tous les Pods du namespace `demo`. C'est la base de la stratégie "zero trust" réseau.
> **Pre-requis** : Un CNI compatible NetworkPolicy doit être installé (Calico, Cilium, Weave Net, etc.). Le namespace `demo` doit exister.

```yaml
apiVersion: networking.k8s.io/v1            # API réseau de Kubernetes
kind: NetworkPolicy                         # Ressource de politique réseau
metadata:
  name: default-deny-all                    # Nom : politique de déni par défaut
  namespace: demo                           # Namespace ciblé
spec:
  podSelector: {}                           # Sélecteur vide = s'applique à TOUS les Pods du namespace
  policyTypes: ["Ingress","Egress"]         # Active les règles sur les deux directions
                                            # Sans aucune règle ingress/egress → tout est bloqué
```

> **Résultat attendu** :
> ```
> networkpolicy.networking.k8s.io/default-deny-all created
> ```
> **Vérification** : `kubectl get netpol -n demo` — la policy existe. Depuis un Pod dans `demo`, aucun ping/curl vers l'extérieur ou d'autres namespaces ne fonctionne.

**Autoriser web → api (Ingress)**

> **Objectif** : Autoriser uniquement les Pods étiquetés `app.kubernetes.io/name: web` à communiquer avec les Pods `app.kubernetes.io/name: api` sur le port TCP 8080.
> **Pre-requis** : La NetworkPolicy `default-deny-all` doit être appliquée. Les Pods doivent avoir les labels correspondants.

```yaml
apiVersion: networking.k8s.io/v1            # API réseau
kind: NetworkPolicy                         # Politique réseau
metadata:
  name: allow-web-to-api                    # Nom de la policy
  namespace: demo                           # Namespace
spec:
  podSelector: { matchLabels: { app.kubernetes.io/name: api } }  # Cible les Pods 'api'
  ingress:                                  # Règles de trafic entrant
  - from:
    - podSelector: { matchLabels: { app.kubernetes.io/name: web } }  # Source autorisée : Pods 'web'
    ports: [ { protocol: TCP, port: 8080 } ]  # Port autorisé : TCP 8080 uniquement
```

> **Résultat attendu** :
> ```
> networkpolicy.networking.k8s.io/allow-web-to-api created
> ```
> **Vérification** : Depuis un Pod `web`, `curl http://api:8080` fonctionne. Depuis un Pod sans label `web`, la connexion échoue.

**Autoriser egress DNS + DB**

> **Objectif** : Autoriser les Pods `api` à communiquer vers l'extérieur uniquement pour le DNS (UDP/TCP 53 dans kube-system) et vers la base de données (TCP 5432) dans le même namespace.
> **Pre-requis** : La NetworkPolicy `default-deny-all` doit être appliquée. Un Pod `db` avec le label `app.kubernetes.io/name: db` doit exister.

```yaml
apiVersion: networking.k8s.io/v1            # API réseau
kind: NetworkPolicy                         # Politique réseau
metadata:
  name: allow-egress-dns-db                 # Nom de la policy
  namespace: demo                           # Namespace
spec:
  podSelector: { matchLabels: { app.kubernetes.io/name: api } }  # Cible les Pods 'api'
  policyTypes: ["Egress"]                   # S'applique au trafic sortant uniquement
  egress:
  - to:                                     # Règle 1 : autoriser le DNS
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system  # Destination : namespace kube-system
    ports:
    - { protocol: UDP, port: 53 }           # DNS UDP (requêtes standard)
    - { protocol: TCP, port: 53 }           # DNS TCP (requêtes > 512 bytes, zone transfers)
  - to:                                     # Règle 2 : autoriser l'accès à la DB
    - podSelector:
        matchLabels: { app.kubernetes.io/name: db }  # Destination : Pods 'db' dans le même namespace
    ports: [ { protocol: TCP, port: 5432 } ]  # Port PostgreSQL
```

> **Résultat attendu** :
> ```
> networkpolicy.networking.k8s.io/allow-egress-dns-db created
> ```
> **Vérification** : Depuis un Pod `api`, `nslookup google.com` fonctionne (DNS), `psql -h db` fonctionne (5432). Tout autre trafic sortant est bloqué.

**Commandes**

> **Objectif** : Lister et inspecter les NetworkPolicies du namespace `demo` pour vérifier la configuration réseau.
> **Pre-requis** : Des NetworkPolicies doivent être créées dans le namespace `demo`.

```bash
kubectl get netpol -n demo                  # Liste toutes les NetworkPolicies du namespace
kubectl describe netpol default-deny-all -n demo  # Détails de la policy default-deny
                                                # Affiche les sélecteurs, règles, ports
```

> **Résultat attendu** :
> ```
> NAME                 POD-SELECTOR   AGE
> default-deny-all     <none>         5m
> allow-web-to-api     app=api        3m
> allow-egress-dns-db  app=api        2m
>
> Name:         default-deny-all
> Namespace:    demo
> PodSelector:  <none>
> Ingress:      <none>
> Egress:       <none>
> ```
> **Vérification** : Trois policies sont listées. `default-deny-all` a un sélecteur vide et aucune règle (tout bloqué).

> *Nécessite un CNI compatible NetPol (Calico/Cilium, …).*

---

## 7) **ResourceQuota** & **LimitRange** — éviter l'abus de ressources

**ResourceQuota**

> **Objectif** : Limiter la consommation totale de ressources dans le namespace `demo` : nombre de Pods, CPU/mémoire (requests et limits), nombre de PVC et stockage total.
> **Pre-requis** : Le namespace `demo` doit exister.

```yaml
apiVersion: v1                              # API core
kind: ResourceQuota                         # Ressource : quota de ressources par namespace
metadata:
  name: rq                                  # Nom du quota
  namespace: demo                           # Namespace ciblé
spec:
  hard:                                     # Limites maximales (hard limits)
    pods: "50"                              # Maximum 50 Pods dans le namespace
    requests.cpu: "10"                      # Total des requests CPU : 10 cores
    requests.memory: "20Gi"                 # Total des requests mémoire : 20 GiB
    limits.cpu: "20"                        # Total des limits CPU : 20 cores
    limits.memory: "40Gi"                   # Total des limits mémoire : 40 GiB
    persistentvolumeclaims: "20"            # Maximum 20 PVC
    requests.storage: "200Gi"               # Stockage total demandé : 200 GiB
```

> **Résultat attendu** :
> ```
> resourcequota/rq created
> ```
> **Vérification** : `kubectl describe resourcequota rq -n demo` — les limites sont affichées avec la consommation actuelle (Used) et la limite (Hard).

**LimitRange (défauts/bornes par conteneur)**

> **Objectif** : Définir des valeurs par défaut et des bornes maximales pour les ressources de chaque conteneur dans le namespace `demo`. Si un Pod ne spécifie pas de requests/limits, celles-ci sont injectées automatiquement.
> **Pre-requis** : Le namespace `demo` doit exister.

```yaml
apiVersion: v1                              # API core
kind: LimitRange                            # Ressource : limites par conteneur
metadata:
  name: lr                                  # Nom du LimitRange
  namespace: demo                           # Namespace ciblé
spec:
  limits:
  - type: Container                         # S'applique à chaque conteneur (pas au Pod entier)
    defaultRequest: { cpu: "100m", memory: "128Mi" }  # Requests par défaut si non spécifiées
    default:        { cpu: "500m", memory: "512Mi" }  # Limits par défaut si non spécifiées
    max:            { cpu: "2",    memory: "2Gi" }    # Maximum autorisé par conteneur
```

> **Résultat attendu** :
> ```
> limitrange/lr created
> ```
> **Vérification** : `kubectl describe limitrange lr -n demo` — les valeurs par défaut et les bornes sont affichées. Créer un Pod sans requests/limits → les valeurs par défaut sont injectées.

---

## 8) **Politiques d'images** (supply-chain)

### 8.1 Signature & vérification (Cosign)

> **Objectif** : Signer une image container avec Cosign (signature cryptographique) puis vérifier cette signature pour garantir l'intégrité et l'origine de l'image.
> **Pre-requis** : Cosign doit être installé (`brew install cosign` ou téléchargement binaire). Une paire de clés doit exister (`cosign generate-key-pair`). L'image doit être poussée dans le registre.

```bash
# Signer (clé)
# Signe l'image avec la clé privée cosign.key
# La signature est stockée dans le registre comme un objet OCI
cosign sign --key cosign.key ghcr.io/acme/app:1.2.3

# Vérifier (CI/CD ou admission)
# Vérifie la signature avec la clé publique cosign.pub
# Retourne 0 si la signature est valide, erreur sinon
cosign verify --key cosign.pub ghcr.io/acme/app:1.2.3
```

> **Résultat attendu** :
> ```
> Pushing signature to: ghcr.io/acme/app
#
> Verification for ghcr.io/acme/app:1.2.3 --
> The following checks were performed on each of these signatures:
#   - The cosign claims were validated
#   - Existence of the claims in the transparency log was verified offline
#   - The signatures were verified against the specified public key
> [{"critical":{"identity":...}}]
> ```
> **Vérification** : La commande `verify` retourne un JSON avec les détails de la signature. Si l'image est modifiée ou non signée, la commande échoue.

### 8.2 Admission : **allow-list** registres, **interdire `:latest`**, **exiger digest**

* Kyverno `allowed-registries-no-latest` (ci-dessus).
* Variante : bloquer si image **sans digest** (`image: repo@sha256:...` préféré).

Exemple (exiger un **digest** sur toutes les images) :

> **Objectif** : Créer une ClusterPolicy Kyverno qui exige que toutes les images de conteneurs soient référencées par leur digest SHA256 (ex: `repo@sha256:abc...`) plutôt que par un tag mutable.
> **Pre-requis** : Kyverno installé dans le cluster.

```yaml
apiVersion: kyverno.io/v1                 # API Kyverno v1
kind: ClusterPolicy                       # Policy cluster-wide
metadata:
  name: require-digest                    # Nom de la policy
spec:
  validationFailureAction: Enforce        # Bloque les violations
  rules:
  - name: image-must-use-digest           # Nom de la règle
    match: { resources: { kinds: ["Pod"] } }  # Cible les Pods
    validate:
      message: "Les images doivent être référencées par digest (repo@sha256:...)."
      pattern:
        spec:
          containers:
          - image: "*@sha256:*"           # Pattern glob : l'image DOIT contenir '@sha256:'
                                          # Ex: ghcr.io/acme/app@sha256:abcdef1234567890...
```

> **Résultat attendu** :
> ```
> clusterpolicy.kyverno.io/require-digest created
> ```
> **Vérification** : `kubectl run test --image=ghcr.io/acme/app:1.2.3` → rejeté. `kubectl run test --image=ghcr.io/acme/app@sha256:abc123...` → accepté.

---

## 9) Durcissement **runtime** (securityContext, seccomp, AppArmor, SELinux)

**Principes**

* **Non-root**, `readOnlyRootFilesystem`, **drop ALL capabilities**, **seccomp RuntimeDefault**.
* **Pas** de `hostPath`/`hostNetwork/PID/IPC` (sauf cas hyper cadrés).
* SA dédié, `automountServiceAccountToken: false`.

**Commandes de lecture/contrôle**

> **Objectif** : Explorer les champs de securityContext disponibles dans l'API Kubernetes et inspecter la configuration de sécurité d'un Pod existant.
> **Pre-requis** : Un Pod doit exister dans le cluster. L'outil `yq` doit être installé pour la troisième commande.

```bash
# Affiche la documentation de securityContext au niveau du Pod
kubectl explain pod.spec.securityContext

# Affiche la documentation de securityContext au niveau du conteneur
kubectl explain pod.spec.containers.securityContext

# Extrait et affiche les securityContext d'un Pod spécifique
# Utilise yq pour parser le YAML et extraire les champs pertinents
kubectl get pod <p> -o yaml | yq '.spec.securityContext, .spec.containers[].securityContext'
```

> **Résultat attendu** :
> ```
> KIND:     Pod
> VERSION:  v1
> RESOURCE: securityContext
> DESCRIPTION:
>   PodSecurityContext holds pod-level security attributes...
> FIELDS:
>   fsGroup    <integer>
>   runAsGroup <integer>
>   runAsNonRoot    <boolean>
>   runAsUser  <integer>
>   seccompProfile  <Object>
>   ...
>
> runAsNonRoot: true
> runAsUser: 10001
> readOnlyRootFilesystem: true
> allowPrivilegeEscalation: false
> capabilities:
>   drop: ["ALL"]
> ```
> **Vérification** : Les champs `runAsNonRoot`, `readOnlyRootFilesystem`, `capabilities.drop` sont bien présents et configurés.

---

## 10) **Audit de l'API server** — traçabilité sécurité

**Extrait de Policy (cible secrets & opérations sensibles)**

> **Objectif** : Définir une politique d'audit de l'API server Kubernetes qui journalise les métadonnées des opérations sur les Pods/ConfigMaps/Secrets, et le contenu complet (RequestResponse) pour les Secrets afin de tracer tout accès aux données sensibles.
> **Pre-requis** : Accès à la configuration de l'API server (fichier manifeste statique ou configuration kubeadm).

```yaml
apiVersion: audit.k8s.io/v1               # API d'audit Kubernetes
kind: Policy                              # Ressource : politique d'audit
rules:
- level: Metadata                         # Niveau 1 : journalise les métadonnées (qui, quand, quoi)
                                          # Pas le corps de la requête/réponse
  resources:
  - group: ""                             # API core
    resources: ["pods","configmaps","secrets"]  # Ressources ciblées
- level: RequestResponse                  # Niveau 2 : journalise TOUT (corps de la requête + réponse)
  verbs: ["create","update","patch","delete","get","list","watch"]  # Toutes les opérations
  resources:
  - group: ""                             # API core
    resources: ["secrets"]                # Uniquement les Secrets (données sensibles)
```

> **Résultat attendu** :
> ```
> Fichier créé : /etc/kubernetes/audit-policy.yaml
> ```
> **Vérification** : Le fichier est bien formé YAML. Après redémarrage de l'API server avec les flags appropriés, les événements d'audit apparaissent dans le log.

**Drapeaux API server**

* `--audit-policy-file=/etc/kubernetes/audit-policy.yaml`
* `--audit-log-path=/var/log/kubernetes/audit.log`

Acheminer vers **SIEM** (ELK/Loki), corréler avec **Falco**.

---

## 11) Mini-labs (rapides)

### Lab A — Activer PSA + refuser un Pod non conforme

> **Objectif** : Mettre en pratique PSA en créant un namespace avec le profil `restricted`, puis tenter de créer un Pod non conforme (runAsNonRoot: false) pour vérifier qu'il est rejeté.
> **Pre-requis** : Kubernetes 1.23+ avec PSA activé.

```bash
# Crée un namespace 'secure' et active PSA en mode enforce=restricted
kubectl create ns secure && \
kubectl label ns secure pod-security.kubernetes.io/enforce=restricted --overwrite

# Tente de créer un Pod qui viole PSA (runAsNonRoot: false)
# --overrides permet d'injecter du JSON dans le spec du Pod
kubectl -n secure run bad --image=alpine --overrides='{"spec":{"securityContext":{"runAsNonRoot":false}}}'
# Attendu : admission denied (PSA)

# Vérifie les événements pour voir le rejet PSA
kubectl -n secure get events --sort-by=.lastTimestamp | tail -n 20
```

> **Résultat attendu** :
> ```
> namespace/secure created
> namespace/secure labeled
> Error from server (Forbidden): pods "bad" is forbidden: violates PodSecurity "restricted:latest": (...allowPrivilegeEscalation != false, runAsNonRoot != true...)
>
> LAST SEEN   TYPE      REASON         OBJECT   MESSAGE
> 1m          Warning   FailedCreate   job/bad  Error creating: pods "bad" is forbidden: violates PodSecurity "restricted:latest"
> ```
> **Vérification** : Le Pod `bad` n'est PAS créé. L'événement montre clairement la violation PSA avec les champs manquants.

### Lab B — RBAC minimal + tests `kubectl auth can-i`

> **Objectif** : Tester les permissions RBAC d'un ServiceAccount en utilisant `kubectl auth can-i` pour vérifier que le principe du moindre privilège est correctement appliqué.
> **Pre-requis** : Le namespace `demo`, le SA `app-sa`, le Role `read-cm` et le RoleBinding `rb-read-cm` doivent être appliqués.

```bash
kubectl create ns demo                    # Crée le namespace demo
# (appliquer Role + RoleBinding + SA comme plus haut)

# Test 1 : le SA peut-il lister les ConfigMaps ? → attendu : yes
kubectl auth can-i list configmaps --as=system:serviceaccount:demo:app-sa -n demo

# Test 2 : le SA peut-il lire les Secrets ? → attendu : no
kubectl auth can-i get secrets     --as=system:serviceaccount:demo:app-sa -n demo
```

> **Résultat attendu** :
> ```
> namespace/demo created
> yes
> no
> ```
> **Vérification** : La première commande répond `yes` (le SA a le droit de lister les ConfigMaps), la seconde `no` (pas d'accès aux Secrets).

### Lab C — NetPol défaut-deny + ouverture ciblée

> **Objectif** : Appliquer une politique réseau default-deny puis des ouvertures ciblées, et tester la connectivité depuis un Pod de test (netshoot) pour valider que les règles fonctionnent.
> **Pre-requis** : Un CNI compatible NetworkPolicy (Calico/Cilium). Les NetworkPolicies `default-deny-all`, `allow-web-to-api`, `allow-egress-dns-db` doivent être appliquées.

```bash
# Appliquer default-deny-all puis allow-web-to-api et allow-egress-dns-db
# (appliquer les YAML des NetworkPolicies ci-dessus)

# Vérifie que les 3 policies sont bien actives
kubectl -n demo get netpol

# Lance un Pod interactif netshoot (boîte à outils réseau) pour tester la connectivité
# --rm supprime le Pod à la sortie, --restart=Never évite les restarts
kubectl -n demo run -it test --image=nicolaka/netshoot --rm --restart=Never -- sh
```

> **Résultat attendu** :
> ```
> NAME                 POD-SELECTOR   AGE
> default-deny-all     <none>         2m
> allow-web-to-api     app=api        1m
> allow-egress-dns-db  app=api        1m
>
> If you don't see a command prompt, try pressing enter.
> # (shell netshoot)
> ```
> **Vérification** : Depuis le shell netshoot, `curl http://api:8080` fonctionne si le Pod a le label `web`, `nslookup google.com` fonctionne (DNS autorisé), mais `curl http://random-service:80` échoue.

### Lab D — Kyverno : bloquer `:latest`

> **Objectif** : Vérifier que la policy Kyverno `no-latest` bloque correctement le déploiement d'images avec le tag `:latest`.
> **Pre-requis** : Kyverno installé. La ClusterPolicy `allowed-registries-no-latest` doit être appliquée.

```bash
# Appliquer la policy no-latest, puis:

# Tente de créer un Pod avec l'image taggée :latest
kubectl -n demo run u1 --image=ghcr.io/acme/app:latest --restart=Never
# Attendu : denied (rejeté par Kyverno)

# Vérifie les événements pour voir le rejet
kubectl get events --sort-by=.lastTimestamp | tail -n 30
```

> **Résultat attendu** :
> ```
> Error from server: admission webhook "validate.kyverno.svc-fail" denied the request:
#
> policy default/no-latest for resource Pod u1: Tag :latest interdit. Utilisez un tag versionné ou un digest.
>
> LAST SEEN   TYPE      REASON      OBJECT   MESSAGE
> 30s         Warning   Denied      pod/u1   Tag :latest interdit...
> ```
> **Vérification** : Le Pod `u1` n'est PAS créé. L'événement montre le déni par Kyverno avec le message de la policy.

---

## 12) Runbooks (dépannage)

### 12.1 "**Refus PSA**"

> **Objectif** : Diagnostiquer un rejet de Pod par Pod Security Admission. Identifier le champ manquant ou non conforme dans le securityContext.
> **Pre-requis** : PSA activé sur le namespace concerné. Un Pod a été rejeté.

```bash
# Affiche les 20 derniers événements du namespace, triés par timestamp
# Chercher les événements de type Warning avec reason FailedCreate
kubectl -n <ns> get events --sort-by=.lastTimestamp | tail -n 20

# Extrait les labels PSA du namespace pour vérifier le niveau actif
kubectl describe ns <ns> | sed -n '/pod-security/p'
# Corriger securityContext (non-root, seccomp...), ou utiliser warn/audit en transition.
```

> **Résultat attendu** :
> ```
> LAST SEEN   TYPE      REASON         OBJECT          MESSAGE
> 2m          Warning   FailedCreate   job/myapp       Error creating: pods "..." is forbidden: violates PodSecurity "restricted:latest": allowPrivilegeEscalation != false
>
> pod-security.kubernetes.io/enforce=restricted
> pod-security.kubernetes.io/enforce-version=latest
> pod-security.kubernetes.io/warn=restricted
> pod-security.kubernetes.io/audit=restricted
> ```
> **Vérification** : Le message d'erreur indique précisément le champ à corriger (ex: `allowPrivilegeEscalation != false`). Ajouter les champs manquants dans le securityContext du Pod.

### 12.2 "**Denied par Kyverno/Gatekeeper**"

> **Objectif** : Diagnostiquer un rejet par une policy Kyverno ou Gatekeeper. Identifier la policy et la règle qui a bloqué le déploiement.
> **Pre-requis** : Kyverno ou Gatekeeper installé. Un Pod a été rejeté par le webhook d'admission.

```bash
# Affiche les derniers événements pour voir le rejet
kubectl get events --sort-by=.lastTimestamp | tail -n 30

# Liste toutes les ClusterPolicies Kyverno et les rapports de conformité
kubectl get cpol -A ; kubectl get policyreport -A

# Inspecte la policy spécifique qui a bloqué le déploiement
kubectl describe cpol allowed-registries-no-latest
# Adapter manifest selon message 'validate' de la policy.
```

> **Résultat attendu** :
> ```
> LAST SEEN   TYPE      REASON   OBJECT   MESSAGE
> 1m          Warning   Denied   pod/x    admission webhook "validate.kyverno.svc-fail" denied...
>
> NAME                               READY   AGE
> allowed-registries-no-latest       true    10m
>
> Name:         allowed-registries-no-latest
> Rules:
#   - name: no-latest
#     validate: ... message: "Tag :latest interdit..."
> ```
> **Vérification** : L'événement montre le webhook qui a rejeté. Le `describe cpol` affiche les règles et messages. Adapter le manifest du Pod selon le message.

### 12.3 "**RBAC : accès refusé**"

> **Objectif** : Diagnostiquer un refus d'accès RBAC. Vérifier si le ServiceAccount a les permissions nécessaires et identifier le Role/RoleBinding manquant.
> **Pre-requis** : Un utilisateur ou ServiceAccount reçoit une erreur "forbidden" lors d'une opération kubectl.

```bash
# Vérifie si le SA a la permission demandée
kubectl auth can-i get secrets --as=system:serviceaccount:demo:app-sa -n demo

# Liste les Roles et RoleBindings du namespace pour voir ce qui est configuré
kubectl get role,rolebinding -n demo -o wide
# Ajouter un Role ciblé ; éviter ClusterRoleBinding global.
```

> **Résultat attendu** :
> ```
> no
>
> NAME                                       CREATED AT
> role.rbac.authorization.k8s.io/read-cm     10m
>
> NAME                                              ROLE              AGE
> rolebinding.rbac.authorization.k8s.io/rb-read-cm  Role/read-cm      10m
> ```
> **Vérification** : `auth can-i` répond `no` pour la ressource demandée. Créer un Role avec les verbs manquants et un RoleBinding vers le SA.

### 12.4 "**Trafic bloqué (NetPol)**"

> **Objectif** : Diagnostiquer un problème de connectivité réseau entre Pods causé par des NetworkPolicies trop restrictives. Identifier la policy bloquante et la règle manquante.
> **Pre-requis** : Des NetworkPolicies sont appliquées dans le namespace. Un Pod n'arrive pas à communiquer avec un autre service.

```bash
# Liste toutes les NetworkPolicies du namespace
kubectl get netpol -n demo

# Inspecte les détails d'une policy spécifique (règles ingress/egress, sélecteurs, ports)
kubectl describe netpol <name> -n demo
# Ajouter la règle manquante (DNS/DB/front), valider ports/protocoles exacts.
```

> **Résultat attendu** :
> ```
> NAME                 POD-SELECTOR   AGE
> default-deny-all     <none>         30m
> allow-web-to-api     app=api        25m
>
> Name:         allow-web-to-api
> Ingress Rules:
#   from:
#     - podSelector: app=web
#   ports:
#     - TCP/8080
> ```
> **Vérification** : Comparer les règles avec les flux attendus. Si le DNS est bloqué, ajouter une règle egress vers kube-system sur UDP/TCP 53. Si un service est inaccessible, vérifier les labels et ports.

### 12.5 "**Image non signée / `:latest` interdit**"

* Lire l'event d'admission.
* **Signer** (Cosign) ou pousser une **version taggée**/digest.
* Re-déployer et **vérifier** avec `cosign verify`.

---

## 13) Bonnes pratiques (check-list)

* **Namespaces** par appli/env ; **PSA `restricted`** par défaut (warn/audit en montée de version).
* **RBAC minimal**, SA dédiés, `automountServiceAccountToken: false`.
* **securityContext** strict (non-root, RO rootfs, seccomp RuntimeDefault, drop ALL caps).
* **NetworkPolicies** : **défaut-deny** + ouvertures nécessaires (DNS/DB/monitoring).
* **Images** : scanner en CI, **signer** (Cosign), **vérifier à l'admission** ; interdire `:latest`, exiger **digest**.
* **Quotas/LimitRanges** : éviter l'abus de ressources ; PDB (disponibilité) si besoin.
* **Audit** activé (API) + logs expédiés au **SIEM** ; corrélation avec **Falco**.

---

## 14) Aide-mémoire (commandes)

> **Objectif** : Regrouper toutes les commandes essentielles du chapitre en un seul endroit pour référence rapide lors du dépannage ou de la mise en place de la sécurité.
> **Pre-requis** : `kubectl` configuré avec un contexte valide. Kyverno/Gatekeeper/Cosign installés selon les sections.

```bash
# RBAC — Vérifier les permissions d'un ServiceAccount
kubectl auth can-i get configmaps --as=system:serviceaccount:demo:app-sa -n demo
# Liste les Roles et RoleBindings du namespace
kubectl get role,rolebinding -n demo -o wide

# PSA — Activer le profil restricted sur un namespace
kubectl label ns demo pod-security.kubernetes.io/enforce=restricted --overwrite
# Vérifier les labels PSA actifs
kubectl describe ns demo | sed -n '/pod-security/p'

# Kyverno / Gatekeeper — Lister les policies et rapports
kubectl get cpol ; kubectl get policyreport -A
# Lister les templates et contraintes Gatekeeper
kubectl get constrainttemplates.constraints.gatekeeper.sh
kubectl get constraints -A

# ValidatingAdmissionPolicy — Lister les policies et bindings natifs (CEL)
kubectl get validatingadmissionpolicy,validatingadmissionpolicybinding

# NetworkPolicies — Lister et inspecter les politiques réseau
kubectl get netpol -n demo
kubectl describe netpol default-deny-all -n demo

# Quotas & Limits — Vérifier la consommation et les bornes
kubectl get resourcequota,limitrange -n demo
kubectl describe resourcequota rq -n demo

# Cosign (local) — Vérifier la signature d'une image
cosign verify --key cosign.pub ghcr.io/acme/app:1.2.3

# Audit (API server) — Vérifier que l'audit est activé sur l'API server
# Recherche les flags d'audit dans la ligne de commande du processus kube-apiserver
ps aux | grep kube-apiserver | grep -- '--audit'
```

> **Résultat attendu** :
> ```
> yes
> NAME                                       CREATED AT
> role.rbac.authorization.k8s.io/read-cm     30m
> NAME                                              ROLE              AGE
> rolebinding.rbac.authorization.k8s.io/rb-read-cm  Role/read-cm      30m
>
> NAME                               READY   AGE
> disallow-hostpath-privileged       true    1h
> ...
>
> /usr/bin/kube-apiserver --audit-policy-file=/etc/kubernetes/audit-policy.yaml --audit-log-path=/var/log/kubernetes/audit.log
> ```
> **Vérification** : Chaque commande retourne l'état actuel de la configuration sécurité. Les policies sont READY, les quotas montrent Used/Hard, l'audit est confirmé par les flags du processus.