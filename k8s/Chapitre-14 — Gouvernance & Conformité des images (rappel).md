# Chapitre 14 — Gouvernance & Conformité des images (rappel **exigeant & opérationnel**)

*(nomenclature & versions, **immutabilité/digest**, **rétention/GC** registre, **SBOM obligatoire**, **signatures cosign**, **politiques d'admission**, **journalisation & traçabilité**. Chaque commande et champ utile est expliqué.)*

---

## 0) Objectifs

* Normaliser **comment on nomme, versionne et promeut** les images.
* Garantir l'**immutabilité** : déployer **uniquement par digest** (et jamais `:latest`).
* Mettre en place **SBOM, scan et signature** systématiques (supply chain).
* Encadrer via **politiques d'admission** (Kyverno / Gatekeeper / Sigstore Policy Controller).
* Assurer **journalisation & traçabilité** (K8s + registre) et un **process d'exceptions** formalisé.

---

## 1) Nommage & versions (SemVer, canaux)

### 1.1 Conventions de nommage (référentiel)

> **Objectif** : Illustrer le format standard de référence d'une image OCI, composé du registre, de l'organisation, du projet/service, et optionnellement d'un tag ou d'un digest immuable.
> **Pre-requis** : Aucun — il s'agit d'une convention de nommage.

```
# Format général d'une référence d'image OCI :
# <registry>        → adresse du registre (ex: ghcr.io, docker.io, harbor.local)
# <org>             → organisation ou namespace dans le registre
# <projet>/<service>→ hiérarchie du projet et du service
# [:tag]            → tag optionnel (ex: 1.4.2) — mutable, donc à éviter en prod
# [@sha256:<digest>]→ digest immuable — recommandé pour les déploiements
<registry>/<org>/<projet>/<service>[:tag]  ou  @sha256:<digest>
# Exemple concret : image 'api' du projet 'billing' de l'org 'acme', version 1.4.2
Ex. ghcr.io/acme/billing/api:1.4.2
```

> **Résultat attendu** :
> ```
> ghcr.io/acme/billing/api:1.4.2
> ```
> **Vérification** : La référence doit contenir au minimum le registre, l'org et le service. En production, préférer `@sha256:<digest>`.

**Recommandations**

* Toujours **minuscule**, noms courts et stables.
* Deux niveaux max après l'org si possible (`projet/service`).
* **Labels OCI** (traçabilité) systématiques :

> **Objectif** : Ajouter des métadonnées OCI standardisées lors du build Docker pour assurer la traçabilité de l'image (version, commit Git, source).
> **Pre-requis** : Avoir un Dockerfile valide, les variables `$VER` et `$GIT_SHA` définies dans l'environnement.

  ```bash
  docker build \
    # Titre de l'image (nom du service)
    --label org.opencontainers.image.title="api" \
    # Version sémantique de l'image (ex: 1.4.2)
    --label org.opencontainers.image.version="$VER" \
    # SHA du commit Git source (traçabilité code → image)
    --label org.opencontainers.image.revision="$GIT_SHA" \
    # URL du dépôt source (lien vers le code)
    --label org.opencontainers.image.source="https://github.com/acme/billing" \
    # Tag de l'image avec le numéro de version
    -t ghcr.io/acme/billing/api:$VER .
  ```

> **Résultat attendu** :
> ```
> Successfully built abc123def456
> Successfully tagged ghcr.io/acme/billing/api:1.4.2
> ```
> **Vérification** : `docker inspect ghcr.io/acme/billing/api:1.4.2 | jq '.[0].Config.Labels'` doit afficher les 4 labels OCI.

### 1.2 Versions & canaux

* **SemVer** : `MAJOR.MINOR.PATCH` (ex. `1.4.2`).
* **Pré-release** : `1.5.0-rc.1`, `1.5.0-beta.2`.
* **Canaux** (optionnels) : `dev`, `rc`, `stable`.

  > ⚠️ Ces tags ne sont **pas** des cibles de déploiement long terme : en prod, **déployer par digest**.

---

## 2) Immutabilité & déploiement **par digest**

### 2.1 Pourquoi le digest ?

* `:tag` peut être **réécrit** ; le digest (`@sha256:…`) est **immuable**.
* Garantit que l'image déployée est **exactement** celle qui a été **scannée et signée**.

### 2.2 Commandes (digest & déploiement)

> **Objectif** : Récupérer le digest SHA256 d'une image taguée via skopeo, puis déployer cette image par digest avec Helm pour garantir l'immutabilité.
> **Pre-requis** : `skopeo` et `jq` installés ; `helm` configuré ; le chart Helm `./deploy/helm/api` existant ; accès au registre `ghcr.io`.

```bash
# Inspecte l'image distante via skopeo et extrait le champ Digest avec jq
# Le digest est l'identifiant immuable de l'image (hash du manifest)
skopeo inspect docker://ghcr.io/acme/billing/api:1.4.2 | jq -r .Digest
# -> sha256:ABCD...

# Déploiement Helm en utilisant le digest plutôt que le tag
# image.repository = registre/org/projet/service (sans tag)
# image.digest     = sha256 récupéré ci-dessus (immuable)
# --wait           = attend que les Pods soient Ready avant de rendre la main
helm upgrade --install api ./deploy/helm/api -n app \
  --set image.repository=ghcr.io/acme/billing/api \
  --set image.digest=sha256:ABCD... \
  --wait
```

> **Résultat attendu** :
> ```
> sha256:a1b2c3d4e5f6...
> Release "api" has been upgraded. Happy Helming!
> NAME: api
> NAMESPACE: app
> STATUS: deployed
> ```
> **Vérification** : `kubectl get pod -n app -o jsonpath='{.items[*].spec.containers[*].image}'` doit afficher l'image avec `@sha256:...` et non un tag.

### 2.3 Politiques internes (immutabilité)

* Interdire **tout redepôt** d'un tag **prod** (paramètres du registre).
* **Promotion** = re-tag/copie **sans rebuild** (préserve le digest) :

> **Objectif** : Promouvoir une image d'un registre source (ghcr.io) vers un registre interne (harbor.local) sans la reconstruire, ce qui préserve le digest et garantit l'intégrité.
> **Pre-requis** : `skopeo` installé ; authentification configurée sur les deux registres (`skopeo login`) ; l'image source `ghcr.io/acme/billing/api:1.4.2` doit exister.

  ```bash
  # Copie l'image du registre source vers le registre cible
  # Le digest est préservé car c'est une copie binaire (pas de rebuild)
  # docker:// indique un registre distant (par opposition à dir: ou oci:)
  skopeo copy docker://ghcr.io/acme/billing/api:1.4.2 \
               docker://harbor.local/acme/billing/api:1.4.2
  ```

> **Résultat attendu** :
> ```
> Getting image source signatures
> Copying blob sha256:...
> Copying config sha256:...
> Writing manifest to image destination
> ```
> **Vérification** : `skopeo inspect docker://harbor.local/acme/billing/api:1.4.2 | jq -r .Digest` doit retourner le même digest que l'image source.

---

## 3) Rétention & Garbage Collection (registre)

### 3.1 Principes

* **Rétention par environnement** (ex. dev 14 j, staging 30 j, prod 12–24 mois).
* **Immutabilité** sur tags **prod**.
* **GC planifié** (nettoie couches orphelines après suppression de tags).

### 3.2 Exemples (typologies de règles)

* **Harbor** : politiques "Keep n most recently pulled/pushed", "Exclude by label/pattern".
* **GitLab Container Registry** : régles de nettoyage (keep latest N, regex par branche).
* **GHCR** : nettoyage via workflow/outil (pas de GC natif fin → script de rétention par API).

> Conseil : **tagger par version SemVer** + **labels d'environnements** puis appliquer des règles simples et auditées ("keep last N per minor", "delete rc/beta older than 30d"…).

---

## 4) SBOM obligatoire, scan & signatures

### 4.1 SBOM (composition logicielle)

> **Objectif** : Générer une SBOM (Software Bill of Materials) au format SPDX pour l'image, puis la publier comme artefact OCI associé à l'image dans le registre.
> **Pre-requis** : `syft` installé (generateur SBOM) ; `oras` installé (push d'artefacts OCI) ; accès en lecture au registre `ghcr.io` ; accès en écriture pour pousser l'artefact.

```bash
# Génère la SBOM de l'image au format SPDX-JSON
# syft analyse les couches, packages système, deps langage, etc.
syft ghcr.io/acme/billing/api:1.4.2 -o spdx-json > sbom.spdx.json
# Publie la SBOM comme artefact OCI attaché à l'image
# Le tag sbom-1.4.2 lie la SBOM à la version de l'image
# --artifact-type indique le MIME type du contenu
oras push ghcr.io/acme/billing/api:sbom-1.4.2 \
  --artifact-type application/spdx+json sbom.spdx.json
```

> **Résultat attendu** :
> ```
> {"spdxVersion":"SPDX-2.3", "dataLicense":"CC0-1.0", ...}
> Uploaded application/spdx+json sbom.spdx.json
> Digest: sha256:xxxx...
> ```
> **Vérification** : `oras pull ghcr.io/acme/billing/api:sbom-1.4.2` doit récupérer le fichier SBOM ; `cat sbom.spdx.json | jq .spdxVersion` doit afficher `"SPDX-2.3"`.

* **Format** : SPDX ou CycloneDX.
* SBOM **versionnée** et **liée** à l'image (annexe de release).

### 4.2 Scan vulnérabilités & licences (bloquant)

> **Objectif** : Scanner l'image avec Trivy pour détecter les vulnérabilités HIGH et CRITICAL non corrigées. La commande échoue (exit-code 1) si des CVE sont trouvées, bloquant ainsi le pipeline CI.
> **Pre-requis** : `trivy` installé ; accès au registre (ou image en local) ; base de données de vulnérabilités Trivy à jour (`trivy image --download-db-only`).

```bash
# Scanne l'image pour les sévérités HIGH et CRITICAL
# --ignore-unfixed : ignore les CVE sans correctif disponible (réduit le bruit)
# --exit-code 1    : retourne un code de sortie 1 si des CVE sont trouvées
#                    → fait échouer le job CI automatiquement
trivy image ghcr.io/acme/billing/api:1.4.2 \
  --severity HIGH,CRITICAL \
  --ignore-unfixed \
  --exit-code 1                # échoue la CI si CVE graves
```

> **Résultat attendu** (si aucune CVE) :
> ```
> Total: 0 (HIGH: 0, CRITICAL: 0)
> ```
> **Résultat attendu** (si CVE trouvées) :
> ```
> Total: 3 (HIGH: 2, CRITICAL: 1)
> +---------+------------------+----------+-------------------+
> | Library | Vulnerability ID | Severity | Installed Version |
> +---------+------------------+----------+-------------------+
> | openssl | CVE-2025-XXXX    | CRITICAL | 1.1.1k            |
> +---------+------------------+----------+-------------------+
> ERROR: found vulnerabilities (exit code 1)
> ```
> **Vérification** : En CI, le job doit échouer si des CVE HIGH/CRITICAL unfixed existent. Utiliser `.trivyignore` pour les exceptions datées et justifiées.

* Exceptions via `.trivyignore` **datées** et **justifiées** (expiration).

### 4.3 Signature **cosign** (clé ou keyless/OIDC)

> **Objectif** : Signer l'image avec une clé privée cosign (mode "key-based"), puis vérifier la signature avec la clé publique correspondante. Cela garantit l'authenticité et l'intégrité de l'image.
> **Pre-requis** : `cosign` installé ; une paire de clés générée (`cosign generate-key-pair`) ; la clé privée `cosign.key` protégée (en CI, stockée en secret) ; authentification au registre.

```bash
# Signe l'image avec la clé privée cosign
# La signature est stockée dans le registre comme manifest OCI
# cosign.key = clé privée (à garder secrète, jamais committer)
cosign sign --key cosign.key ghcr.io/acme/billing/api:1.4.2

# Vérifie la signature de l'image avec la clé publique
#cosign.pub = clé publique (peut être distribuée)
# Si la signature est valide → sortie OK ; sinon → erreur
cosign verify --key cosign.pub ghcr.io/acme/billing/api:1.4.2
```

> **Résultat attendu** (sign) :
> ```
> Pushing signature to: ghcr.io/acme/billing/api
> ```
> **Résultat attendu** (verify) :
> ```
> Verification is valid -- the image is signed
> ```
> **Vérification** : `cosign verify` doit retourner "Verification is valid". Si l'image est modifiée ou non signée, la commande échoue.

**Keyless (OIDC)** :

> **Objectif** : Signer et vérifier l'image sans clé statique, en utilisant l'identité OIDC (ex: GitHub Actions, GitLab CI). Cosign utilise Sigstore Fulcio (certificat éphémère) et Rekor (transparency log).
> **Pre-requis** : `cosign` installé ; `COSIGN_EXPERIMENTAL=1` activé ; un fournisseur OIDC configuré (ex: `ACTIONS_ID_TOKEN_REQUEST_TOKEN` dans GitHub Actions) ; accès au registre.

```bash
# Active le mode expérimental keyless (OIDC via Sigstore/Fulcio)
# cosign demande un certificat éphémère lié à l'identité OIDC du runner CI
COSIGN_EXPERIMENTAL=1 cosign sign ghcr.io/acme/billing/api:1.4.2
# Vérifie la signature keyless en validant le certificat via Rekor (transparency log)
COSIGN_EXPERIMENTAL=1 cosign verify ghcr.io/acme/billing/api:1.4.2
```

> **Résultat attendu** :
> ```
> Retrieving signed certificate...
# Successfully verified SCT...
> Pushing signature to: ghcr.io/acme/billing/api
> ```
> **Vérification** : La sortie de `verify` doit montrer le certificat Fulcio et l'entrée Rekor. L'identité OIDC (issuer + subject) doit correspondre au CI attendu.

* Attestations (provenance/SBOM) :

> **Objectif** : Créer une attestation cosign liant la SBOM SPDX à l'image. L'attestation est un objet signé qui prouve que la SBOM est bien associée à cette image spécifique.
> **Pre-requis** : `cosign` installé ; le fichier `sbom.spdx.json` généré (voir §4.1) ; authentification au registre ; une clé cosign ou mode keyless configuré.

  ```bash
  # Attache une attestation de type SPDX à l'image
  # --predicate = le fichier de preuve (ici la SBOM)
  # --type spdx = format du predicate (spdx, cyclonedx, slsaprovenance, etc.)
  # L'attestation est signée et stockée dans le registre
  cosign attest --predicate sbom.spdx.json \
    --type spdx \
    ghcr.io/acme/billing/api:1.4.2
  ```

> **Résultat attendu** :
> ```
> Pushing attestation to: ghcr.io/acme/billing/api
> ```
> **Vérification** : `cosign verify-attestation --type spdx --key cosign.pub ghcr.io/acme/billing/api:1.4.2` doit retourner le contenu de l'attestation vérifié.

---

## 5) Politiques d'admission (cluster)

### 5.1 Interdire `:latest` (Gatekeeper **OPA**)

> **Objectif** : Déployer une politique Gatekeeper (OPA) qui refuse tout Pod dont un conteneur utilise l'image avec le tag `:latest`. Cela force les équipes à utiliser des tags explicites ou des digests.
> **Pre-requis** : Gatekeeper installé sur le cluster (`kubectl get pods -n gatekeeper-system`) ; le CRD `ConstraintTemplate` disponible ; droits admin sur le cluster.

```yaml
# --- ConstraintTemplate : définit le type de contrainte et la logique Rego ---
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8sdenylatest  # nom unique du template
spec:
  crd:
    spec:
      names:
        kind: K8sDenyLatest  # nom du CRD de contrainte qui sera créé
  targets:
  - target: admission.k8s.gatekeeper.sh  # cible : admission webhook K8s
    rego: |
      package k8sdenylatest
      # Parcourt tous les conteneurs du Pod
      violation[{"msg": msg}] {
        c := input.review.object.spec.template.spec.containers[_]
        # Vérifie si l'image se termine par ":latest"
        endswith(c.image, ":latest")
        # Message d'erreur avec le nom de l'image fautive
        msg := sprintf("image %v uses :latest", [c.image])
      }
---
# --- Constraint : instance de la contrainte (active la politique) ---
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sDenyLatest
metadata:
  name: deny-latest  # nom de l'instance de contrainte
spec: {}  # pas de filtre supplémentaire → s'applique à tout le cluster
```

> **Résultat attendu** :
> ```
> constrainttemplate.templates.gatekeeper.sh/k8sdenylatest created
> k8sdenylatest.constraints.gatekeeper.sh/deny-latest created
> ```
> **Vérification** : Tenter de créer un Pod avec `image: nginx:latest` doit être rejeté avec le message `image nginx:latest uses :latest`. `kubectl get k8sdenylatest` doit lister `deny-latest`.

### 5.2 Exiger **digest** (Kyverno)

> **Objectif** : Politique Kyverno qui exige que toutes les images de Pods soient référencées par digest (`@sha256:...`) et non par tag. Mode `Enforce` = bloque la création si non conforme.
> **Pre-requis** : Kyverno installé sur le cluster (`kubectl get pods -n kyverno`) ; droits admin pour créer des ClusterPolicy.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-image-digest  # nom unique de la politique
spec:
  validationFailureAction: Enforce  # bloque la requête si non conforme (vs Audit = log seulement)
  rules:
  - name: must-use-digest
    match:
      any:
      - resources:
          kinds: ["Pod"]  # s'applique uniquement aux Pods
    validate:
      message: "Les images doivent être référencées par digest."
      pattern:
        spec:
          containers:
          # Le pattern exige que l'image contienne "@sha256:" (wildcard avant et après)
          - image: "*@sha256:*"
```

> **Résultat attendu** :
> ```
> clusterpolicy.kyverno.io/require-image-digest created
> ```
> **Vérification** : Créer un Pod avec `image: nginx:1.4.2` doit être rejeté. Créer un Pod avec `image: nginx@sha256:abc...` doit réussir. `kubectl get clusterpolicy` doit montrer `require-image-digest` avec `Enforce`.

### 5.3 Exiger **signature cosign** (Kyverno)

> **Objectif** : Politique Kyverno qui vérifie la signature cosign des images provenant de `ghcr.io/acme/*`. Seules les images signées avec la clé publique spécifiée sont autorisées.
> **Pre-requis** : Kyverno installé avec le support `verifyImages` ; la clé publique cosign (`cosign.pub`) disponible ; les images cibles déjà signées avec la clé privée correspondante.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-image-signature  # nom de la politique
spec:
  validationFailureAction: Enforce  # bloque si la signature est invalide ou absente
  rules:
  - name: verify-signature
    match:
      any:
      - resources:
          kinds: ["Pod"]  # s'applique aux Pods
    verifyImages:
    # Référence d'images concernées (wildcard sur le namespace du registre)
    - imageReferences: ["ghcr.io/acme/*"]
      attestors:
      - entries:
        - keys:
            # Clé publique cosign utilisée pour vérifier la signature
            # Doit correspondre à la clé privée utilisée lors du cosign sign
            publicKeys: |
              -----BEGIN PUBLIC KEY-----
              ...
              -----END PUBLIC KEY-----
```

> **Résultat attendu** :
> ```
> clusterpolicy.kyverno.io/require-image-signature created
> ```
> **Vérification** : Déployer un Pod avec une image `ghcr.io/acme/*` non signée doit être rejeté. `kubectl get clusterpolicy` doit montrer la politique active. Les logs Kyverno (`-n kyverno`) doivent montrer les vérifications de signature.

### 5.4 (Option) Sigstore **Policy Controller**

* Politique de vérification par **issuer/subject** OIDC (keyless).
* Utile si vous signez **sans clés** statiques (GitHub/GitLab OIDC).

### 5.5 Allow-list registres (Kyverno/Gatekeeper)

* Refuser images hors registres approuvés : `ghcr.io/acme/*`, `harbor.local/*`.

---

## 6) Journalisation & traçabilité

### 6.1 Labels OCI & annotations (provenance)

* **Obligatoires** dans le Dockerfile :

  * `org.opencontainers.image.version`, `revision`, `source`, `created`, `authors`…
* Exploitables dans vos dashboards et vos **audits** (extraction via `docker image inspect`).

### 6.2 Journalisation Kubernetes (Audit Policy)

**AuditPolicy** (extrait) pour journaliser la **création** de Pods/Jobs :

> **Objectif** : Configurer la politique d'audit Kubernetes pour journaliser au niveau RequestResponse les opérations de création/modification sur les Pods et Jobs. Cela permet de tracer qui a déployé quoi et quand.
> **Pre-requis** : Cluster K8s avec l'audit log activé (flag `--audit-policy-file` sur l'API Server) ; un backend de sortie configuré (fichier ou webhook).

```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
# Niveau RequestResponse = log complet (metadata + body de la requête et réponse)
- level: RequestResponse
  # Journaux uniquement pour les opérations d'écriture (création, modification)
  verbs: ["create","update","patch"]
  resources:
  # Groupe core (api "") = Pods
  - group: ""
    resources: ["pods"]
  # Groupe "batch" = Jobs et CronJobs
  - group: "batch"
    resources: ["jobs","cronjobs"]
```

> **Résultat attendu** :
> ```
> # Dans le fichier d'audit log (ex: /var/log/kubernetes/audit.log) :
> {"kind":"Event","level":"RequestResponse","verb":"create",
>  "resources":[{"resource":"pods"}],"objectRef":{"name":"api-xyz"},...}
> ```
> **Vérification** : Créer un Pod puis vérifier le fichier d'audit ou le webhook. `kubectl create pod test --image=nginx` doit générer un événement `level: RequestResponse` dans les logs d'audit.

* Sortie vers **fichier** ou **webhook** (stack logs : Loki/Elastic).
* Lien avec **runbooks** (annotation `runbook_url` sur alertes).

### 6.3 Journalisation du **registre**

* Activer **audit logs** côté registre (Harbor : system logs, GHCR : via API/événements, GitLab : activity).
* **Conserver** : actions push/pull/delete, changements de politique, **GC**.

---

## 7) Process d'exceptions & gouvernance

1. **Demande** d'exception (ticket) : description, **CVE**, justification, durée.
2. **Validation** sécurité (RSSI) + **périmètre** (namespace/service) + **expiration**.
3. **Mise en œuvre contrôlée** :

   * Règle temporaire Kyverno/Gatekeeper ciblée (label/namespace).
   * `.trivyignore` / allowlist **datée**.
4. **Sortie d'exception** : patch correctif livré, exception **révoquée**.

**Exemple Kyverno "exception par label"**

> **Objectif** : Configurer une règle Kyverno en mode Audit (non bloquant) qui cible uniquement les Pods portant un label d'exception spécifique (ex: `exception-cve: CVE-2025-XXXX`). Cela permet de suivre les dérogations sans bloquer le déploiement.
> **Pre-requis** : Kyverno installé ; un ticket d'exception validé par le RSSI ; le label `exception-cve` défini sur les Pods concernés.

```yaml
match:
  any:
  - resources:
      kinds: ["Pod"]
      selector:
        matchLabels:
          # Cible uniquement les Pods portant ce label d'exception
          exception-cve: "CVE-2025-XXXX"
# Mode Audit = ne bloque pas la création, mais logue et alerte
# Permet de suivre l'usage de l'exception sans interrompre le service
validationFailureAction: Audit     # ne bloque pas, mais alerte
```

> **Résultat attendu** :
> ```
> # Les Pods avec le label sont audités mais pas bloqués
> # Kyverno Policy Report montre :
> kind: PolicyReport
> results:
> - policy: require-image-digest
>   rule: must-use-digest
>   result: warn   # warn car mode Audit
>   resources: [{name: api-xyz, labels: {exception-cve: CVE-2025-XXXX}}]
> ```
> **Vérification** : `kubectl get policyreport -n app` doit montrer des entrées `result: warn` pour les Pods avec le label d'exception. Les Pods sans ce label restent en mode `Enforce`.

---

## 8) KPI & contrôles de conformité (à auditer mensuellement)

* % d'images **déployées par digest** (objectif : 100%).
* % d'images **signées** (objectif : 100% prod).
* **Délai moyen** de résolution CVE **CRITICAL/HIGH**.
* **Couverture SBOM** : 100% des images.
* Taux d'**échec admission** (policies) & temps de résolution.
* **Âge moyen** des bases images (renouvellement).
* **Taille moyenne** des images & temps de **pull** (optimisation).

---

## 9) Aide-mémoire (commandes clés)

> **Objectif** : Regrouper toutes les commandes essentielles de gouvernance d'images en un seul bloc : récupération du digest, génération de SBOM, scan de vulnérabilités, signature/vérification, et déploiement Helm par digest.
> **Pre-requis** : `skopeo`, `jq`, `syft`, `oras`, `trivy`, `cosign`, `helm` installés ; authentification au registre `ghcr.io` configurée ; le chart Helm `./deploy/helm/api` existant.

```bash
# === DIGEST IMMUTABLE ===
# Récupère le digest SHA256 de l'image taguée via skopeo
skopeo inspect docker://ghcr.io/acme/billing/api:1.4.2 | jq -r .Digest

# === SBOM (Software Bill of Materials) ===
# Génère la SBOM au format SPDX-JSON et la sauvegarde dans un fichier
syft ghcr.io/acme/billing/api:1.4.2 -o spdx-json > sbom.spdx.json
# Publie la SBOM comme artefact OCI dans le registre (lié à l'image)
oras push ghcr.io/acme/billing/api:sbom-1.4.2 --artifact-type application/spdx+json sbom.spdx.json

# === SCAN VULNÉRABILITÉS (bloquant en CI) ===
# Scanne l'image, échoue si des CVE HIGH ou CRITICAL sont trouvées
trivy image ghcr.io/acme/billing/api:1.4.2 --severity HIGH,CRITICAL --exit-code 1

# === SIGNATURE & VÉRIFICATION COSIGN ===
# Signe l'image (mode keyless OIDC par défaut si COSIGN_EXPERIMENTAL=1)
cosign sign ghcr.io/acme/billing/api:1.4.2
# Vérifie que l'image est bien signée
cosign verify ghcr.io/acme/billing/api:1.4.2

# === DÉPLOIEMENT HELM PAR DIGEST ===
# Capture le digest dans une variable shell
DIGEST=$(skopeo inspect docker://ghcr.io/acme/billing/api:1.4.2 | jq -r .Digest)
# Déploie/upgrade avec Helm en utilisant le digest (immutabilité garantie)
helm upgrade --install api ./deploy/helm/api -n app \
  --set image.repository=ghcr.io/acme/billing/api \
  --set image.digest=$DIGEST --wait
```

> **Résultat attendu** :
> ```
> # Digest :
> sha256:a1b2c3d4e5f6...
> # SBOM :
> {"spdxVersion":"SPDX-2.3",...}
> Digest: sha256:xxxx...
> # Scan :
> Total: 0 (HIGH: 0, CRITICAL: 0)
> # Signature :
> Pushing signature to: ghcr.io/acme/billing/api
> # Helm :
> Release "api" has been upgraded. Happy Helming!
> STATUS: deployed
> ```
> **Vérification** : Chaque commande doit réussir sans erreur. `kubectl get pod -n app -o jsonpath='{.items[*].spec.containers[*].image}'` doit afficher l'image avec `@sha256:...`.
