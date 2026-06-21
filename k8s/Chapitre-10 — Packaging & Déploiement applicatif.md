# Chapitre 10 — Packaging & Déploiement applicatif

*(images reproductibles, versionning & promotion, SBOM & signatures, registres, configuration 12-factor, packaging des manifests **(raw/Kustomize/Helm OCI)**, stratégies de déploiement **(Rolling/Blue-Green/Canary)**, hooks & migrations, probes, vérifications, **commandes et champs expliqués en détail**)*

---

## 0) Pré-requis & conventions

* **Organisation** :
  `org = acme` · `app = api` · `registry = ghcr.io` · `ns k8s = app`
  Variables exportées (utiles pour tous les exemples) :

> **Objectif** : Définir des variables d'environnement réutilisables dans tous les exemples du chapitre (organisation, nom d'app, registre, version, commit Git). Ces variables évitent la duplication et centralisent la configuration.
> **Pre-requis** : Avoir un dépôt Git initialisé (pour `git rev-parse`), et les droits d'accès au registre `ghcr.io`.

  ```bash
  # Définit l'organisation Docker, le nom de l'application et le registre cible
  export ORG=acme APP=api REG=ghcr.io
  # Construit le nom complet de l'image : ghcr.io/acme/api
  export IMG=$REG/$ORG/$APP
  # Version sémantique de la release courante
  export VER=1.3.0
  # Récupère le SHA court du commit HEAD (ou "unknown" si hors repo Git)
  export GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
  ```

> **Resultat attendu** :
> ```
> $ echo $IMG
> ghcr.io/acme/api
> $ echo $VER
> 1.3.0
> $ echo $GIT_SHA
> a1b2c3d
> ```
> **Verification** : `echo $IMG` doit afficher `ghcr.io/acme/api` et `$GIT_SHA` un hash court de 7 caractères.

* **Objectif** : produire un **artefact immuable** (image OCI signée + chart/overlays), déployé **par digest**.
* **Règles** : pas de secrets dans l'image; **config** hors build; **labels OCI** pour la traçabilité; **USER non-root**.

---

## 1) Packaging conteneur — Dockerfile **reproductible** (champ-par-champ)

### 1.1 Arborescence minimale

> **Objectif** : Présenter la structure de fichiers minimale requise pour construire une image conteneur reproductible. Le code source est dans `cmd/app/`, la configuration non sensible dans `conf/`.
> **Pre-requis** : Aucun — il s'agit d'une structure de référence à créer.

```
.
├─ Dockerfile          # Instructions de build multi-stage
├─ .dockerignore       # Exclut les fichiers inutiles du contexte Docker
├─ cmd/app/            # code runnable (ex: main.go / app.py / index.js)
├─ go.mod / pyproject.toml / package.json ...  # Fichiers de dépendances
└─ conf/               # fichiers non sensibles (ex: schémas, seeds publics)
```

> **Resultat attendu** :
> ```
> $ tree .
> .
> ├── Dockerfile
> ├── .dockerignore
> ├── cmd/app/
> │   └── main.go
> ├── go.mod
> ├── go.sum
> └── conf/
> ```
> **Verification** : Chaque fichier/dossier listé doit exister avant de lancer `docker build`.

### 1.2 `.dockerignore` (réduit le contexte et les couches)

> **Objectif** : Exclure du contexte Docker les fichiers inutiles (dépôt Git, dépendances locales, logs, variables d'environnement) pour réduire la taille du contexte, éviter les fuites de données et améliorer le cache.
> **Pre-requis** : Être à la racine du projet.

```gitignore
# Exclut le répertoire Git (historique, hooks) — inutile dans l'image
.git
# Fichier de règles Git — pas nécessaire dans le conteneur
.gitignore
# Dépendances Node.js locales — seront réinstallées dans l'image
node_modules
# Cache Python généré automatiquement
**/__pycache__
# Artéfacts de compilation
dist
build
# Fichiers de logs qui pourraient contenir des données sensibles
*.log
# Variables d'environnement locales — JAMAIS dans l'image
.env
```

> **Pourquoi** : tout ce qui entre dans le contexte peut finir dans une **couche** : taille ↑, fuite ↑, cache ↓.

> **Resultat attendu** :
> ```
> $ docker build .
> Sending build context to Docker daemon  2.5MB   # taille réduite
> ```
> **Verification** : La taille du contexte envoyé doit être nettement inférieure à `du -sh .` (sans .dockerignore).

### 1.3 Dockerfile multi-stage (exemple **Go**, transposable aux autres langages)

> **Objectif** : Construire une image minimale et reproductible en séparant la phase de compilation (stage `build`) de la phase runtime (image distroless). Le binaire statique est compilé avec les métadonnées de version/commit intégrées.
> **Pre-requis** : Avoir `go.mod` et `go.sum` à la racine, le code dans `cmd/app/`, et les variables `$VERSION` / `$GIT_SHA` disponibles.

```dockerfile
# syntax=docker/dockerfile:1.7    # Active les features BuildKit (cache/secret/ssh)
# Épingle l'image de base Go par son digest SHA256 → build reproductible
FROM golang:1.22@sha256:<digest> AS build
# Définit le répertoire de travail dans le conteneur de build
WORKDIR /src

# 1) Dépendances (couche stable)
# Copie uniquement les fichiers de dépendances → cette couche est mise en cache
# tant que go.mod/go.sum ne changent pas (optimisation du cache Docker)
COPY go.mod go.sum ./
# Télécharge les modules Go en utilisant un cache monté (BuildKit)
# Le cache est isolé et persiste entre les builds sans créer de couche
RUN --mount=type=cache,target=/go/pkg/mod go mod download

# 2) Sources (couche volatile)
# Copie tout le code source — cette couche change à chaque modification
COPY . .

# 3) Build reproductible
# Arguments de build injectés au moment de la compilation
ARG VERSION
ARG GIT_SHA
# Fixe les timestamps dans l'archive pour garantir une empreinte identique
ARG SOURCE_DATE_EPOCH=1700000000   # fixe les timestamps pour l'empreinte
# Désactive CGo → produit un binaire 100% statique (pas de libc dynamique)
ENV CGO_ENABLED=0
# Compile le binaire avec cache go-build monté, en injectant version/commit
# -s -w suppriment les symboles de debug → binaire plus léger
RUN --mount=type=cache,target=/root/.cache/go-build \
    go build -ldflags "-s -w -X main.version=${VERSION} -X main.commit=${GIT_SHA}" \
    -o /out/app ./cmd/app

# 4) Image runtime minimale (surface d'attaque faible)
# Image distroless épinglée par digest : pas de shell, pas de package manager
FROM gcr.io/distroless/static@sha256:<digest>
# Exécute le conteneur avec un utilisateur non-root (UID 10001)
USER 10001:10001
# Copie uniquement le binaire compilé depuis le stage build
COPY --from=build /out/app /app

# 5) Labels OCI = provenance
# Métadonnées standard OCI pour la traçabilité de l'image
LABEL org.opencontainers.image.title="api" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/${ORG}/${APP}"

# Point d'entrée unique : le binaire statique
ENTRYPOINT ["/app"]
```

**Décryptage (lignes clés)**

* `# syntax=...` : active **BuildKit** (cache précis, `--mount`, secrets).
* `FROM …@sha256:<digest>` : **pin** la base par **digest** ⇒ build **reproductible**.
* `--mount=type=cache,target=…` : caches **isolés** par étape (accélère les builds).
* `ARG`/`ENV` : version/commit dans le binaire et **labels OCI**.
* `CGO_ENABLED=0` + distroless : binaire **statique**, image **minuscule**, pas de shell.
* `USER 10001` : **non-root** by default.

> **Resultat attendu** :
> ```
> $ docker build --build-arg VERSION=1.3.0 --build-arg GIT_SHA=a1b2c3d -t ghcr.io/acme/api:1.3.0 .
> => [build 5/5] RUN go build -ldflags "..." -o /out/app ./cmd/app
> => [stage-1 2/2] COPY --from=build /out/app /app
> => exporting to image
> => => naming to ghcr.io/acme/api:1.3.0
> $ docker image inspect ghcr.io/acme/api:1.3.0 --format '{{.Size}}'
> 15200000    # ~15 MB (distroless + binaire statique)
> ```
> **Verification** : `docker image inspect` confirme la taille réduite (~15 MB), les labels OCI présents, et l'USER non-root.

> **Variantes utiles**
>
> * **Node.js** : multi-stage (deps → prune dev → distroless/nodejs ou gcr.io/distroless/cc + `node` static).
> * **Python** : base slim + **uv**/pip avec `--mount=type=cache,target=/root/.cache/pip`; second stage distroless/python.

---

## 2) Build & tags (options **expliquées**)

### 2.1 Build simple (avec cache et métadonnées)

> **Objectif** : Construire l'image Docker en activant BuildKit, en injectant les métadonnées de version/commit, et en utilisant un cache distribué via le registre pour accélérer les builds en CI.
> **Pre-requis** : Variables `$IMG`, `$VER`, `$GIT_SHA` exportées (section 0). Docker avec BuildKit activé.

```bash
# Active BuildKit pour ce build (cache avancé, --mount, multi-stage optimisé)
DOCKER_BUILDKIT=1 docker build \
  # Injecte la version sémantique dans le Dockerfile (ARG VERSION)
  --build-arg VERSION=$VER \
  # Injecte le SHA du commit pour la traçabilité dans le binaire
  --build-arg GIT_SHA=$GIT_SHA \
  # Fixe les timestamps pour garantir une empreinte reproductible
  --build-arg SOURCE_DATE_EPOCH=1700000000 \
  # Ajoute un label OCI avec le SHA du commit (visible dans docker inspect)
  --label org.opencontainers.image.revision=$GIT_SHA \
  # Récupère le cache depuis le registre (partage entre runners CI)
  --cache-from type=registry,ref=$IMG:cache \
  # Pousse le cache vers le registre après le build (mode=max = toutes les couches)
  --cache-to   type=registry,ref=$IMG:cache,mode=max \
  # Tag de l'image avec la version sémantique
  -t $IMG:$VER \
  # Spécifie le Dockerfile et le contexte de build
  -f Dockerfile .
```

**Options clés**

* `DOCKER_BUILDKIT=1` : active BuildKit.
* `--cache-from/to type=registry,ref=…` : **cache distribué** entre runners CI.
* `-t $IMG:$VER` : tag **versionné** (SemVer).
* `--label` : **traçabilité** (visible via `docker image inspect`).

> **Resultat attendu** :
> ```
> $ DOCKER_BUILDKIT=1 docker build --build-arg VERSION=1.3.0 --build-arg GIT_SHA=a1b2c3d \
>     --build-arg SOURCE_DATE_EPOCH=1700000000 \
>     --label org.opencontainers.image.revision=a1b2c3d \
>     --cache-from type=registry,ref=ghcr.io/acme/api:cache \
>     --cache-to type=registry,ref=ghcr.io/acme/api:cache,mode=max \
>     -t ghcr.io/acme/api:1.3.0 -f Dockerfile .
> => [build 5/5] RUN go build -ldflags "..." -o /out/app ./cmd/app
> => => naming to ghcr.io/acme/api:1.3.0
> ```
> **Verification** : `docker images ghcr.io/acme/api:1.3.0` affiche l'image. `docker inspect` montre les labels OCI.

### 2.2 Multi-arch (amd64/arm64) avec **buildx**

> **Objectif** : Construire l'image pour plusieurs architectures CPU (amd64 et arm64) afin qu'elle fonctionne sur des nodes hétérogènes. Le manifeste multi-arch est poussé directement dans le registre.
> **Pre-requis** : `docker buildx` installé. Un builder buildx créé. Les variables `$IMG`, `$VER`, `$GIT_SHA` exportées.

```bash
# Crée un builder buildx nommé "builder" (ignore l'erreur s'il existe déjà)
docker buildx create --name builder || true
# Active ce builder pour les builds suivants
docker buildx use builder
# Lance le build multi-architecture et pousse le résultat dans le registre
docker buildx build \
  # Cible les architectures amd64 (x86_64) et arm64 (ARM)
  --platform linux/amd64,linux/arm64 \
  # Injecte les métadonnées de version et commit
  --build-arg VERSION=$VER --build-arg GIT_SHA=$GIT_SHA \
  # Tag de l'image (sera un manifest list pointant vers les 2 archs)
  -t $IMG:$VER \
  # Pousse immédiatement — obligatoire pour multi-arch (le manifest list
  # ne peut pas être stocké localement, il doit être dans le registre)
  --push .
```

* `--platform` : construit **plusieurs architectures**.
* `--push` : pousse immédiatement (nécessaire pour multi-arch manifest).

> **Resultat attendu** :
> ```
> $ docker buildx build --platform linux/amd64,linux/arm64 \
>     --build-arg VERSION=1.3.0 --build-arg GIT_SHA=a1b2c3d \
>     -t ghcr.io/acme/api:1.3.0 --push .
> #13 exporting to image
> #13 pushing layers 3.2s done
> #13 pushing manifest for ghcr.io/acme/api:1.3.0
> #13 DONE 2.1s
> ```
> **Verification** : `docker buildx imagetools inspect $IMG:$VER` affiche les deux manifests (amd64 + arm64).

### 2.3 Inspection & digest

> **Objectif** : Récupérer le digest SHA256 de l'image poussée dans le registre. Ce digest est la référence immuable à utiliser pour le déploiement en production (garantie d'intégrité).
> **Pre-requis** : Image `$IMG:$VER` poussée dans le registre. `skopeo` et `jq` installés.

```bash
# Télécharge l'image localement (optionnel, pour inspection locale)
docker pull $IMG:$VER
# Affiche l'ID interne de l'image (hash de la config, pas le digest du manifest)
docker image inspect $IMG:$VER --format '{{.Id}}'
# Récupère le digest du manifest dans le registre (référence immuable)
skopeo inspect docker://$IMG:$VER | jq -r .Digest   # sha256:...
```

> **Digest** = référence **immut**ible pour déployer.

> **Resultat attendu** :
> ```
> $ docker image inspect ghcr.io/acme/api:1.3.0 --format '{{.Id}}'
> sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4
> $ skopeo inspect docker://ghcr.io/acme/api:1.3.0 | jq -r .Digest
> sha256:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2
> ```
> **Verification** : Le digest (`sha256:...`) retourné par skopeo est la référence à utiliser dans les manifests Kubernetes (`image: ghcr.io/acme/api@sha256:...`).

---

## 3) SBOM, scan & signature (supply-chain)

### 3.1 SBOM + scan (CLI)

> **Objectif** : Générer un inventaire logiciel (SBOM) de l'image au format SPDX et scanner les vulnérabilités connues. Le scan fait échouer le pipeline CI si des vulnérabilités HIGH/CRITICAL non corrigées sont trouvées.
> **Pre-requis** : Image `$IMG:$VER` construite. `syft` et `trivy` installés.

```bash
# Génère un SBOM (Software Bill of Materials) au format SPDX JSON
# Liste tous les paquets, librairies et dépendances contenus dans l'image
syft $IMG:$VER -o spdx-json > sbom.spdx.json
# Scan les vulnérabilités HIGH et CRITICAL uniquement
# --ignore-unfixed : ignore les CVE sans correctif disponible
# --exit-code 1 : fait échouer la commande (et donc le pipeline CI) si des vulnérabilités sont trouvées
trivy image $IMG:$VER --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1
```

* `syft` : inventorie paquets/libs → **SPDX** (ou **CycloneDX**).
* `trivy --exit-code 1` : **échoue** si vulnérabilités **critiques**.

> **Resultat attendu** :
> ```
> $ syft ghcr.io/acme/api:1.3.0 -o spdx-json > sbom.spdx.json
> ✔ Indexed packages       packages=42
> $ trivy image ghcr.io/acme/api:1.3.0 --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1
> Total: 0 (HIGH: 0, CRITICAL: 0)
> # (si aucune vulnérabilité → exit code 0)
> ```
> **Verification** : Le fichier `sbom.spdx.json` est généré. `trivy` retourne exit code 0 (sinon le pipeline CI échoue).

### 3.2 Signatures **Cosign**

> **Objectif** : Signer l'image avec une paire de clés Cosign pour garantir son authenticité et son intégrité. La vérification peut ensuite être automatisée par un contrôleur d'admission Kubernetes (chap. 8) pour refuser les images non signées.
> **Pre-requis** : Paire de clés Cosign générée (`cosign generate-key-pair`). Image `$IMG:$VER` poussée dans le registre. Variable `$COSIGN_PASSWORD` définie.

```bash
# Signe l'image avec la clé privée Cosign
# La signature est stockée dans le registre (à côté de l'image, via OCI)
cosign sign --key cosign.key $IMG:$VER
# Vérifie la signature avec la clé publique
# Échoue si la signature est absente ou invalide
cosign verify --key cosign.pub $IMG:$VER
```

* **Signer** puis **vérifier** en CI/CD; admission (chap. 8) peut **refuser** si non signé.
* Optionnel : **attestations** (SBOM, provenance) via `cosign attest`.

> **Resultat attendu** :
> ```
> $ cosign sign --key cosign.key ghcr.io/acme/api:1.3.0
> Pushing signature to: ghcr.io/acme/api:sha256-a1b2c3d...sig
> $ cosign verify --key cosign.pub ghcr.io/acme/api:1.3.0
> Verification is successful — all validations passed
> ```
> **Verification** : `cosign verify` affiche "Verification is successful". Le registry contient un objet de signature lié au digest de l'image.

---

## 4) Registres, login, push & **promotion** (sans rebuild)

### 4.1 Login & push

> **Objectif** : S'authentifier auprès du registre Docker (ghcr.io) de manière sécurisée (le mot de passe est passé via stdin, pas en argument) puis pousser l'image versionnée.
> **Pre-requis** : Token d'accès au registre dans `$REG_TOKEN`, nom d'utilisateur dans `$REG_USER`. Image `$IMG:$VER` construite localement.

```bash
# Authentification sécurisée : le token est lu depuis stdin (pas visible dans ps)
echo "$REG_TOKEN" | docker login $REG -u "$REG_USER" --password-stdin
# Pousse l'image versionnée vers le registre
docker push $IMG:$VER
```

> **Resultat attendu** :
> ```
> $ echo "$REG_TOKEN" | docker login ghcr.io -u "$REG_USER" --password-stdin
> Login Succeeded
> $ docker push ghcr.io/acme/api:1.3.0
> The push refers to repository [ghcr.io/acme/api]
> a1b2c3d: Pushed
> 1.3.0: digest: sha256:a1b2c3d4... size: 1234
> ```
> **Verification** : `docker push` affiche le digest. L'image est accessible via `docker pull $IMG:$VER` depuis une autre machine.

### 4.2 Promotion entre registres **sans rebuild** (air-gapped friendly)

> **Objectif** : Copier l'image d'un registre public (ghcr.io) vers un registre interne (harbor.local) sans la reconstruire. Utile pour les environnements air-gapped ou pour promouvoir une image de staging vers production.
> **Pre-requis** : `skopeo` installé. Accès en lecture au registre source et en écriture au registre cible. Image `$IMG:$VER` existante dans le registre source.

```bash
# Copie l'image telle quelle d'un registre à l'autre (sans passer par le daemon Docker)
# Préserve le manifest, les couches et les signatures
skopeo copy docker://$IMG:$VER docker://harbor.local/$ORG/$APP:$VER
```

> **Resultat attendu** :
> ```
> $ skopeo copy docker://ghcr.io/acme/api:1.3.0 docker://harbor.local/acme/api:1.3.0
> Getting image source signatures
> Copying blob sha256:...
> Copying config sha256:...
> Writing manifest to image destination
> ```
> **Verification** : `skopeo inspect docker://harbor.local/acme/api:1.3.0` retourne les mêmes métadonnées que l'image source.

### 4.3 Bonnes pratiques registres

* **Immutabilité** activée sur tags prod; **rétention/GC** planifiés.
* **Pull-through cache**/mirrors pour accélérer.
* **Autoriser** uniquement des registres **allow-list** (policy Kyverno).

---

## 5) Configuration **12-factor** (ConfigMap/Secret/ENV)

### 5.1 Manifests (champs **expliqués**)

> **Objectif** : Créer les ressources Kubernetes de configuration (ConfigMap pour les variables non sensibles, Secret pour les identifiants) et un Deployment qui les consomme. Les secrets sont montés en fichiers (pas en variables d'env) pour éviter les fuites via `/proc`.
> **Pre-requis** : Namespace `app` créé. `kubectl` configuré avec accès au cluster.

```yaml
# ConfigMap : stocke les variables de configuration non sensibles
# Accessible en clair, versionnable, modifiable sans rebuild
apiVersion: v1
kind: ConfigMap
metadata:
  name: api-config          # Nom de référence pour les Pods
  namespace: app            # Doit être dans le même namespace que le Deployment
data:
  APP_ENV: "prod"           # Environnement logique de l'application
  DB_HOST: "db.app.svc.cluster.local"  # Nom DNS interne du service DB
---
# Secret : stocke les données sensibles (encodées base64 par k8s)
# En production, utiliser SOPS ou SealedSecret pour le chiffrement Git
apiVersion: v1
kind: Secret
metadata:
  name: db-creds            # Nom de référence pour les Pods
  namespace: app
type: Opaque                # Type générique (clé-valeur arbitraires)
stringData:                 # Accepte du clair (k8s encode en base64 automatiquement)
  DB_USER: "app"            # ⚠ clair dans Git → SOPS/SealedSecret recommandé
  DB_PASS: "s3cret!"
---
# Deployment : orchestre les replicas du conteneur API
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api                 # Nom du Deployment
  namespace: app
  labels:
    app: api                # Label principal pour la sélection Service/NetPol
spec:
  replicas: 3               # Nombre de pods souhaités (HA)
  selector:
    matchLabels:
      app: api              # Sélectionne les pods avec ce label
  template:
    metadata:
      labels:
        app: api            # Label appliqué à chaque pod
    spec:
      # Désactive le montage automatique du token du ServiceAccount
      # À false si l'app n'a pas besoin d'accéder à l'API Kubernetes
      automountServiceAccountToken: false
      containers:
      - name: api
        # Image versionnée (en prod, préférer le digest : image@sha256:...)
        image: ghcr.io/acme/api:1.3.0
        # Ne re-télécharge l'image que si absente localement
        imagePullPolicy: IfNotPresent
        # Injecte TOUTES les clés du ConfigMap comme variables d'environnement
        envFrom:
          - configMapRef:
              name: api-config
        # Injecte les secrets individuellement (plus explicite et sécurisé)
        env:
          - name: DB_USER
            valueFrom:
              secretKeyRef:
                name: db-creds    # Nom du Secret
                key: DB_USER      # Clé spécifique dans le Secret
        volumeMounts:
          - name: s-db
            # Monte le Secret en fichier → évite la fuite via /proc/<pid>/environ
            mountPath: /var/run/secrets/db
            readOnly: true        # Lecture seule (bonne pratique)
        ports:
          - name: http
            containerPort: 8080   # Port d'écoute du conteneur
      volumes:
        - name: s-db
          secret:
            secretName: db-creds  # Référence le Secret défini plus haut
```

**Clés** :

* **Secrets montés en fichiers** ⇒ évite fuites via `/proc`/dumps.
* **`automountServiceAccountToken: false`** si l'app n'appelle pas l'API.
* **Labels** homogènes pour la sélection Service/NetPol/Monitors.

> **Resultat attendu** :
> ```
> $ kubectl apply -f configmap-secret-deploy.yaml
> configmap/api-config created
> secret/db-creds created
> deployment.apps/api created
> $ kubectl -n app get pods -l app=api
> NAME                   READY   STATUS    RESTARTS   AGE
> api-6d4f5b8c9-abc12   1/1     Running   0          10s
> api-6d4f5b8c9-def34   1/1     Running   0          10s
> api-6d4f5b8c9-ghi56   1/1     Running   0          10s
> ```
> **Verification** : 3 pods Running. `kubectl exec` dans un pod : `cat /var/run/secrets/db/DB_PASS` affiche `s3cret!`. `env | grep APP_ENV` affiche `prod`.

---

## 6) Packaging des manifests : **raw**, **Kustomize**, **Helm (OCI)**

### 6.1 **Raw** (rapide, peu flexible)

> **Objectif** : Appliquer directement des fichiers YAML bruts avec kubectl. Méthode simple mais sans paramétrage par environnement. `diff` permet de prévisualiser les changements.
> **Pre-requis** : Fichiers YAML dans `deploy/raw/`. `kubectl` configuré avec accès au cluster.

```bash
# Applique tous les manifests YAML du répertoire deploy/raw/
# Crée ou met à jour les ressources dans le cluster
kubectl apply -f deploy/raw/
# Prévisualise les différences entre l'état actuel et les fichiers YAML
# N'applique rien — sert uniquement à vérifier avant apply
kubectl diff  -f deploy/raw/         # voir les changements avant apply
```

> **Resultat attendu** :
> ```
> $ kubectl apply -f deploy/raw/
> configmap/api-config configured
> deployment.apps/api configured
> service/api unchanged
> $ kubectl diff -f deploy/raw/
> (pas de sortie = aucun changement)
> ```
> **Verification** : `kubectl diff` ne retourne rien si le cluster est à jour. Sinon, il affiche les différences au format unified diff.

### 6.2 **Kustomize** (overlays par environnement)

**Structure**

> **Objectif** : Présenter l'arborescence Kustomize avec une base de manifests partagée et des overlays par environnement (dev, prod) qui appliquent des patches spécifiques.
> **Pre-requis** : Aucun — structure de référence.

```
deploy/kustomize/
 ├─ base/                        # Manifests communs à tous les environnements
 │   ├─ deployment.yaml          # Deployment de base (replicas, image, etc.)
 │   ├─ service.yaml             # Service ClusterIP de base
 │   └─ kustomization.yaml      # Déclare les ressources de la base
 └─ overlays/                    # Patches spécifiques par environnement
     ├─ dev/kustomization.yaml   # Overrides pour dev (ex: replicas=1)
     └─ prod/kustomization.yaml # Overrides pour prod (ex: replicas=5, resources)
```

> **Resultat attendu** :
> ```
> $ tree deploy/kustomize/
> deploy/kustomize/
> ├── base/
> │   ├── deployment.yaml
> │   ├── service.yaml
> │   └── kustomization.yaml
> └── overlays/
>     ├── dev/kustomization.yaml
>     └── prod/kustomization.yaml
> ```
> **Verification** : Chaque `kustomization.yaml` référence les bonnes ressources.

**`base/kustomization.yaml`**

> **Objectif** : Déclarer les fichiers YAML qui composent la base Kustomize (Deployment + Service). Ces ressources seront communes à tous les environnements.
> **Pre-requis** : Fichiers `deployment.yaml` et `service.yaml` présents dans le même répertoire.

```yaml
# Liste les fichiers YAML qui constituent la base
# Kustomize les combinera et appliquera les patches des overlays
resources:
  - deployment.yaml    # Deployment de l'application
  - service.yaml       # Service pour exposer l'application
```

> **Resultat attendu** :
> ```
> $ kustomize build deploy/kustomize/base/
> apiVersion: apps/v1
> kind: Deployment
> metadata:
>   name: api
> spec:
>   replicas: 1
>   ...
> ---
> apiVersion: v1
> kind: Service
> metadata:
>   name: api
>   ...
> ```
> **Verification** : `kustomize build` affiche les manifests combinés de deployment.yaml et service.yaml.

**`overlays/prod/kustomization.yaml`** (champs détaillés)

> **Objectif** : Définir les overrides spécifiques à la production : version de l'image, nombre de replicas, et ressources CPU/mémoire. Utilise des patches JSON pour modifier les champs du Deployment de base.
> **Pre-requis** : Base Kustomize fonctionnelle. `kustomize` ou `kubectl kustomize` disponible.

```yaml
# Référence la base dont ce overlay hérite les ressources
resources: ["../../base"]
# Remplace le tag de l'image par la version de production
images:
  - name: ghcr.io/acme/api       # Nom original de l'image dans la base
    newName: ghcr.io/acme/api    # Même nom (pas de changement de registre)
    newTag: "1.3.0"              # Tag de production (ou "@sha256:..." pour un digest)
# Patches appliqués au Deployment "api" de la base
patches:
  - target:
      kind: Deployment           # Cible les Deployments
      name: api                  # Nommé "api"
    patch: |-
      # Patch JSON Patch (RFC 6902) pour modifier des champs spécifiques
      - op: replace              # Remplace la valeur existante
        path: /spec/replicas     # Chemin JSON vers le champ replicas
        value: 5                 # 5 replicas en production
      - op: add                  # Ajoute un champ (ou remplace s'il existe)
        path: /spec/template/spec/containers/0/resources
        value:
          # Ressources garanties (réservées par le scheduler)
          requests: { cpu: "200m", memory: "256Mi" }
          # Ressources maximales (au-delà → throttling ou OOMKill)
          limits:   { cpu: "1",    memory: "512Mi" }
```

> **Resultat attendu** :
> ```
> $ kustomize build deploy/kustomize/overlays/prod/
> apiVersion: apps/v1
> kind: Deployment
> metadata:
>   name: api
> spec:
>   replicas: 5
>   template:
>     spec:
>       containers:
>       - name: api
>         image: ghcr.io/acme/api:1.3.0
>         resources:
>           requests: { cpu: "200m", memory: "256Mi" }
>           limits:   { cpu: "1",    memory: "512Mi" }
> ```
> **Verification** : Le rendu montre `replicas: 5`, l'image taguée `1.3.0`, et les resources requests/limits.

**Commandes**

> **Objectif** : Valider le rendu Kustomize avec kubeconform (vérifie les schémas Kubernetes) puis l'appliquer au cluster. Le pipe permet de valider avant d'appliquer.
> **Pre-requis** : `kustomize` et `kubeconform` installés. Accès au cluster Kubernetes.

```bash
# Génère les manifests YAML et les valide contre les schémas officiels Kubernetes
# Si kubeconform échoue, le && empêche l'apply (gate de qualité)
kustomize build deploy/kustomize/overlays/prod | kubeconform - && \
# Si la validation passe, applique les manifests au cluster
kustomize build deploy/kustomize/overlays/prod | kubectl apply -f -
```

* `kubeconform -` : **valide** le rendu contre les schémas (évite erreurs de champs).

> **Resultat attendu** :
> ```
> $ kustomize build deploy/kustomize/overlays/prod | kubeconform -
> (aucune sortie = validation réussie)
> $ kustomize build deploy/kustomize/overlays/prod | kubectl apply -f -
> configmap/api-config configured
> deployment.apps/api configured
> service/api unchanged
> ```
> **Verification** : `kubeconform` ne retourne aucune erreur. `kubectl apply` confirme les ressources créées/mises à jour.

### 6.3 **Helm** (chart versionné, **push OCI**)

**`Chart.yaml`**

> **Objectif** : Définir les métadonnées du chart Helm : nom, description, version du chart (incrémentée à chaque modification des templates) et version applicative (correspond au tag de l'image Docker).
> **Pre-requis** : Répertoire du chart Helm créé avec les templates.

```yaml
# Version de l'API Helm (v2 = Helm 3+)
apiVersion: v2
# Nom du chart (utilisé comme nom de release par défaut)
name: api
# Description affichée dans les catalogues de charts
description: API service
# Type "application" (par opposition à "library" qui n'est pas déployable)
type: application
# Version du chart — à incrémenter à chaque modification des templates/values
version: 0.3.0      # version du chart
# Version de l'application déployée (tag de l'image Docker par défaut)
appVersion: "1.3.0" # version applicative
```

> **Resultat attendu** :
> ```
> $ helm lint deploy/helm/api
> ==> Linting deploy/helm/api
> 1 chart(s) linted, 0 chart(s) failed
> ```
> **Verification** : `helm lint` ne retourne aucune erreur. Les versions sont cohérentes (chart ≠ app).

**`values.yaml`** (expliqué)

> **Objectif** : Définir les valeurs par défaut du chart Helm. Ces valeurs peuvent être surcouchées lors de l'installation (`--set` ou `-f`). Elles contrôlent l'image, les replicas, le service, les ressources et l'ingress.
> **Pre-requis** : Chart Helm créé avec `Chart.yaml`.

```yaml
# Configuration de l'image conteneur
image:
  repository: ghcr.io/acme/api    # registre + nom du dépôt d'images
  tag: "1.3.0"                    # tag de l'image (utilisé si digest est vide)
  digest: ""                      # si non vide, priorité au digest (immuable)
# Nombre de replicas du Deployment
replicaCount: 3

# Configuration du Service Kubernetes
service:
  type: ClusterIP                 # Service interne au cluster (pas de LoadBalancer)
  port: 8080                      # Port exposé par le Service

# Ressources CPU/mémoire du conteneur
resources:
  # Minimum garanti (le scheduler réserve ces ressources)
  requests: { cpu: "200m", memory: "256Mi" }
  # Maximum autorisé (au-delà → throttling CPU ou OOMKill mémoire)
  limits:   { cpu: "1",    memory: "512Mi" }

# Configuration de l'Ingress (exposition HTTP externe)
ingress:
  enabled: true                   # Active la création de l'Ingress
  className: nginx                # Classe d'Ingress (contrôleur NGINX)
  hosts:
    - host: api.example.com       # Nom de domaine externe
      paths:
        - path: "/"               # Chemin URL
          pathType: Prefix        # Matche tout ce qui commence par "/"
```

> **Resultat attendu** :
> ```
> $ helm template api deploy/helm/api -f values.yaml
> ---
> # Source: api/templates/service.yaml
> apiVersion: v1
> kind: Service
> metadata:
>   name: api
> spec:
>   type: ClusterIP
>   ports:
>     - port: 8080
> ---
> # Source: api/templates/deployment.yaml
> apiVersion: apps/v1
> kind: Deployment
>   ...
> ```
> **Verification** : `helm template` génère les manifests avec les valeurs correctes (3 replicas, image ghcr.io/acme/api:1.3.0, ingress activé).

**`templates/deployment.yaml`** (image par **digest** prioritaire)

> **Objectif** : Template Helm du Deployment avec une logique conditionnelle : si un digest est fourni, l'image est référencée par digest (immuable) ; sinon, par tag. Inclut la stratégie de rolling update et les bonnes pratiques de sécurité.
> **Pre-requis** : Chart Helm avec `values.yaml` définissant `image`, `replicaCount`.

```yaml
spec:
  # Nombre de replicas depuis values.yaml
  replicas: {{ .Values.replicaCount }}
  # Stratégie de mise à jour progressive
  strategy:
    type: RollingUpdate
    # maxSurge: nombre de pods supplémentaires pendant le rollout (25% = arrondi sup)
    # maxUnavailable: 0 = aucun pod indisponible pendant le rollout (zero-downtime)
    rollingUpdate: { maxSurge: 25%, maxUnavailable: 0 }
  template:
    metadata:
      labels: { app: api }       # Labels du pod (sélectionnés par Service/NetPol)
    spec:
      # Désactive le token ServiceAccount (sécurité)
      automountServiceAccountToken: false
      containers:
      - name: api
        # Logique conditionnelle : digest prioritaire, sinon tag
        # Si .Values.image.digest est non vide → image@sha256:...
        # Sinon → image:tag
        image: "{{ .Values.image.repository }}{{ if .Values.image.digest }}@{{ .Values.image.digest }}{{ else }}:{{ .Values.image.tag }}{{ end }}"
        imagePullPolicy: IfNotPresent    # Ne re-télécharge que si absente
        ports:
          - name: http
            containerPort: 8080          # Port d'écoute du conteneur
```

> **Resultat attendu** :
> ```
> # Avec digest :
> $ helm template api deploy/helm/api --set image.digest=sha256:a1b2c3d...
>         image: "ghcr.io/acme/api@sha256:a1b2c3d..."
> # Sans digest (par tag) :
> $ helm template api deploy/helm/api
>         image: "ghcr.io/acme/api:1.3.0"
> ```
> **Verification** : Le template rendu montre soit `image@sha256:...` (si digest fourni) soit `image:tag`.

**Workflow commandes**

> **Objectif** : Exécuter le workflow complet Helm : validation qualité (lint + kubeconform), packaging du chart, push vers un registre OCI, et installation/mise à jour avec déploiement par digest.
> **Pre-requis** : Chart Helm fonctionnel. Registre OCI accessible. `helm`, `skopeo`, `jq`, `kubeconform` installés.

```bash
# 1) Qualité — validation statique avant tout déploiement
# Vérifie la syntaxe et les bonnes pratiques du chart
helm lint deploy/helm/api
# Rend les templates et valide les YAML contre les schémas Kubernetes
helm template api deploy/helm/api -f values.yaml | kubeconform -

# 2) Package — crée une archive .tgz du chart
helm package deploy/helm/api          # => api-0.3.0.tgz

# 3) Push OCI — publie le chart dans le registre comme artefact OCI
# Active le support OCI (expérimental dans Helm 3, standard dans Helm 4)
export HELM_EXPERIMENTAL_OCI=1
# Pousse le chart packagé vers le registre OCI
helm push oci://$REG/$ORG/charts api-0.3.0.tgz

# 4) Install/Upgrade (par digest) — déploiement immuable
# Récupère le digest SHA256 de l'image dans le registre
DIGEST=$(skopeo inspect docker://$IMG:$VER | jq -r .Digest)
# Installe ou met à jour la release "api" en utilisant le chart OCI
helm upgrade --install api oci://$REG/$ORG/charts/api \
  # Version spécifique du chart (reproductibilité)
  --version 0.3.0 \
  # Namespace cible (créé s'il n'existe pas)
  -n app --create-namespace \
  # Force l'utilisation du digest (image immuable)
  --set image.digest=$DIGEST
```

**Explications**

* `helm template … | kubeconform -` : **rend** les YAML et **valide** avant apply.
* `--set image.digest` : garantit que l'on déploie **exactement** l'artefact testé.

> **Resultat attendu** :
> ```
> $ helm lint deploy/helm/api
> 1 chart(s) linted, 0 chart(s) failed
> $ helm package deploy/helm/api
> Successfully packaged chart and saved it to: api-0.3.0.tgz
> $ helm push api-0.3.0.tgz oci://ghcr.io/acme/charts
> Pushed: ghcr.io/acme/charts/api:0.3.0
> $ helm upgrade --install api oci://ghcr.io/acme/charts/api \
>     --version 0.3.0 -n app --create-namespace \
>     --set image.digest=sha256:a1b2c3d...
> Release "api" has been upgraded. Happy Helming!
> NAME: api
> STATUS: deployed
> REVISION: 3
> ```
> **Verification** : `helm status api -n app` affiche STATUS: deployed. `kubectl -n app get pods` montre les pods avec l'image référencée par digest.

---

## 7) Stratégies de déploiement (rendu + **commandes**)

### 7.1 RollingUpdate (défaut contrôlé)

> **Objectif** : Configurer la stratégie de mise à jour progressive du Deployment pour garantir zero-downtime. `maxSurge` permet des pods supplémentaires temporaires, `maxUnavailable: 0` garantit qu'aucun pod n'est arrêté avant que le nouveau soit prêt.
> **Pre-requis** : Deployment existant dans le namespace `app`.

```yaml
strategy:
  # Type de stratégie : mise à jour progressive (rolling)
  type: RollingUpdate
  rollingUpdate:
    # Nombre de pods supplémentaires autorisés pendant le rollout
    # 25% de 3 replicas = 1 pod supplémentaire max (arrondi sup)
    maxSurge: 25%       # n pods supplémentaires pendant le rollout
    # Nombre de pods pouvant être indisponibles pendant le rollout
    # 0 = capacité totale intacte (recommandé en production)
    maxUnavailable: 0   # capacité intacte (prod recommandé)
```

> **Resultat attendu** :
> ```
> # Lors d'un rollout avec replicas=3, maxSurge=25%, maxUnavailable=0 :
> $ kubectl -n app get pods -l app=api -w
> NAME                   READY   STATUS
> api-6d4f5b8c9-abc12   1/1     Running       # ancien pod
> api-6d4f5b8c9-def34   1/1     Running       # ancien pod
> api-6d4f5b8c9-ghi56   1/1     Running       # ancien pod
> api-7e5g6c9d0-jkl78   0/1     ContainerCreating  # nouveau pod (+1 surge)
> api-7e5g6c9d0-jkl78   1/1     Running            # nouveau pod prêt
> api-6d4f5b8c9-abc12   1/1     Terminating        # ancien pod retiré
> ```
> **Verification** : Pendant le rollout, le nombre total de pods est toujours >= 3 (capacité intacte).

**Commandes**

> **Objectif** : Surveiller le statut d'un rollout, consulter l'historique des révisions, et effectuer un rollback vers la révision précédente en cas de problème.
> **Pre-requis** : Deployment `api` dans le namespace `app` avec au moins un rollout effectué.

```bash
# Attend et affiche la progression du rollout en cours
# Bloque jusqu'à ce que tous les pods soient à jour (ou timeout)
kubectl rollout status deploy/api -n app
# Affiche l'historique des révisions (chaque apply/create crée une révision)
kubectl rollout history deploy/api -n app
# Annule le dernier rollout et revient à la révision précédente
kubectl rollout undo    deploy/api -n app
```

> **Resultat attendu** :
> ```
> $ kubectl rollout status deploy/api -n app
> deployment "api" successfully rolled out
> $ kubectl rollout history deploy/api -n app
> REVISION  CHANGE-CAUSE
> 1         Initial deployment
> 2         Update image to 1.3.0
> 3         Update resources
> $ kubectl rollout undo deploy/api -n app
> deployment.apps/api rolled back
> ```
> **Verification** : Après `undo`, `kubectl rollout history` montre une nouvelle révision. `kubectl get pods` affiche des pods avec l'image de la révision précédente.

### 7.2 Blue-Green (switch **atomique** du trafic)

**Principe**

* Deux Deployments (`api-blue`, `api-green`) avec `labels: {track: blue|green}`.
* Le **Service** pointe vers `track: blue`, on **bascule** sur `green` quand prêt.

**Service (selector par "track")**

> **Objectif** : Configurer le Service pour qu'il sélectionne les pods par le label `track`. En changeant ce selector (de `blue` à `green`), on bascule instantanément tout le trafic vers la nouvelle version.
> **Pre-requis** : Deployments `api-blue` et `api-green` déployés avec les labels `track: blue` et `track: green`.

```yaml
spec:
  # Le Service route le trafic vers les pods qui ont CES deux labels
  # Pour basculer : changer "blue" en "green" (ou inversement)
  selector: { app: api, track: blue }
```

> **Resultat attendu** :
> ```
> $ kubectl -n app get endpoints api
> NAME   ENDPOINTS                          AGE
> api    10.0.1.5:8080,10.0.1.6:8080       # IPs des pods "track: blue"
> ```
> **Verification** : Les endpoints listés correspondent aux IPs des pods avec `track: blue`.

**Bascule (patch)**

> **Objectif** : Basculer atomiquement le trafic de la version bleue vers la version verte en modifiant le selector du Service. Le changement est instantané (pas de période de transition).
> **Pre-requis** : Deployment `api-green` déployé et ses pods prêts (Ready). Service `api` existant pointant vers `track: blue`.

```bash
# Patch le selector du Service pour pointer vers les pods "track: green"
# Le changement est atomique : les endpoints sont mis à jour instantanément
kubectl -n app patch svc api -p '{"spec":{"selector":{"app":"api","track":"green"}}}'
# Vérifie que le déploiement vert est bien déployé et stable
kubectl -n app rollout status deploy/api-green
```

**Rollback** : re-patcher le **Service** vers `blue`.

> **Resultat attendu** :
> ```
> $ kubectl -n app patch svc api -p '{"spec":{"selector":{"app":"api","track":"green"}}}'
> service/api patched
> $ kubectl -n app get endpoints api
> NAME   ENDPOINTS                            AGE
> api    10.0.2.10:8080,10.0.2.11:8080       # IPs des pods "track: green"
> $ kubectl -n app rollout status deploy/api-green
> deployment "api-green" successfully rolled out
> ```
> **Verification** : Les endpoints du Service pointent vers les IPs des pods verts. Le trafic est basculé.

### 7.3 Canary (progressif, pondéré)

**Ingress NGINX (annotations)** :

> **Objectif** : Configurer un Ingress NGINX en mode canary pour router un pourcentage donné du trafic vers la version canari. Permet de tester progressivement une nouvelle version avec un sous-ensemble du trafic réel.
> **Pre-requis** : Contrôleur Ingress NGINX installé. Ingress principal (stable) existant. Deployment canari déployé avec son propre Service.

```yaml
metadata:
  annotations:
    # Active le mode canary sur cet Ingress (secondaire)
    nginx.ingress.kubernetes.io/canary: "true"
    # Pourcentage du trafic routé vers le backend canari (ici 10%)
    # Le reste (90%) reste sur l'Ingress principal (stable)
    nginx.ingress.kubernetes.io/canary-weight: "10"   # 10% du trafic
```

> **Resultat attendu** :
> ```
> # Sur 100 requêtes, environ 10 vont vers le canari, 90 vers le stable
> $ for i in $(seq 1 100); do curl -s http://api.example.com/version; done | sort | uniq -c
>    89 api/1.3.0
>    11 api/1.4.0-rc1
> ```
> **Verification** : La répartition du trafic correspond approximativement au poids configuré (10%). Les métriques NGINX (`nginx_ingress_controller_requests`) confirment la répartition.

**Étapes** : 5% → 10% → 25% → 50% → 100%, avec **vérifications SLO** (erreurs 5xx, p95, saturation) entre étapes.
**Alternative** : Argo Rollouts (poids, analyse automatisée).

---

## 8) Hooks & migrations (Helm **pré/post**)

**Job de migration (idempotent)**

> **Objectif** : Exécuter une migration de base de données automatiquement avant chaque install/upgrade Helm. Le Job est idempotent (peut être rejoué sans effet de bord) et ses annotations Helm contrôlent son cycle de vie (quand le lancer, dans quel ordre, quand le nettoyer).
> **Pre-requis** : Chart Helm avec un template de Job dans `templates/`. Secret `db-creds` existant. Image `migrator` contenant les scripts de migration.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  annotations:
    # Déclenche ce Job AVANT les opérations install et upgrade Helm
    # Helm exécute les hooks dans l'ordre de poids avant de déployer les ressources
    "helm.sh/hook": pre-install,pre-upgrade
    # Poids d'exécution : les hooks de poids inférieur s'exécutent en premier
    # (ex: weight -5 = avant weight 5)
    "helm.sh/hook-weight": "5"
    # Politique de nettoyage : supprime le Job existant avant d'en recréer un
    # ET supprime le Job après succès (évite l'accumulation de Jobs terminés)
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  # Nombre de tentatives en cas d'échec (1 = pas de retry)
  backoffLimit: 1
  # Supprime le Job terminé après 600 secondes (nettoyage automatique)
  ttlSecondsAfterFinished: 600
  template:
    spec:
      # Ne pas redémarrer le conteneur en cas d'échec (géré par backoffLimit)
      restartPolicy: OnFailure
      containers:
      - name: migrate
        # Image du migrateur, versionnée selon la version applicative du chart
        image: ghcr.io/acme/migrator:{{ .Chart.AppVersion }}
        # Injecte les identifiants DB depuis le Secret (toutes les clés)
        envFrom:
          - secretRef: { name: db-creds }
```

**Clés**

* `hook-delete-policy` : évite l'accumulation de Jobs terminés.
* **Idempotence** : la migration doit pouvoir **repasser** sans dégâts.

> **Resultat attendu** :
> ```
> $ helm upgrade api oci://ghcr.io/acme/charts/api --version 0.3.0 -n app
> # Hook exécuté avant le déploiement :
> job.batch/db-migrate created
> # Migration terminée avec succès :
> $ kubectl -n app get jobs
> NAME         COMPLETIONS   DURATION   AGE
> db-migrate   1/1           12s        30s
> # Le Job est automatiquement supprimé (hook-delete-policy: hook-succeeded)
> ```
> **Verification** : `kubectl -n app get jobs` montre le Job complété. Les logs (`kubectl logs job/db-migrate`) confirment la migration réussie. Le hook est nettoyé après succès.

---

## 9) Probes & "gates" de trafic (explications fines)

> **Objectif** : Configurer les trois types de probes Kubernetes pour gérer le cycle de vie du conteneur : `startupProbe` (démarrage lent), `readinessProbe` (prêt pour le trafic), `livenessProbe` (redémarrage en cas de deadlock). Chaque probe a un rôle distinct et des paramètres calibrés.
> **Pre-requis** : Deployment avec un conteneur exposant les endpoints `/healthz`, `/livez`, `/startupz`. Le port nommé `http` défini dans `ports`.

```yaml
# readinessProbe : détermine si le pod reçoit du trafic (Service/endpoints)
# Si échoue → le pod est retiré des endpoints du Service (plus de trafic)
# Si réussit à nouveau → le pod est remis dans les endpoints
readinessProbe:
  httpGet:
    path: /healthz     # Endpoint de vérification de santé (vérifie les dépendances)
    port: http         # Référence le port nommé "http" défini dans containers.ports
  periodSeconds: 5     # Vérifie toutes les 5 secondes
  timeoutSeconds: 2    # Timeout de chaque requête HTTP (2s max)
  failureThreshold: 3  # 3 échecs consécutifs → marqué "NotReady" (~15s)
# livenessProbe : détermine si le conteneur doit être redémarré
# Si échoue → kubelet tue le conteneur et le redémarre (restartPolicy)
# Utilisé pour détecter les deadlocks / états corrompus
livenessProbe:
  httpGet:
    path: /livez       # Endpoint léger (vérifie que le process répond, pas les deps)
    port: http
  initialDelaySeconds: 15  # Attend 15s après le démarrage avant la première vérification
  periodSeconds: 10        # Vérifie toutes les 10 secondes
# startupProbe : protège les applications à démarrage lent
# Tant qu'elle échoue, liveness et readiness sont désactivées
# Évite les faux positifs liveness pendant le boot
startupProbe:
  httpGet:
    path: /startupz    # Endpoint spécifique au démarrage
    port: http
  failureThreshold: 30  # 30 échecs autorisés
  periodSeconds: 5      # toutes les 5s → 30*5s = 150s de grâce maximale
```

* **readiness** : **garde** l'entrée de trafic (Service/endpoints).
* **liveness** : redémarre si verrou mort.
* **startup** : large fenêtre pour gros démarrages (évite faux positifs liveness).

> **Resultat attendu** :
> ```
> $ kubectl -n app describe pod api-6d4f5b8c9-abc12
> ...
> Containers:
>   api:
>     Readiness:  http-get /healthz delay=0s timeout=2s period=5s #success=1 #failure=3
>     Liveness:   http-get /livez delay=15s timeout=1s period=10s #success=1 #failure=3
>     Startup:    http-get /startupz delay=0s timeout=1s period=5s #success=1 #failure=30
> ...
> Events:
>   Normal  Created    ...  Created container api
>   Normal  Started    ...  Started container api
>   Normal  Killing    ...  Container api failed liveness probe, will be restarted
> ```
> **Verification** : `kubectl describe pod` affiche les trois probes. Un pod en démarrage lent ne doit pas être tué par liveness grâce à startupProbe. `kubectl get endpoints api` ne liste que les pods Ready.

> **gRPC** : utiliser `grpc.health.v1.Health` (via `grpc` probe si dispo, sinon TCP/exec).

---

## 10) Vérifications post-déploiement (scripts & commandes)

> **Objectif** : Vérifier que le déploiement s'est bien passé : pods sains, endpoints peuplés, smoke test réussi, images correctes, rollout terminé. Script à exécuter systématiquement après chaque déploiement.
> **Pre-requis** : Deployment `api` déployé dans le namespace `app`. `kubectl` configuré.

```bash
# 1) Santé & endpoints — vérifie que les pods sont Running et les endpoints peuplés
# Affiche les pods avec leurs IPs, le node hôte et leur statut
kubectl -n app get pods -l app=api -o wide
# Vérifie que le Service "api" a des endpoints (pods Ready derrière le Service)
kubectl -n app get endpoints api
# Affiche les détails du Service, en se concentrant sur la section Endpoints
kubectl -n app describe svc api | sed -n '/Endpoints/,$p'

# 2) Smoke test (depuis un pod netshoot) — teste l'accès HTTP interne au cluster
# Lance un pod temporaire avec l'image netshoot (outils réseau), exécute un curl
# vers le Service interne, puis supprime le pod (--rm)
kubectl -n app run -it net --image=nicolaka/netshoot --rm -- sh -lc \
  "curl -sS http://api.app.svc.cluster.local:8080/healthz && echo OK"

# 3) Images & digests réellement déployés — vérifie que les pods tournent bien
# avec l'image attendue (par digest si possible)
kubectl -n app get pod -l app=api -o jsonpath='{range .items[*]}{.spec.containers[0].image}{"\n"}{end}'

# 4) Rollout — attend la fin du déploiement et confirme qu'il est terminé
kubectl -n app rollout status deploy/api
```

> **Resultat attendu** :
> ```
> $ kubectl -n app get pods -l app=api -o wide
> NAME                   READY   STATUS    RESTARTS   AGE   IP          NODE
> api-7e5g6c9d0-jkl78   1/1     Running   0          2m    10.0.2.10   node-1
> api-7e5g6c9d0-mno90   1/1     Running   0          2m    10.0.3.15   node-2
> api-7e5g6c9d0-pqr12   1/1     Running   0          2m    10.0.1.22   node-3
>
> $ kubectl -n app get endpoints api
> NAME   ENDPOINTS                                                AGE
> api    10.0.1.22:8080,10.0.2.10:8080,10.0.3.15:8080            5d
>
> $ kubectl -n app run -it net --image=nicolaka/netshoot --rm -- sh -lc \
>     "curl -sS http://api.app.svc.cluster.local:8080/healthz && echo OK"
> OK
>
> $ kubectl -n app get pod -l app=api -o jsonpath='{range .items[*]}{.spec.containers[0].image}{"\n"}{end}'
> ghcr.io/acme/api@sha256:a1b2c3d4e5f6...
> ghcr.io/acme/api@sha256:a1b2c3d4e5f6...
> ghcr.io/acme/api@sha256:a1b2c3d4e5f6...
>
> $ kubectl -n app rollout status deploy/api
> deployment "api" successfully rolled out
> ```
> **Verification** : Tous les pods sont `1/1 Running`. Les endpoints sont peuplés (3 IPs). Le smoke test retourne `OK`. Les images correspondent au digest attendu. Le rollout est terminé.

---

## 11) Runbooks (dépannage ciblé déploiement)

### A) `ImagePullBackOff`

> **Objectif** : Diagnostiquer un pod bloqué en état `ImagePullBackOff` (impossible de télécharger l'image). Les causes fréquentes sont : credentials registre manquants, nom d'image incorrect, tag inexistant, ou restriction réseau (NetworkPolicy egress).
> **Pre-requis** : Un pod en état `ImagePullBackOff` dans le namespace `app`.

```bash
# Affiche les événements du pod pour identifier la cause exacte du pull failure
# (ex: "unauthorized", "manifest unknown", "dial tcp: i/o timeout")
kubectl -n app describe pod <pod> | sed -n '/Events/,$p'
# Vérifie si le Secret de credentials registre existe et contient les bonnes données
kubectl -n app get secret regcred -o yaml    # cred registry ?
```

**Correctifs** : credentials / nom d'image / **egress** NetPol / tag inexistant / limite de tirage côté registry.

> **Resultat attendu** :
> ```
> $ kubectl -n app describe pod api-7e5g6c9d0-xyz99 | sed -n '/Events/,$p'
> Events:
>   Type     Reason     Message
>   Warning  Failed     Failed to pull image "ghcr.io/acme/api:1.3.0":
>     rpc error: code = Unknown desc = Error response from daemon:
>     unauthorized: unauthenticated: cannot retrieve access token
>   Warning  Failed     Error: ErrImagePull
>   Normal   BackOff    Back-off pulling image "ghcr.io/acme/api:1.3.0"
>   Warning  Failed     Error: ImagePullBackOff
> ```
> **Verification** : Les événements indiquent la cause. Si "unauthorized" → recréer le `imagePullSecret`. Si "manifest unknown" → vérifier le tag. Si "dial tcp" → vérifier la NetworkPolicy egress.

### B) `CrashLoopBackOff`

> **Objectif** : Diagnostiquer un pod qui redémarre en boucle (`CrashLoopBackOff`). Les causes fréquentes sont : variable d'environnement manquante, schéma DB non migré, port/probe incorrect. On examine les logs du conteneur précédent et l'état du pod.
> **Pre-requis** : Un pod en état `CrashLoopBackOff` dans le namespace `app`.

```bash
# Affiche les logs du conteneur PRÉCÉDENT (avant le redémarrage)
# C'est dans ces logs que se trouve la cause du crash
kubectl -n app logs <pod> --previous
# Affiche l'état détaillé du pod (State, Last State, Reason, Exit Code)
# Extrait la section entre "State:" et "Events" pour voir les infos de crash
kubectl -n app describe pod <pod> | sed -n '/State:/,/Events/p'
```

**Correctifs** : variables manquantes, schema DB non migré, port/probe erronés → **rollback** Helm si nécessaire.

> **Resultat attendu** :
> ```
> $ kubectl -n app logs api-7e5g6c9d0-xyz99 --previous
> panic: connection refused: db.app.svc.cluster.local:5432
> goroutine 1 [running]:
> main.main()
>     /src/cmd/app/main.go:42
>
> $ kubectl -n app describe pod api-7e5g6c9d0-xyz99 | sed -n '/State:/,/Events/p'
>     State:          Waiting
>       Reason:       CrashLoopBackOff
>     Last State:     Terminated
>       Reason:       Error
>       Exit Code:    2
> ```
> **Verification** : Les logs `--previous` montrent l'erreur fatale. L'Exit Code indique le type d'erreur (1=générique, 2=usage incorrect). Si le crash est lié au déploiement → `helm rollback api -n app`.

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
* **SBOM** et **scan bloquant** (HIGH/CRITICAL), **signatures** Cosign vérifiées à l'admission.
* **Config** via **ConfigMap/ENV**; **secrets** montés en **fichiers**; jamais dans l'image.
* **Déployer par digest** en prod; **Rolling** (`maxUnavailable: 0`); **Blue-Green/Canary** pour MAJ risquées.
* **Hooks** idempotents; **migrations** testées; **rollback** documenté.
* **Probes** justes; **PDB/HPA** cohérents; **kubeconform** avant apply.
* **Kustomize** : overlays clairs; **Helm** : chart versionné, **push OCI**, `helm lint/template`.
* **Vérifs post-deploy** automatiques (smoke tests) + **observabilité** (chap. 9).

---

## 13) Aide-mémoire (commandes clés)

> **Objectif** : Récapitulatif de toutes les commandes essentielles du chapitre, organisées par domaine. Sert de référence rapide pour les opérations courantes de packaging, déploiement et vérification.
> **Pre-requis** : Variables `$IMG`, `$VER`, `$ORG`, `$REG` exportées (section 0). Outils installés : docker, skopeo, syft, trivy, cosign, kustomize, helm, kubeconform, kubectl.

```bash
# === Build / Inspect / Digest ===
# Construit l'image avec BuildKit, taguée avec la version
DOCKER_BUILDKIT=1 docker build -t $IMG:$VER .
# Récupère le digest immuable de l'image dans le registre
skopeo inspect docker://$IMG:$VER | jq -r .Digest

# === SBOM / Scan / Signature ===
# Génère l'inventaire logiciel (SBOM) au format SPDX
syft $IMG:$VER -o spdx-json > sbom.spdx.json
# Scan les vulnérabilités critiques (échoue le pipeline si trouvées)
trivy image $IMG:$VER --severity HIGH,CRITICAL --exit-code 1
# Signe l'image puis vérifie la signature (chaîne de confiance)
cosign sign --key cosign.key $IMG:$VER && cosign verify --key cosign.pub $IMG:$VER

# === Push & Promotion ===
# Pousse l'image versionnée vers le registre source
docker push $IMG:$VER
# Copie l'image vers un registre interne (promotion sans rebuild)
skopeo copy docker://$IMG:$VER docker://harbor.local/$ORG/$APP:$VER

# === Kustomize ===
# Rend les manifests prod, les valide, et les applique en une pipeline
kustomize build deploy/kustomize/overlays/prod | kubeconform - | kubectl apply -f -

# === Helm OCI ===
# Valide la syntaxe et les bonnes pratiques du chart
helm lint deploy/helm/api
# Rend les templates et valide les YAML contre les schémas k8s
helm template api deploy/helm/api -f values.yaml | kubeconform -
# Package le chart en archive .tgz
helm package deploy/helm/api
# Active le support OCI pour le push de charts
export HELM_EXPERIMENTAL_OCI=1
# Pousse le chart vers le registre OCI
helm push oci://$REG/$ORG/charts api-0.3.0.tgz
# Récupère le digest de l'image pour un déploiement immuable
DIGEST=$(skopeo inspect docker://$IMG:$VER | jq -r .Digest)
# Installe/met à jour la release Helm en déployant par digest
helm upgrade --install api oci://$REG/$ORG/charts/api --version 0.3.0 \
  -n app --create-namespace --set image.digest=$DIGEST

# === Déploiement / Rollback / Vérifs ===
# Attend la fin du rollout et confirme le succès
kubectl -n app rollout status deploy/api
# Vérifie que les endpoints du Service sont peuplés
kubectl -n app get endpoints api
# Annule le dernier rollout (revient à la révision précédente)
kubectl -n app rollout undo deploy/api
```

> **Resultat attendu** :
> ```
> # Chaque commande produit le résultat documenté dans les sections précédentes.
> # Exemple pour le workflow complet :
> $ DOCKER_BUILDKIT=1 docker build -t ghcr.io/acme/api:1.3.0 .
> => naming to ghcr.io/acme/api:1.3.0
> $ skopeo inspect docker://ghcr.io/acme/api:1.3.0 | jq -r .Digest
> sha256:a1b2c3d4e5f6...
> $ helm upgrade --install api oci://ghcr.io/acme/charts/api --version 0.3.0 \
>     -n app --create-namespace --set image.digest=sha256:a1b2c3d4e5f6...
> Release "api" has been upgraded. Happy Helming!
> ```
> **Verification** : Chaque commande peut être exécutée indépendamment. Le workflow complet (build → sign → push → deploy → verify) doit fonctionner de bout en bout sans erreur.
