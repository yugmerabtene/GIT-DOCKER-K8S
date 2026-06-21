# Chapitre-11 — CI/CD Docker

*(builds reproductibles, caches distants, promotion par digest, SBOM & signatures)*

## Objectifs d'apprentissage

* Concevoir des **pipelines Docker** fiables : lint/test → build → scan → signer/attester → push → **promote by digest**.
* Produire des images **reproductibles** (tags/digests pinés, BuildKit, multi-arch) avec **caches distants**.
* Générer et publier **SBOM** & **provenance** ; appliquer des **scans** (CVE/licences) bloquants.
* Intégrer la **signature** (cosign) et des **politiques d'admission** (deny si non signé/non scanné).
* Mettre en place une **stratégie de tags** (SemVer/canaux) et des **workflows de promotion** sans rebuild.

## Pré-requis

* Chap. 01–10 maîtrisés (Images, BuildKit, Registry, Sécurité, Perf).
* Accès à un registry (GHCR/Docker Hub/Harbor/ECR/GAR/ACR).

---

## 1) Principes d'architecture CI/CD Docker

**Étapes standardisées**

1. **Verify**: lint (Dockerfile/compose), SAST, tests unitaires.
2. **Build** (BuildKit/buildx) → **multi-arch**, **cache to/from**.
3. **Scan** (CVE/licences) → **fail-the-build** si seuil dépassé.
4. **Attest**: **SBOM + provenance**.
5. **Sign**: cosign (clé/"keyless" OIDC).
6. **Push**: tags SemVer + tag canal + **digest** (artefact).
7. **Promote**: copier **le digest validé** vers `staging`/`prod` (pas de rebuild).
8. **Policy**: admission par **digest signé** + SBOM présent.

**Règles d'or**

* **Jamais** de secrets dans l'image ou le repo.
* Déployer **par digest** (immutabilité).
* Tous les artefacts → **registry** (image, SBOM, attestation, signature).

---

## 2) Stratégie de versionning & tags

* **SemVer**: `1.4.2` (+ raccourcis `1.4`, `1`) **en build**, puis "gel" en prod (pas d'écrasement).
* **Canaux**: `-rc`, `-beta`, `-dev` pour branches de release.
* **Metadata**: tag **commit** (`sha-7`) + **branch** (ex. `main`) pour traçabilité.
* **Déploiement**: utiliser **`@sha256:<digest>`** côté infra (Compose/K8s).

---

## 3) Pipeline GitHub Actions — modèle complet

### 3.1 Variables utiles (exemple)

* `REGISTRY=ghcr.io`
* `IMAGE=ghcr.io/acme/web`
* `SEMVER` dérivé des tags Git (fallback `0.0.0`).

### 3.2 Workflow (multi-arch, scan, sbom, sign, push)

> **Objectif** : Définir un workflow GitHub Actions complet qui build une image Docker multi-architecture (amd64/arm64), génère des tags SemVer automatiques, scan les vulnérabilités avec Trivy, signe l'image avec cosign (keyless OIDC), et publie le SBOM et la provenance.
> **Pré-requis** : Un dépôt GitHub avec un Dockerfile à la racine, un compte GHCR (GitHub Container Registry), et les permissions `packages: write` + `id-token: write` activées.

```yaml
name: ci-docker                                          # Nom du workflow affiché dans l'onglet Actions
on:
  push:
    branches: [ main ]                                   # Déclenché sur chaque push vers main
    tags:     [ 'v*.*.*' ]                               # Déclenché sur chaque tag SemVer (v1.0.0, v2.3.1, etc.)
  pull_request:                                          # Déclenché sur chaque PR (build de vérification)

jobs:
  build:
    runs-on: ubuntu-latest                               # Exécute sur un runner GitHub hébergé (Ubuntu)
    permissions:
      contents: read                                     # Lecture du code source (checkout)
      packages: write          # push GHCR               # Écriture dans GHCR pour pousser l'image
      id-token: write          # OIDC (cosign keyless)   # Nécessaire pour la signature keyless via OIDC
    env:
      REGISTRY: ghcr.io                                  # Adresse du registry (GitHub Container Registry)
      IMAGE: ghcr.io/acme/web                            # Nom complet de l'image dans le registry
    steps:
      - uses: actions/checkout@v4                        # Récupère le code source du dépôt

      # Métadonnées d'image (tags/labels OCI)
      - uses: docker/metadata-action@v5                  # Génère automatiquement les tags et labels OCI
        id: meta
        with:
          images: ${{ env.IMAGE }}                       # Image cible pour les métadonnées
          tags: |
            type=semver,pattern={{version}},prefix=v     # Tag complet : v1.4.2
            type=semver,pattern={{major}}.{{minor}},prefix=v  # Tag majeur.mineur : v1.4
            type=ref,event=branch                        # Tag basé sur la branche : main
            type=sha                                     # Tag basé sur le SHA du commit : sha-abc1234
          labels: |
            org.opencontainers.image.source=${{ github.repository }}   # Lien vers le dépôt source
            org.opencontainers.image.revision=${{ github.sha }}        # SHA complet du commit

      # Buildx + QEMU multi-arch
      - uses: docker/setup-qemu-action@v3               # Installe QEMU pour l'émulation multi-arch (arm64 sur runner amd64)
      - uses: docker/setup-buildx-action@v3              # Installe et configure BuildKit/buildx

      # Login au registry (GHCR utilise GITHUB_TOKEN)
      - uses: docker/login-action@v3                     # Authentification auprès du registry
        with:
          registry: ${{ env.REGISTRY }}                  # ghcr.io
          username: ${{ github.actor }}                  # L'utilisateur qui a déclenché le workflow
          password: ${{ secrets.GITHUB_TOKEN }}          # Token automatique fourni par GitHub Actions

      # Build & push multi-arch + caches + SBOM+provenance
      - uses: docker/build-push-action@v6                # Build, push, et publication des artefacts OCI
        id: build
        with:
          context: .                                     # Contexte de build = racine du dépôt
          file: ./Dockerfile                             # Dockerfile à utiliser
          target: runtime                                # Cible multi-stage (étape finale de production)
          platforms: linux/amd64,linux/arm64             # Build pour les deux architectures
          push: true                                     # Pousse l'image vers le registry après le build
          tags: ${{ steps.meta.outputs.tags }}           # Tags générés par metadata-action
          labels: ${{ steps.meta.outputs.labels }}       # Labels OCI générés par metadata-action
          provenance: true                               # Génère l'attestation de provenance (SLSA)
          sbom: true                                     # Génère le SBOM (Software Bill of Materials)
          cache-from: type=registry,ref=${{ env.IMAGE }}:buildcache   # Récupère le cache depuis le registry
          cache-to:   type=registry,ref=${{ env.IMAGE }}:buildcache,mode=max  # Pousse le cache complet vers le registry

      # Digest (manifest list) en sortie
      - name: Export digest
        run: echo "DIGEST=${{ steps.build.outputs.digest }}" >> $GITHUB_ENV  # Exporte le digest SHA256 comme variable d'env

      # Scan (ex: Trivy). Échoue sur HIGH/CRITICAL
      - uses: aquasecurity/trivy-action@0.24.0           # Action de scan de vulnérabilités Trivy
        with:
          image-ref: ${{ env.IMAGE }}@${{ env.DIGEST }}  # Scanne l'image par digest (immutabilité)
          format: 'table'                                # Affiche les résultats en tableau lisible
          exit-code: '1'                                 # Échoue le pipeline si des vulnérabilités sont trouvées
          ignore-unfixed: true                           # Ignore les CVE sans correctif disponible
          vuln-type: 'os,library'                        # Scanne les vulnérabilités OS et bibliothèques
          severity: 'HIGH,CRITICAL'                      # Ne remonte que les sévérités HIGH et CRITICAL

      # Signature cosign (keyless via OIDC)
      - uses: sigstore/cosign-installer@v3.5.0           # Installe l'outil cosign pour la signature d'images
      - name: Cosign sign (keyless)
        env:
          COSIGN_EXPERIMENTAL: "true"                    # Active le mode keyless (signature via identité OIDC)
        run: |
          cosign sign --yes $IMAGE@${DIGEST}             # Signe l'image par son digest (pas par tag)

      # Upload digest pour la promotion
      - name: Save digest artifact
        uses: actions/upload-artifact@v4                 # Sauvegarde le digest comme artefact téléchargeable
        with:
          name: image-digest                             # Nom de l'artefact
          path: digest.txt                               # Fichier contenant le digest
        env:
          DIGEST_FILE: digest.txt
        shell: bash
        run: echo "${{ env.DIGEST }}" > digest.txt       # Écrit le digest dans un fichier texte
```

> **Résultat attendu** :
> ```
> ✅ docker/metadata-action → tags: ghcr.io/acme/web:v1.4.2, ghcr.io/acme/web:v1.4, ghcr.io/acme/web:main, ghcr.io/acme/web:sha-abc1234
> ✅ docker/build-push-action → Image poussée : ghcr.io/acme/web@sha256:e3b0c44298fc1c149afbf4c8996fb924...
> ✅ Trivy → Scan terminé : 0 HIGH, 0 CRITICAL
> ✅ cosign sign → Signature attachée à ghcr.io/acme/web@sha256:e3b0c44298fc1c149afbf4c8996fb924...
> ✅ Artefact "image-digest" uploadé contenant le SHA256
> ```
> **Vérification** : Dans l'onglet Actions, vérifier que toutes les étapes sont vertes. Sur GHCR, vérifier que l'image a les tags attendus, un SBOM attaché, une attestation de provenance, et une signature cosign visible.

### 3.3 Job de **promotion** (copie du digest)

> **Objectif** : Copier une image déjà buildée, scannée et signée d'un dépôt source vers un dépôt cible (ex: de `acme/web` vers `acme/web-prod`) en utilisant uniquement le digest, sans aucun rebuild. Cela garantit que l'image déployée en production est exactement celle qui a été validée.
> **Pré-requis** : Le workflow `ci-docker` doit avoir été exécuté avec succès et l'artefact `image-digest` doit être disponible. L'outil `crane` est utilisé pour la copie.

```yaml
name: promote                                            # Nom du workflow de promotion manuelle
on:
  workflow_dispatch:                                     # Déclenchement manuel depuis l'UI GitHub
    inputs:
      from:
        description: 'repo source (ex: acme/web)'       # Dépôt source contenant l'image validée
        required: true
        default: 'acme/web'
      to:
        description: 'repo cible (ex: acme/web-prod)'   # Dépôt cible pour la production
        required: true
        default: 'acme/web-prod'
      tag:
        description: 'tag cible (ex: v1.4.2)'           # Tag à appliquer sur l'image dans le dépôt cible
        required: true

jobs:
  copy:
    runs-on: ubuntu-latest                               # Runner GitHub Ubuntu
    permissions:
      packages: write                                    # Nécessaire pour pousser dans GHCR
      id-token: write                                    # OIDC si nécessaire pour l'auth
    steps:
      - uses: actions/checkout@v4                        # Checkout du code (nécessaire pour les actions)
      - uses: imjasonh/setup-crane@v0.3                  # Installe crane (outil de manipulation d'images OCI)
      - name: Download digest
        uses: actions/download-artifact@v4               # Récupère l'artefact contenant le digest du build
        with: { name: image-digest, path: . }            # Télécharge dans le répertoire courant
      - name: Copy by digest (no rebuild)
        run: |
          SRC=ghcr.io/${{ github.event.inputs.from }}@$(cat digest.txt)   # Source = image source + digest (référence immutable)
          DST=ghcr.io/${{ github.event.inputs.to }}:${{ github.event.inputs.tag }}  # Destination = dépôt cible + tag de release
          crane copy "$SRC" "$DST"                       # Copie l'image sans rebuild (copie manifest + couches)
```

> **Résultat attendu** :
> ```
> ✅ crane copy → Image copiée : ghcr.io/acme/web@sha256:e3b0c44... → ghcr.io/acme/web-prod:v1.4.2
> ✅ Le digest source et le digest cible sont identiques (même contenu binaire)
> ```
> **Vérification** : Exécuter `crane digest ghcr.io/acme/web-prod:v1.4.2` et vérifier que le SHA256 retourné est identique à celui de l'image source.

**Points clés**

* **`build-push-action`** publie manifest list (amd64/arm64).
* **Caches** persos vers **tag `:buildcache`** dans le registry.
* **Trivy** échoue en cas de vulnérabilités sévères.
* **Cosign keyless** (OIDC) → signatures stockées comme artefacts OCI.
* **Promotion** = `crane copy` par **digest** (pas de rebuild/push binaire).

---

## 4) Pipeline GitLab CI — deux variantes

### 4.1 Docker-in-Docker (simple)

`.gitlab-ci.yml`

> **Objectif** : Configurer un pipeline GitLab CI complet utilisant Docker-in-Docker (DinD) pour construire, scanner, signer et promouvoir une image Docker multi-architecture. Le pipeline est découpé en 5 stages séquentiels : test → build → scan → sign → release.
> **Pré-requis** : Un projet GitLab avec un Dockerfile, un GitLab Container Registry activé, et un runner GitLab avec le support Docker. Les variables CI `$CI_REGISTRY`, `$CI_REGISTRY_USER`, `$CI_REGISTRY_PASSWORD` doivent être configurées.

```yaml
stages: [ test, build, scan, sign, release ]             # Définit l'ordre d'exécution des 5 stages du pipeline

variables:
  DOCKER_DRIVER: overlay2                                # Driver de stockage Docker (performance optimale)
  DOCKER_TLS_CERTDIR: ""     # dind non-TLS (réseau privé runner)  # Désactive TLS pour DinD (acceptable en réseau isolé)
  IMAGE: $CI_REGISTRY_IMAGE                              # Image = URL complète du registry GitLab + projet

services:
  - name: docker:dind                                    # Service Docker-in-Docker (daemon Docker partagé)

.test:                                                   # Template de job de test (réutilisable via héritage)
  stage: test                                            # Stage de test (premier à s'exécuter)
  image: docker:24-git                                   # Image avec Docker CLI + Git installés
  script:
    - docker version                                     # Vérifie que le daemon Docker est accessible
    - docker build --target=test -t test .               # Build l'étape "test" du Dockerfile multi-stage
    - docker run --rm test ./run-tests.sh                # Exécute les tests unitaires dans le conteneur

build:
  stage: build                                           # Stage de build (après les tests)
  image: docker:24-git                                   # Image avec Docker CLI + Git
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" "$CI_REGISTRY"  # Authentification au registry GitLab
    - docker buildx create --use                         # Crée et active un builder BuildKit
    - docker buildx build \
        --platform linux/amd64,linux/arm64 \             # Build multi-architecture
        --provenance=true --sbom=true \                  # Génère provenance SLSA + SBOM
        --cache-to=type=registry,ref=$IMAGE:buildcache,mode=max \   # Pousse le cache complet vers le registry
        --cache-from=type=registry,ref=$IMAGE:buildcache \          # Récupère le cache depuis le registry
        -t $IMAGE:$CI_COMMIT_SHORT_SHA \                 # Tag avec le SHA court du commit
        -t $IMAGE:${CI_COMMIT_TAG:-dev} \                # Tag avec le tag Git (ou "dev" si pas de tag)
        --push .                                         # Pousse l'image vers le registry

scan:
  stage: scan                                            # Stage de scan (après le build)
  image: aquasec/trivy:latest                            # Image Trivy pour le scan de vulnérabilités
  script:
    - trivy image --severity HIGH,CRITICAL --exit-code 1 $IMAGE:$CI_COMMIT_SHORT_SHA  # Scan bloquant : échoue si HIGH/CRITICAL trouvés

sign:
  stage: sign                                            # Stage de signature (après le scan)
  image: ghcr.io/sigstore/cosign/cosign:v2.4.0          # Image cosign pour la signature
  script:
    - cosign login $CI_REGISTRY -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD"  # Auth cosign au registry GitLab
    - cosign sign --yes $IMAGE:$CI_COMMIT_SHORT_SHA     # Signe l'image (cosign keyless ou avec clé)

release:
  stage: release                                         # Stage de promotion/release (dernier stage)
  image: gcr.io/go-containerregistry/crane:debug         # Image crane pour manipuler les images OCI
  script:
    - DIGEST=$(crane digest $IMAGE:$CI_COMMIT_SHORT_SHA) # Récupère le digest SHA256 de l'image poussée
    - crane copy $IMAGE@$DIGEST $IMAGE:${CI_COMMIT_TAG:-rc}  # Copie l'image par digest vers le tag de release (ou "rc")
```

> **Résultat attendu** :
> ```
> ✅ Stage test → Tests unitaires exécutés avec succès dans le conteneur
> ✅ Stage build → Image multi-arch poussée : registry.gitlab.com/group/project:abc1234 (amd64+arm64)
> ✅ Stage scan → Trivy : 0 vulnérabilité HIGH/CRITICAL
> ✅ Stage sign → Signature cosign attachée à l'image
> ✅ Stage release → Image copiée : registry.gitlab.com/group/project@sha256:xxx → registry.gitlab.com/group/project:v1.4.2
> ```
> **Vérification** : Dans GitLab CI/CD > Pipelines, tous les 5 stages doivent être verts. Dans le Container Registry, vérifier la présence du SBOM, de la provenance et de la signature.

### 4.2 Kaniko (sans daemon) + cosign

* Remplace `docker buildx build` par **`gcr.io/kaniko-project/executor`** (build sans démon).
* Signature cosign possible dans un job suivant avec `crane digest`.

---

## 5) Jenkins Pipeline (extrait)

> **Objectif** : Implémenter un pipeline Jenkins déclaratif avec 5 stages (Checkout, Buildx, Scan, Sign, Promote) pour construire une image Docker multi-architecture, la scanner, la signer et la promouvoir. Utilise BuildKit/buildx et des outils CLI (trivy, cosign, crane).
> **Pré-requis** : Un agent Jenkins avec Docker et buildx installés (label `docker`). Les credentials `$REG_USER`/`$REG_PASS` doivent être configurés dans Jenkins. Les outils `trivy`, `cosign` et `crane` doivent être disponibles sur l'agent.

```groovy
pipeline {
  agent { label 'docker' }                               // Exécute sur un agent Jenkins ayant le label "docker"
  environment {
    IMAGE = "registry.example.com/team/app"              // Nom complet de l'image dans le registry
  }
  stages {
    stage('Checkout'){ steps { checkout scm } }          // Récupère le code depuis le SCM (Git)

    stage('Buildx'){
      steps {
        sh '''
          docker login registry.example.com -u $REG_USER -p $REG_PASS   # Authentification au registry privé
          docker buildx create --use                                    # Crée et active un builder BuildKit
          docker buildx build \
            --platform linux/amd64,linux/arm64 \                        # Build multi-architecture
            --provenance --sbom \                                       // Génère provenance + SBOM
            --cache-from=type=registry,ref=$IMAGE:buildcache \          # Cache depuis le registry
            --cache-to=type=registry,ref=$IMAGE:buildcache,mode=max \   # Cache vers le registry (mode complet)
            -t $IMAGE:${GIT_COMMIT:0:7} \                               # Tag = 7 premiers caractères du commit Git
            --push .                                                    // Pousse l'image vers le registry
        '''
      }
    }

    stage('Scan'){
      steps {
        sh 'trivy image --severity HIGH,CRITICAL --exit-code 1 $IMAGE:${GIT_COMMIT:0:7}'  // Scan bloquant : échoue si HIGH/CRITICAL
      }
    }

    stage('Sign'){
      steps { sh 'cosign sign --yes $IMAGE:${GIT_COMMIT:0:7}' }  // Signe l'image avec cosign (mode interactif auto-confirmé)
    }

    stage('Promote'){
      steps {
        sh '''
          DIGEST=$(crane digest $IMAGE:${GIT_COMMIT:0:7})         # Récupère le digest SHA256 de l'image
          crane copy $IMAGE@$DIGEST $IMAGE:stable                 # Copie l'image par digest vers le tag "stable"
        '''
      }
    }
  }
}
```

> **Résultat attendu** :
> ```
> ✅ Checkout → Code récupéré depuis Git
> ✅ Buildx → Image multi-arch construite et poussée : registry.example.com/team/app:abc1234
> ✅ Scan → Trivy : aucune vulnérabilité HIGH/CRITICAL
> ✅ Sign → Image signée : registry.example.com/team/app:abc1234
> ✅ Promote → Image copiée : registry.example.com/team/app@sha256:xxx → registry.example.com/team/app:stable
> ```
> **Vérification** : Dans l'interface Jenkins, chaque stage doit être vert. Vérifier sur le registry que l'image `stable` a le même digest que `abc1234`.

---

## 6) Scans, SBOM, signatures & politiques

* **Scans**: Trivy/Docker Scout en **pipeline** (bloquer **HIGH/CRITICAL**), rapport attaché.
* **SBOM**: `buildx --sbom` (SPDX/CycloneDX) → stocké comme artefact OCI au registry.
* **Provenance**: `buildx --provenance` → attestation SLSA-like.
* **Signatures**: cosign (clé locale ou **keyless OIDC**).
* **Policies** (pré-déploiement): OPA/Conftest sur Dockerfile/Compose/K8s Manifests pour refuser :

  * images non signées / sans SBOM,
  * tags `latest`,
  * conteneurs `--privileged`, sans `USER`, sans healthcheck, ports wildcard.

---

## 7) Caches distants & vitesse en CI

* **Cache registry** (`cache-to/from=type=registry,ref=:buildcache`).
* **Proxy cache** Docker Hub côté infra (voir Chap. 07).
* `.dockerignore` strict ; steps `deps`/`build` séparés (Node/Go/Maven/Python) pour maximiser le cache.

---

## 8) Gestion des secrets en pipeline

* **OIDC → Registry/Cloud** quand possible (pas de mots de passe).
* Secrets dans **store CI** (Actions/GitLab/Jenkins Credentials) ; **jamais** dans le repo.
* BuildKit `RUN --mount=type=secret` pour **ne pas** figer les secrets dans les couches.

---

## 9) Promotion entre environnements (sans rebuild)

**Principe**: promouvoir **le digest validé** (scan+sign) vers `staging`/`prod`.

Outils : `crane copy`, `skopeo copy`, ou API registry.

Exemple CLI:

> **Objectif** : Promouvoir une image d'un environnement de préproduction vers la production en copiant l'image par son digest (référence immutable), garantissant que le contenu binaire est exactement celui qui a été scanné et signé.
> **Pré-requis** : L'outil `crane` doit être installé. L'image source (`ghcr.io/acme/web:v1.4.2`) doit exister dans le registry et avoir été scannée et signée. Les droits d'écriture sur le dépôt cible (`ghcr.io/acme/web-prod`) sont nécessaires.

```bash
DIGEST=$(crane digest ghcr.io/acme/web:v1.4.2)                   # Récupère le digest SHA256 du tag v1.4.2
crane copy ghcr.io/acme/web@${DIGEST} ghcr.io/acme/web-prod:v1.4.2  # Copie l'image par digest vers le dépôt prod avec le même tag
```

> **Résultat attendu** :
> ```
> DIGEST=sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
> Copied ghcr.io/acme/web@sha256:e3b0c44298fc1c149afbf4c8996fb924... → ghcr.io/acme/web-prod:v1.4.2
> ```
> **Vérification** : Exécuter `crane digest ghcr.io/acme/web-prod:v1.4.2` et confirmer que le digest retourné est identique à celui de l'image source.

---

## 10) Déploiement par **digest** (rappel)

Compose/K8s doivent référencer l'image **immutably**:

> **Objectif** : Référencer une image Docker par son digest SHA256 (et non par un tag mutable) dans un fichier de déploiement Compose ou Kubernetes, garantissant l'immutabilité du déploiement et évitant tout effet de bord lié au réétiquetage.
> **Pré-requis** : Le digest SHA256 de l'image doit être connu (obtenu via `crane digest` ou `docker inspect`). L'image doit être accessible depuis le registry spécifié.

```yaml
image: ghcr.io/acme/web@sha256:abcd...     # pas juste :v1.4.2   # Référence immutable par digest (le tag est ignoré au pull)
```

> **Résultat attendu** :
> ```
> Le moteur Docker/Kubernetes pull exactement l'image correspondant au SHA256 spécifié,
> indépendamment de ce que le tag v1.4.2 pointe à un instant donné.
> ```
> **Vérification** : `docker inspect ghcr.io/acme/web@sha256:abcd...` doit retourner le même digest. Un `docker pull ghcr.io/acme/web:v1.4.2` pourrait retourner une image différente si le tag a été réétiqueté.

---

## 11) Aide-mémoire (commandes clés)

> **Objectif** : Regrouper les commandes essentielles pour le CI/CD Docker : build multi-arch avec cache distant, manipulation de digests/copies, scan de vulnérabilités bloquant, et signature/vérification cosign. Ce bloc sert de référence rapide.
> **Pré-requis** : `docker buildx` configuré, `crane` installé, `trivy` installé, `cosign` installé. Être authentifié au registry cible (`docker login` ou `crane auth`).

```bash
# Build multi-arch + push + sbom + provenance
docker buildx build --platform linux/amd64,linux/arm64 \    # Build pour amd64 et arm64
  --provenance --sbom \                                     # Génère attestation SLSA + SBOM
  --cache-from=type=registry,ref=REG/IMG:buildcache \       # Utilise le cache distant du registry
  --cache-to=type=registry,ref=REG/IMG:buildcache,mode=max \ # Pousse le cache complet vers le registry
  -t REG/IMG:1.4.2 --push .                                 # Tag SemVer + push vers le registry

# Digests & copies
crane digest REG/IMG:1.4.2                                  # Affiche le digest SHA256 d'un tag
crane copy REG/IMG@sha256:... REG/IMG-PROD:1.4.2            # Copie l'image par digest vers un autre dépôt/tag

# Scan blocant
trivy image --severity HIGH,CRITICAL --exit-code 1 REG/IMG@sha256:...  # Scan CVE, échoue si HIGH/CRITICAL trouvés

# Signature & vérification
cosign sign --yes REG/IMG@sha256:...                        # Signe l'image par digest (auto-confirme la prompt)
cosign verify REG/IMG@sha256:...                            # Vérifie la signature de l'image
```

> **Résultat attendu** :
> ```
> Build → Image multi-arch poussée avec SBOM + provenance attachés
> crane digest → sha256:a1b2c3d4e5f6...
> crane copy → Copie effectuée sans rebuild (manifest + couches)
> trivy → Table de vulnérabilités ou "0 vulnerabilities found" (exit 0)
> cosign sign → Signature publiée dans le registry
> cosign verify → Affiche le certificat de signature et retourne exit 0
> ```
> **Vérification** : Chaque commande doit retourner un code de sortie 0 en cas de succès. Vérifier avec `echo $?` après chaque commande.

---

## 12) Checklist de clôture (pipeline "prêt-prod")

* **Build**

  * BuildKit/buildx activés ; **multi-arch** si requis.
  * `.dockerignore` strict ; **base pinée** (tag + digest recommandé).
  * **Caches distants** `cache-to/from` configurés.

* **Sécurité & conformité**

  * **Scan** bloquant (CVE HIGH/CRITICAL, licences).
  * **SBOM + provenance** générés et publiés au registry.
  * **Signature cosign** (clé ou keyless OIDC) vérifiée côté admission.

* **Registry & promotion**

  * **Push** tags SemVer/canal + **digest** collecté en artefact.
  * **Promotion par digest** (crane/skopeo), pas de rebuild.
  * Politiques d'**immutabilité** des tags prod (ou contrôles équivalents).

* **Déploiement**

  * Infra consomme **`@sha256`** (immutabilité).
  * Gates d'admission (OPA/Conftest) activés.

* **Opérations**

  * Logs/artefacts CI conservés (digest, rapports scans, attestations).
  * Runners avec ressources suffisantes ; proxy cache Docker Hub.
  * Secrets via OIDC/CI-secrets, **jamais** en clair.
