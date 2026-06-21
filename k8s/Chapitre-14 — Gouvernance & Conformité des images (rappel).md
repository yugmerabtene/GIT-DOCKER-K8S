# Chapitre 14 — Gouvernance & Conformité des images (rappel **exigeant & opérationnel**)

*(nomenclature & versions, **immutabilité/digest**, **rétention/GC** registre, **SBOM obligatoire**, **signatures cosign**, **politiques d’admission**, **journalisation & traçabilité**. Chaque commande et champ utile est expliqué.)*

---

## 0) Objectifs

* Normaliser **comment on nomme, versionne et promeut** les images.
* Garantir l’**immutabilité** : déployer **uniquement par digest** (et jamais `:latest`).
* Mettre en place **SBOM, scan et signature** systématiques (supply chain).
* Encadrer via **politiques d’admission** (Kyverno / Gatekeeper / Sigstore Policy Controller).
* Assurer **journalisation & traçabilité** (K8s + registre) et un **process d’exceptions** formalisé.

---

## 1) Nommage & versions (SemVer, canaux)

### 1.1 Conventions de nommage (référentiel)

```
<registry>/<org>/<projet>/<service>[:tag]  ou  @sha256:<digest>
Ex. ghcr.io/acme/billing/api:1.4.2
```

**Recommandations**

* Toujours **minuscule**, noms courts et stables.
* Deux niveaux max après l’org si possible (`projet/service`).
* **Labels OCI** (traçabilité) systématiques :

  ```bash
  docker build \
    --label org.opencontainers.image.title="api" \
    --label org.opencontainers.image.version="$VER" \
    --label org.opencontainers.image.revision="$GIT_SHA" \
    --label org.opencontainers.image.source="https://github.com/acme/billing" \
    -t ghcr.io/acme/billing/api:$VER .
  ```

### 1.2 Versions & canaux

* **SemVer** : `MAJOR.MINOR.PATCH` (ex. `1.4.2`).
* **Pré-release** : `1.5.0-rc.1`, `1.5.0-beta.2`.
* **Canaux** (optionnels) : `dev`, `rc`, `stable`.

  > ⚠️ Ces tags ne sont **pas** des cibles de déploiement long terme : en prod, **déployer par digest**.

---

## 2) Immutabilité & déploiement **par digest**

### 2.1 Pourquoi le digest ?

* `:tag` peut être **réécrit** ; le digest (`@sha256:…`) est **immuable**.
* Garantit que l’image déployée est **exactement** celle qui a été **scannée et signée**.

### 2.2 Commandes (digest & déploiement)

```bash
# Récupérer le digest d’une image taguée
skopeo inspect docker://ghcr.io/acme/billing/api:1.4.2 | jq -r .Digest
# -> sha256:ABCD...

# Helm par digest
helm upgrade --install api ./deploy/helm/api -n app \
  --set image.repository=ghcr.io/acme/billing/api \
  --set image.digest=sha256:ABCD... \
  --wait
```

### 2.3 Politiques internes (immutabilité)

* Interdire **tout redepôt** d’un tag **prod** (paramètres du registre).
* **Promotion** = re-tag/copie **sans rebuild** (préserve le digest) :

  ```bash
  skopeo copy docker://ghcr.io/acme/billing/api:1.4.2 \
               docker://harbor.local/acme/billing/api:1.4.2
  ```

---

## 3) Rétention & Garbage Collection (registre)

### 3.1 Principes

* **Rétention par environnement** (ex. dev 14 j, staging 30 j, prod 12–24 mois).
* **Immutabilité** sur tags **prod**.
* **GC planifié** (nettoie couches orphelines après suppression de tags).

### 3.2 Exemples (typologies de règles)

* **Harbor** : politiques “Keep n most recently pulled/pushed”, “Exclude by label/pattern”.
* **GitLab Container Registry** : régles de nettoyage (keep latest N, regex par branche).
* **GHCR** : nettoyage via workflow/outil (pas de GC natif fin → script de rétention par API).

> Conseil : **tagger par version SemVer** + **labels d’environnements** puis appliquer des règles simples et auditées (“keep last N per minor”, “delete rc/beta older than 30d”…).

---

## 4) SBOM obligatoire, scan & signatures

### 4.1 SBOM (composition logicielle)

```bash
# Générer une SBOM SPDX
syft ghcr.io/acme/billing/api:1.4.2 -o spdx-json > sbom.spdx.json
# Publier la SBOM comme artefact OCI (optionnel)
oras push ghcr.io/acme/billing/api:sbom-1.4.2 \
  --artifact-type application/spdx+json sbom.spdx.json
```

* **Format** : SPDX ou CycloneDX.
* SBOM **versionnée** et **liée** à l’image (annexe de release).

### 4.2 Scan vulnérabilités & licences (bloquant)

```bash
trivy image ghcr.io/acme/billing/api:1.4.2 \
  --severity HIGH,CRITICAL \
  --ignore-unfixed \
  --exit-code 1                # échoue la CI si CVE graves
```

* Exceptions via `.trivyignore` **datées** et **justifiées** (expiration).

### 4.3 Signature **cosign** (clé ou keyless/OIDC)

```bash
# Signature “clé” (clé privée protégée en CI)
cosign sign --key cosign.key ghcr.io/acme/billing/api:1.4.2

# Vérification (CI/CD ou admission)
cosign verify --key cosign.pub ghcr.io/acme/billing/api:1.4.2
```

**Keyless (OIDC)** :

```bash
COSIGN_EXPERIMENTAL=1 cosign sign ghcr.io/acme/billing/api:1.4.2
COSIGN_EXPERIMENTAL=1 cosign verify ghcr.io/acme/billing/api:1.4.2
```

* Attestations (provenance/SBOM) :

  ```bash
  cosign attest --predicate sbom.spdx.json \
    --type spdx \
    ghcr.io/acme/billing/api:1.4.2
  ```

---

## 5) Politiques d’admission (cluster)

### 5.1 Interdire `:latest` (Gatekeeper **OPA**)

```yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata: { name: k8sdenylatest }
spec:
  crd: { spec: { names: { kind: K8sDenyLatest } } }
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

### 5.2 Exiger **digest** (Kyverno)

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: require-image-digest }
spec:
  validationFailureAction: Enforce
  rules:
  - name: must-use-digest
    match: { any: [ { resources: { kinds: ["Pod"] } } ] }
    validate:
      message: "Les images doivent être référencées par digest."
      pattern:
        spec:
          containers:
          - image: "*@sha256:*"
```

### 5.3 Exiger **signature cosign** (Kyverno)

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: require-image-signature }
spec:
  validationFailureAction: Enforce
  rules:
  - name: verify-signature
    match: { any: [ { resources: { kinds: ["Pod"] } } ] }
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

```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
- level: RequestResponse
  verbs: ["create","update","patch"]
  resources:
  - group: ""
    resources: ["pods"]
  - group: "batch"
    resources: ["jobs","cronjobs"]
```

* Sortie vers **fichier** ou **webhook** (stack logs : Loki/Elastic).
* Lien avec **runbooks** (annotation `runbook_url` sur alertes).

### 6.3 Journalisation du **registre**

* Activer **audit logs** côté registre (Harbor : system logs, GHCR : via API/événements, GitLab : activity).
* **Conserver** : actions push/pull/delete, changements de politique, **GC**.

---

## 7) Process d’exceptions & gouvernance

1. **Demande** d’exception (ticket) : description, **CVE**, justification, durée.
2. **Validation** sécurité (RSSI) + **périmètre** (namespace/service) + **expiration**.
3. **Mise en œuvre contrôlée** :

   * Règle temporaire Kyverno/Gatekeeper ciblée (label/namespace).
   * `.trivyignore` / allowlist **datée**.
4. **Sortie d’exception** : patch correctif livré, exception **révoquée**.

**Exemple Kyverno “exception par label”**

```yaml
match:
  any: [{ resources: { kinds: ["Pod"], selector: { matchLabels: { exception-cve: "CVE-2025-XXXX" } } } }]
validationFailureAction: Audit     # ne bloque pas, mais alerte
```

---

## 8) KPI & contrôles de conformité (à auditer mensuellement)

* % d’images **déployées par digest** (objectif : 100%).
* % d’images **signées** (objectif : 100% prod).
* **Délai moyen** de résolution CVE **CRITICAL/HIGH**.
* **Couverture SBOM** : 100% des images.
* Taux d’**échec admission** (policies) & temps de résolution.
* **Âge moyen** des bases images (renouvellement).
* **Taille moyenne** des images & temps de **pull** (optimisation).

---

## 9) Aide-mémoire (commandes clés)

```bash
# Digest immuable
skopeo inspect docker://ghcr.io/acme/billing/api:1.4.2 | jq -r .Digest

# SBOM
syft ghcr.io/acme/billing/api:1.4.2 -o spdx-json > sbom.spdx.json
oras push ghcr.io/acme/billing/api:sbom-1.4.2 --artifact-type application/spdx+json sbom.spdx.json

# Scan (bloquant)
trivy image ghcr.io/acme/billing/api:1.4.2 --severity HIGH,CRITICAL --exit-code 1

# Signature & vérification
cosign sign ghcr.io/acme/billing/api:1.4.2
cosign verify ghcr.io/acme/billing/api:1.4.2

# Helm par digest
DIGEST=$(skopeo inspect docker://ghcr.io/acme/billing/api:1.4.2 | jq -r .Digest)
helm upgrade --install api ./deploy/helm/api -n app \
  --set image.repository=ghcr.io/acme/billing/api \
  --set image.digest=$DIGEST --wait
```

