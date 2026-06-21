# Chapitre-06 — Docker Compose v2 (multi-services)

## Objectifs d'apprentissage

* Décrire une application **multi-services** avec `docker compose` : services, réseaux, volumes, secrets, configs.
* Piloter les **environnements** (profils, overrides, variables) et la **chaîne build→run** (buildx, cache, args, target).
* Exploiter les commandes **opérationnelles** : `up/down/ps/logs/exec/run/restart/pull/push/build/config/watch`.
* Mettre en œuvre des **dépendances fiables** (healthchecks + `depends_on`), la **séparation réseau**, et une **structure maintenable**.

## Pré-requis

* Docker Engine + CLI Compose v2 (`docker compose version`).
* Aisance avec YAML, Dockerfiles (chapitre 05) et réseau/stockage (ch. 03–04).

---

## 1) Fichiers Compose : repères essentiels

* **Nom par défaut** : `compose.yaml` (ou `docker-compose.yml` maintenu).
* **Plusieurs fichiers** possibles : `-f compose.yaml -f compose.prod.yaml`.
* **`.env`** au même niveau que le compose pour l'**interpolation** (`${VAR:-defaut}`).
* Le champ `version:` est **optionnel** (Compose v2 lit la spec sans).

**Exemple minimal**

> **Objectif** : Définir le plus petit fichier Compose valide — un seul service `web` basé sur l'image nginx, exposant le port 80 du conteneur sur le port 8080 de l'hôte.
> **Pre-requis** : Docker Engine running, port 8080 libre sur l'hôte, un fichier `compose.yaml` dans le repertoire courant.

```yaml
services:                         # Bloc racine : declaration de tous les services
  web:                            # Nom du service (devient le nom du conteneur : <projet>_web_1)
    image: nginx:1.27             # Image publique a telecharger depuis Docker Hub
    ports: ["8080:80"]            # Mapping port hote:port conteneur (TCP par defaut)
```

> **Resultat attendu** :
> ```
> ✔ Network chapitre06_default  Created
> ✔ Container chapitre06-web-1  Started
> ```
> **Verification** : `curl http://localhost:8080` retourne la page d'accueil nginx ; `docker compose ps` affiche le service `web` avec le statut `Up`.

---

## 2) Services : image, build, command, environment…

### 2.1 Image & build

> **Objectif** : Configurer un service qui peut soit utiliser une image pre-construite (`image`), soit etre construit localement (`build`) avec des options avancees : cible multi-stage, arguments de build, acces SSH et secrets de build (BuildKit).
> **Pre-requis** : Un `Dockerfile` present dans le repertoire courant (context `.`), BuildKit active (`DOCKER_BUILDKIT=1`), un secret `npm_token` declare si utilise.

```yaml
services:
  api:
    image: ghcr.io/acme/api:1.4.2   # Tag de l'image finale (ou image a puller si pas de build)
    build:
      context: .                     # Repertoire de contexte pour le build (envoi au daemon Docker)
      dockerfile: Dockerfile         # Fichier Dockerfile a utiliser (defaut : Dockerfile)
      target: runtime                # Cible multi-stage : ne build que l'etape "runtime"
      args:                          # Variables de build injectees dans le Dockerfile (ARG)
        APP_VER: "1.4.2"
      ssh:        # BuildKit           # Transfert de l'agent SSH de l'hote (pour git clone prive)
        - default
      secrets:    # BuildKit (pas dans l'image)  # Secrets disponibles uniquement pendant le build
        - npm_token                            # (montes en /run/secrets/, jamais dans les layers)
```

> **Resultat attendu** :
> ```
> ✔ Service api  Built (target: runtime, APP_VER=1.4.2)
> ✔ Container chapitre06-api-1  Started
> ```
> **Verification** : `docker compose images` affiche l'image `ghcr.io/acme/api:1.4.2` ; `docker history` confirme que le secret `npm_token` n'apparait dans aucun layer.

### 2.2 Commande, entrypoint, workdir, user

> **Objectif** : Surcharger le comportement d'execution du conteneur : la commande lancee, l'entrypoint, le repertoire de travail courant et l'utilisateur (UID:GID) a l'interieur du conteneur.
> **Pre-requis** : Le binaire `./server` et le wrapper `/usr/local/bin/wrapper` doivent exister dans l'image ; l'UID/GID `10001:10001` doit etre defini dans l'image ou etre compatible avec les permissions.

```yaml
  api:
    command: ["./server","--port","8080"]       # CMD : arguments passes a l'entrypoint
    entrypoint: ["/usr/local/bin/wrapper"]       # ENTRYPOINT : remplace celui de l'image
    working_dir: /app                            # Repertoire de travail courant dans le conteneur
    user: "10001:10001"                          # UID:GID pour executer le processus (non-root)
```

> **Resultat attendu** :
> ```
> ✔ Container chapitre06-api-1  Started
> # Le processus tourne : /usr/local/bin/wrapper ./server --port 8080
> # Repertoire courant : /app, Utilisateur : 10001
> ```
> **Verification** : `docker compose exec api whoami` retourne l'UID `10001` ; `docker inspect chapitre06-api-1 --format '{{.Config.WorkingDir}}'` affiche `/app`.

### 2.3 Variables d'environnement

> **Objectif** : Injecter des variables d'environnement dans le conteneur via deux mecanismes : definition directe (`environment`) et chargement depuis un fichier externe (`env_file`).
> **Pre-requis** : Un fichier `.env` present dans le repertoire `./` contenant les variables par defaut ; le fichier doit etre accessible en lecture.

```yaml
  api:
    environment:
      - TZ=Europe/Paris              # Variable definie directement (priorite haute)
      - LOG_LEVEL=info               # Niveau de log de l'application
    env_file:
      - ./.env             # valeurs par défaut   # Charge TOUTES les variables du fichier .env
```

> **Resultat attendu** :
> ```
> ✔ Container chapitre06-api-1  Started
> # Variables injectees : TZ=Europe/Paris, LOG_LEVEL=info, + toutes celles de .env
> ```
> **Verification** : `docker compose exec api env | grep -E 'TZ|LOG_LEVEL'` affiche les valeurs injectees.

**Priorité** (du plus fort au plus faible) : variables shell > `environment` > `.env` > `env_file`.

---

## 3) Réseaux, ports, alias, IPAM

> **Objectif** : Creer une architecture reseau a deux niveaux : un reseau `frontend` (accessible depuis l'exterieur) et un reseau `backend` (isole, sans acces Internet) avec un sous-reseau personnalise et des adresses IP statiques. Les services sont places sur les reseaux appropriés et des alias DNS sont configures.
> **Pre-requis** : Ports 80 libre sur l'hôte ; les images `nginx:1.27`, `ghcr.io/acme/api:1.4.2` et `postgres:16` disponibles (ou buildables).

```yaml
services:
  web:
    image: nginx:1.27
    ports:
      - "80:80"                   # publie sur l'hôte        # Port 80 conteneur → 80 hote
    networks:
      - frontend                                                # Acces uniquement au reseau frontend
  api:
    image: ghcr.io/acme/api:1.4.2
    networks:
      frontend:                                                 # Present sur frontend (reçoit du traffic web)
      backend:
        aliases: [ api-svc ]      # alias DNS sur ce réseau    # Accessible via "api-svc" OU "api" sur backend
  db:
    image: postgres:16
    networks:
      backend:
        ipv4_address: 172.31.0.10 # IP statique (si subnet défini)  # Adresse fixe sur le reseau backend

networks:
  frontend:
    driver: bridge                                              # Reseau bridge standard (acces externe)
  backend:
    driver: bridge
    internal: true                                              # PAS d'acces Internet (egress coupe)
    ipam:
      config:
        - subnet: 172.31.0.0/24                                 # Plage d'adresses personnalisee
          gateway: 172.31.0.1                                   # Passerelle du reseau backend
```

> **Resultat attendu** :
> ```
> ✔ Network chapitre06_frontend  Created (bridge)
> ✔ Network chapitre06_backend   Created (bridge, internal, 172.31.0.0/24)
> ✔ Container chapitre06-db-1    Started (IP: 172.31.0.10)
> ✔ Container chapitre06-api-1   Started
> ✔ Container chapitre06-web-1   Started (0.0.0.0:80->80/tcp)
> ```
> **Verification** : `docker compose exec web ping api-svc` repond depuis le reseau frontend ; `docker compose exec api ping 172.31.0.10` atteint `db` ; `docker compose exec db ping 8.8.8.8` **echoue** (reseau internal).

---

## 4) Volumes, binds et tmpfs

> **Objectif** : Configurer trois types de montage de stockage : un **volume nommé** pour la persistence des donnees PostgreSQL, un **bind mount** en lecture seule pour la configuration nginx, et un **filesystem read_only** avec **tmpfs** pour limiter les ecritures disque de l'application.
> **Pre-requis** : Un fichier `nginx.conf` present dans le repertoire courant ; le repertoire courant doit etre partage avec Docker (Docker Desktop / WSL2 sur Windows).

```yaml
services:
  db:
    image: postgres:16
    volumes:
      - data_pg:/var/lib/postgresql/data        # volume nommé          # Persistence : survit au conteneur
  web:
    image: nginx:1.27
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro   # bind mount (RO)       # Fichier hote monte en lecture seule
  app:
    image: ghcr.io/acme/app:1.0
    read_only: true                              # Filesystem racine en lecture seule (securite)
    tmpfs:
      - /run                                     # Repertoire temporaire en RAM (defaut)
      - /tmp:size=64m,mode=1777                  # /tmp en RAM, 64 Mo max, permissions 1777 (sticky bit)

volumes:
  data_pg: {}                                    # Declaration du volume nomme (options par defaut)
```

> **Resultat attendu** :
> ```
> ✔ Volume "chapitre06_data_pg"     Created
> ✔ Container chapitre06-db-1       Started
> ✔ Container chapitre06-web-1      Started
> ✔ Container chapitre06-app-1      Started
> ```
> **Verification** : `docker volume ls | grep data_pg` affiche le volume ; `docker compose exec app mount | grep tmpfs` montre `/run` et `/tmp` en tmpfs ; `touch /test` dans `app` echoue (read-only).

> Sous Windows, préférez des **chemins relatifs** et, si possible, WSL2 pour éviter les latences de montages sur `\\wsl$`.

---

## 5) Healthcheck, restart, ressources

> **Objectif** : Configurer un healthcheck pour que Docker surveille l'etat de sante du service, definir une politique de redemarrage automatique, et specifier des limites de ressources (note : `deploy.*` est ignore par `docker compose` hors Swarm).
> **Pre-requis** : L'image doit contenir `curl` (pour le healthcheck) ; le endpoint `/health` doit etre implemente dans l'application.

```yaml
services:
  api:
    image: ghcr.io/acme/api:1.4.2
    healthcheck:
      test: ["CMD-SHELL","curl -fsS http://localhost:8080/health || exit 1"]  # Commande de verification
      interval: 30s          # Frequence de verification
      timeout: 5s            # Delai max avant echec d'une verification
      retries: 3             # Nombre d'echecs consecutifs avant statut "unhealthy"
      start_period: 20s      # Delai de grace au demarrage (ignore les echecs initiaux)
    restart: unless-stopped  # Redemarre toujours sauf si arrete explicitement
    deploy:        # ⚠️ Swarm only (ignoré par docker compose)
      resources:
        limits:
          cpus: "1.0"        # Max 1 coeur CPU (Swarm uniquement)
          memory: 512M       # Max 512 Mo RAM (Swarm uniquement)
```

> **Resultat attendu** :
> ```
> ✔ Container chapitre06-api-1  Started
> # Apres ~20s : statut passe a "(healthy)" si curl reussit
> # Apres 3 echecs consecutifs : statut "(unhealthy)"
> ```
> **Verification** : `docker compose ps` affiche `(healthy)` apres le `start_period` ; `docker inspect --format '{{.State.Health.Status}}' chapitre06-api-1` confirme le statut.

* `deploy.*` est **ignoré** par `docker compose` (utile en Swarm).
* En **non-Swarm**, utilisez plutôt `cpus`, `mem_limit`, etc. via `docker run` équivalents… ou passez par `docker update` après coup.

---

## 6) `depends_on` et ordre de démarrage

> **Objectif** : Garantir que le service `api` ne demarre qu'apres que la base de donnees `db` soit operationnelle, en utilisant un healthcheck et la condition `service_healthy` (bien plus fiable qu'un simple `sleep`).
> **Pre-requis** : L'image `postgres:16` doit contenir `pg_isready` (inclus par defaut) ; le service `api` doit etre configure pour se connecter a `db`.

```yaml
services:
  db:
    image: postgres:16
    healthcheck: { test: ["CMD","pg_isready","-U","postgres"] }  # Verification native PostgreSQL
  api:
    image: ghcr.io/acme/api:1.4.2
    depends_on:
      db:
        condition: service_healthy   # attend la santé OK     # api ne demarre QUE si db est "healthy"
```

> **Resultat attendu** :
> ```
> ✔ Container chapitre06-db-1   Started
> # Attente du healthcheck db... (pg_isready retourne 0)
> ✔ Container chapitre06-api-1  Started (apres db healthy)
> ```
> **Verification** : `docker compose logs api` ne montre pas d'erreur de connexion DB ; `docker inspect --format '{{.State.Health.Status}}' chapitre06-db-1` affiche `healthy` avant le demarrage de `api`.

* Les **dépendances fiables** exigent des **healthchecks** côté dépendances.
* N'utilisez pas `sleep` dans des entrypoints : préférez `service_healthy`.

---

## 7) Secrets & configs (fichiers montés)

### 7.1 Secrets (fichiers en lecture seule)

> **Objectif** : Monter un fichier secret (cle JWT) dans le conteneur via le mecanisme `secrets` de Compose. Le fichier est monte en lecture seule dans `/run/secrets/<nom>` et n'est pas inclus dans l'image.
> **Pre-requis** : Le fichier `./secrets/jwt.key` doit exister sur l'hote ; il ne doit PAS etre versionne dans le depot Git (ajouter au `.gitignore`).

```yaml
services:
  api:
    image: ghcr.io/acme/api:1.4.2
    secrets:
      - jwt_secret                           # Reference au secret declare ci-dessous
secrets:
  jwt_secret:
    file: ./secrets/jwt.key                  # Source : fichier local (monte en /run/secrets/jwt_secret)
```

> **Resultat attendu** :
> ```
> ✔ Container chapitre06-api-1  Started
> # Le fichier /run/secrets/jwt_secret est disponible en lecture seule dans le conteneur
> ```
> **Verification** : `docker compose exec api cat /run/secrets/jwt_secret` affiche le contenu de la cle ; `docker compose exec api ls -la /run/secrets/` montre les permissions `-r--r--r--`.

### 7.2 Configs (fichiers non sensibles)

> **Objectif** : Monter un fichier de configuration (non sensible) dans le conteneur via le mecanisme `configs` de Compose. Similaire aux secrets mais pour des donnees non confidentielles, avec possibilite de changer le chemin cible.
> **Pre-requis** : Le fichier `./nginx.conf` doit exister sur l'hote avec une configuration nginx valide.

```yaml
services:
  web:
    image: nginx:1.27
    configs:
      - source: web_conf                     # Reference a la config declaree ci-dessous
        target: /etc/nginx/nginx.conf        # Chemin de destination dans le conteneur
configs:
  web_conf:
    file: ./nginx.conf                       # Source : fichier local
```

> **Resultat attendu** :
> ```
> ✔ Container chapitre06-web-1  Started
> # /etc/nginx/nginx.conf dans le conteneur = copie de ./nginx.conf de l'hote
> ```
> **Verification** : `docker compose exec web cat /etc/nginx/nginx.conf` affiche le contenu du fichier local ; `docker compose exec web nginx -t` valide la configuration.

> Les **secrets** et **configs** de Compose sont montés en **fichiers** (pas en variables). Évitez de stocker des secrets en clair dans le dépôt.

---

## 8) Profils (activer/masquer des services)

> **Objectif** : Rendre des services optionnels en les associant a un **profil**. Les services avec un profil ne sont lances que si ce profil est explicitement active via `--profile`.
> **Pre-requis** : Compose v2.20+ pour le support complet des profils ; les images `grafana/grafana:11` et `grafana/loki:2.9` disponibles.

```yaml
services:
  grafana:
    image: grafana/grafana:11
    profiles: ["observability"]    # Lance seulement avec --profile observability

  loki:
    image: grafana/loki:2.9
    profiles: ["observability"]    # Lance seulement avec --profile observability
```

> **Resultat attendu** :
> ```
> # Sans profil :
> $ docker compose up -d
> # (aucun conteneur cree — tous les services ont un profil)
>
> # Avec profil :
> $ docker compose --profile observability up -d
> ✔ Container chapitre06-grafana-1  Started
> ✔ Container chapitre06-loki-1     Started
> ```
> **Verification** : `docker compose ps` (sans profil) n'affiche aucun conteneur ; `docker compose --profile observability ps` affiche `grafana` et `loki`.

* Lancer **avec profil** : `docker compose --profile observability up -d`.
* Sans ce profil, ces services sont **ignorés**.

---

## 9) Overrides & environnements

### 9.1 Fichiers multiples

> **Objectif** : Organiser la configuration en plusieurs fichiers pour separer la base commune des specifications par environnement (dev, prod). Les fichiers sont merges dans l'ordre, les derniers ecrasant les premiers.

```
compose.yaml             # base commune
compose.dev.yaml         # montages bind, hot-reload, logs verbeux
compose.prod.yaml        # images versionnées, read_only, ressources
```

Commande :

> **Objectif** : Lancer la stack en combinant le fichier de base avec l'override de production. Les valeurs de `compose.prod.yaml` remplacent celles de `compose.yaml`.
> **Pre-requis** : Les fichiers `compose.yaml` et `compose.prod.yaml` doivent exister dans le meme repertoire.

```bash
docker compose -f compose.yaml -f compose.prod.yaml up -d   # -f multiple : merge dans l'ordre
```

> **Resultat attendu** :
> ```
> ✔ Network chapitre06_default  Created
> ✔ Container chapitre06-...    Started (avec la config prod : images versionnees, read_only, etc.)
> ```
> **Verification** : `docker compose -f compose.yaml -f compose.prod.yaml config` affiche le YAML fusionne ; verifier que les valeurs prod sont bien appliquees.

### 9.2 `docker compose config` (rendu final)

> **Objectif** : Valider et visualiser le resultat de la fusion de tous les fichiers Compose. Utile pour deboguer des conflits d'overrides et verifier la configuration avant deploiement.
> **Pre-requis** : Les fichiers Compose specifies doivent exister et etre syntaxiquement valides.

```bash
docker compose -f compose.yaml -f compose.prod.yaml config   # Affiche le YAML fusionne complet
# Affiche le YAML fusionné (utile pour valider)              # Resout les variables, merge les overrides
```

> **Resultat attendu** :
> ```yaml
> name: chapitre06
> services:
>   api:
>     image: ghcr.io/acme/api:1.4.2
>     read_only: true
>     # ... configuration complete fusionnee ...
> ```
> **Verification** : Le YAML affiche ne contient plus de references `${...}` non resolues ; les valeurs de `compose.prod.yaml` ont bien remplace celles de `compose.yaml`.

---

## 10) Interpolation & .env

> **Objectif** : Utiliser un fichier `.env` pour externaliser les variables utilisees dans le fichier Compose via l'interpolation `${VAR}`. Cela permet de changer d'environnement sans modifier le compose.
> **Pre-requis** : Le fichier `.env` doit etre dans le meme repertoire que le fichier `compose.yaml` (lu automatiquement par Compose).

`.env`

```
APP_IMAGE=ghcr.io/acme/api    # Nom du registre/image (sans tag)
APP_TAG=1.4.2                 # Tag de version de l'image
```

> **Objectif** : Definir les variables qui seront interpolees dans le fichier `compose.yaml`. Ces variables servent uniquement a la construction du compose (pas injectees dans les conteneurs).
> **Pre-requis** : Le fichier `.env` doit etre a la racine du projet, au meme niveau que `compose.yaml`.

`compose.yaml`

> **Objectif** : Utiliser les variables du `.env` dans la definition du service via la syntaxe `${VAR}`. La syntaxe `${VAR:-defaut}` permet de fournir une valeur par defaut si la variable n'est pas definie.
> **Pre-requis** : Le fichier `.env` defini ci-dessus doit exister.

```yaml
services:
  api:
    image: "${APP_IMAGE}:${APP_TAG}"        # Interpolation : devient ghcr.io/acme/api:1.4.2
    environment:
      - LOG_LEVEL=${LOG_LEVEL:-info}        # Valeur par defaut si LOG_LEVEL non definie
```

> **Resultat attendu** :
> ```
> # Le service api utilise l'image ghcr.io/acme/api:1.4.2
> # LOG_LEVEL=info dans le conteneur (sauf si LOG_LEVEL exporte dans le shell)
> ```
> **Verification** : `docker compose config | grep image` affiche `ghcr.io/acme/api:1.4.2` ; `docker compose exec api env | grep LOG_LEVEL` affiche `info`.

* Valeur par défaut : `${VAR:-defaut}`.
* **Attention** : `.env` est **différent** de `env_file` (qui injecte des variables **dans le conteneur**).

---

## 11) Build Compose (buildx, caches)

> **Objectif** : Configurer un build avance avec buildx : cache distribue via un registre (accelere les builds CI/CD), arguments de build dynamiques via interpolation, et cible multi-stage.
> **Pre-requis** : BuildKit active (`DOCKER_BUILDKIT=1`) ; acces en ecriture au registre `ghcr.io/acme/cache` pour le cache distribue ; un `Dockerfile` avec une etape `runtime`.

```yaml
services:
  web:
    build:
      context: .                                        # Contexte de build (repertoire envoye au daemon)
      dockerfile: Dockerfile                            # Dockerfile utilise
      target: runtime                                   # Cible multi-stage
      args: { BUILD_DATE: "${BUILD_DATE}" }             # Argument de build depuis variable shell/env
      cache_from:
        - type=registry,ref=ghcr.io/acme/cache:web      # Source de cache : registre distant (pull)
      cache_to:
        - type=registry,ref=ghcr.io/acme/cache:web,mode=max  # Destination cache : push tous les layers
```

> **Objectif** : Creer et activer un builder buildx personnalise, puis lancer le build et le push des services via Compose.
> **Pre-requis** : Docker buildx plugin installe ; acces au registre pour le push ; variable `BUILD_DATE` definie si utilisee.

```bash
docker buildx create --name builder --use    # Cree un nouveau builder et le definit comme actif
docker buildx inspect --bootstrap            # Verifie le builder et initialise les nodes

# Build & push via compose (si image et push configurés)
docker compose build                         # Construit tous les services avec un bloc "build"
docker compose push                          # Pousse les images vers leur registre
```

> **Resultat attendu** :
> ```
> Name: builder
> Driver: docker-container
> Status: running
>
> ✔ Service web  Built (cache hit depuis ghcr.io/acme/cache:web)
> ✔ Service web  Pushed to ghcr.io/acme/web:latest
> ```
> **Verification** : `docker buildx ls` affiche le builder `builder` avec `*` (actif) ; le registre `ghcr.io/acme/cache:web` contient les layers en cache.

---

## 12) Cycle de vie : commandes opérationnelles

> **Objectif** : Reference complete des commandes operationnelles pour gerer le cycle de vie des services Compose : creation, arret, inspection, mises a jour et mise a l'echelle.
> **Pre-requis** : Un fichier `compose.yaml` valide dans le repertoire courant ; les images doivent etre disponibles (localement ou sur un registre).

```bash
# Créer/lancer
docker compose up -d                # crée & démarre si absent          # -d = detach (arriere-plan)
docker compose up --build -d        # reconstruit avant de lancer       # Force un rebuild des images

# Arrêter/retirer
docker compose stop                                                 # Arrete les conteneurs (conserve tout)
docker compose down                 # + retire les réseaux            # Arrete + supprime conteneurs et reseaux
docker compose down --volumes       # + supprime volumes (prudent)    # Supprime AUSSI les volumes nommes (!)
docker compose down --remove-orphans                                # Supprime aussi les conteneurs orphelins

# Inspection
docker compose ps                                                     # Etat des services (nom, statut, ports)
docker compose logs -f --tail=200                                     # Logs en continu, 200 dernieres lignes
docker compose exec api sh          # shell dans "api"                # Ouvre un shell interactif dans le conteneur
docker compose run --rm job sh -c 'echo one-shot'                     # Conteneur ephemere (supprime apres)

# Mises à jour
docker compose pull                 # tire les images taguées         # Met a jour les images depuis le registre
docker compose restart api                                            # Redemarre un service specifique
docker compose up -d --no-deps api  # redémarrer un service sans toucher aux dépendances  # Isole le service

# Échelle (non-Swarm)
docker compose up -d --scale web=3                                    # Lance 3 instances du service web
```

> **Resultat attendu** :
> ```
> # up -d :
> ✔ Network chapitre06_default  Created
> ✔ Container chapitre06-api-1  Started
>
> # ps :
> NAME               IMAGE                    STATUS
> chapitre06-api-1   ghcr.io/acme/api:1.4.2   Up 2 minutes (healthy)
>
> # scale web=3 :
> ✔ Container chapitre06-web-1  Started
> ✔ Container chapitre06-web-2  Started
> ✔ Container chapitre06-web-3  Started
> ```
> **Verification** : `docker compose ps` apres `--scale web=3` affiche 3 instances de `web` ; `docker compose down --volumes` supprime tout (y compris les volumes — attention aux donnees).

---

## 13) Développement : `docker compose watch` (hot reload)

**Compose v2.22+**

> **Objectif** : Configurer le mode developpement avec synchronisation automatique des fichiers : les modifications locales sont propagees en temps reel dans le conteneur (sync) ou declenchent un rebuild automatique (rebuild).
> **Pre-requis** : Docker Compose v2.22+ ; un fichier `compose.dev.yaml` avec la section `develop.watch` ; le service doit etre buildable localement.

```yaml
# compose.dev.yaml
services:
  api:
    build: { context: . }            # Build local (pas d'image pre-construite en dev)
    develop:
      watch:
        - action: sync               # Copie les fichiers en direct (sans rebuild)
          path: ./src                # Surveille le repertoire ./src sur l'hote
          target: /app/src           # Copie vers /app/src dans le conteneur
        - action: rebuild            # Declenche un rebuild complet du conteneur
          path: package.json         # Quand package.json change (nouvelles dependances)
```

> **Objectif** : Lancer le mode watch qui surveille les fichiers et applique les actions configurees automatiquement.
> **Pre-requis** : Les fichiers `compose.yaml` et `compose.dev.yaml` doivent exister ; le service ne doit pas deja tourner (watch le lance).

```bash
docker compose -f compose.yaml -f compose.dev.yaml watch   # Surveille et synchronise en continu
```

> **Resultat attendu** :
> ```
> watching /home/user/project/src
> sync: ./src/index.js -> /app/src/index.js (api)
> rebuild: package.json changed (api)
> ```
> **Verification** : Modifier un fichier dans `./src` → le fichier apparait dans le conteneur en < 1s ; modifier `package.json` → le conteneur est reconstruit et redemarre.

* **sync** copie les fichiers en direct, **rebuild** relance un build sur changement.

---

## 14) Exemple "prod-like" complet (frontend/api/db + réseaux + health + secrets)

> **Objectif** : Assembler tous les concepts du chapitre dans une stack complete de production : 3 services (db, api, web), 2 reseaux separes (frontend/backend), healthchecks avec dependances fiables, secrets en fichiers, filesystem read_only, et deploiement par digest.
> **Pre-requis** : Le fichier `./secrets/postgres.password` doit exister ; `./nginx.conf` doit etre configure pour proxyfier vers `api:8080` ; l'image API doit avoir un endpoint `/health` ; le port 80 doit etre libre.

```yaml
services:
  db:
    image: postgres:16
    environment:
      - POSTGRES_PASSWORD_FILE=/run/secrets/pg_pwd    # Mot de passe lu depuis le fichier secret
    secrets: [ pg_pwd ]                               # Monte le secret en /run/secrets/pg_pwd
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]   # Verification native de PostgreSQL
      interval: 10s                                    # Toutes les 10 secondes
      retries: 10                                      # 10 tentatives avant unhealthy
    networks:
      - backend                                        # DB isolee sur le reseau backend uniquement
    volumes:
      - data_pg:/var/lib/postgresql/data               # Persistence des donnees PostgreSQL
    restart: unless-stopped                            # Redemarrage automatique

  api:
    image: ghcr.io/acme/api:1.4.2@sha256:...   # déploiement par digest conseillé  # Immutabilite
    environment:
      - DB_HOST=db                                     # Resolution DNS via nom de service Compose
      - DB_USER=postgres
      - DB_PASSWORD_FILE=/run/secrets/pg_pwd           # Lit le mot de passe depuis le secret monte
    depends_on:
      db:
        condition: service_healthy                     # Attend que db soit healthy avant de demarrer
    healthcheck:
      test: ["CMD-SHELL","curl -fsS http://localhost:8080/health || exit 1"]
      interval: 30s
    read_only: true                                    # Filesystem racine en lecture seule
    tmpfs: [ /run, /tmp ]                              # Repertoires temporaires en RAM
    user: "10001:10001"                                # Execution en non-root
    networks:
      - frontend                                       # Communique avec le reverse proxy
      - backend                                        # Communique avec la base de donnees
    restart: unless-stopped

  web:
    image: nginx:1.27
    ports: [ "80:80" ]                                 # Seul service expose sur l'hote
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro          # Configuration nginx depuis l'hote
    depends_on:
      api:
        condition: service_started                     # Demarre des que api est lance (pas healthy)
    networks:
      - frontend                                       # Acces uniquement au reseau frontend
    restart: unless-stopped

networks:
  frontend: { driver: bridge }                         # Reseau expose (web ↔ api)
  backend:
    driver: bridge
    internal: true                                     # Backend isole : pas d'acces Internet

volumes:
  data_pg: {}                                          # Volume nomme pour la persistence DB

secrets:
  pg_pwd:
    file: ./secrets/postgres.password                  # Fichier local contenant le mot de passe
```

> **Resultat attendu** :
> ```
> ✔ Network chapitre06_frontend  Created (bridge)
> ✔ Network chapitre06_backend   Created (bridge, internal)
> ✔ Volume "chapitre06_data_pg"  Created
> ✔ Container chapitre06-db-1    Started (healthy after ~10s)
> ✔ Container chapitre06-api-1   Started (after db healthy)
> ✔ Container chapitre06-web-1   Started (after api started)
> ```
> **Verification** : `curl http://localhost` repond (nginx → api) ; `docker compose ps` affiche les 3 services avec `db (healthy)` et `api (healthy)` ; `docker compose exec db ping 8.8.8.8` echoue (internal).

---

## 15) Réutilisation & factorisation (anchors, `x-`)

> **Objectif** : Utiliser les **ancres YAML** (`&` / `*`) et les **extension fields** (`x-`) pour factoriser les configurations repetitives (ici, des healthchecks partages). Les champs `x-` sont ignores par Compose mais servent de templates reutilisables.
> **Pre-requis** : Les images `ghcr.io/acme/a:1.0` et `ghcr.io/acme/b:1.0` doivent contenir les binaires `/health` et `/ping` respectivement.

```yaml
x-health-fast: &health_fast           # Extension field (x-) + ancre YAML (&health_fast)
  interval: 10s                       # Definition reutilisable
  timeout: 3s
  retries: 5

services:
  svc-a:
    image: ghcr.io/acme/a:1.0
    healthcheck:
      test: ["CMD","/health"]         # Commande specifique a svc-a
      <<: *health_fast                # Fusionne l'ancre : injecte interval, timeout, retries

  svc-b:
    image: ghcr.io/acme/b:1.0
    healthcheck:
      test: ["CMD","/ping"]           # Commande specifique a svc-b
      <<: *health_fast                # Meme configuration de timing reutilisée
```

> **Resultat attendu** :
> ```
> ✔ Container chapitre06-svc-a-1  Started (healthcheck: /health, interval 10s, timeout 3s, retries 5)
> ✔ Container chapitre06-svc-b-1  Started (healthcheck: /ping, interval 10s, timeout 3s, retries 5)
> ```
> **Verification** : `docker compose config` montre que les deux healthchecks ont les memes valeurs `interval`, `timeout`, `retries` ; `docker inspect --format '{{json .State.Health}}'` confirme la configuration.

---

## 16) Dépannage & bonnes pratiques

**Dépannage**

* `docker compose config` : valider le YAML généré.
* `docker compose logs -f SERVICE` : voir les erreurs de démarrage.
* `depends_on` + **healthchecks** : diagnostiquer les enchaînements.
* `docker inspect` (conteneur) : confirmer réseaux/ports/volumes réellement montés.

**Do**

* Un **réseau interne** pour les backends, un **frontend** exposé.
* **Healthchecks** + `depends_on: condition: service_healthy`.
* **Secrets/configs** en fichiers (pas en variables) ; **read_only** + `tmpfs`.
* **Overrides** par environnement et **profils** pour options (observabilité, debug).
* Déployer par **digest** pour l'immutabilité.

**Don't**

* Éviter `deploy.*` en pensant que Compose l'applique (c'est pour **Swarm**).
* Éviter `-P` (publication automatique) en prod ; mappez les ports **explicitement**.
* Éviter de mettre tous les services sur le même réseau par facilité.
* Ne jamais commit de **secrets** dans le dépôt.

---

## 17) Aide-mémoire (commandes clés)

> **Objectif** : Reference rapide de toutes les commandes Compose essentielles, organisees par categorie, pour un usage quotidien en developpement et en production.
> **Pre-requis** : Docker Compose v2 installe ; un fichier `compose.yaml` valide dans le repertoire courant.

```bash
# Lancer / arrêter
docker compose up -d                    # Demarre tous les services en arriere-plan
docker compose down --remove-orphans    # Arrete et supprime tout (conteneurs, reseaux, orphelins)

# Inspection
docker compose ps                       # Liste les services avec statut et ports
docker compose logs -f --tail=200 api   # Logs en continu du service api (200 dernieres lignes)
docker compose config                   # Affiche le YAML fusionne et valide

# Déboguer un service
docker compose exec api sh              # Shell interactif dans le conteneur api
docker compose run --rm api sh -lc 'curl -v http://localhost:8080/health'  # Commande one-shot

# Mises à jour
docker compose pull                     # Telecharge les dernieres images
docker compose up -d --no-deps api      # Recree api uniquement (sans toucher aux deps)
docker compose restart web              # Redemarre le service web

# Échelle
docker compose up -d --scale web=3      # Lance 3 instances du service web

# Dev (watch)
docker compose -f compose.yaml -f compose.dev.yaml watch  # Synchronisation temps reel
```

> **Resultat attendu** :
> ```
> # Chaque commande retourne un statut avec des icones ✔/✘
> # ps : tableau avec NAME, IMAGE, SERVICE, STATUS, PORTS
> # config : YAML complet resolu et fusionne
> ```
> **Verification** : Tester chaque commande dans un projet reel ; `docker compose config` doit toujours retourner un YAML valide sans erreur.

---

## 18) Checklist de clôture (qualité d'une stack Compose)

* Réseaux **séparés** (frontend exposé, backend `internal` si possible).
* **Healthchecks** pertinents ; `depends_on` avec `service_healthy` pour l'ordre.
* **Secrets/configs** gérés en fichiers ; **rootfs read_only** + `tmpfs` déclarés.
* Volumes **nommés** pour la persistance (DB, state) ; binds **RO** pour configs.
* Variables/interpolation `.env` maîtrisées ; **overrides** prod/dev documentés.
* Commandes d'exploitation **standardisées** (up/down/logs/exec/restart).
* Images **versionnées** et idéalement déployées par **digest** ; buildx/caches configurés.
* `docker compose config` **propre** ; pas d'options Swarm critiques supposées actives.
