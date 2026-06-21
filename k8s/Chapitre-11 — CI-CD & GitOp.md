# Chapitre 11 — CI/CD & GitOps (aperçu opérationnel **très détaillé**)

*(pipeline : **build → tests → scan CVE/licences → SBOM/provenance → signature → push → déploiement par digest**.
Intégrations : **GitHub Actions / GitLab CI / Jenkins**. CD : **Helm/Kustomize** en push-based et **GitOps** (Argo CD / Flux).
Chaque commande et chaque champ YAML important est **expliqué**.)*

---

## 0) Pré-requis & conventions

Variables communes (tu peux les réutiliser dans tous les blocs) :

```bash
export REG=ghcr.io              # registre (GHCR/Harbor/GitLab Registry…)
export ORG=acme                 # organisation/projet
export APP=api                  # nom de l’app
export IMG=$REG/$ORG/$APP       # ex: ghcr.io/acme/api
export VER=1.3.0                # version SemVer (tag git 'v1.3.0' conseillé)
export GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
```

Buts opérationnels :

* **Artefact unique et immuable** : image OCI **signée**, référencée par **digest** au déploiement.
* **Supply-chain** : SBOM + scan + signature **obligatoires** (cf. Ch. 8 : politiques d’admission « signée », « pas de `:latest` », « digest requis »).
* **Deux modes CD** :

  1. **Push-based** : la CI applique directement sur le cluster (Helm/Kubectl).
  2. **GitOps** : la CI **committe** dans un repo d’infra → **Argo CD/Flux** synchronise.

---

## 1) Pipeline : vue d’ensemble & responsabilités

```
[Développeur → git push / tag]
    ├─ (CI) 1. Build multi-arch (BuildKit/Buildx + cache)
    ├─ (CI) 2. Tests (unitaires/intégration en conteneurs)
    ├─ (CI) 3. Scan (CVE/licences) + SBOM (SPDX/CycloneDX)
    ├─ (CI) 4. Signature (Cosign) + éventuelles attestations SLSA
    ├─ (CI) 5. Push image → registre (récupérer **digest**)
    ├─ (CD) 6A. Déploiement push-based (Helm/Kustomize) par **digest**
    └─ (CD) 6B. Déploiement GitOps (maj fichier valeurs/kustomize → Argo/Flux)
```

---

## 2) Build **reproductible** (BuildKit/Buildx) — commandes & options expliquées

### 2.1 Build (cache distribué)

```bash
DOCKER_BUILDKIT=1 docker build \
  --build-arg VERSION=$VER \                 # insère la version dans le binaire/labels
  --build-arg GIT_SHA=$GIT_SHA \            # trace le commit
  --build-arg SOURCE_DATE_EPOCH=1700000000 \# timestamps stables (reproductibilité)
  --label org.opencontainers.image.revision=$GIT_SHA \
  --cache-from type=registry,ref=$IMG:cache \ # récupère le cache du registre
  --cache-to   type=registry,ref=$IMG:cache,mode=max \ # publie le cache pour les prochains builds
  -t $IMG:$VER \
  -f Dockerfile .
```

* **BuildKit** : parallélisme, `--mount=type=cache`, secrets, empreintes stables.
* **cache-from/to** : **cache partagé** entre runners → builds plus rapides.
* **tag $VER** : on poussera ce tag, mais **on déploiera par digest**.

### 2.2 Multi-arch (amd64/arm64)

```bash
docker buildx create --name builder || true
docker buildx use builder
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --build-arg VERSION=$VER --build-arg GIT_SHA=$GIT_SHA \
  --cache-from type=registry,ref=$IMG:cache \
  --cache-to   type=registry,ref=$IMG:cache,mode=max \
  -t $IMG:$VER \
  --push .
```

* `--platform` : publie un **manifest index** multi-arch.
* `--push` : nécessaire (sinon l’index ne peut pas être créé localement).

### 2.3 Digest & labels (vérifications)

```bash
skopeo inspect docker://$IMG:$VER | jq -r .Digest  # sha256:... (référence immuable)
docker image inspect $IMG:$VER --format '{{json .Config.Labels}}' | jq .
```

---

## 3) Tests **dans des conteneurs** (iso prod)

### 3.1 Unitaires (ex. Python)

```bash
docker run --rm -v "$PWD":/app -w /app python:3.12 \
  bash -lc "pip install -r requirements.txt && pytest -q --maxfail=1 --disable-warnings"
```

* `-v`/`-w` : **monte** le code et définit le **répertoire de travail**.
* **Code retour** `pytest` => succès/échec du job CI.

### 3.2 Intégration (docker compose éphémère)

`compose.yaml` (extrait) :

```yaml
services:
  api:
    build: .
    environment:
      DB_HOST: db
    depends_on: [ db ]
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: test
```

CI :

```bash
docker compose up -d --build
docker compose run --rm api pytest -q
docker compose down -v      # -v: supprime les volumes → pas d’état persistant parasite
```

---

## 4) Scan CVE/licences & **SBOM**

### 4.1 SBOM & Scan (bloquant)

```bash
syft $IMG:$VER -o spdx-json > sbom.spdx.json   # inventaire composants
trivy image $IMG:$VER \
  --severity HIGH,CRITICAL \   # échoue sur CVE sévères
  --ignore-unfixed \           # optionnel: ignore CVE sans correctif (politique)
  --exit-code 1 \
  --format table
```

* **SBOM** : preuve de composition (SPDX/CycloneDX).
* **Trivy** : peut aussi **scanner licences** (`--ignore-policy` pour allowlist).

---

## 5) Signature & provenance (**Cosign**)

### 5.1 Signature « clé »

```bash
cosign sign --key cosign.key $IMG:$VER
cosign verify --key cosign.pub $IMG:$VER
```

### 5.2 Signature **keyless OIDC** (GitHub/GitLab)

```bash
COSIGN_EXPERIMENTAL=1 cosign sign $IMG:$VER
COSIGN_EXPERIMENTAL=1 cosign verify $IMG:$VER
```

* **Attributs d’identité** (issuer, subject) enregistrés → **vérifiables** côté cluster.
* Possibles **attestations** (SLSA provenance, SBOM) via `cosign attest`.

---

## 6) Push & **promotion** d’images (sans rebuild)

### 6.1 Login & push

```bash
echo "$REG_TOKEN" | docker login $REG -u "$REG_USER" --password-stdin
docker push $IMG:$VER
```

### 6.2 Promotion (ex. GHCR → Harbor) **sans rebuild**

```bash
skopeo copy docker://$IMG:$VER docker://harbor.local/$ORG/$APP:$VER
```

* **Préserve le digest** (trace immuable).

---

## 7) **Déploiement push-based** (Helm/Kustomize) — par **digest**

### 7.1 Helm (image par digest, explications flags)

```bash
DIGEST=$(skopeo inspect docker://$IMG:$VER | jq -r .Digest)

helm upgrade --install api ./deploy/helm/api \
  -n app --create-namespace \         # crée le namespace au besoin
  --set image.repository=$IMG \       # repo de l’image
  --set image.digest=$DIGEST \        # digest précis (immutabilité)
  --wait --timeout 5m                 # attend readiness/health, sinon échec CI
```

* `--wait/--timeout` : **garde-fou** (évite « déploiement vert » alors que non prêt).
* **Rollback** Helm en cas d’échec post-checks (voir runbooks).

### 7.2 Kustomize (overlays)

```bash
kustomize build deploy/kustomize/overlays/prod | kubeconform - && \
kustomize build deploy/kustomize/overlays/prod | kubectl apply -f -
kubectl -n app rollout status deploy/api
```

* `kubeconform -` : **valide** le rendu contre les schémas.

---

## 8) **GitOps** (Argo CD / Flux) — principes et manifests

### 8.1 Organisation des dépôts

* **Repo applicatif** : code + Dockerfile + chart Helm base / kustomize base.
* **Repo d’infra (GitOps)** : dossiers `envs/dev|staging|prod` (values Helm ou overlays Kustomize).

  * La CI **modifie** le repo d’infra (commit du **digest**), puis **Argo/Flux** synchronise.

---

### 8.2 Argo CD — `Application` (Helm par exemple)

`argocd-app-api.yaml`

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: api
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/acme/infra.git     # repo d’infra (GitOps)
    targetRevision: main
    path: envs/prod/helm/api                       # dossier chart/values
    helm:
      valueFiles: [ "values-prod.yaml" ]           # fichier où l’on met le digest
  destination:
    server: https://kubernetes.default.svc
    namespace: app
  syncPolicy:
    automated:
      prune: true         # supprime les objets orphelins
      selfHeal: true      # corrige les dérives
    syncOptions:
      - CreateNamespace=true
      - ApplyOutOfSyncOnly=true
```

* **Argo** lit le repo d’infra et **applique** les changements.
* **Promotion** : PR vers `envs/prod` (review/approbation), merge ⇒ Argo sync.

**Mettre à jour le digest (CI côté repo infra)** :

```bash
# Dans le repo d’infra:
export DIGEST=$(skopeo inspect docker://$IMG:$VER | jq -r .Digest)
yq -i '.image.repository=strenv(IMG) | .image.digest=strenv(DIGEST)' envs/prod/helm/api/values-prod.yaml
git commit -am "api: $VER ($DIGEST)" && git push origin main
```

> Alternative Argo : **Argo Image Updater** (scrute le registre et ouvre des PRs pour bump tag/digest).

---

### 8.3 FluxCD — GitRepository + (HelmRelease **ou** Kustomization)

**Référencer le repo d’infra**

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata: { name: infra, namespace: flux-system }
spec:
  interval: 1m
  url: https://github.com/acme/infra.git
  ref: { branch: main }
```

**Déployer un chart Helm (HelmRelease)**
`HelmRelease` (digest dans `values`) :

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata: { name: api, namespace: app }
spec:
  interval: 1m
  chart:
    spec:
      chart: ./envs/prod/helm/api
      sourceRef:
        kind: GitRepository
        name: infra
        namespace: flux-system
  values:
    image:
      repository: ghcr.io/acme/api
      digest: "sha256:ABCD..."    # CI met à jour ce champ par commit
  install: { remediation: { retries: 3 } }
  upgrade: { remediation: { retries: 3 } }
```

**Automatisation du bump d’image (Flux Image Automation)** :

* `ImageRepository` → source registre,
* `ImagePolicy` → règle (tag semver ou latest digest),
* `ImageUpdateAutomation` → commite le fichier `values` ou kustomize image.

---

## 9) Sécurité du pipeline & politiques d’admission (rappel croisé Ch. 8)

* **OIDC** CI → Registre/Cloud (évite secrets statiques).
* **Permissions minimales** (GitHub : `id-token: write`, `packages: write`, rien d’autre).
* **Pas de secrets** dans les logs (masking).
* Admission (Kyverno/OPA/CEL) :

  * **Interdire** `:latest`,
  * **Exiger** `repo@sha256:…`,
  * **Exiger** **signature Cosign** par clef/issuer attendu,
  * **Allow-list** des **registres** autorisés.

---

## 10) Observabilité du CI/CD

* **Artefacts** : SBOM (SPDX/CycloneDX), rapports Trivy (SARIF), coverage/tests (JUnit).
* **Métriques** : durée par stage, taux d’échec, ratio cache hit, temps de pull/push.
* **Alertes** : échec build/test/scan/deploy → Slack/Teams/PagerDuty avec **runbook_url**.

---

## 11) **TD minimal** : pipeline qui build & déploie **par digest** (Helm)

### 11.1 Préparer le chart (déjà posé au Ch. 10)

Dans `values.yaml`, prévoir :

```yaml
image:
  repository: ghcr.io/acme/api
  tag: ""        # non utilisé en prod
  digest: ""     # ← c’est CE champ que la CI renseigne
```

### 11.2 GitHub Actions — workflow minimal annoté

`.github/workflows/ci.yml`

```yaml
name: ci
on:
  push:
    tags: [ 'v*.*.*' ]                 # on déploie sur release tag

jobs:
  build-scan-sign-push-deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write                  # pour cosign keyless
      packages: write
      security-events: write           # upload SARIF
    env:
      REG: ghcr.io
      ORG: acme
      APP: api
    steps:
      - uses: actions/checkout@v4

      - name: Set vars
        run: |
          echo "VER=${GITHUB_REF_NAME#v}" >> $GITHUB_ENV
          echo "IMG=${REG}/${ORG}/${APP}" >> $GITHUB_ENV

      - uses: docker/setup-buildx-action@v3

      - name: Login GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REG }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build & Push (multi-arch + cache)
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          platforms: linux/amd64,linux/arm64
          tags: ${{ env.IMG }}:${{ env.VER }}
          cache-from: type=registry,ref=${{ env.IMG }}:cache
          cache-to:   type=registry,ref=${{ env.IMG }}:cache,mode=max
          build-args: |
            VERSION=${{ env.VER }}
            GIT_SHA=${{ github.sha }}

      - name: Compute digest
        id: dig
        run: echo "DIGEST=$(skopeo inspect docker://${IMG}:${VER} | jq -r .Digest)" >> $GITHUB_OUTPUT

      - name: SBOM (Syft) + Scan (Trivy)
        run: |
          syft ${IMG}:${VER} -o spdx-json > sbom.spdx.json
          trivy image ${IMG}:${VER} --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1

      - name: Sign image (Cosign keyless)
        env: { COSIGN_EXPERIMENTAL: "1" }
        run: cosign sign ${IMG}:${VER}

      - name: Install kubectl & helm
        uses: azure/setup-helm@v4

      - name: Kubeconfig
        run: echo "${KUBECONFIG_B64}" | base64 -d > $HOME/.kube/config
        env:
          KUBECONFIG_B64: ${{ secrets.KUBECONFIG_B64 }}

      - name: Helm upgrade by digest
        run: |
          helm upgrade --install api ./deploy/helm/api -n app --create-namespace \
            --set image.repository=${IMG} --set image.digest=${{ steps.dig.outputs.DIGEST }} \
            --wait --timeout 5m
```

**À noter** :

* `id-token: write` ⇒ **cosign keyless** sans secret.
* **Digest** calculé via `skopeo` puis injecté dans Helm.
* **Scan bloquant** (Trivy) avant signature/push.
* Variante **GitOps** : au lieu du job Helm, **modifier** le `values-prod.yaml` dans le **repo d’infra** (PR/merge), Argo/Flux synchronise.

---

## 12) Runbooks (CI/CD & GitOps)

* **`denied: requested access is denied` (push)**
  → Mauvais login/permissions, repo privé, scope insuffisant. Vérifier `docker login`, droits « write:packages ».

* **`cosign: no identity token` (keyless)**
  → GitHub Actions : vérifier `permissions.id-token: write`.
  → Repli temporaire : signature **avec clé** (secret CI) + rotation.

* **`trivy --exit-code 1`**
  → Lire rapport, patcher base image, ou add `ignorefile` **temporaire** avec justification.

* **`helm --wait` timeout / `Readiness probe failed`**
  → `kubectl -n app get events --sort-by=.lastTimestamp | tail -n 50` ; vérifier probes/port/ingress/netpol.
  → `helm rollback api <REV>` si nécessaire.

* **Argo CD `OutOfSync` en boucle**
  → Diff non géré (CRD non ignorée, drift manuel). Ajouter `ignoreDifferences` si champ géré par opérateur.
  → Vérifier droits du ServiceAccount Argo (RBAC).

* **Flux `reconciliation failed`**
  → Voir `kubectl -n flux-system logs deploy/kustomize-controller` et `helm-controller`.
  → Vérifier la réf Git, droit d’accès au repo, CRD présentes.

---

## 13) Check-list opérationnelle

* [ ] Dockerfile **multi-stage**, **USER non-root**, labels OCI, bases **pinées par digest**.
* [ ] Build **Buildx** multi-arch + **cache** registre.
* [ ] Tests unitaires/intégration (Compose ou services CI).
* [ ] **SBOM** générée ; **scan** CVE/licences **bloquant** (exceptions datées/justifiées).
* [ ] **Signature** Cosign (key/Keyless) + (option) **attestations** provenance/SBOM.
* [ ] **Push** image ; **digest** récupéré.
* [ ] CD **par digest** : Helm/Kustomize (push-based) **ou** PR GitOps vers repo d’infra.
* [ ] Politiques d’admission (Kyverno/OPA/CEL) : **signature requise**, **digest obligatoire**, **no `:latest`**, allow-list registres.
* [ ] Observabilité CI/CD (artefacts, métriques, alertes) + **runbooks** reliés.

