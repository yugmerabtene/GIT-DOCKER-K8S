# Chapitre-05 — Dockerfile & Build (BuildKit avancé)

## Objectifs d'apprentissage

* Écrire des **Dockerfiles** clairs, sûrs et performants : maîtriser les instructions, les scopes (`ARG`, `ENV`, `FROM`, `USER`, `WORKDIR`, `ENTRYPOINT`/`CMD`, `HEALTHCHECK`, etc.).
* Concevoir des **multi-stage builds** (builder → runtime) pour réduire la taille et la surface d'attaque.
* Exploiter **BuildKit** : `RUN --mount=type=cache|secret|ssh`, `COPY --from`, labels OCI, `.dockerignore`, optimisation des couches.
* Produire des images **multi-architecture** et traçables avec **buildx** (`--platform`, `--provenance`, `--sbom`, caches distants).
* Garantir **reproductibilité** et **gouvernance** (pinning versions, metadata, SBOM/provenance, politiques de tags).

## Pré-requis

* Docker Engine/CLI, BuildKit activé (Docker Desktop : par défaut ; Linux : `DOCKER_BUILDKIT=1`).
* Bases Linux (shell, permissions), notions réseau pour accès à des registries.

---

## 1) Fondamentaux du Dockerfile

### 1.1 En-tête BuildKit (recommandé)

> **Objectif** : Activer le moteur de build BuildKit (au lieu du legacy builder) pour bénéficier des fonctionnalités avancées comme `RUN --mount`, le cache amélioré, et les builds parallélisés.
> **Pré-requis** : Docker 18.09+ avec BuildKit disponible (activé par défaut sur Docker Desktop ; sur Linux serveur, positionner `DOCKER_BUILDKIT=1`).

```dockerfile
# syntax=docker/dockerfile:1.7  # Directive MUST be on line 1 — active BuildKit front-end v1.7
```

* Active les features récentes (ex. `RUN --mount=...`, `COPY --chmod/--chown`, améliorations de cache).

> **Résultat attendu** :
> ```
> # Au début du build, BuildKit affiche :
> #1 [internal] load build definition from Dockerfile
> #1 transferring dockerfile: 45B done
> #1 DONE 0.0s
> ```
> **Vérification** : La première ligne du build montre "load build definition" via BuildKit (pas l'ancien "Sending build context").

### 1.2 `FROM`, `ARG`, `ENV`

> **Objectif** : Définir l'image de base de manière paramétrable via `ARG`, puis configurer des variables d'environnement persistantes dans l'image avec `ENV`.
> **Pré-requis** : Avoir une image de base accessible (ici `alpine:3.20` depuis Docker Hub).

```dockerfile
ARG BASE_TAG=3.20                          # ARG avant FROM = scope global, accessible par tous les FROM
FROM alpine:${BASE_TAG} AS base            # Image de base Alpine 3.20, nommée "base" pour référence multi-stage

# ARG défini AVANT le FROM suivant si vous devez le réutiliser
ARG APP_VER=1.4.2                          # ARG local au stage courant (après FROM) — utilisé uniquement au build
ENV TZ=UTC LANG=C.UTF-8                    # Variables persistées dans l'image, disponibles au runtime
```

* `ARG` : disponible **à la construction** (non présent à l'exécution). Scope **local au stage** si déclaré après `FROM`.
* `ENV` : persiste **dans l'image** et sera visible au runtime.

> **Résultat attendu** :
> ```
> #2 [internal] load metadata for docker.io/library/alpine:3.20
> #2 DONE 1.2s
> #3 [base 1/1] FROM docker.io/library/alpine:3.20@sha256:...
> ```
> **Vérification** : `docker run --rm <image> env | grep TZ` affiche `TZ=UTC`. `docker inspect <image> --format '{{.Config.Env}}'` montre `[TZ=UTC LANG=C.UTF-8]`.

### 1.3 `COPY` vs `ADD`

* **Préférer `COPY`** (comportement explicite).
* `ADD` **seulement** pour :
  a) extraire automatiquement un **tar** vers le FS, ou
  b) **télécharger** une URL (peu recommandé pour supply-chain).

> **Objectif** : Copier un binaire depuis le contexte de build vers l'image en définissant le propriétaire (UID:GID) et les permissions (mode) directement lors du COPY, évitant ainsi une couche supplémentaire pour `chown`/`chmod`.
> **Pré-requis** : Le fichier `./bin/app` doit exister dans le contexte de build. BuildKit requis pour `--chmod` (syntax >= 1.3).

```dockerfile
COPY --chown=10001:10001 --chmod=0755 ./bin/app /usr/local/bin/app  # Copie avec owner UID 10001 et perms rwxr-xr-x
```

> **Résultat attendu** :
> ```
> #5 COPY --chown=10001:10001 --chmod=0755 ./bin/app /usr/local/bin/app
> #5 DONE 0.1s
> ```
> **Vérification** : `docker run --rm <image> ls -la /usr/local/bin/app` montre le fichier appartenant à `10001:10001` avec les permissions `-rwxr-xr-x`.

### 1.4 `WORKDIR`, `USER`, `SHELL`

> **Objectif** : Définir le répertoire de travail, créer un utilisateur non-root (bonne pratique de sécurité) et basculer vers cet utilisateur pour que le conteneur ne s'exécute pas en tant que root.
> **Pré-requis** : Image Alpine (pour les commandes `addgroup`/`adduser`).

```dockerfile
WORKDIR /app                               # Définit /app comme répertoire courant (le crée s'il n'existe pas)
# Créer un user non-root (ex. Alpine)
RUN addgroup -S app && adduser -S -G app -u 10001 app  # -S = system user/group, UID 10001 fixe
USER 10001:10001                           # UID:GID — toutes les instructions suivantes et le runtime tournent sans root
# SHELL utile côté Windows ou bash spécifique
```

> **Résultat attendu** :
> ```
> #4 [stage-0 1/3] WORKDIR /app
> #4 DONE 0.1s
> #5 [stage-0 2/3] RUN addgroup -S app && adduser -S -G app -u 10001 app
> #5 DONE 0.4s
> ```
> **Vérification** : `docker run --rm <image> whoami` retourne `app` (ou l'UID 10001). `docker run --rm <image> id` affiche `uid=10001(app) gid=10001(app)`.

### 1.5 `ENTRYPOINT` & `CMD` (formes exec vs shell)

* **Forme exec** (recommandée) : pas de shell implicite, signaux mieux relayés.

> **Objectif** : Configurer le processus principal du conteneur en forme exec (JSON array) pour que le binaire reçoive directement les signaux (SIGTERM, SIGINT) sans intermédiaire shell.
> **Pré-requis** : Le binaire `/usr/local/bin/app` doit exister dans l'image.

```dockerfile
ENTRYPOINT ["/usr/local/bin/app"]          # Forme exec : le binaire est le PID 1 direct (pas de /bin/sh -c)
CMD ["--help"]                             # Arguments par défaut, remplaçables par ceux passés à `docker run`
```

* **Forme shell** : `ENTRYPOINT myapp.sh` (shell `/bin/sh -c`) → moins prévisible pour signaux/env.

> **Résultat attendu** :
> ```
> $ docker run --rm <image>
> # Affiche l'aide de l'application (--help est l'argument par défaut de CMD)
> $ docker run --rm <image> --version
> # Affiche la version (CMD est remplacé par --version)
> ```
> **Vérification** : `docker inspect <image> --format '{{.Config.Entrypoint}} {{.Config.Cmd}}'` affiche `[/usr/local/bin/app] [--help]`. Un `docker stop` envoie SIGTERM directement au PID 1 (le binaire).

### 1.6 `HEALTHCHECK`, `EXPOSE`, `STOPSIGNAL`, `ONBUILD`

> **Objectif** : Ajouter une vérification de santé périodique pour le conteneur, documenter le port d'écoute, définir le signal d'arrêt et comprendre `ONBUILD` (à éviter sauf images-modèles).
> **Pré-requis** : L'application doit écouter sur le port 8080 et répondre sur `/health` avec un code HTTP 200. `wget` doit être disponible dans l'image.

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \    # Vérifie toutes les 30s, timeout 5s, 3 échecs = unhealthy
  CMD wget -qO- http://127.0.0.1:8080/health || exit 1   # Requête silencieuse ; exit 1 = échec si non-200

EXPOSE 8080              # métadonnée documentaire (aucune ouverture de port) — informer que le conteneur écoute sur 8080
STOPSIGNAL SIGTERM       # signal d'arrêt conseillé — Docker envoie SIGTERM avant SIGKILL (après 10s de grâce)
# ONBUILD : à éviter sauf images-modèles (déclenche une instruction dans l'enfant)
```

> **Résultat attendu** :
> ```
> $ docker run -d --name web -p 8080:8080 <image>
> $ docker ps
> CONTAINER ID   IMAGE    STATUS                    PORTS
> abc123         <image>  Up 2 minutes (healthy)    0.0.0.0:8080->8080/tcp
> ```
> **Vérification** : `docker inspect --format '{{.State.Health.Status}}' web` affiche `healthy`. `docker inspect <image> --format '{{.Config.ExposedPorts}}'` montre `map[8080/tcp:{}]`.

### 1.7 `.dockerignore` (critique)

* Réduire le **contexte** envoyé au démon (perf & sécurité).
* Empêcher l'embarquement involontaire de secrets/artefacts lourds.

Exemple générique :

> **Objectif** : Exclure du contexte de build les fichiers inutiles (dépôts Git, dépendances locales, fichiers sensibles, artefacts de compilation) pour accélérer le build et éviter d'embarquer des secrets ou des fichiers volumineux dans l'image.
> **Pré-requis** : Créer un fichier `.dockerignore` à la racine du projet (même niveau que le Dockerfile).

```
.git                 # Exclut tout le répertoire .git (historique, objets — souvent > 100 Mo)
.gitignore
**/.env              # Exclut tous les fichiers .env à n'importe quelle profondeur (contiennent des secrets)
**/node_modules      # Exclut les node_modules locaux (seront réinstallés dans l'image via npm ci)
**/target            # Exclut les artefacts de compilation (Maven, Rust, etc.)
**/venv              # Exclut les environnements virtuels Python
*.pem                # Exclut les certificats PEM (clés privées potentielles)
*.key                # Exclut les fichiers de clés privées
*.crt                # Exclut les certificats publics
*.log                # Exclut les fichiers de log (données sensibles, volumineux)
dist/                # Exclut le répertoire de distribution (sera recompilé dans le build stage)
build/               # Exclut le répertoire de build local
```

> Les patterns `!` ré-incluent des fichiers si nécessaire.

> **Résultat attendu** :
> ```
> $ docker build -t monapp .
> [+] Building 2.1s (5/5) FINISHED
>  => [internal] load build definition from Dockerfile
>  => [internal] load .dockerignore
>  => => transferring context: 2.50kB                          # Contexte très léger (quelques Ko)
> ```
> **Vérification** : Observer la taille du "transferring context" dans les logs de build — elle doit être minimale (quelques Ko/Mo, pas des centaines de Mo). `docker run --rm <image> ls -la /app/` ne doit pas contenir de `.git/` ni de `node_modules/` local.

---

## 2) Multi-stage builds (patrons utiles)

### 2.1 Go (binaire statique, image runtime minimale)

> **Objectif** : Compiler un binaire Go statique dans un stage de build complet, puis le copier dans une image distroless minimale (sans shell, sans package manager) pour une image finale de ~10-20 Mo avec une surface d'attaque minimale.
> **Pré-requis** : Projet Go avec `go.mod` et `go.sum` présents. Code source dans `./cmd/app/`. Docker avec BuildKit activé.

```dockerfile
# syntax=docker/dockerfile:1.7             # Active BuildKit front-end v1.7

FROM golang:1.22 AS build                  # Stage 1 : image Go complète (~900 Mo) pour la compilation
WORKDIR /src                               # Répertoire de travail dans le stage de build
COPY go.mod go.sum ./                      # Copie uniquement les descripteurs de dépendances (optimise le cache)
RUN --mount=type=cache,target=/go/pkg/mod \  # Monte un cache persistant pour les modules Go (évite re-téléchargement)
    go mod download                        # Télécharge toutes les dépendances Go
COPY . .                                   # Copie le code source complet
RUN --mount=type=cache,target=/root/.cache/go-build \  # Cache du compilateur Go (accélère les builds incrémentaux)
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \  # Compilation statique pure (pas de libc), cible Linux amd64
    go build -ldflags="-s -w" -o /out/app ./cmd/app  # -s -w = strip debug+DWARF → binaire plus petit

FROM gcr.io/distroless/static:nonroot      # Stage 2 : image ~20 Mo, pas de shell, CA certs inclus
COPY --from=build /out/app /app            # Seul le binaire est copié depuis le stage de build
USER 65532:65532                           # User "nonroot" fourni par distroless (UID 65532)
ENTRYPOINT ["/app"]                        # Le binaire statique se suffit à lui-même
```

> **Résultat attendu** :
> ```
> [+] Building 25.3s (12/12) FINISHED
>  => [build 4/5] RUN go mod download
>  => [build 6/6] RUN go build -ldflags="-s -w" -o /out/app ./cmd/app
>  => [runtime 1/2] COPY --from=build /out/app /app
>  => exporting to image
>  => => naming to docker.io/library/goapp:latest
> ```
> **Vérification** : `docker images goapp` montre une image de ~10-20 Mo. `docker run --rm goapp --help` affiche l'aide du binaire. `docker run --rm goapp whoami` échoue (pas de shell dans distroless). `docker inspect goapp --format '{{.Config.User}}'` affiche `65532:65532`.

### 2.2 Node.js (builder → runtime)

> **Objectif** : Installer les dépendances de dev et compiler le code TypeScript dans des stages intermédiaires, puis produire une image de production ne contenant que le code compilé, les dépendances de production et le runtime Node.js, exécutée en tant qu'utilisateur non-root `node`.
> **Pré-requis** : Projet Node.js avec `package.json`, `package-lock.json`, code TypeScript dans `./dist/` après `npm run build`. BuildKit activé.

```dockerfile
# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS deps                # Stage 1 : installation des dépendances (dev + prod)
WORKDIR /app
COPY package*.json ./                      # Copie uniquement les descripteurs de packages (cache optimisé)
RUN --mount=type=cache,target=/root/.npm \ # Cache du répertoire npm (accélère npm ci)
    npm ci                                 # Installation déterministe depuis package-lock.json

FROM node:20-alpine AS build               # Stage 2 : compilation du code source
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules  # Récupère les node_modules du stage deps
COPY . .                                   # Copie tout le code source
RUN --mount=type=cache,target=/root/.npm \ # Cache npm pour le build
    npm run build                          # Compile TypeScript → JavaScript dans ./dist/

FROM node:20-alpine AS runtime             # Stage 3 : image de production minimale
WORKDIR /app
ENV NODE_ENV=production                    # Mode production (dépendances dev ignorées)
COPY --from=build /app/dist ./dist         # Uniquement le code compilé (pas les .ts sources)
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev                      # Installe uniquement les dépendances de production
USER node                                  # Utilisateur "node" pré-créé dans l'image Alpine Node
EXPOSE 8080
ENTRYPOINT ["node","dist/server.js"]       # Lance le serveur compilé
```

> **Résultat attendu** :
> ```
> [+] Building 45.2s (18/18) FINISHED
>  => [deps 3/3] RUN npm ci
>  => [build 4/4] RUN npm run build
>  => [runtime 5/6] RUN npm ci --omit=dev
>  => => naming to docker.io/library/nodeapp:latest
> ```
> **Vérification** : `docker images nodeapp` montre une image de ~150-200 Mo (vs ~1 Go pour l'image de build). `docker run --rm -p 8080:8080 nodeapp` démarre le serveur. `docker run --rm nodeapp ls /app/` ne montre PAS les fichiers `.ts` sources, seulement `dist/`, `node_modules/`, `package.json`.

### 2.3 Java (Maven → JRE distroless/jlink)

> **Objectif** : Compiler un projet Java avec Maven dans un stage de build, puis copier le JAR résultant dans une image distroless Java qui ne contient que le JRE, pour une image finale réduite sans JDK ni outils de build.
> **Pré-requis** : Projet Maven avec `pom.xml` et `src/`. Le `pom.xml` doit produire `target/app.jar`. BuildKit activé.

```dockerfile
# syntax=docker/dockerfile:1.7
FROM maven:3.9-eclipse-temurin-21 AS build # Stage 1 : JDK + Maven complet (~700 Mo)
WORKDIR /src
COPY pom.xml .                             # Copie le POM seul d'abord (cache les dépendances Maven)
COPY src ./src                             # Copie le code source
RUN --mount=type=cache,target=/root/.m2 \  # Cache du dépôt Maven local (~accélère fortement les rebuilds)
    mvn -B -DskipTests package             # -B = batch (non-interactif), skip tests pour le build image

FROM gcr.io/distroless/java21-debian12:nonroot  # Stage 2 : JRE 21 uniquement (~200 Mo)
WORKDIR /app
COPY --from=build /src/target/app.jar /app/app.jar  # Seul le JAR est copié
EXPOSE 8080
USER nonroot                               # Utilisateur non-root fourni par distroless
ENTRYPOINT ["java","-jar","/app/app.jar"]  # Lance le JAR avec le JRE
```

> **Résultat attendu** :
> ```
> [+] Building 60.5s (10/10) FINISHED
>  => [build 4/4] RUN mvn -B -DskipTests package
>  => [runtime 2/3] COPY --from=build /src/target/app.jar /app/app.jar
>  => => naming to docker.io/library/javaapp:latest
> ```
> **Vérification** : `docker images javaapp` montre ~200 Mo (vs ~700 Mo pour l'image Maven). `docker run --rm -p 8080:8080 javaapp` démarre l'application Spring Boot / Java. `docker run --rm javaapp java -version` affiche la version du JRE 21.

### 2.4 Python (wheelhouse + venv immuable)

> **Objectif** : Compiler toutes les dépendances Python en wheels dans un stage de build, puis les installer depuis le cache local dans l'image finale (sans besoin de compilateur ni d'accès réseau), avec un utilisateur non-root.
> **Pré-requis** : Projet Python avec `pyproject.toml` et `poetry.lock` (ou `requirements.txt`). BuildKit activé.

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build             # Stage 1 : image avec compilateur (gcc, python3-dev)
WORKDIR /w
COPY pyproject.toml poetry.lock ./         # Descripteurs de dépendances
RUN --mount=type=cache,target=/root/.cache/pip \  # Cache pip (wheels téléchargées et compilées)
    pip install --upgrade pip wheel build \     # Outils de build Python
 && pip wheel --wheel-dir /wheels .             # Compile TOUTES les dépendances en .whl dans /wheels

FROM python:3.12-slim                      # Stage 2 : image slim sans compilateur
WORKDIR /app
COPY --from=build /wheels /wheels          # Wheels pré-compilées depuis le stage build
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-index --find-links=/wheels /wheels/*.whl \  # Installation 100% locale (pas d'accès réseau)
 && useradd -u 10001 -r -s /sbin/nologin app \  # Crée un utilisateur système non-root (UID 10001)
 && rm -rf /wheels                              # Supprime les wheels installées (gain de place)
COPY . .                                   # Code source de l'application
USER 10001                                 # Bascule vers l'utilisateur non-root
EXPOSE 8000
ENTRYPOINT ["python","-m","app"]           # Lance le module Python "app"
```

> **Résultat attendu** :
> ```
> [+] Building 35.8s (12/12) FINISHED
>  => [build 3/3] RUN pip wheel --wheel-dir /wheels .
>  => [stage-1 3/5] RUN pip install --no-index --find-links=/wheels /wheels/*.whl
>  => => naming to docker.io/library/pyapp:latest
> ```
> **Vérification** : `docker images pyapp` montre une image de ~150-250 Mo. `docker run --rm pyapp --help` affiche l'aide. `docker run --rm pyapp id` affiche `uid=10001(app)`. `docker run --rm pyapp ls /wheels` échoue (répertoire supprimé).

---

## 3) BuildKit : `RUN --mount` (cache, secrets, ssh)

> Nécessite `# syntax=docker/dockerfile:1.x` + BuildKit activé.

### 3.1 Cache persistant entre builds

> **Objectif** : Monter un cache persistant pour le répertoire apt afin que les paquets téléchargés ne soient pas re-téléchargés à chaque build, tout en ne gardant PAS le cache dans l'image finale (le montage est éphémère).
> **Pré-requis** : Image Debian/Ubuntu. BuildKit activé avec `# syntax=docker/dockerfile:1.7` en première ligne du Dockerfile.

```dockerfile
RUN --mount=type=cache,target=/var/cache/apt \    # Monte un volume de cache persistant pour les .deb téléchargés
    apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*  # Installe curl, nettoie les listes index
```

* Conserve un **cache** côté builder sans gonfler l'image.

> **Résultat attendu** :
> ```
> # Premier build :
> #6 [stage-0 2/3] RUN --mount=type=cache,target=/var/cache/apt apt-get update && apt-get install -y curl
> #6 1.234 Get:1 http://deb.debian.org/debian bookworm InRelease [147 kB]
> #6 DONE 8.5s
>
> # Deuxième build (cache hit) :
> #6 [stage-0 2/3] RUN --mount=type=cache,target=/var/cache/apt apt-get update && apt-get install -y curl
> #6 CACHED
> ```
> **Vérification** : Le deuxième build affiche `CACHED` pour l'étape RUN. `docker run --rm <image> curl --version` confirme que curl est installé. `docker run --rm <image> ls /var/cache/apt/` montre un répertoire quasi-vide (le cache n'est PAS dans l'image).

### 3.2 Secrets (ne **pas** figer dans les couches)

> **Objectif** : Injecter un secret (token NPM, clé API, etc.) de manière éphémère pendant le build sans qu'il ne soit jamais enregistré dans les couches de l'image. Le secret est monté en mémoire et supprimé après l'exécution du `RUN`.
> **Pré-requis** : Fichier `./.npm_token` contenant le token NPM. BuildKit activé. Commande de build avec `--secret`.

```dockerfile
# build: docker build --secret id=npm_token,src=./.npm_token    # Passe le fichier comme secret au build
RUN --mount=type=secret,id=npm_token \                          # Monte le secret en /run/secrets/npm_token (tmpfs)
    export NPM_TOKEN="$(cat /run/secrets/npm_token)" \          # Lit le secret dans une variable d'env (en mémoire seulement)
 && npm ci                                                      # npm utilise NPM_TOKEN pour authentifier les packages privés
```

> **Résultat attendu** :
> ```
> $ docker build --secret id=npm_token,src=./.npm_token -t nodeapp .
> [+] Building 12.3s (8/8) FINISHED
>  => [internal] load secret npm_token
>  => [stage-0 3/4] RUN --mount=type=secret,id=npm_token export NPM_TOKEN=... && npm ci
>  => => npm info ok — added 342 packages
> ```
> **Vérification** : `npm ci` réussit et installe les packages privés. `docker run --rm nodeapp cat /run/secrets/npm_token` échoue (fichier inexistant). `docker history nodeapp` ne montre AUCUNE trace du token dans les couches.

### 3.3 Accès SSH (clés éphémères)

> **Objectif** : Utiliser l'agent SSH de l'hôte pour cloner un dépôt privé pendant le build sans copier la clé SSH dans l'image. La clé est montée via un socket SSH éphémère.
> **Pré-requis** : Agent SSH actif sur l'hôte (`eval $(ssh-agent) && ssh-add`). Clé SSH ajoutée à l'agent et autorisée sur GitHub. BuildKit activé.

```dockerfile
# build: docker build --ssh default                              # Forward l'agent SSH de l'hôte
RUN --mount=type=ssh \                                          # Monte le socket SSH en /run/buildkit/ssh_agent.*
    git clone git@github.com:org/private-repo.git               # Git utilise l'agent SSH pour s'authentifier
```

> **Résultat attendu** :
> ```
> $ docker build --ssh default -t myapp .
> [+] Building 15.7s (8/8) FINISHED
>  => [stage-0 3/4] RUN --mount=type=ssh git clone git@github.com:org/private-repo.git
>  => => Cloning into 'private-repo'...
>  => => remote: Enumerating objects: 1234, done.
> ```
> **Vérification** : Le clone réussit pendant le build. `docker run --rm myapp ls /run/buildkit/ssh_agent.*` échoue (socket inexistant). `docker run --rm myapp ssh-add -l` échoue (pas d'agent dans l'image finale).

### 3.4 Montage depuis un autre stage (bind éphémère)

> **Objectif** : Monter un répertoire d'un autre stage de build de manière éphémère (bind mount) pour copier des artefacts sans créer de couche supplémentaire et sans garder les fichiers sources dans l'image.
> **Pré-requis** : Un stage nommé `build` produisant des artefacts dans `/out/`. BuildKit activé.

```dockerfile
# Copier des artefacts lourds sans créer de couche inutile
RUN --mount=type=bind,from=build,source=/out,target=/mnt/out \  # Monte /out du stage "build" en lecture seule sur /mnt/out
    cp /mnt/out/app /usr/local/bin/app                          # Copie le binaire vers sa destination finale
```

> **Résultat attendu** :
> ```
> #7 RUN --mount=type=bind,from=build,source=/out,target=/mnt/out cp /mnt/out/app /usr/local/bin/app
> #7 DONE 0.3s
> ```
> **Vérification** : `docker run --rm <image> /usr/local/bin/app --help` fonctionne. `docker run --rm <image> ls /mnt/out` échoue (le montage bind est éphémère, uniquement pendant le RUN). `docker history <image>` ne montre PAS de couche contenant le contenu complet de `/out/`.

---

## 4) `COPY` avancé & ordre des couches

* Grouper ce qui change **le moins** tôt (cache maximal).
* Exploiter `COPY --from=<stage>` pour extraire **uniquement** les artefacts nécessaires.
* Utiliser `--chown` et `--chmod` pendant `COPY` pour éviter un `chown` séparé (une couche en moins).

Exemple :

> **Objectif** : Copier un binaire depuis un stage de build nommé `build` vers l'image finale en définissant le propriétaire et les permissions en une seule opération, évitant ainsi une couche `RUN chown` supplémentaire.
> **Pré-requis** : Stage `build` ayant produit un binaire dans `/out/app`. BuildKit activé pour `--chmod`.

```dockerfile
COPY --from=build --chown=10001:10001 /out/app /usr/local/bin/app  # Copie multi-stage avec owner et perms en une seule couche
```

> **Résultat attendu** :
> ```
> #8 COPY --from=build --chown=10001:10001 /out/app /usr/local/bin/app
> #8 DONE 0.1s
> ```
> **Vérification** : `docker run --rm <image> ls -la /usr/local/bin/app` montre `10001 10001` et `-rwxr-xr-x`. `docker history <image>` ne montre PAS de couche `RUN chown` séparée (économie d'une couche).

---

## 5) Optimisations de taille & de surface

* **Base slim/distroless** lorsque possible.
* Nettoyer **dans la même couche** :

> **Objectif** : Installer un paquet ET nettoyer les caches dans la même instruction `RUN` pour que les fichiers supprimés n'apparaissent jamais dans la couche finale (chaque `RUN` crée une couche — si on installe puis nettoie dans des `RUN` séparés, les fichiers installés persistent dans la couche d'installation).
> **Pré-requis** : Image Debian/Ubuntu.

  ```dockerfile
  RUN apt-get update && apt-get install -y curl \   # Installe curl
   && rm -rf /var/lib/apt/lists/*                   # Nettoie les index APT dans la MÊME couche (&&)
  ```

> **Résultat attendu** :
> ```
> #5 RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
> #5 2.1 Installing curl (7.88.1-10+deb12.8)
> #5 DONE 5.3s
> ```
> **Vérification** : `docker run --rm <image> curl --version` fonctionne. `docker run --rm <image> ls /var/lib/apt/lists/` est vide. `docker history <image>` montre une seule couche pour install+cleanup.

* Supprimer docs/locales inutiles si acceptable (packages).
* `-ldflags="-s -w"` (Go), `strip` binaire, compilation statique si adaptée.
* **USER non-root** (et répertoires détenus par l'utilisateur).
* Éviter `ADD` avec URL (préférez `curl | tar` en build stage puis copier l'artefact).

---

## 6) Métadonnées & labels OCI (traçabilité)

Labels recommandés :

> **Objectif** : Ajouter des métadonnées standardisées OCI (Open Container Initiative) à l'image pour la traçabilité : origine du code, version, date de build, licence, auteur. Ces labels sont exploitables par les registres, les scanners de sécurité et les outils de gouvernance.
> **Pré-requis** : Définir `BUILD_DATE` via `--build-arg` lors du build. Les valeurs (source, version, revision) doivent être fournies par le pipeline CI/CD.

```dockerfile
LABEL org.opencontainers.image.title="acme-web" \                          # Nom de l'image
      org.opencontainers.image.description="Service web" \                 # Description courte
      org.opencontainers.image.url="https://acme.example" \                # URL de l'application
      org.opencontainers.image.source="https://github.com/acme/web" \      # URL du dépôt source
      org.opencontainers.image.version="1.4.2" \                           # Version applicative (semver)
      org.opencontainers.image.revision="abc1234" \                        # Commit SHA du code source
      org.opencontainers.image.created="${BUILD_DATE}" \                   # Date de build (ISO 8601 UTC)
      org.opencontainers.image.licenses="Apache-2.0" \                     # Licence du projet
      org.opencontainers.image.authors="Equipe Platform <platform@acme.example>"  # Contact mainteneur
```

* Fixez `BUILD_DATE` via `--build-arg BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)`.

> **Résultat attendu** :
> ```
> $ docker build --build-arg BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) -t acme-web .
> => => naming to docker.io/library/acme-web:latest
> $ docker inspect acme-web --format '{{json .Config.Labels}}' | jq
> {
>   "org.opencontainers.image.title": "acme-web",
>   "org.opencontainers.image.version": "1.4.2",
>   "org.opencontainers.image.created": "2025-06-21T10:30:00Z",
>   "org.opencontainers.image.source": "https://github.com/acme/web"
> }
> ```
> **Vérification** : `docker inspect <image> --format '{{index .Config.Labels "org.opencontainers.image.version"}}'` retourne `1.4.2`. Les labels sont visibles dans Docker Hub / GHCR dans la section "Tags & Layers".

---

## 7) Reproductibilité & gouvernance

* **Pinning** : images de base par tag **et** idéalement par **digest**.
* Gel des dépendances (lockfiles, `requirements.txt`, `package-lock.json`, `poetry.lock`).
* Variables d'ambiance déterministes : `TZ=UTC`, `LANG=C.UTF-8`.
* **SBOM** & **provenance** (voir section buildx) ; sauvegarder comme artefacts OCI.
* Politique : pas de `latest` en prod ; **déploiement par digest**.

> **Objectif** : Appliquer les bonnes pratiques de reproductibilité et de gouvernance pour garantir que les builds sont déterministes, traçables et conformes aux politiques de sécurité enterprise : pinning des images par digest, gel des dépendances, génération de SBOM et de provenance, déploiement par digest plutôt que par tag mutable.
> **Pré-requis** : Pipeline CI/CD configuré. Accès à un registre supportant les attestations OCI (GHCR, AWS ECR, etc.). Outils de scan (Trivy, Docker Scout) disponibles.

> **Résultat attendu** :
> ```
> # Build reproductible avec digest :
> FROM alpine:3.20@sha256:a8560b36e8b8b10c4b8f2e...
> # Build avec SBOM :
> $ docker buildx build --sbom=true --provenance=true -t app:1.4.2 --push .
> # Le registre affiche les attestations liées à l'image
> ```
> **Vérification** : Reconstruire l'image deux fois de suite avec les mêmes sources produit des couches identiques. `docker buildx imagetools inspect ghcr.io/acme/app:1.4.2` montre les attestations SBOM et provenance. `cosign verify-attestation` valide la provenance.

---

## 8) `docker buildx` : multi-arch, SBOM, provenance, caches

### 8.1 Préparer un builder

> **Objectif** : Créer et activer une instance de builder BuildKit dédiée (avec support multi-architecture) pour la CI/CD. Le builder utilise un driver `docker-container` qui permet le build multi-plateforme via QEMU.
> **Pré-requis** : Docker 23.0+ avec le plugin buildx. `docker run --privileged` peut être nécessaire pour QEMU si on build pour des architectures différentes de l'hôte.

```bash
docker buildx create --name builder-ci --use    # Crée un builder nommé "builder-ci" et le définit comme actif
docker buildx inspect --bootstrap               # Affiche les infos du builder et démarre le conteneur BuildKit
```

> **Résultat attendu** :
> ```
> $ docker buildx create --name builder-ci --use
> builder-ci
> $ docker buildx inspect --bootstrap
> Name:          builder-ci
> Driver:        docker-container
> Last Activity: 2025-06-21 10:00:00 +0000 UTC
>
> Nodes:
> NAME                    STATUS   BUILDKIT PLATFORMS
> builder-ci0             running  v0.13.0  linux/amd64, linux/amd64/v2, linux/arm64, linux/riscv64, ...
> ```
> **Vérification** : Le builder affiche `running` et supporte plusieurs plateformes (amd64, arm64, etc.). `docker buildx ls` montre `builder-ci` avec un `*` (actif).

### 8.2 Multi-architecture + push

> **Objectif** : Construire l'image pour plusieurs architectures CPU (amd64 pour x86_64, arm64 pour ARM) et la pousser vers un registre sous forme de manifest list (index), permettant à chaque nœud de tirer l'image correspondant à son architecture.
> **Pré-requis** : Builder buildx configuré (section 8.1). QEMU installé pour l'émulation si l'hôte ne supporte pas nativement toutes les architectures. Compte sur le registre cible (ghcr.io) avec `docker login`.

```bash
docker buildx build \                     # Commande buildx (supporte multi-arch)
  --platform linux/amd64,linux/arm64 \    # Cible les architectures amd64 (x86_64) et arm64 (ARM 64-bit)
  -t ghcr.io/acme/web:1.4.2 \            # Tag de l'image dans le registre GitHub Container Registry
  --push .                                # Construit ET pousse immédiatement vers le registre (--push requis pour multi-arch)
```

* Publie un **manifest list** (index multi-arch).

> **Résultat attendu** :
> ```
> $ docker buildx build --platform linux/amd64,linux/arm64 -t ghcr.io/acme/web:1.4.2 --push .
> [+] Building 120.5s (15/15) FINISHED
>  => [linux/amd64] => [runtime 5/5] COPY --from=build /app/dist ./dist
>  => [linux/arm64] => [runtime 5/5] COPY --from=build /app/dist ./dist
>  => exporting to image
>  => => pushing layers
>  => => pushing manifest for ghcr.io/acme/web:1.4.2
> ```
> **Vérification** : `docker buildx imagetools inspect ghcr.io/acme/web:1.4.2` affiche un manifest list avec deux entrées (amd64 et arm64), chacune avec son propre digest. Sur un serveur ARM : `docker pull ghcr.io/acme/web:1.4.2` tire automatiquement l'image arm64.

### 8.3 SBOM & provenance (attestations)

> **Objectif** : Générer et pousser des attestations supply-chain avec l'image : un SBOM (Software Bill of Materials au format SPDX) listant toutes les dépendances, et une provenance (SLSA-like) documentant comment l'image a été construite (source, builder, paramètres).
> **Pré-requis** : Builder buildx avec driver `docker-container`. Registre supportant les attestations OCI (GHCR, AWS ECR v2). BuildKit >= 0.11.

```bash
docker buildx build \                                 # Commande buildx
  --platform linux/amd64,linux/arm64 \                # Multi-architecture
  -t ghcr.io/acme/web:1.4.2 \                        # Tag cible
  --provenance=true \                                 # Génère l'attestation de provenance (SLSA Build Level 1)
  --sbom=true \                                       # Génère le SBOM au format SPDX
  --push .                                            # Pousse image + attestations vers le registre
```

* Génère et pousse **attestations** (provenance SLSA-like) + **SBOM** (SPDX/CycloneDX).

> **Résultat attendu** :
> ```
> $ docker buildx build --platform linux/amd64,linux/arm64 \
>     -t ghcr.io/acme/web:1.4.2 --provenance=true --sbom=true --push .
> [+] Building 125.3s (18/18) FINISHED
>  => [attestations] generating provenance attestation
>  => [attestations] generating SBOM attestation (SPDX)
>  => => pushing manifest for ghcr.io/acme/web:1.4.2
> ```
> **Vérification** : `docker buildx imagetools inspect ghcr.io/acme/web:1.4.2` montre des entrées `Attestation: provenance` et `Attestation: sbom`. Sur GitHub, l'image dans "Packages" affiche un lien "View SBOM". `cosign verify-attestation --type spdx <image>` valide le SBOM.

### 8.4 Caches de build (CI/CD)

> **Objectif** : Externaliser le cache de build vers un registre pour le partager entre les exécutions CI/CD : exporter le cache après un build (mode `max` = toutes les couches) puis le réutiliser lors du build suivant pour accélérer significativement les builds incrémentaux.
> **Pré-requis** : Builder buildx configuré. Accès en lecture/écriture au registre pour le cache. Le registre doit supporter les manifests OCI (GHCR, AWS ECR).

```bash
# Remplissage du cache vers un registry
docker buildx build \                                              # Build avec export de cache
  --cache-to=type=registry,ref=ghcr.io/acme/cache:web,mode=max \  # Exporte TOUTES les couches vers le registry (mode=max)
  -t ghcr.io/acme/web:1.4.2 .                                      # Tag de l'image applicative

# Réutilisation du cache
docker buildx build \                                              # Build avec import de cache
  --cache-from=type=registry,ref=ghcr.io/acme/cache:web \         # Importe le cache depuis le registry
  -t ghcr.io/acme/web:1.4.3 .                                      # Nouvelle version de l'image
```

* Alternatives : `type=local` (`--cache-to=type=local,dest=./.buildx-cache`).

> **Résultat attendu** :
> ```
> # Premier build (remplissage) :
> $ docker buildx build --cache-to=type=registry,ref=ghcr.io/acme/cache:web,mode=max -t ghcr.io/acme/web:1.4.2 .
>  => exporting cache
>  => => pushing cache manifest to ghcr.io/acme/cache:web
>
> # Deuxième build (réutilisation) :
> $ docker buildx build --cache-from=type=registry,ref=ghcr.io/acme/cache:web -t ghcr.io/acme/web:1.4.3 .
>  => importing cache manifest from ghcr.io/acme/cache:web
>  => [deps 2/3] RUN npm ci
>  => => CACHED   # Les couches inchangées sont récupérées depuis le cache
> ```
> **Vérification** : Le deuxième build est nettement plus rapide. Les logs montrent `importing cache manifest from ghcr.io/acme/cache:web` et `CACHED` pour les étapes inchangées. `docker buildx du` montre la taille du cache local.

---

## 9) Contextes & sources de build

* **Contexte local** (dossier courant) = **par défaut**.
* Contexte **Git** :

> **Objectif** : Construire une image Docker directement depuis un dépôt Git distant, sans avoir à cloner manuellement le dépôt. Docker envoie le contenu du dépôt (à la branche/commit spécifié) comme contexte de build au daemon.
> **Pré-requis** : Le dépôt Git doit être accessible (public ou avec credentials configurés). Un Dockerfile doit être présent à la racine du dépôt.

  ```bash
  docker build https://github.com/acme/web.git#main    # Clone la branche "main" et utilise le contenu comme contexte de build
  ```

* **Archives**/URL : possible mais moins contrôlé (supply-chain).

> **Résultat attendu** :
> ```
> $ docker build https://github.com/acme/web.git#main
> [+] Building 30.5s (12/12) FINISHED
>  => [internal] load remote build context
>  => => transferring context from https://github.com/acme/web.git#main
>  => => naming to docker.io/library/web:latest
> ```
> **Vérification** : L'image est construite avec succès. `docker images web` montre l'image créée. Attention : le contexte envoyé est le dépôt entier — utiliser `.dockerignore` dans le dépôt pour limiter.

> Limiter le **contexte** via `.dockerignore`.

---

## 10) Sécurité de build (rappels)

* **Pas de secrets** dans le Dockerfile. Utiliser `RUN --mount=type=secret`.
* Ne **jamais** committer de clés dans le repo/contexte.
* Vérifier les **licences** (scans) et CVE (Trivy/Docker Scout).
* Préférer des bases **officielles**/maintenues (et mises à jour).

> **Objectif** : Appliquer les règles fondamentales de sécurité pour le build d'images Docker : ne jamais embarquer de secrets dans les couches, protéger le contexte de build contre les fichiers sensibles, scanner les vulnérabilités (CVE) et les licences, et utiliser des images de base fiables et maintenues.
> **Pré-requis** : Outil de scan installé (Trivy : `brew install trivy` ou `docker run aquasec/trivy`). Docker Scout activé (Docker Desktop) ou CLI (`docker scout`).

> **Résultat attendu** :
> ```
> $ trivy image acme-web:1.4.2
> 2025-06-21T10:00:00Z  INFO  Detected OS: alpine
> 2025-06-21T10:00:00Z  INFO  Number of language-specific files: 1
> acme-web:1.4.2 (alpine 3.20.0)
> Total: 0 (UNKNOWN: 0, LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0)
> ```
> **Vérification** : `trivy image <image>` ne trouve aucune CVE critique. `docker scout cves <image>` confirme. `docker history <image>` ne montre aucun `ARG` ou `ENV` contenant des tokens/mots de passe. `git log --all --diff-filter=D -- '*.pem' '*.key'` vérifie qu'aucun secret n'a été commité dans l'historique.

---

## 11) Exemples complets "prod-like"

### 11.1 Microservice web (Node) compact & traçable

> **Objectif** : Dockerfile de production complet combinant toutes les bonnes pratiques du chapitre : ARG paramétrables, multi-stage 3 étapes (deps → build → runtime), labels OCI, healthcheck, utilisateur non-root, cache npm via BuildKit, et variables d'environnement déterministes.
> **Pré-requis** : Projet Node.js avec `package.json`, `package-lock.json`, code TypeScript. Script `npm run build` produisant `./dist/`. Script `dist/healthcheck.js` pour le healthcheck. BuildKit activé.

```dockerfile
# syntax=docker/dockerfile:1.7             # Active BuildKit front-end v1.7
ARG NODE_VER=20-alpine                     # Version de Node.js paramétrable (défaut : 20-alpine)
ARG APP_VER=1.4.2                          # Version applicative (injectée dans les labels OCI)
ARG BUILD_DATE                             # Date de build (à passer via --build-arg)

FROM node:${NODE_VER} AS deps              # Stage 1 : installation déterministe des dépendances
WORKDIR /app
COPY package*.json ./                      # Descripteurs de packages (cache-friendly)
RUN --mount=type=cache,target=/root/.npm npm ci  # npm ci = installation déterministe depuis lock file

FROM node:${NODE_VER} AS build             # Stage 2 : compilation TypeScript
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules  # Réutilise les node_modules du stage deps
COPY . .                                   # Code source complet
RUN --mount=type=cache,target=/root/.npm npm run build  # Compile → ./dist/

FROM node:${NODE_VER} AS runtime           # Stage 3 : image de production
WORKDIR /app
ENV NODE_ENV=production TZ=UTC LANG=C.UTF-8  # Environnement déterministe et production
LABEL org.opencontainers.image.title="acme-web" \
      org.opencontainers.image.version="${APP_VER}" \        # Version depuis ARG
      org.opencontainers.image.created="${BUILD_DATE}" \     # Date depuis ARG
      org.opencontainers.image.source="https://github.com/acme/web"
COPY --from=build /app/dist ./dist         # Code compilé uniquement
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --omit=dev \  # Dépendances de production uniquement
 && addgroup -S app && adduser -S -G app -u 10001 app        # Utilisateur non-root
USER 10001                                 # Exécution sans root
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD node dist/healthcheck.js || exit 1   # Vérification de santé via script Node
ENTRYPOINT ["node","dist/server.js"]       # Forme exec (PID 1 direct)
```

Build & push multi-arch avec attestations :

> **Objectif** : Construire l'image pour amd64 et arm64, injecter les métadonnées de version et de date via des build-args, ajouter les attestations SBOM et provenance, et pousser le manifest list complet vers le registre GHCR.
> **Pré-requis** : Builder buildx actif (section 8.1). Authentifié sur GHCR (`docker login ghcr.io`). Code source et Dockerfile prêts.

```bash
docker buildx build \                                  # Build multi-arch via buildx
  --platform linux/amd64,linux/arm64 \                 # Cible x86_64 et ARM 64-bit
  --build-arg APP_VER=1.4.2 \                          # Injecte la version dans les labels OCI
  --build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \  # Injecte la date ISO 8601 UTC
  -t ghcr.io/acme/web:1.4.2 \                         # Tag sémantique (pas de latest)
  --provenance=true --sbom=true \                      # Attestations supply-chain
  --push .                                             # Pousse vers le registre
```

> **Résultat attendu** :
> ```
> $ docker buildx build --platform linux/amd64,linux/arm64 \
>     --build-arg APP_VER=1.4.2 \
>     --build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
>     -t ghcr.io/acme/web:1.4.2 --provenance=true --sbom=true --push .
> [+] Building 130.2s (22/22) FINISHED
>  => [linux/amd64] => [runtime 7/8] RUN npm ci --omit=dev && addgroup -S app && adduser -S -G app -u 10001 app
>  => [linux/arm64] => [runtime 7/8] RUN npm ci --omit=dev && addgroup -S app && adduser -S -G app -u 10001 app
>  => [attestations] generating provenance + SBOM
>  => => pushing manifest for ghcr.io/acme/web:1.4.2
> ```
> **Vérification** : `docker buildx imagetools inspect ghcr.io/acme/web:1.4.2` montre le manifest list multi-arch avec les labels OCI corrects et les attestations. `docker pull ghcr.io/acme/web:1.4.2 && docker run --rm -p 8080:8080 ghcr.io/acme/web:1.4.2` démarre le service. `docker inspect` confirme les labels `version=1.4.2` et `created=<date>`.

### 11.2 Go (binaire unique distroless)

> **Objectif** : Dockerfile Go de production avec multi-stage build : compilation statique avec optimisations de taille (strip debug info, CGO désactivé), puis copie du binaire unique dans une image distroless non-root pour une image finale de ~10-20 Mo.
> **Pré-requis** : Projet Go avec `go.mod`, `go.sum`, code dans `./cmd/app/`. BuildKit activé.

```dockerfile
# syntax=docker/dockerfile:1.7
FROM golang:1.22 AS build                  # Stage 1 : image Go complète pour la compilation
WORKDIR /src
COPY go.mod go.sum ./                      # Descripteurs de dépendances (cache optimisé)
RUN --mount=type=cache,target=/go/pkg/mod go mod download  # Télécharge les modules avec cache
COPY . .                                   # Code source complet
RUN --mount=type=cache,target=/root/.cache/go-build \  # Cache du compilateur Go
    CGO_ENABLED=0 GOOS=linux GOARCH=arm64 \  # Compilation statique pure, cible ARM64
    go build -ldflags="-s -w" -o /out/app ./cmd/app  # Strip debug info → binaire minimal

FROM gcr.io/distroless/static:nonroot      # Stage 2 : image ~10 Mo, pas de shell
COPY --from=build /out/app /app            # Binaire statique uniquement
USER 65532                                 # nonroot user de distroless
ENTRYPOINT ["/app"]                        # Exécute le binaire directement
```

> **Résultat attendu** :
> ```
> [+] Building 20.5s (10/10) FINISHED
>  => [build 4/5] RUN go mod download
>  => [build 5/5] RUN go build -ldflags="-s -w" -o /out/app ./cmd/app
>  => [stage-1 1/2] COPY --from=build /out/app /app
>  => => naming to docker.io/library/goapp:latest
> ```
> **Vérification** : `docker images goapp` montre ~10-20 Mo. `docker run --rm goapp` exécute le binaire. `file $(docker create --name tmp goapp):/app` (via `docker cp`) montre `ELF 64-bit LSB executable, ARM aarch64, statically linked`. `docker inspect goapp --format '{{.Config.User}}'` affiche `65532`.

---

## 12) Commandes utiles & aide-mémoire

> **Objectif** : Récapitulatif des commandes Docker/buildx les plus courantes pour le build d'images : build local simple, build sans cache, build multi-arch avec attestations, gestion de cache distribué, et inspection des images produites.
> **Pré-requis** : Docker Engine/CLI installé. Builder buildx configuré pour les commandes multi-arch. Authentifié sur le registre pour les commandes `--push`.

```bash
# Build local classique
docker build -t acme/app:1.0 .                    # Construit l'image depuis le Dockerfile du répertoire courant, tag 1.0

# Build sans cache et en tirant la base à jour
docker build --no-cache --pull -t acme/app:clean .  # --no-cache = ignore le cache, --pull = force le pull de la base

# Build multi-arch + push + attestations
docker buildx build --platform linux/amd64,linux/arm64 \  # Multi-architecture
  -t ghcr.io/acme/app:1.0 \                              # Tag dans GHCR
  --provenance --sbom \                                  # Attestations supply-chain
  --push .                                               # Pousse vers le registre

# Caches registry
docker buildx build \
  --cache-to=type=registry,ref=ghcr.io/acme/cache:app,mode=max \   # Exporte le cache (mode max = toutes les couches)
  --cache-from=type=registry,ref=ghcr.io/acme/cache:app \          # Importe le cache existant
  -t ghcr.io/acme/app:1.1 .                                        # Build + tag

# Inspecter couches & metadata
docker history ghcr.io/acme/app:1.0                   # Affiche l'historique des couches (taille, commande)
docker inspect ghcr.io/acme/app:1.0 | jq              # Métadonnées complètes en JSON (config, labels, layers)
```

> **Résultat attendu** :
> ```
> $ docker build -t acme/app:1.0 .
> [+] Building 15.3s (8/8) FINISHED
>  => => naming to docker.io/library/acme/app:1.0
>
> $ docker history ghcr.io/acme/app:1.0
> IMAGE          CREATED       SIZE      COMMENT
> abc123         2 min ago     5.2MB     COPY --from=build /out/app /usr/local/bin/app
> def456         2 min ago     0B        USER 10001
> ...
>
> $ docker inspect ghcr.io/acme/app:1.0 | jq '.[0].Config.Labels'
> {
>   "org.opencontainers.image.version": "1.0",
>   "org.opencontainers.image.source": "https://github.com/acme/app"
> }
> ```
> **Vérification** : Chaque commande produit le résultat attendu. `docker history` montre des couches individuelles avec leurs tailles. `docker inspect | jq` extrait proprement les labels et la configuration.

---

## 13) Checklist de clôture (qualité du Dockerfile)

* Image de base **pinnée** (tag clair, idéalement **digest**).
* **Multi-stage** : pas d'outils de build dans le runtime ; binaire/artefacts **seuls**.
* `.dockerignore` propre ; **pas de secrets** embarqués.
* **USER non-root** ; permissions correctes au `COPY --chown/--chmod`.
* **HEALTHCHECK** pertinent ; `EXPOSE` documentaire ; `ENTRYPOINT` en **forme exec**.
* **Labels OCI** renseignés (source, version, révision, created, licences).
* **Taille** raisonnable (layers limitées, caches nettoyés).
* Build reproductible : locks/versions ; **SBOM & provenance** générés ; politique de **tags/digests** conforme.

---

## Voir aussi

* **[Kubernetes — Chapitre 10 : Packaging & Deploiement](../k8s/Chapitre-10%20—%20Packaging%20&%20Déploiement%20applicatif.md)** : comment deployer ces images en production avec Helm/Kustomize.
* **[Kubernetes — Chapitre 14 : Gouvernance & Conformite](../k8s/Chapitre-14%20—%20Gouvernance%20&%20Conformité%20des%20images%20(rappel).md)** : politiques d'admission, SBOM obligatoire, signatures.
