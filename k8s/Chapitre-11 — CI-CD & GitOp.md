# Chapitre 11 — CI/CD & GitOps (aperçu opérationnel **très détaillé**)

*(pipeline : **build → tests → scan CVE/licences → SBOM/provenance → signature → push → déploiement par digest**.
Intégrations : **GitHub Actions / GitLab CI / Jenkins**. CD : **Helm/Kustomize** en push-based et **GitOps** (Argo CD / Flux).
Chaque commande et chaque champ YAML important est **expliqué**.)*

---

## 0) Pré-requis & conventions

Variables communes (tu peux les réutiliser dans tous les blocs) :

> **Objectif** : Définir des variables d'environnement réutilisables pour standardiser les commandes du pipeline CI/CD (registre, organisation, nom d'image, version, commit SHA).
> **Pre-requis** : Avoir `git` installé et être dans un dépôt git (pour `GIT_SHA`). Avoir défini les valeurs de `REG`, `ORG`, `APP`, `VER` selon votre environnement.

```bash
# --- Définition des variables communes pour le pipeline CI/CD ---
export REG=ghcr.io              # Adresse du registre de conteneurs (GHCR, Harbor, GitLab Registry…)
export ORG=acme                 # Nom de l'organisation ou du projet dans le registre
export APP=api                  # Nom de l'application (sera le nom de l'image)
export IMG=$REG/$ORG/$APP       # Chemin complet de l'image : ex: ghcr.io/acme/api
export VER=1.3.0                # Version SemVer de l'application (idéalement liée à un tag git 'v1.3.0')
# Récupère le SHA court du dernier commit git, ou 'unknown' si pas dans un repo git
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
> **Verification** : Les variables `$IMG`, `$VER`, `$GIT_SHA` sont correctement définies et réutilisables dans les blocs suivants.

Buts opérationnels :

* **Artefact unique et immuable** : image OCI **signée**, référencée par **digest** au déploiement.
* **Supply-chain** : SBOM + scan + signature **obligatoires** (cf. Ch. 8 : politiques d'admission « signée », « pas de `:latest` », « digest requis »).
* **Deux modes CD** :

  1. **Push-based** : la CI applique directement sur le cluster (Helm/Kubectl).
  2. **GitOps** : la CI **committe** dans un repo d'infra → **Argo CD/Flux** synchronise.

---

## 1) Pipeline : vue d'ensemble & responsabilités

> **Objectif** : Visualiser les étapes séquentielles du pipeline CI/CD complet, de la poussée git jusqu'au déploiement en production, en distinguant les phases CI (build, test, scan, signature, push) et CD (déploiement push-based ou GitOps).
> **Pre-requis** : Aucun — ce bloc est un schéma de référence pour comprendre la suite du chapitre.

```
# Schéma du pipeline CI/CD complet
[Développeur → git push / tag]
    ├─ (CI) 1. Build multi-arch (BuildKit/Buildx + cache)          # Construction de l'image conteneur
    ├─ (CI) 2. Tests (unitaires/intégration en conteneurs)         # Validation du code dans un env. isolé
    ├─ (CI) 3. Scan (CVE/licences) + SBOM (SPDX/CycloneDX)        # Sécurité : inventaire + vulnérabilités
    ├─ (CI) 4. Signature (Cosign) + éventuelles attestations SLSA  # Preuve d'intégrité et provenance
    ├─ (CI) 5. Push image → registre (récupérer **digest**)        # Publication de l'image signée
    ├─ (CD) 6A. Déploiement push-based (Helm/Kustomize) par **digest**  # Mode 1 : déploiement direct
    └─ (CD) 6B. Déploiement GitOps (maj fichier valeurs/kustomize → Argo/Flux)  # Mode 2 : via GitOps
```

> **Resultat attendu** :
> ```
> Aucun — schéma conceptuel de référence.
> ```
> **Verification** : Comprendre que chaque étape est un « gate » : si une étape échoue, le pipeline s'arrête.

---

## 2) Build **reproductible** (BuildKit/Buildx) — commandes & options expliquées

### 2.1 Build (cache distribué)

> **Objectif** : Construire une image Docker de manière reproductible en utilisant BuildKit, avec un cache distribué via le registre pour accélérer les builds successifs sur différents runners CI.
> **Pre-requis** : Docker avec BuildKit activé (`DOCKER_BUILDKIT=1`), un `Dockerfile` valide à la racine, les variables `$VER`, `$GIT_SHA`, `$IMG` définies (section 0).

```bash
# --- Build reproductible avec BuildKit et cache distribué ---
DOCKER_BUILDKIT=1 docker build \
  --build-arg VERSION=$VER \                 # Injecte la version SemVer dans le binaire/labels OCI
  --build-arg GIT_SHA=$GIT_SHA \            # Injecte le SHA du commit pour traçabilité
  --build-arg SOURCE_DATE_EPOCH=1700000000 \# Fixe les timestamps (reproductibilité : mêmes empreintes)
  --label org.opencontainers.image.revision=$GIT_SHA \  # Label OCI : lien vers le commit source
  --cache-from type=registry,ref=$IMG:cache \ # Télécharge le cache de build depuis le registre
  --cache-to   type=registry,ref=$IMG:cache,mode=max \ # Publie le cache complet pour les builds futurs
  -t $IMG:$VER \                            # Tag de l'image : registre/org/app:version
  -f Dockerfile .                           # Utilise le Dockerfile dans le répertoire courant
```

> **Resultat attendu** :
> ```
> # Build réussi (exemple)
> => [internal] load build definition from Dockerfile
> => [build 1/5] FROM docker.io/library/python:3.12-slim@sha256:...
> => [build 2/5] WORKDIR /app
> => [build 3/5] COPY requirements.txt .
> => [build 4/5] RUN pip install --no-cache-dir -r requirements.txt
> => [build 5/5] COPY . .
> => exporting to image
> => => naming to ghcr.io/acme/api:1.3.0
> ```
> **Verification** : L'image `ghcr.io/acme/api:1.3.0` est construite localement. Vérifier avec `docker images ghcr.io/acme/api`.

* **BuildKit** : parallélisme, `--mount=type=cache`, secrets, empreintes stables.
* **cache-from/to** : **cache partagé** entre runners → builds plus rapides.
* **tag $VER** : on poussera ce tag, mais **on déploiera par digest**.

### 2.2 Multi-arch (amd64/arm64)

> **Objectif** : Construire et pousser une image multi-architecture (amd64 pour x86_64, arm64 pour ARM) en utilisant Buildx, ce qui crée un manifest index pointant vers les deux variantes.
> **Pre-requis** : Buildx configuré (création d'un builder), les variables `$VER`, `$GIT_SHA`, `$IMG` définies. Avoir les droits de push sur le registre cible.

```bash
# --- Création et sélection d'un builder Buildx (nécessaire pour multi-arch) ---
docker buildx create --name builder || true   # Crée un builder nommé 'builder' (ignore si existe déjà)
docker buildx use builder                     # Active ce builder pour les commandes suivantes

# --- Build multi-architectures avec push direct vers le registre ---
docker buildx build \
  --platform linux/amd64,linux/arm64 \        # Cible deux architectures : x86_64 et ARM64
  --build-arg VERSION=$VER --build-arg GIT_SHA=$GIT_SHA \  # Arguments de build (version + commit)
  --cache-from type=registry,ref=$IMG:cache \ # Récupère le cache depuis le registre
  --cache-to   type=registry,ref=$IMG:cache,mode=max \ # Publie le cache complet
  -t $IMG:$VER \                              # Tag de l'image finale
  --push .                                    # Pousse directement (obligatoire pour multi-arch)
```

> **Resultat attendu** :
> ```
> #1 [linux/amd64] load build definition from Dockerfile
> #2 [linux/arm64] load build definition from Dockerfile
> ...
> => => naming to ghcr.io/acme/api:1.3.0
> => => manifest sha256:e3b0c44298fc1c149afb...
> ```
> **Verification** : Vérifier le manifest multi-arch avec `docker buildx imagetools inspect $IMG:$VER` — on doit voir deux entrées (amd64 et arm64).

* `--platform` : publie un **manifest index** multi-arch.
* `--push` : nécessaire (sinon l'index ne peut pas être créé localement).

### 2.3 Digest & labels (vérifications)

> **Objectif** : Récupérer le digest SHA256 immuable de l'image poussée et vérifier les labels OCI associés (traçabilité du commit source).
> **Pre-requis** : L'image `$IMG:$VER` doit avoir été poussée sur le registre. Avoir `skopeo` et `jq` installés.

```bash
# --- Récupération du digest immuable de l'image depuis le registre ---
skopeo inspect docker://$IMG:$VER | jq -r .Digest  # Retourne sha256:... (référence immuable unique)

# --- Vérification des labels OCI intégrés dans l'image ---
docker image inspect $IMG:$VER --format '{{json .Config.Labels}}' | jq .
# Affiche les labels : org.opencontainers.image.revision, etc.
```

> **Resultat attendu** :
> ```
> # Digest :
> sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
>
> # Labels :
> {
>   "org.opencontainers.image.revision": "a1b2c3d"
> }
> ```
> **Verification** : Le digest est un `sha256:...` unique. Le label `revision` correspond bien au `$GIT_SHA` du build.

---

## 3) Tests **dans des conteneurs** (iso prod)

### 3.1 Unitaires (ex. Python)

> **Objectif** : Exécuter les tests unitaires dans un conteneur isolé (environnement reproductible, identique à la prod) sans rien installer sur le runner CI.
> **Pre-requis** : Avoir un fichier `requirements.txt` et des tests `pytest` dans le répertoire courant. Docker disponible sur le runner.

```bash
# --- Exécution des tests unitaires Python dans un conteneur éphémère ---
docker run --rm \                   # --rm : supprime le conteneur après exécution (pas de résidu)
  -v "$PWD":/app \                  # Monte le code source local dans /app du conteneur
  -w /app \                         # Définit /app comme répertoire de travail
  python:3.12 \                     # Image Python 3.12 (environnement d'exécution)
  bash -lc "pip install -r requirements.txt && pytest -q --maxfail=1 --disable-warnings"
  # Installe les dépendances puis lance pytest :
  #   -q : mode quiet (sortie concise)
  #   --maxfail=1 : stoppe dès le premier échec
  #   --disable-warnings : masque les warnings pour lisibilité
```

> **Resultat attendu** :
> ```
> ========================= test session starts ==========================
> collected 42 items
>
> tests/test_api.py ............                                    [ 28%]
> tests/test_models.py .................                            [ 69%]
> tests/test_utils.py ..............                                [100%]
>
> ========================= 42 passed in 3.21s ===========================
> ```
> **Verification** : Le code retour de la commande est 0 (succès). En cas d'échec, le code retour est non-nul → la CI échoue automatiquement.

* `-v`/`-w` : **monte** le code et définit le **répertoire de travail**.
* **Code retour** `pytest` => succès/échec du job CI.

### 3.2 Intégration (docker compose éphémère)

`compose.yaml` (extrait) :

> **Objectif** : Définir un environnement de test d'intégration éphémère avec l'API et une base PostgreSQL, orchestré par Docker Compose, pour tester les interactions entre services.
> **Pre-requis** : Avoir un `Dockerfile` pour l'API, Docker Compose v2 installé.

```yaml
# --- Définition des services pour les tests d'intégration ---
services:
  api:
    build: .                          # Construit l'image API depuis le Dockerfile local
    environment:
      DB_HOST: db                     # Pointe vers le service 'db' (résolution DNS interne Compose)
    depends_on: [ db ]                # Démarre 'db' avant 'api' (ordre de démarrage)
  db:
    image: postgres:16                # Image PostgreSQL 16 officielle
    environment:
      POSTGRES_PASSWORD: test         # Mot de passe PostgreSQL pour le test (ne pas utiliser en prod !)
```

> **Resultat attendu** :
> ```
> # Le fichier compose.yaml est valide et prêt à être utilisé par docker compose.
> ```
> **Verification** : `docker compose config` affiche la configuration résolue sans erreur.

CI :

> **Objectif** : Démarrer l'environnement de test (API + DB), exécuter les tests d'intégration contre l'API, puis détruire l'environnement proprement (sans état résiduel).
> **Pre-requis** : Le fichier `compose.yaml` ci-dessus doit exister. Les tests d'intégration doivent être configurés dans l'application.

```bash
# --- Démarrage de l'environnement de test (API + PostgreSQL) ---
docker compose up -d --build          # -d : détaché (en arrière-plan), --build : rebuild les images

# --- Exécution des tests d'intégration dans le service 'api' ---
docker compose run --rm api pytest -q # Lance pytest dans un conteneur 'api' éphémère (--rm)

# --- Nettoyage complet de l'environnement de test ---
docker compose down -v                # -v : supprime les volumes (pas d'état persistant parasite)
```

> **Resultat attendu** :
> ```
> # docker compose up -d --build
> ✔ Network ci_default    Created
> ✔ Container ci-db-1     Started
> ✔ Container ci-api-1    Started
>
> # docker compose run --rm api pytest -q
> ========================= 15 passed in 2.45s ===========================
>
> # docker compose down -v
> ✔ Container ci-api-1    Removed
> ✔ Container ci-db-1     Removed
> ✔ Network ci_default    Removed
> ```
> **Verification** : Tous les tests passent (code retour 0). `docker compose ps` après `down` ne montre aucun conteneur résiduel.

---

## 4) Scan CVE/licences & **SBOM**

### 4.1 SBOM & Scan (bloquant)

> **Objectif** : Générer une SBOM (Software Bill of Materials) au format SPDX pour inventorier tous les composants de l'image, puis scanner les vulnérabilités CVE critiques/hautes. Le scan est bloquant : si des CVE sévères sont trouvées, le pipeline échoue.
> **Pre-requis** : L'image `$IMG:$VER` doit exister (localement ou sur le registre). Avoir `syft` et `trivy` installés.

```bash
# --- Génération de la SBOM (inventaire de tous les composants/packages de l'image) ---
syft $IMG:$VER -o spdx-json > sbom.spdx.json   # Format SPDX-JSON : standard interopérable

# --- Scan de vulnérabilités CVE (bloquant sur HIGH et CRITICAL) ---
trivy image $IMG:$VER \
  --severity HIGH,CRITICAL \   # Ne remonte que les CVE de sévérité HIGH ou CRITICAL
  --ignore-unfixed \           # Ignore les CVE sans correctif disponible (politique configurable)
  --exit-code 1 \              # Code retour 1 si des CVE trouvées → fait échouer le pipeline CI
  --format table               # Affichage en tableau lisible dans les logs CI
```

> **Resultat attendu** :
> ```
> # SBOM (sbom.spdx.json) :
> # Fichier JSON contenant la liste de tous les packages (nom, version, licence, supplier)
>
> # Trivy scan :
> 2024-01-15T10:30:00.000Z  INFO  Detected OS: debian
> 2024-01-15T10:30:00.000Z  INFO  Scanning image for vulnerabilities...
>
> ghcr.io/acme/api:1.3.0 (debian 12.4)
> Total: 0 (HIGH: 0, CRITICAL: 0)
> ```
> **Verification** : Le fichier `sbom.spdx.json` est généré et non vide. Trivy retourne un code 0 (aucune CVE HIGH/CRITICAL). Si `Total > 0`, le pipeline échoue.

* **SBOM** : preuve de composition (SPDX/CycloneDX).
* **Trivy** : peut aussi **scanner licences** (`--ignore-policy` pour allowlist).

---

## 5) Signature & provenance (**Cosign**)

### 5.1 Signature « clé »

> **Objectif** : Signer l'image conteneur avec une paire de clés Cosign (clé privée/publique) pour garantir son intégrité et son origine. La signature est stockée dans le registre alongside l'image.
> **Pre-requis** : Avoir généré une paire de clés Cosign (`cosign generate-key-pair`). Avoir les fichiers `cosign.key` (privée) et `cosign.pub` (publique). Être authentifié sur le registre.

```bash
# --- Signature de l'image avec la clé privée Cosign ---
cosign sign --key cosign.key $IMG:$VER
# Demande le mot de passe de la clé privée (ou utilise COSIGN_PASSWORD)

# --- Vérification de la signature avec la clé publique ---
cosign verify --key cosign.pub $IMG:$VER
# Retourne le certificat de signature si valide, erreur sinon
```

> **Resultat attendu** :
> ```
> # cosign sign
> Enter password for private key:
> Pushing signature to: ghcr.io/acme/api:sha256-e3b0c44298fc1c149...sig
>
> # cosign verify
> Verification is successful -- all signatures are valid
> ```
> **Verification** : `cosign verify` retourne "Verification is successful". La signature est visible dans le registre (tag `sha256-<digest>.sig`).

### 5.2 Signature **keyless OIDC** (GitHub/GitLab)

> **Objectif** : Signer l'image sans clé privée statique, en utilisant l'identité OIDC du CI (GitHub Actions ou GitLab CI). Plus sécurisé : pas de secret à gérer/rotater. Utilise Sigstore/Rekor pour la transparence.
> **Pre-requis** : Être dans un CI supportant OIDC (GitHub Actions avec `id-token: write`, ou GitLab CI). Avoir `cosign` v2+ installé. `COSIGN_EXPERIMENTAL=1` active le mode keyless.

```bash
# --- Signature keyless via OIDC (l'identité du CI sert de preuve) ---
COSIGN_EXPERIMENTAL=1 cosign sign $IMG:$VER
# Utilise le token OIDC du CI pour obtenir un certificat éphémère Sigstore

# --- Vérification keyless (vérifie via le certificat transparent Sigstore) ---
COSIGN_EXPERIMENTAL=1 cosign verify $IMG:$VER
# Vérifie l'identité (issuer: github.com, subject: repo acme/api)
```

> **Resultat attendu** :
> ```
> # cosign sign (keyless)
> Generating ephemeral keys...
> Retrieving signed certificate...
> Successfully verified SCT...
> Pushing signature to: ghcr.io/acme/api:sha256-e3b0c44298fc1c149...sig
>
> # cosign verify (keyless)
> Verification is successful -- all signatures are valid
> ```
> **Verification** : La signature est liée à l'identité OIDC du CI (visible dans Rekor). Pas de clé privée stockée.

* **Attributs d'identité** (issuer, subject) enregistrés → **vérifiables** côté cluster.
* Possibles **attestations** (SLSA provenance, SBOM) via `cosign attest`.

---

## 6) Push & **promotion** d'images (sans rebuild)

### 6.1 Login & push

> **Objectif** : S'authentifier sur le registre de conteneurs de manière sécurisée (mot de passe via stdin, pas en argument) et pousser l'image signée vers le registre.
> **Pre-requis** : Avoir un token d'accès au registre (`$REG_TOKEN`) et un nom d'utilisateur (`$REG_USER`). L'image `$IMG:$VER` doit être construite localement.

```bash
# --- Authentification sécurisée au registre (mot de passe via stdin) ---
echo "$REG_TOKEN" | docker login $REG -u "$REG_USER" --password-stdin
# --password-stdin : évite que le mot de passe apparaisse dans 'ps' ou l'historique

# --- Push de l'image vers le registre ---
docker push $IMG:$VER
# Pousse l'image et retourne le digest dans la sortie
```

> **Resultat attendu** :
> ```
> # docker login
> Login Succeeded
>
> # docker push
> The push refers to repository [ghcr.io/acme/api]
> 5e1234abcd: Pushed
> 1.3.0: digest: sha256:e3b0c44298fc1c149... size: 1782
> ```
> **Verification** : `docker login` retourne "Login Succeeded". Le push affiche un digest `sha256:...`.

### 6.2 Promotion (ex. GHCR → Harbor) **sans rebuild**

> **Objectif** : Copier/promouvoir une image d'un registre à un autre (ex. de GHCR vers Harbor interne) **sans reconstruire**, en préservant le digest immuable. Utile pour les environnements air-gap ou la promotion entre environnements.
> **Pre-requis** : Avoir `skopeo` installé. Être authentifié sur les deux registres (source et destination). L'image source `$IMG:$VER` doit exister.

```bash
# --- Copie de l'image d'un registre source vers un registre destination (sans rebuild) ---
skopeo copy docker://$IMG:$VER docker://harbor.local/$ORG/$APP:$VER
# Copie le manifest + toutes les layers → préserve le digest exact
```

> **Resultat attendu** :
> ```
> Getting image source signatures
> Copying blob sha256:... done
> Copying config sha256:... done
> Writing manifest to image destination
> ```
> **Verification** : Le digest de l'image dans Harbor est identique à celui de GHCR : `skopeo inspect docker://harbor.local/$ORG/$APP:$VER | jq .Digest` retourne le même `sha256:...`.

* **Préserve le digest** (trace immuable).

---

## 7) **Déploiement push-based** (Helm/Kustomize) — par **digest**

### 7.1 Helm (image par digest, explications flags)

> **Objectif** : Déployer ou mettre à jour l'application dans Kubernetes via Helm, en référençant l'image par son **digest SHA256** (immuable) plutôt que par tag. Cela garantit que la version déployée est exactement celle qui a été buildée/testée/signée.
> **Pre-requis** : Avoir `skopeo`, `jq`, `helm` installés. Avoir un chart Helm dans `./deploy/helm/api`. Avoir un kubeconfig valide pointant vers le cluster cible.

```bash
# --- Récupération du digest immuable depuis le registre ---
DIGEST=$(skopeo inspect docker://$IMG:$VER | jq -r .Digest)
# Ex: DIGEST=sha256:e3b0c44298fc1c149...

# --- Déploiement/mise à jour Helm avec l'image référencée par digest ---
helm upgrade --install api ./deploy/helm/api \
  -n app --create-namespace \         # Déploie dans le namespace 'app', le crée s'il n'existe pas
  --set image.repository=$IMG \       # Override : repo de l'image (ghcr.io/acme/api)
  --set image.digest=$DIGEST \        # Override : digest précis (immutabilité garantie)
  --wait --timeout 5m                 # Attend que tous les pods soient Ready (max 5 min), sinon échec
```

> **Resultat attendu** :
> ```
> Release "api" has been upgraded. Happy Helming!
> NAME: api
> NAMESPACE: app
> STATUS: deployed
> REVISION: 3
> TEST SUITE: None
> ```
> **Verification** : `kubectl -n app get pods` montre les pods en état `Running` avec `READY 1/1`. `kubectl -n app get deploy api -o jsonpath='{.spec.template.spec.containers[0].image}'` affiche l'image avec `@sha256:...`.

* `--wait/--timeout` : **garde-fou** (évite « déploiement vert » alors que non prêt).
* **Rollback** Helm en cas d'échec post-checks (voir runbooks).

### 7.2 Kustomize (overlays)

> **Objectif** : Générer les manifests Kubernetes avec Kustomize pour l'environnement de production, les valider avec `kubeconform` (vérification de schéma), puis les appliquer au cluster et suivre le statut du déploiement.
> **Pre-requis** : Avoir `kustomize` et `kubeconform` installés. Avoir une structure Kustomize dans `deploy/kustomize/overlays/prod`. Avoir un kubeconfig valide.

```bash
# --- Validation + Application des manifests Kustomize pour la production ---
kustomize build deploy/kustomize/overlays/prod | kubeconform - && \
# kubeconform - : valide le YAML rendu contre les schémas Kubernetes (erreurs de structure)
kustomize build deploy/kustomize/overlays/prod | kubectl apply -f -
# Applique les manifests validés au cluster (fournis via stdin)

# --- Suivi du déploiement (attend que le rollout soit terminé) ---
kubectl -n app rollout status deploy/api
# Bloque jusqu'à ce que le déploiement soit complet ou timeout
```

> **Resultat attendu** :
> ```
> # kubeconform : aucune sortie si valide
> # kubectl apply :
> deployment.apps/api configured
> service/api unchanged
>
> # kubectl rollout status :
> deployment "api" successfully rolled out
> ```
> **Verification** : `kubeconform` ne retourne aucune erreur. `kubectl rollout status` affiche "successfully rolled out". `kubectl -n app get pods` montre les nouveaux pods Ready.

* `kubeconform -` : **valide** le rendu contre les schémas.

---

## 8) **GitOps** (Argo CD / Flux) — principes et manifests

### 8.1 Organisation des dépôts

* **Repo applicatif** : code + Dockerfile + chart Helm base / kustomize base.
* **Repo d'infra (GitOps)** : dossiers `envs/dev|staging|prod` (values Helm ou overlays Kustomize).

  * La CI **modifie** le repo d'infra (commit du **digest**), puis **Argo/Flux** synchronise.

---

### 8.2 Argo CD — `Application` (Helm par exemple)

`argocd-app-api.yaml`

> **Objectif** : Définir une ressource Argo CD `Application` qui déclare l'état désiré du déploiement de l'API. Argo CD surveille le repo d'infra Git et synchronise automatiquement les changements vers le cluster Kubernetes.
> **Pre-requis** : Argo CD installé sur le cluster. Le repo d'infra (`acme/infra.git`) doit contenir le chart Helm et les values. Le namespace `argocd` doit exister.

```yaml
# --- Définition de l'Application Argo CD pour le déploiement de l'API ---
apiVersion: argoproj.io/v1alpha1       # API group Argo CD (version alpha mais stable en pratique)
kind: Application                      # Ressource Argo CD représentant une application déployée
metadata:
  name: api                            # Nom unique de l'application dans Argo CD
  namespace: argocd                    # Namespace où Argo CD est installé
spec:
  project: default                     # Projet Argo CD (regroupement logique, 'default' par défaut)
  source:
    repoURL: https://github.com/acme/infra.git     # URL du repo GitOps (source de vérité)
    targetRevision: main                           # Branche Git à surveiller
    path: envs/prod/helm/api                       # Chemin dans le repo vers le chart/values
    helm:
      valueFiles: [ "values-prod.yaml" ]           # Fichier de values où le digest est mis à jour par la CI
  destination:
    server: https://kubernetes.default.svc         # Cluster cible (ici, le cluster local d'Argo)
    namespace: app                                 # Namespace de déploiement des ressources
  syncPolicy:
    automated:
      prune: true         # Supprime automatiquement les ressources orphelines (non présentes dans Git)
      selfHeal: true      # Re-synchronise automatiquement en cas de dérive manuelle (drift)
    syncOptions:
      - CreateNamespace=true          # Crée le namespace 'app' s'il n'existe pas
      - ApplyOutOfSyncOnly=true       # N'applique que les ressources modifiées (plus rapide)
```

> **Resultat attendu** :
> ```
> # Après kubectl apply -f argocd-app-api.yaml :
> # Dans l'UI Argo CD, l'application 'api' apparaît avec le statut :
> STATUS: Synced
> HEALTH: Healthy
> ```
> **Verification** : `argocd app get api` montre `Status: Synced` et `Health: Healthy`. Les pods sont Running dans le namespace `app`.

* **Argo** lit le repo d'infra et **applique** les changements.
* **Promotion** : PR vers `envs/prod` (review/approbation), merge ⇒ Argo sync.

**Mettre à jour le digest (CI côté repo infra)** :

> **Objectif** : Mettre à jour le fichier `values-prod.yaml` dans le repo d'infra avec le nouveau digest de l'image, puis committer et pousser pour déclencher la synchronisation Argo CD.
> **Pre-requis** : Être dans le repo d'infra (cloné localement). Avoir `skopeo`, `jq`, `yq` installés. Avoir les droits de commit/push sur le repo d'infra.

```bash
# --- Mise à jour du digest dans le repo GitOps (déclenche Argo CD) ---
# Dans le repo d'infra:
export DIGEST=$(skopeo inspect docker://$IMG:$VER | jq -r .Digest)
# Récupère le digest immuable de l'image depuis le registre

yq -i '.image.repository=strenv(IMG) | .image.digest=strenv(DIGEST)' envs/prod/helm/api/values-prod.yaml
# Met à jour les champs 'image.repository' et 'image.digest' dans le fichier values
# strenv() : injecte les variables d'environnement comme chaînes YAML

git commit -am "api: $VER ($DIGEST)" && git push origin main
# Commit le changement avec le message incluant version + digest, puis pousse
# → Argo CD détecte le changement et synchronise automatiquement
```

> **Resultat attendu** :
> ```
> [main abc1234] api: 1.3.0 (sha256:e3b0c44298fc1c149...)
>  1 file changed, 2 insertions(+), 2 deletions(-)
> To https://github.com/acme/infra.git
>    def5678..abc1234  main -> main
> ```
> **Verification** : Dans Argo CD, l'application passe en `OutOfSync` puis `Synced` après quelques secondes. `kubectl -n app get deploy api -o jsonpath='{.spec.template.spec.containers[0].image}'` montre le nouveau digest.

> Alternative Argo : **Argo Image Updater** (scrute le registre et ouvre des PRs pour bump tag/digest).

---

### 8.3 FluxCD — GitRepository + (HelmRelease **ou** Kustomization)

**Référencer le repo d'infra**

> **Objectif** : Déclarer une source Git pour Flux CD, qui pointe vers le repo d'infra et le scrute toutes les minutes pour détecter les changements (commits).
> **Pre-requis** : Flux CD installé sur le cluster (namespace `flux-system`). Le repo `acme/infra.git` doit être accessible.

```yaml
# --- Source Git pour Flux CD : définit le repo d'infra à surveiller ---
apiVersion: source.toolkit.fluxcd.io/v1   # API Flux source controller
kind: GitRepository                        # Ressource déclarant un repo Git comme source
metadata:
  name: infra                              # Nom de référence pour les autres ressources Flux
  namespace: flux-system                   # Namespace de Flux (où tourne le source-controller)
spec:
  interval: 1m                             # Fréquence de scrutation du repo (toutes les 1 minute)
  url: https://github.com/acme/infra.git   # URL du repo GitOps
  ref: { branch: main }                    # Branche à surveiller
```

> **Resultat attendu** :
> ```
> # kubectl apply -f gitrepository.yaml
> gitrepository.source.toolkit.fluxcd.io/infra created
>
> # kubectl -n flux-system get gitrepository infra
> NAME    URL                              AGE   READY
> infra   https://github.com/acme/infra.git  30s   True
> ```
> **Verification** : `kubectl -n flux-system get gitrepository infra` montre `READY: True`. Le controller a cloné le repo.

**Déployer un chart Helm (HelmRelease)**
`HelmRelease` (digest dans `values`) :

> **Objectif** : Déclarer un déploiement Helm géré par Flux CD. Le HelmRelease référence le chart dans le repo Git et injecte les values (dont le digest de l'image). Flux surveille les changements Git et les changements d'image, et réconcilie automatiquement.
> **Pre-requis** : Le `GitRepository` ci-dessus doit être créé et Ready. Le chart Helm doit exister dans `./envs/prod/helm/api` du repo d'infra. Flux helm-controller doit être installé.

```yaml
# --- HelmRelease Flux CD : déploiement Helm automatisé avec réconciliation ---
apiVersion: helm.toolkit.fluxcd.io/v2      # API Flux helm controller (v2)
kind: HelmRelease                          # Ressource déclarant un déploiement Helm
metadata:
  name: api                                # Nom du HelmRelease
  namespace: app                           # Namespace de déploiement
spec:
  interval: 1m                             # Fréquence de réconciliation (vérifie chaque minute)
  chart:
    spec:
      chart: ./envs/prod/helm/api          # Chemin vers le chart dans le repo Git
      sourceRef:
        kind: GitRepository                # Référence la source Git déclarée plus haut
        name: infra                        # Nom du GitRepository
        namespace: flux-system             # Namespace du GitRepository
  values:
    image:
      repository: ghcr.io/acme/api         # Repo de l'image conteneur
      digest: "sha256:ABCD..."             # Digest immuable (mis à jour par CI ou Image Automation)
  install: { remediation: { retries: 3 } } # En cas d'échec à l'installation : 3 tentatives
  upgrade: { remediation: { retries: 3 } } # En cas d'échec à la mise à jour : 3 tentatives
```

> **Resultat attendu** :
> ```
> # kubectl apply -f helmrelease.yaml
> helmrelease.helm.toolkit.fluxcd.io/api created
>
> # kubectl -n app get helmrelease api
> NAME   AGE   READY   STATUS
> api    45s   True    Release reconciliation succeeded
> ```
> **Verification** : `kubectl -n app get helmrelease api` montre `READY: True`. `flux -n app get helmreleases` confirme le statut. Les pods sont Running.

**Automatisation du bump d'image (Flux Image Automation)** :

* `ImageRepository` → source registre,
* `ImagePolicy` → règle (tag semver ou latest digest),
* `ImageUpdateAutomation` → commite le fichier `values` ou kustomize image.

---

## 9) Sécurité du pipeline & politiques d'admission (rappel croisé Ch. 8)

* **OIDC** CI → Registre/Cloud (évite secrets statiques).
* **Permissions minimales** (GitHub : `id-token: write`, `packages: write`, rien d'autre).
* **Pas de secrets** dans les logs (masking).
* Admission (Kyverno/OPA/CEL) :

  * **Interdire** `:latest`,
  * **Exiger** `repo@sha256:…`,
  * **Exiger** **signature Cosign** par clef/issuer attendu,
  * **Allow-list** des **registres** autorisés.

---

## 10) Observabilité du CI/CD

* **Artefacts** : SBOM (SPDX/CycloneDX), rapports Trivy (SARIF), coverage/tests (JUnit).
* **Métriques** : durée par stage, taux d'échec, ratio cache hit, temps de pull/push.
* **Alertes** : échec build/test/scan/deploy → Slack/Teams/PagerDuty avec **runbook_url**.

---

## 11) **TD minimal** : pipeline qui build & déploie **par digest** (Helm)

### 11.1 Préparer le chart (déjà posé au Ch. 10)

Dans `values.yaml`, prévoir :

> **Objectif** : Définir la structure du fichier `values.yaml` du chart Helm pour supporter le déploiement par digest. Le champ `tag` est inutilisé en production ; seul `digest` est renseigné par la CI.
> **Pre-requis** : Avoir un chart Helm dans `deploy/helm/api/`. Le template du déploiement doit utiliser `{{ .Values.image.repository }}@{{ .Values.image.digest }}` comme référence d'image.

```yaml
# --- Configuration de l'image dans values.yaml du chart Helm ---
image:
  repository: ghcr.io/acme/api   # Repository de l'image (sans tag ni digest)
  tag: ""                        # Non utilisé en production (réservé au dev local)
  digest: ""                     # ← Champ renseigné par la CI avec le sha256 de l'image
  # En production, l'image sera : ghcr.io/acme/api@sha256:xxxx
```

> **Resultat attendu** :
> ```
> # Le fichier values.yaml est valide et sera utilisé comme base par Helm.
> # La CI override 'digest' via --set image.digest=sha256:...
> ```
> **Verification** : `helm template ./deploy/helm/api --set image.digest=sha256:test` génère un Deployment avec l'image `ghcr.io/acme/api@sha256:test`.

### 11.2 GitHub Actions — workflow minimal annoté

`.github/workflows/ci.yml`

> **Objectif** : Définir un workflow GitHub Actions complet qui automatise tout le pipeline CI/CD : build multi-arch, scan de vulnérabilités, SBOM, signature keyless, push vers GHCR, et déploiement Helm par digest sur le cluster Kubernetes.
> **Pre-requis** : Le dépôt doit contenir un `Dockerfile`, un chart Helm dans `deploy/helm/api/`. Les secrets `GITHUB_TOKEN` (automatique) et `KUBECONFIG_B64` (kubeconfig encodé en base64) doivent être configurés. Le workflow se déclenche sur les tags `v*.*.*`.

```yaml
# --- Workflow CI/CD complet : Build → Scan → Sign → Push → Deploy ---
name: ci                                 # Nom du workflow (affiché dans l'UI GitHub)
on:
  push:
    tags: [ 'v*.*.*' ]                   # Déclenchement uniquement sur les tags SemVer (v1.0.0, v1.3.0, etc.)

jobs:
  build-scan-sign-push-deploy:           # Job unique contenant toutes les étapes séquentielles
    runs-on: ubuntu-latest               # Runner GitHub Actions (Ubuntu dernière version)
    permissions:
      contents: read                     # Lecture du code (checkout)
      id-token: write                    # OIDC : nécessaire pour cosign keyless (pas de secret)
      packages: write                    # Push vers GHCR (GitHub Container Registry)
      security-events: write             # Upload des rapports SARIF (Security tab)
    env:
      REG: ghcr.io                       # Registre cible (GitHub Container Registry)
      ORG: acme                          # Organisation / propriétaire du package
      APP: api                           # Nom de l'application / image
    steps:
      # --- Étape 1 : Récupération du code source ---
      - uses: actions/checkout@v4        # Action officielle : clone le dépôt

      # --- Étape 2 : Définition des variables dérivées ---
      - name: Set vars
        run: |
          # Extrait la version depuis le tag (enlève le 'v' prefix : v1.3.0 → 1.3.0)
          echo "VER=${GITHUB_REF_NAME#v}" >> $GITHUB_ENV
          # Construit le chemin complet de l'image
          echo "IMG=${REG}/${ORG}/${APP}" >> $GITHUB_ENV

      # --- Étape 3 : Configuration de Buildx (builder multi-arch) ---
      - uses: docker/setup-buildx-action@v3  # Installe et configure Buildx

      # --- Étape 4 : Authentification au registre GHCR ---
      - name: Login GHCR
        uses: docker/login-action@v3         # Action officielle : login Docker
        with:
          registry: ${{ env.REG }}           # ghcr.io
          username: ${{ github.actor }}      # Utilisateur GitHub actuel
          password: ${{ secrets.GITHUB_TOKEN }}  # Token automatique GitHub

      # --- Étape 5 : Build multi-arch + Push avec cache distribué ---
      - name: Build & Push (multi-arch + cache)
        uses: docker/build-push-action@v6    # Action officielle : build Docker avec Buildx
        with:
          context: .                         # Contexte de build (répertoire courant)
          push: true                         # Pousse l'image vers le registre après build
          platforms: linux/amd64,linux/arm64 # Multi-architecture
          tags: ${{ env.IMG }}:${{ env.VER }}  # Tag de l'image (version SemVer)
          cache-from: type=registry,ref=${{ env.IMG }}:cache    # Cache source (accélère le build)
          cache-to:   type=registry,ref=${{ env.IMG }}:cache,mode=max  # Cache destination
          build-args: |
            VERSION=${{ env.VER }}           # Version injectée dans le build
            GIT_SHA=${{ github.sha }}        # SHA complet du commit

      # --- Étape 6 : Calcul du digest immuable ---
      - name: Compute digest
        id: dig                              # ID de l'étape (pour récupérer les outputs)
        run: |
          # Récupère le digest SHA256 depuis le registre et le stocke en output
          echo "DIGEST=$(skopeo inspect docker://${IMG}:${VER} | jq -r .Digest)" >> $GITHUB_OUTPUT

      # --- Étape 7 : Génération SBOM + Scan de vulnérabilités ---
      - name: SBOM (Syft) + Scan (Trivy)
        run: |
          # Génère la SBOM au format SPDX-JSON (inventaire des composants)
          syft ${IMG}:${VER} -o spdx-json > sbom.spdx.json
          # Scan CVE HIGH/CRITICAL : échoue le pipeline si des CVE sont trouvées
          trivy image ${IMG}:${VER} --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1

      # --- Étape 8 : Signature de l'image (Cosign keyless via OIDC) ---
      - name: Sign image (Cosign keyless)
        env: { COSIGN_EXPERIMENTAL: "1" }    # Active le mode keyless (OIDC)
        run: cosign sign ${IMG}:${VER}       # Signe l'image avec l'identité du workflow GitHub

      # --- Étape 9 : Installation des outils Kubernetes ---
      - name: Install kubectl & helm
        uses: azure/setup-helm@v4            # Installe Helm (et kubectl est pré-installé sur ubuntu-latest)

      # --- Étape 10 : Configuration du kubeconfig ---
      - name: Kubeconfig
        run: echo "${KUBECONFIG_B64}" | base64 -d > $HOME/.kube/config
        # Décode le kubeconfig encodé en base64 (stocké en secret) et le place au chemin standard
        env:
          KUBECONFIG_B64: ${{ secrets.KUBECONFIG_B64 }}  # Secret contenant le kubeconfig encodé

      # --- Étape 11 : Déploiement Helm par digest ---
      - name: Helm upgrade by digest
        run: |
          # Déploie/met à jour l'application Helm en référençant l'image par son digest immuable
          helm upgrade --install api ./deploy/helm/api -n app --create-namespace \
            --set image.repository=${IMG} \                          # Repo de l'image
            --set image.digest=${{ steps.dig.outputs.DIGEST }} \     # Digest calculé à l'étape 6
            --wait --timeout 5m                                      # Attend pods Ready (max 5 min)
```

> **Resultat attendu** :
> ```
> # Dans l'UI GitHub Actions, le workflow s'exécute avec tous les steps verts :
> ✓ Set vars
> ✓ Login GHCR
> ✓ Build & Push (multi-arch + cache)    → Image poussée sur ghcr.io/acme/api:1.3.0
> ✓ Compute digest                        → sha256:e3b0c44298fc1c149...
> ✓ SBOM (Syft) + Scan (Trivy)           → 0 CVE HIGH/CRITICAL
> ✓ Sign image (Cosign keyless)           → Signature uploadée dans le registre
> ✓ Helm upgrade by digest                → Release "api" deployed, REVISION: 3
> ```
> **Verification** : Le workflow est vert. `kubectl -n app get pods` montre les pods Running. `kubectl -n app get deploy api -o jsonpath='{.spec.template.spec.containers[0].image}'` affiche `ghcr.io/acme/api@sha256:...`.

**À noter** :

* `id-token: write` ⇒ **cosign keyless** sans secret.
* **Digest** calculé via `skopeo` puis injecté dans Helm.
* **Scan bloquant** (Trivy) avant signature/push.
* Variante **GitOps** : au lieu du job Helm, **modifier** le `values-prod.yaml` dans le **repo d'infra** (PR/merge), Argo/Flux synchronise.

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
  → Vérifier la réf Git, droit d'accès au repo, CRD présentes.

---

## 13) Check-list opérationnelle

* [ ] Dockerfile **multi-stage**, **USER non-root**, labels OCI, bases **pinées par digest**.
* [ ] Build **Buildx** multi-arch + **cache** registre.
* [ ] Tests unitaires/intégration (Compose ou services CI).
* [ ] **SBOM** générée ; **scan** CVE/licences **bloquant** (exceptions datées/justifiées).
* [ ] **Signature** Cosign (key/Keyless) + (option) **attestations** provenance/SBOM.
* [ ] **Push** image ; **digest** récupéré.
* [ ] CD **par digest** : Helm/Kustomize (push-based) **ou** PR GitOps vers repo d'infra.
* [ ] Politiques d'admission (Kyverno/OPA/CEL) : **signature requise**, **digest obligatoire**, **no `:latest`**, allow-list registres.
* [ ] Observabilité CI/CD (artefacts, métriques, alertes) + **runbooks** reliés.
