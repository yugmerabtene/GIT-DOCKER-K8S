# Chapitre 10 — Packaging & Déploiement applicatif

*(images reproductibles, versionning & promotion, SBOM & signatures, registres, configuration 12-factor, packaging des manifests **(raw/Kustomize/Helm OCI)**, stratégies de déploiement **(Rolling/Blue-Green/Canary)**, hooks & migrations, probes, vérifications, **commandes et champs expliqués en détail**)*

---

## 0) Pré-requis & conventions

* **Organisation** :
  `org = acme` · `app = api` · `registry = ghcr.io` · `ns k8s = app`
  Variables exportées (utiles pour tous les exemples) :

  ```bash
  export ORG=acme APP=api REG=ghcr.io
  export IMG=$REG/$ORG/$APP
  export VER=1.3.0
  export GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
  ```
* **Objectif** : produire un **artefact immuable** (image OCI signée + chart/overlays), déployé **par digest**.
* **Règles** : pas de secrets dans l’image; **config** hors build; **labels OCI** pour la traçabilité; **USER non-root**.

---

## 1) Packaging conteneur — Dockerfile **reproductible** (champ-par-champ)

### 1.1 Arborescence minimale

```
.
├─ Dockerfile
├─ .dockerignore
├─ cmd/app/          # code runnable (ex: main.go / app.py / index.js)
├─ go.mod / pyproject.toml / package.json ...
└─ conf/             # fichiers non sensibles (ex: schémas, seeds publics)
```

### 1.2 `.dockerignore` (réduit le contexte et les couches)

```gitignore
.git
.gitignore
node_modules
**/__pycache__
dist
build
*.log
.env
```

> **Pourquoi** : tout ce qui entre dans le contexte peut finir dans une **couche** : taille ↑, fuite ↑, cache ↓.

### 1.3 Dockerfile multi-stage (exemple **Go**, transposable aux autres langages)

```dockerfile
# syntax=docker/dockerfile:1.7    # Active les features BuildKit (cache/secret/ssh)
FROM golang:1.22@sha256:<digest> AS build
WORKDIR /src

# 1) Dépendances (couche stable)
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download

# 2) Sources (couche volatile)
COPY . .

# 3) Build reproductible
ARG VERSION
ARG GIT_SHA
ARG SOURCE_DATE_EPOCH=1700000000   # fixe les timestamps pour l'empreinte
ENV CGO_ENABLED=0
RUN --mount=type=cache,target=/root/.cache/go-build \
    go build -ldflags "-s -w -X main.version=${VERSION} -X main.commit=${GIT_SHA}" \
    -o /out/app ./cmd/app

# 4) Image runtime minimale (surface d’attaque faible)
FROM gcr.io/distroless/static@sha256:<digest>
USER 10001:10001
COPY --from=build /out/app /app

# 5) Labels OCI = provenance
LABEL org.opencontainers.image.title="api" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/${ORG}/${APP}"

ENTRYPOINT ["/app"]
```

**Décryptage (lignes clés)**

* `# syntax=...` : active **BuildKit** (cache précis, `--mount`, secrets).
* `FROM …@sha256:<digest>` : **pin** la base par **digest** ⇒ build **reproductible**.
* `--mount=type=cache,target=…` : caches **isolés** par étape (accélère les builds).
* `ARG`/`ENV` : version/commit dans le binaire et **labels OCI**.
* `CGO_ENABLED=0` + distroless : binaire **statique**, image **minuscule**, pas de shell.
* `USER 10001` : **non-root** by default.

> **Variantes utiles**
>
> * **Node.js** : multi-stage (deps → prune dev → distroless/nodejs ou gcr.io/distroless/cc + `node` static).
> * **Python** : base slim + **uv**/pip avec `--mount=type=cache,target=/root/.cache/pip`; second stage distroless/python.

---

## 2) Build & tags (options **expliquées**)

### 2.1 Build simple (avec cache et métadonnées)

```bash
DOCKER_BUILDKIT=1 docker build \
  --build-arg VERSION=$VER \
  --build-arg GIT_SHA=$GIT_SHA \
  --build-arg SOURCE_DATE_EPOCH=1700000000 \
  --label org.opencontainers.image.revision=$GIT_SHA \
  --cache-from type=registry,ref=$IMG:cache \
  --cache-to   type=registry,ref=$IMG:cache,mode=max \
  -t $IMG:$VER \
  -f Dockerfile .
```

**Options clés**

* `DOCKER_BUILDKIT=1` : active BuildKit.
* `--cache-from/to type=registry,ref=…` : **cache distribué** entre runners CI.
* `-t $IMG:$VER` : tag **versionné** (SemVer).
* `--label` : **traçabilité** (visible via `docker image inspect`).

### 2.2 Multi-arch (amd64/arm64) avec **buildx**

```bash
docker buildx create --name builder || true
docker buildx use builder
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --build-arg VERSION=$VER --build-arg GIT_SHA=$GIT_SHA \
  -t $IMG:$VER \
  --push .
```

* `--platform` : construit **plusieurs architectures**.
* `--push` : pousse immédiatement (nécessaire pour multi-arch manifest).

### 2.3 Inspection & digest

```bash
docker pull $IMG:$VER
docker image inspect $IMG:$VER --format '{{.Id}}'
skopeo inspect docker://$IMG:$VER | jq -r .Digest   # sha256:...
```

> **Digest** = référence **immut**ible pour déployer.

---

## 3) SBOM, scan & signature (supply-chain)

### 3.1 SBOM + scan (CLI)

```bash
syft $IMG:$VER -o spdx-json > sbom.spdx.json
trivy image $IMG:$VER --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1
```

* `syft` : inventorie paquets/libs → **SPDX** (ou **CycloneDX**).
* `trivy --exit-code 1` : **échoue** si vulnérabilités **critiques**.

### 3.2 Signatures **Cosign**

```bash
cosign sign --key cosign.key $IMG:$VER
cosign verify --key cosign.pub $IMG:$VER
```

* **Signer** puis **vérifier** en CI/CD; admission (chap. 8) peut **refuser** si non signé.
* Optionnel : **attestations** (SBOM, provenance) via `cosign attest`.

---

## 4) Registres, login, push & **promotion** (sans rebuild)

### 4.1 Login & push

```bash
echo "$REG_TOKEN" | docker login $REG -u "$REG_USER" --password-stdin
docker push $IMG:$VER
```

### 4.2 Promotion entre registres **sans rebuild** (air-gapped friendly)

```bash
skopeo copy docker://$IMG:$VER docker://harbor.local/$ORG/$APP:$VER
```

### 4.3 Bonnes pratiques registres

* **Immutabilité** activée sur tags prod; **rétention/GC** planifiés.
* **Pull-through cache**/mirrors pour accélérer.
* **Autoriser** uniquement des registres **allow-list** (policy Kyverno).

---

## 5) Configuration **12-factor** (ConfigMap/Secret/ENV)

### 5.1 Manifests (champs **expliqués**)

```yaml
apiVersion: v1
kind: ConfigMap
metadata: { name: api-config, namespace: app }
data:
  APP_ENV: "prod"
  DB_HOST: "db.app.svc.cluster.local"
---
apiVersion: v1
kind: Secret
metadata: { name: db-creds, namespace: app }
type: Opaque
stringData:                 # clair dans Git ? → SOPS/SealedSecret recommandé
  DB_USER: "app"
  DB_PASS: "s3cret!"
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: api, namespace: app, labels: { app: api } }
spec:
  replicas: 3
  selector: { matchLabels: { app: api } }
  template:
    metadata: { labels: { app: api } }
    spec:
      automountServiceAccountToken: false
      containers:
      - name: api
        image: ghcr.io/acme/api:1.3.0
        imagePullPolicy: IfNotPresent
        envFrom:                   # variables non sensibles
          - configMapRef: { name: api-config }
        env:                       # secrets précis (éviter envFrom: secretRef)
          - name: DB_USER
            valueFrom: { secretKeyRef: { name: db-creds, key: DB_USER } }
        volumeMounts:
          - name: s-db
            mountPath: /var/run/secrets/db
            readOnly: true
        ports: [ { name: http, containerPort: 8080 } ]
      volumes:
        - name: s-db
          secret: { secretName: db-creds }
```

**Clés** :

* **Secrets montés en fichiers** ⇒ évite fuites via `/proc`/dumps.
* **`automountServiceAccountToken: false`** si l’app n’appelle pas l’API.
* **Labels** homogènes pour la sélection Service/NetPol/Monitors.

---

## 6) Packaging des manifests : **raw**, **Kustomize**, **Helm (OCI)**

### 6.1 **Raw** (rapide, peu flexible)

```bash
kubectl apply -f deploy/raw/
kubectl diff  -f deploy/raw/         # voir les changements avant apply
```

### 6.2 **Kustomize** (overlays par environnement)

**Structure**

```
deploy/kustomize/
 ├─ base/
 │   ├─ deployment.yaml
 │   ├─ service.yaml
 │   └─ kustomization.yaml
 └─ overlays/
     ├─ dev/kustomization.yaml
     └─ prod/kustomization.yaml
```

**`base/kustomization.yaml`**

```yaml
resources:
  - deployment.yaml
  - service.yaml
```

**`overlays/prod/kustomization.yaml`** (champs détaillés)

```yaml
resources: ["../../base"]
images:
  - name: ghcr.io/acme/api
    newName: ghcr.io/acme/api
    newTag: "1.3.0"     # ou digest via newTag: "@sha256:..."
patches:
  - target: { kind: Deployment, name: api }
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 5
      - op: add
        path: /spec/template/spec/containers/0/resources
        value:
          requests: { cpu: "200m", memory: "256Mi" }
          limits:   { cpu: "1",    memory: "512Mi" }
```

**Commandes**

```bash
kustomize build deploy/kustomize/overlays/prod | kubeconform - && \
kustomize build deploy/kustomize/overlays/prod | kubectl apply -f -
```

* `kubeconform -` : **valide** le rendu contre les schémas (évite erreurs de champs).

### 6.3 **Helm** (chart versionné, **push OCI**)

**`Chart.yaml`**

```yaml
apiVersion: v2
name: api
description: API service
type: application
version: 0.3.0      # version du chart
appVersion: "1.3.0" # version applicative
```

**`values.yaml`** (expliqué)

```yaml
image:
  repository: ghcr.io/acme/api    # registre + repo
  tag: "1.3.0"                    # tag (ou vide si digest)
  digest: ""                      # si non vide, priorité au digest
replicaCount: 3

service:
  type: ClusterIP
  port: 8080

resources:
  requests: { cpu: "200m", memory: "256Mi" }
  limits:   { cpu: "1",    memory: "512Mi" }

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: api.example.com
      paths: [ { path: "/", pathType: Prefix } ]
```

**`templates/deployment.yaml`** (image par **digest** prioritaire)

```yaml
spec:
  replicas: {{ .Values.replicaCount }}
  strategy:
    type: RollingUpdate
    rollingUpdate: { maxSurge: 25%, maxUnavailable: 0 }
  template:
    metadata:
      labels: { app: api }
    spec:
      automountServiceAccountToken: false
      containers:
      - name: api
        image: "{{ .Values.image.repository }}{{ if .Values.image.digest }}@{{ .Values.image.digest }}{{ else }}:{{ .Values.image.tag }}{{ end }}"
        imagePullPolicy: IfNotPresent
        ports: [ { name: http, containerPort: 8080 } ]
```

**Workflow commandes**

```bash
# 1) Qualité
helm lint deploy/helm/api
helm template api deploy/helm/api -f values.yaml | kubeconform -

# 2) Package
helm package deploy/helm/api          # => api-0.3.0.tgz

# 3) Push OCI
export HELM_EXPERIMENTAL_OCI=1
helm push oci://$REG/$ORG/charts api-0.3.0.tgz

# 4) Install/Upgrade (par digest)
DIGEST=$(skopeo inspect docker://$IMG:$VER | jq -r .Digest)
helm upgrade --install api oci://$REG/$ORG/charts/api \
  --version 0.3.0 -n app --create-namespace \
  --set image.digest=$DIGEST
```

**Explications**

* `helm template … | kubeconform -` : **rend** les YAML et **valide** avant apply.
* `--set image.digest` : garantit que l’on déploie **exactement** l’artefact testé.

---

## 7) Stratégies de déploiement (rendu + **commandes**)

### 7.1 RollingUpdate (défaut contrôlé)

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 25%       # n pods supplémentaires pendant le rollout
    maxUnavailable: 0   # capacité intacte (prod recommandé)
```

**Commandes**

```bash
kubectl rollout status deploy/api -n app
kubectl rollout history deploy/api -n app
kubectl rollout undo    deploy/api -n app
```

### 7.2 Blue-Green (switch **atomique** du trafic)

**Principe**

* Deux Deployments (`api-blue`, `api-green`) avec `labels: {track: blue|green}`.
* Le **Service** pointe vers `track: blue`, on **bascule** sur `green` quand prêt.

**Service (selector par “track”)**

```yaml
spec:
  selector: { app: api, track: blue }
```

**Bascule (patch)**

```bash
kubectl -n app patch svc api -p '{"spec":{"selector":{"app":"api","track":"green"}}}'
kubectl -n app rollout status deploy/api-green
```

**Rollback** : re-patcher le **Service** vers `blue`.

### 7.3 Canary (progressif, pondéré)

**Ingress NGINX (annotations)** :

```yaml
metadata:
  annotations:
    nginx.ingress.kubernetes.io/canary: "true"
    nginx.ingress.kubernetes.io/canary-weight: "10"   # 10% du trafic
```

**Étapes** : 5% → 10% → 25% → 50% → 100%, avec **vérifications SLO** (erreurs 5xx, p95, saturation) entre étapes.
**Alternative** : Argo Rollouts (poids, analyse automatisée).

---

## 8) Hooks & migrations (Helm **pré/post**)

**Job de migration (idempotent)**

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "5"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 600
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: migrate
        image: ghcr.io/acme/migrator:{{ .Chart.AppVersion }}
        envFrom:
          - secretRef: { name: db-creds }
```

**Clés**

* `hook-delete-policy` : évite l’accumulation de Jobs terminés.
* **Idempotence** : la migration doit pouvoir **repasser** sans dégâts.

---

## 9) Probes & “gates” de trafic (explications fines)

```yaml
readinessProbe:
  httpGet: { path: /healthz, port: http }
  periodSeconds: 5
  timeoutSeconds: 2
  failureThreshold: 3   # ~15 s pour marquer "NotReady"
livenessProbe:
  httpGet: { path: /livez, port: http }
  initialDelaySeconds: 15
  periodSeconds: 10
startupProbe:
  httpGet: { path: /startupz, port: http }
  failureThreshold: 30   # 30*5s = 150s de grâce
  periodSeconds: 5
```

* **readiness** : **garde** l’entrée de trafic (Service/endpoints).
* **liveness** : redémarre si verrou mort.
* **startup** : large fenêtre pour gros démarrages (évite faux positifs liveness).

> **gRPC** : utiliser `grpc.health.v1.Health` (via `grpc` probe si dispo, sinon TCP/exec).

---

## 10) Vérifications post-déploiement (scripts & commandes)

```bash
# 1) Santé & endpoints
kubectl -n app get pods -l app=api -o wide
kubectl -n app get endpoints api
kubectl -n app describe svc api | sed -n '/Endpoints/,$p'

# 2) Smoke test (depuis un pod netshoot)
kubectl -n app run -it net --image=nicolaka/netshoot --rm -- sh -lc \
  "curl -sS http://api.app.svc.cluster.local:8080/healthz && echo OK"

# 3) Images & digests réellement déployés
kubectl -n app get pod -l app=api -o jsonpath='{range .items[*]}{.spec.containers[0].image}{"\n"}{end}'

# 4) Rollout
kubectl -n app rollout status deploy/api
```

---

## 11) Runbooks (dépannage ciblé déploiement)

### A) `ImagePullBackOff`

```bash
kubectl -n app describe pod <pod> | sed -n '/Events/,$p'
kubectl -n app get secret regcred -o yaml    # cred registry ?
```

**Correctifs** : credentials / nom d’image / **egress** NetPol / tag inexistant / limite de tirage côté registry.

### B) `CrashLoopBackOff`

```bash
kubectl -n app logs <pod> --previous
kubectl -n app describe pod <pod> | sed -n '/State:/,/Events/p'
```

**Correctifs** : variables manquantes, schema DB non migré, port/probe erronés → **rollback** Helm si nécessaire.

### C) `Readiness probe failed`

* Corriger path/port; ajouter **startupProbe** si boot long; ajuster **timeouts**.

### D) Blue-Green non basculé

* `kubectl -n app get svc api -o yaml | sed -n '/selector/,$p'` → selector encore `blue`.
* **Patch** le selector; vérifier endpoints.

### E) Canary dégrade les SLO

* Réduire `canary-weight`; surveiller erreurs/latence; retour 0% si persistant; **investiguer** logs/traces.

---

## 12) Bonnes pratiques (check-list)

* **Base images pinées par digest**, **multi-stage**, **USER non-root**, labels **OCI** complets.
* **SBOM** et **scan bloquant** (HIGH/CRITICAL), **signatures** Cosign vérifiées à l’admission.
* **Config** via **ConfigMap/ENV**; **secrets** montés en **fichiers**; jamais dans l’image.
* **Déployer par digest** en prod; **Rolling** (`maxUnavailable: 0`); **Blue-Green/Canary** pour MAJ risquées.
* **Hooks** idempotents; **migrations** testées; **rollback** documenté.
* **Probes** justes; **PDB/HPA** cohérents; **kubeconform** avant apply.
* **Kustomize** : overlays clairs; **Helm** : chart versionné, **push OCI**, `helm lint/template`.
* **Vérifs post-deploy** automatiques (smoke tests) + **observabilité** (chap. 9).

---

## 13) Aide-mémoire (commandes clés)

```bash
# Build / Inspect / Digest
DOCKER_BUILDKIT=1 docker build -t $IMG:$VER .
skopeo inspect docker://$IMG:$VER | jq -r .Digest

# SBOM / Scan / Signature
syft $IMG:$VER -o spdx-json > sbom.spdx.json
trivy image $IMG:$VER --severity HIGH,CRITICAL --exit-code 1
cosign sign --key cosign.key $IMG:$VER && cosign verify --key cosign.pub $IMG:$VER

# Push & Promotion
docker push $IMG:$VER
skopeo copy docker://$IMG:$VER docker://harbor.local/$ORG/$APP:$VER

# Kustomize
kustomize build deploy/kustomize/overlays/prod | kubeconform - | kubectl apply -f -

# Helm OCI
helm lint deploy/helm/api
helm template api deploy/helm/api -f values.yaml | kubeconform -
helm package deploy/helm/api
export HELM_EXPERIMENTAL_OCI=1
helm push oci://$REG/$ORG/charts api-0.3.0.tgz
DIGEST=$(skopeo inspect docker://$IMG:$VER | jq -r .Digest)
helm upgrade --install api oci://$REG/$ORG/charts/api --version 0.3.0 \
  -n app --create-namespace --set image.digest=$DIGEST

# Déploiement / Rollback / Vérifs
kubectl -n app rollout status deploy/api
kubectl -n app get endpoints api
kubectl -n app rollout undo deploy/api
```

