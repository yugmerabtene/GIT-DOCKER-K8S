# Chapitre-12 — Déploiement & Releases

*(Compose "prod-like", blue/green, canary, rollbacks, migrations de base de données, runbooks)*

## Objectifs d'apprentissage

* Structurer un **déploiement Docker/Compose** prêt pour la prod (réseaux, LB, santé, secrets, immutabilité par digest).
* Exécuter des **releases sans interruption** : **blue/green**, **canary** pondéré, **rollback** rapide.
* Mettre en œuvre des **migrations de schéma** sûres (**expand-migrate-contract**).
* Outiller le processus : **runbooks**, **listes de contrôle**, artefacts versionnés (digest, SBOM, signatures).

## Pré-requis

* Chap. 01–11 (images, réseau, storage, Dockerfile, Compose, registry, sécurité, observabilité, perf, CI/CD).
* Notions reverse-proxy (Nginx/HAProxy/Traefik) et SQL (indexes, verrous, transactions).

---

## 1) Stratégies de déploiement : panorama

| Stratégie                  | Interruption |     Complexité | Idéal quand                                  |
| -------------------------- | -----------: | -------------: | -------------------------------------------- |
| **Recreate** (stop→start)  |          Oui |         Faible | Petites apps, maintenance planifiée          |
| **Blue/Green**             |          Non |        Moyenne | Changement rapide et **rollback instantané** |
| **Canary** (pondéré)       |          Non | Moyenne/Élevée | Valider en prod sur **x %** d'utilisateurs   |
| **A/B** (features toggles) |          Non |         Élevée | Expérimentations longues, UX/produit         |

> Compose ne gère pas "rolling update" natif comme K8s, mais **blue/green** + **canary via LB** couvre 95% des besoins.

---

## 2) Architecture "prod-like" de base (Compose)

Principes :

* **LB** en frontal (Nginx/HAProxy/Traefik), **frontend** exposé, **backend** interne.
* Services **read_only** + **tmpfs**, **healthchecks**, **digests** (pas de `:latest`).
* **Secrets** montés en fichiers, **volumes nommés** pour la persistance, **réseaux séparés**.

Extrait minimal :

> **Objectif** : Définir une stack Docker Compose de base « production-like » avec un reverse-proxy (Nginx), une API immuable par digest, un filesystem en lecture seule, des healthchecks, une base PostgreSQL avec secrets montés en fichiers, et des réseaux isolés frontend/backend.
> **Pre-requis** : Docker et Docker Compose installés ; un fichier `./secrets/postgres.password` existant ; l'image API poussée sur GHCR avec un digest SHA256 connu.

```yaml
# compose.base.yaml
services:
  # --- Reverse-proxy frontal : expose le port 80 vers l'extérieur ---
  web:
    image: nginx:1.27                          # version pinée (pas de :latest)
    ports: ["80:80"]                           # exposition HTTP publique
    networks: [ frontend ]                     # réseau frontal uniquement
    depends_on: { api: { condition: service_started } }  # démarre après l'API

  # --- API backend : image immuable, filesystem verrouillé ---
  api:
    image: ghcr.io/acme/api@sha256:<digest>    # immuable : référencée par digest SHA256
    read_only: true                            # filesystem racine en lecture seule (sécurité)
    tmpfs: [ /run, /tmp ]                      # répertoires inscriptibles en mémoire volatile
    healthcheck:
      test: ["CMD-SHELL","curl -fsS http://localhost:8080/health || exit 1"]  # sonde de santé HTTP
      interval: 20s                            # vérification toutes les 20 secondes
      retries: 5                               # 5 échecs avant statut "unhealthy"
    networks: [ backend ]                      # réseau interne uniquement (pas d'accès direct)

  # --- Base de données PostgreSQL : secrets via fichier, volume persistant ---
  db:
    image: postgres:16                         # version majeure pinée
    environment:
      - POSTGRES_PASSWORD_FILE=/run/secrets/pg_pwd  # mot de passe lu depuis un fichier secret
    secrets: [ pg_pwd ]                        # montage du secret dans /run/secrets/
    volumes: [ data_pg:/var/lib/postgresql/data ]  # volume nommé pour persistance des données
    networks: [ backend ]                      # réseau interne (isolé du frontend)
    healthcheck: { test: ["CMD","pg_isready","-U","postgres"] }  # vérifie que PG accepte les connexions

# --- Définition des réseaux isolés ---
networks:
  frontend: { driver: bridge }                 # réseau pont accessible depuis l'hôte
  backend:  { driver: bridge, internal: true } # réseau pont interne (pas d'accès internet)

# --- Volumes persistants ---
volumes:
  data_pg: {}                                  # volume nommé pour les données PostgreSQL

# --- Secrets montés depuis des fichiers locaux ---
secrets:
  pg_pwd: { file: ./secrets/postgres.password }  # fichier contenant le mot de passe PG
```

> **Résultat attendu** :
> ```
> ✔ Network app_frontend  Created
> ✔ Network app_backend   Created
> ✔ Volume "app_data_pg"  Created
> ✔ Container app-db-1    Healthy
> ✔ Container app-api-1   Started
> ✔ Container app-web-1   Started
> ```
> **Vérification** : `docker compose ps` doit afficher les 3 services avec un statut healthy pour `api` et `db` ; `curl http://localhost/health` doit répondre 200.

---

## 3) Blue/Green avec Compose (2 *projects* parallèles)

Idée : exécuter **deux stacks** séparées (blue/green) derrière **un LB unique** et **basculer**.

### 3.1 Deux stacks « blue » et « green »

> **Objectif** : Décrire les deux fichiers de surcouche qui définissent les tags/digests distincts pour chaque environnement (blue = version actuelle, green = nouvelle version).
> **Pre-requis** : Le fichier `compose.base.yaml` doit exister ; les images blue et green doivent être poussées sur le registry avec des digests différents.

```
compose.blue.yaml   # mêmes services mais tag/digest BLUE (version actuellement en production)
compose.green.yaml  # mêmes services mais tag/digest GREEN (nouvelle version à déployer)
```

> **Résultat attendu** :
> ```
> compose.blue.yaml   → services avec image: ghcr.io/acme/api@sha256:aaa...
> compose.green.yaml  → services avec image: ghcr.io/acme/api@sha256:bbb...
> ```
> **Vérification** : Les deux fichiers doivent être identiques hormis les références d'images (digests).

Lancement :

> **Objectif** : Démarrer les deux stacks en parallèle sous des noms de projets Docker Compose distincts (`app-blue` et `app-green`), ce qui isole leurs réseaux, volumes et conteneurs.
> **Pre-requis** : Les fichiers `compose.base.yaml`, `compose.blue.yaml`, `compose.green.yaml` sont présents ; les images référencées sont disponibles dans le registry.

```bash
# Démarre la stack BLUE (version actuelle) dans le projet "app-blue"
docker compose -p app-blue  -f compose.base.yaml -f compose.blue.yaml  up -d
# Démarre la stack GREEN (nouvelle version) dans le projet "app-green"
docker compose -p app-green -f compose.base.yaml -f compose.green.yaml up -d
```

> **Résultat attendu** :
> ```
> ✔ Network app-blue_backend   Created
> ✔ Container app-blue-api-1   Started
> ✔ Container app-blue-db-1    Started
> ✔ Container app-blue-web-1   Started
> ✔ Network app-green_backend  Created
> ✔ Container app-green-api-1  Started
> ✔ Container app-green-db-1   Started
> ✔ Container app-green-web-1  Started
> ```
> **Vérification** : `docker compose -p app-blue ps` et `docker compose -p app-green ps` doivent chacun afficher leurs services ; les réseaux `app-blue_backend` et `app-green_backend` sont distincts (`docker network ls`).

> L'option `-p` isole réseaux/ressources : `app-blue_backend`, `app-green_backend`, etc.

### 3.2 LB HAProxy (pondération & bascule)

`haproxy.cfg` (extrait) :

> **Objectif** : Configurer HAProxy comme load balancer frontal qui route le trafic HTTP vers les backends blue et green, avec un système de pondération (weight) permettant de basculer progressivement le trafic d'un environnement à l'autre. Inclut des health checks pour écarter les serveurs défaillants.
> **Pre-requis** : HAProxy LTS installé ou image Docker `haproxy:lts` disponible ; les conteneurs `api_blue` et `api_green` doivent être résolubles via le réseau Docker (aliases configurés).

```
global
  log stdout format raw local0              # logs envoyés sur stdout (compatible Docker)
defaults
  mode http                                  # mode HTTP (couche 7)
  timeout client  30s                        # timeout côté client
  timeout server  30s                        # timeout côté serveur backend
  timeout connect 5s                         # timeout de connexion TCP

frontend fe_http
  bind *:80                                  # écoute sur le port 80 toutes interfaces
  default_backend be_api                     # route tout le trafic vers le backend "be_api"

backend be_api
  option httpchk GET /health                 # health check HTTP : GET /health sur chaque serveur
  server api_blue  api_blue:8080  check weight 100   # blue : 100% du trafic (actif)
  server api_green api_green:8080 check weight 0     # green : 0% du trafic (en attente)
```

> **Résultat attendu** :
> ```
> [NOTICE] HAProxy démarré, frontend fe_http écoute sur *:80
> backend be_api : api_blue UP (weight 100), api_green UP (weight 0)
> ```
> **Vérification** : `curl http://localhost/` doit router vers l'instance blue ; `echo "show stat" | socat stdio /run/haproxy/admin.sock` montre les poids et états.

Compose du LB :

> **Objectif** : Définir le service HAProxy dans Compose, connecté à la fois au réseau frontal (exposition port 80) et aux réseaux backend des deux stacks blue/green (réseaux externes préexistants).
> **Pre-requis** : Les stacks `app-blue` et `app-green` doivent être démarrées (leurs réseaux `_backend` existent) ; le fichier `haproxy.cfg` est présent dans le répertoire courant.

```yaml
# compose.lb.yaml
services:
  haproxy:
    image: haproxy:lts                       # version LTS d'HAProxy (stable long terme)
    ports: ["80:80"]                         # exposition HTTP publique
    volumes: [ "./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" ]  # config montée en lecture seule
    networks: [ lb, blue_net, green_net ]    # connecté aux 3 réseaux : frontal + 2 backends
networks:
  lb: {}                                     # réseau frontal du LB
  blue_net:  { external: true, name: app-blue_backend }   # réseau externe de la stack blue
  green_net: { external: true, name: app-green_backend }  # réseau externe de la stack green
```

> **Résultat attendu** :
> ```
> ✔ Network app-lb_lb        Created
> ✔ Container app-lb-haproxy-1  Started
> ```
> **Vérification** : `docker compose -f compose.lb.yaml ps` affiche haproxy UP ; `curl http://localhost/` répond via le backend blue.

Dans chaque stack, donnez aux services des **aliases** que le LB résout :

> **Objectif** : Configurer des alias réseau dans chaque stack pour que HAProxy puisse résoudre les noms `api_blue` et `api_green` vers les conteneurs API correspondants via le DNS Docker.
> **Pre-requis** : Les fichiers `compose.blue.yaml` et `compose.green.yaml` existent déjà avec un service `api` défini.

```yaml
# dans compose.blue.yaml
services:
  api:
    networks:
      backend:
        aliases: [ api_blue ]                # alias DNS résolu dans le réseau app-blue_backend

# dans compose.green.yaml
services:
  api:
    networks:
      backend:
        aliases: [ api_green ]               # alias DNS résolu dans le réseau app-green_backend
```

> **Résultat attendu** :
> ```
> # Depuis le conteneur haproxy :
> dig api_blue   → résout vers l'IP du conteneur app-blue-api-1
> dig api_green  → résout vers l'IP du conteneur app-green-api-1
> ```
> **Vérification** : `docker exec app-lb-haproxy-1 getent hosts api_blue` et `api_green` doivent retourner des IPs valides.

**Basculer** (canary/green) = changer **weights** (10/90 → 50/50 → 100/0) dans `haproxy.cfg` puis :

> **Objectif** : Recharger la configuration HAProxy à chaud (sans couper les connexions existantes) en envoyant le signal SIGHUP au conteneur, après avoir modifié les poids dans le fichier de configuration.
> **Pre-requis** : Le fichier `haproxy.cfg` a été modifié avec les nouveaux poids ; le conteneur HAProxy tourne sous le nom `app-lb-haproxy`.

```bash
# Envoie SIGHUP à HAProxy pour recharger sa config sans interrompre le service
docker kill -s HUP app-lb-haproxy   # reload sans downtime
```

> **Résultat attendu** :
> ```
> app-lb-haproxy
> # Dans les logs HAProxy : [NOTICE] ... Reexecuting process
> ```
> **Vérification** : `docker logs app-lb-haproxy --tail=5` doit montrer un rechargement ; les nouveaux poids sont actifs (`show stat` via socket admin).

> Variante Nginx : `upstream api { server api_blue:8080 weight=100; server api_green:8080 weight=0; }`

---

## 4) Scénario **Canary** (pondéré)

1. **Déployer** green (weight=10) → 10% du trafic.
2. **Observer** (erreurs, latence P95, logs, métriques).
3. **Augmenter** progressif (25 → 50 → 100).
4. **Figer** (weight=100 green / 0 blue), conserver blue comme **filet de sécurité** 24–48h.
5. **Désactiver** blue une fois confirmé (ou conserver pour rollback ultra-rapide).

---

## 5) **Rollback** en une commande

* Avec HAProxy/Nginx : remettre **weight=100** sur **blue**, **0** sur **green**, `HUP` LB → retour quasi instantané.
* Côté Compose, ne **supprimez** pas la stack ancienne tant que la nouvelle n'est pas validée.

**Bonnes pratiques rollback** :

* **Déployer par digest** → vous savez **exactement** à quoi revenir.
* Conserver le **runbook** et les **artefacts** (digest, SBOM, signatures) de la version précédente.
* Un **script** "switch-back" prêt à lancer (voir §10).

---

## 6) Migrations de base de données (expand → migrate → contract)

But : **aucun downtime** et **compatibilité bilatérale** entre ancien et nouveau code.

### 6.1 Étapes

1. **Expand** (pré-release)

   * Ajouter colonnes/tables/index **sans casser** l'existant.
   * Par ex. Postgres : `CREATE INDEX CONCURRENTLY`, éviter **locks** prolongés.
   * Déployer **green** qui sait lire **ancien + nouveau** schéma.

2. **Migrate/Backfill**

   * Tâche de **rétro-remplissage** (idempotente) qui copie/convertit les données.
   * Exécuter dans un **job** Compose dédié, monitoré.

3. **Switch** (canary/blue-green)

   * Basculer le trafic vers la version green.

4. **Contract** (post-validation)

   * Supprimer les champs/chemins **obsolètes** une fois la nouvelle version confirmée.

### 6.2 Jobs Compose pour migrations

> **Objectif** : Définir des services Compose jetables (`run --rm`) pour exécuter les migrations de schéma (`migrate`) et le rétro-remplissage des données (`backfill`) dans la stack green, en attendant que la base soit saine avant le switch de trafic.
> **Pre-requis** : L'image `api-migrations` contient l'outil de migration (ex. golang-migrate, Flyway) ; la variable `DB_URL` est définie dans le `.env` ; le service `db` est démarré ethealthy.

```yaml
services:
  # --- Job de migration de schéma (DDL : CREATE, ALTER, INDEX) ---
  migrate:
    image: ghcr.io/acme/api-migrations@sha256:<digest>  # image immuable dédiée aux migrations
    command: ["./migrate","up","--safe"]                # applique les migrations en mode sûr
    networks: [ backend ]                               # accès réseau interne vers la DB
    environment: [ DB_URL=${DB_URL} ]                   # chaîne de connexion depuis .env
    depends_on:
      db: { condition: service_healthy }                # attend que la DB soit prête

  # --- Job de rétro-remplissage (backfill) des données ---
  backfill:
    image: ghcr.io/acme/api@sha256:<digest>             # image de l'API (contient les tâches)
    command: ["./tasks","backfill-new-column"]          # exécute la tâche de backfill idempotente
    networks: [ backend ]                               # accès réseau interne vers la DB
    environment: [ DB_URL=${DB_URL} ]                   # chaîne de connexion depuis .env
```

> **Résultat attendu** :
> ```
> migrate  : "Applied 3 migration(s) successfully"
> backfill : "Backfilled 12450 rows in 45s (idempotent: OK)"
> ```
> **Vérification** : `docker compose -p app-green ps -a` montre les jobs en état `Exited (0)` ; les logs confirment l'application des migrations et le nombre de lignes traitées.

Exécution :

> **Objectif** : Exécuter séquentiellement les jobs de migration puis de backfill dans la stack green, en mode éphémère (`--rm` pour supprimer le conteneur après exécution).
> **Pre-requis** : La stack `app-green` est démarrée (`docker compose -p app-green up -d`) ; le service `db` est healthy ; les fichiers de migration sont inclus dans l'image `api-migrations`.

```bash
# Exécute les migrations de schéma (DDL) dans la stack green, puis supprime le conteneur
docker compose -p app-green run --rm migrate
# Exécute le rétro-remplissage des données (DML) dans la stack green, puis supprime le conteneur
docker compose -p app-green run --rm backfill
```

> **Résultat attendu** :
> ```
> Creating app-green_migrate_run ... done
> Applied 3 migration(s) successfully
> Creating app-green_backfill_run ... done
> Backfilled 12450 rows in 45s
> ```
> **Vérification** : `docker compose -p app-green ps -a` ne montre plus les conteneurs de job (supprimés par `--rm`) ; la base de données contient les nouvelles colonnes/tables et les données migrées.

**Rappels DB** :

* **Transactions** pour petits changements, **batchs** pour gros volumes.
* Index **concurrently** (PG), éviter `ALTER` bloquants en heures pleines.
* **Feature flags** côté app pour écrire **double** (old+new) durant la transition.

---

## 7) Gestion des **configs & secrets** par environnement

* **Fichiers Compose superposés** : `compose.base.yaml` + `compose.prod.yaml`.
* `.env` par environnement (attention à l'interpolation, cf. Chap. 06).
* **Secrets** via `secrets:` (montés en **fichiers**), pas en variables.
* **Immutabilité** : images référencées **par digest** (CI/CD produit le digest validé).

---

## 8) Observabilité de release

Avant d'augmenter la part de trafic :

* **Healthchecks** OK, **logs** sans erreurs anormales.
* **Métriques** : taux d'erreur, latence P95, CPU/MEM, restart count.
* **Sondes actives** (synthetics) pointées sur la **green**.
* **Dash release** : panneaux comparatifs **blue vs green** (errors, latency, throughput).

---

## 9) Runbook de release (exécutable)

1. **Pré-flight**

   * Vérifier **digest** signé, SBOM/scans OK (CI).
   * Capacité disque `/var/lib/docker`, santé DB, LB disponible, NTP OK.

2. **Déploiement green**

   * `docker compose -p app-green -f compose.base.yaml -f compose.green.yaml up -d`
   * `docker compose -p app-green ps`, `logs -f` (API, web).

3. **Migrations**

   * `docker compose -p app-green run --rm migrate`
   * `docker compose -p app-green run --rm backfill` (si nécessaire)

4. **Canary 10%**

   * Modifier `haproxy.cfg` (weight green=10, blue=90), `kill -s HUP haproxy`
   * Observer 15–30 min (ou x requêtes / y erreurs max)

5. **Ramp-up**

   * 50% → 100% si métriques OK, alertes silencieuses.

6. **Stabilisation**

   * Laisser blue en réserve 24–48h.

7. **Contract**

   * Exécuter migrations "contract", retirer écritures "double".

8. **Nettoyage**

   * `docker compose -p app-blue down` quand validé.
   * Archiver artefacts (digest, cfg LB, logs release).

**Rollback** (à tout moment) :

* Remettre `weight green=0 / blue=100` + `HUP`.
* Si besoin, `docker compose -p app-green down`.

---

## 10) Automatisation (scripts)

### 10.1 Switch de poids HAProxy (bash simple)

> **Objectif** : Script bash qui modifie dynamiquement les poids (weight) des serveurs blue et green dans le fichier de configuration HAProxy, puis recharge HAProxy à chaud. Permet d'automatiser la bascule de trafic lors d'un déploiement canary ou blue/green.
> **Pre-requis** : Le fichier `haproxy.cfg` existe dans le répertoire courant avec des lignes `server api_blue` et `server api_green` contenant des `weight` ; le conteneur `app-lb-haproxy` est en cours d'exécution ; le script reçoit deux arguments entiers (poids blue et green).

```bash
#!/usr/bin/env bash
set -euo pipefail                             # mode strict : erreur, non-set, pipefail
CFG=haproxy.cfg                               # chemin vers le fichier de config HAProxy
BLUE=$1   # 0..100                            # 1er argument : poids du backend blue (0 à 100)
GREEN=$2  # 0..100                            # 2e argument : poids du backend green (0 à 100)
# Remplace le weight de la ligne api_blue par la valeur $BLUE (regex avec groupe capturant)
sed -i -E "s/(server api_blue .* weight )([0-9]+)/\1${BLUE}/"   "$CFG"
# Remplace le weight de la ligne api_green par la valeur $GREEN
sed -i -E "s/(server api_green .* weight )([0-9]+)/\1${GREEN}/" "$CFG"
# Recharge HAProxy à chaud (SIGHUP) sans couper les connexions actives
docker kill -s HUP app-lb-haproxy
echo "Switched weights: blue=${BLUE}, green=${GREEN}"
```

> **Résultat attendu** :
> ```
> $ ./switch-weights.sh 10 90
> Switched weights: blue=10, green=90
> # haproxy.cfg contient maintenant :
> #   server api_blue  api_blue:8080  check weight 10
> #   server api_green api_green:8080 check weight 90
> ```
> **Vérification** : `grep weight haproxy.cfg` montre les nouvelles valeurs ; `docker logs app-lb-haproxy --tail=3` confirme le rechargement ; le trafic est effectivement réparti selon les nouveaux poids.

### 10.2 Verrouillage de version (digest pinning) en Compose

> **Objectif** : Mettre à jour de manière atomique la référence d'image du service `api` dans `compose.green.yaml` pour la figer sur un digest SHA256 spécifique, garantissant l'immutabilité du déploiement.
> **Pre-requis** : L'outil `yq` (v4+) est installé ; la variable d'environnement `$DIGEST` contient le SHA256 de l'image validée (ex. `abc123...`) ; le fichier `compose.green.yaml` existe.

```bash
# Utilise yq pour remplacer le champ .services.api.image par l'image référencée par digest
# La variable $DIGEST est interpolée hors de la chaîne yq pour éviter les problèmes d'échappement
yq -i '.services.api.image = "ghcr.io/acme/api@sha256:'"$DIGEST"'"' compose.green.yaml
```

> **Résultat attendu** :
> ```
> # Avant :
> #   image: ghcr.io/acme/api@sha256:ancien_digest
> # Après :
> #   image: ghcr.io/acme/api@sha256:abc123def456...
> ```
> **Vérification** : `yq '.services.api.image' compose.green.yaml` retourne le nouveau digest ; `git diff compose.green.yaml` montre le changement.

---

## 11) Exemples "prod-like" (synthèse)

### 11.1 Blue/Green via deux projects & HAProxy

* Deux stacks `app-blue` / `app-green` (digests différents).
* LB unique connecté aux deux **backend networks**.
* **Poids** HAProxy pour canary/bascule.
* **Jobs** `migrate`/`backfill` dans la stack candidate.
* **Rollback** = poids → blue 100%.

### 11.2 Canary fin (routes par header)

* Ajouter une **route** "X-Canary: 1" → envoyer 100% de ce trafic vers **green** pour tests E2E internes sans impacter tout le monde (règles HAProxy/Nginx).

---

## 12) Aide-mémoire (commandes clés)

> **Objectif** : Récapitulatif des commandes Docker Compose les plus utilisées lors d'un déploiement blue/green avec canary, couvrant le cycle complet : déploiement, monitoring, migrations, reload LB, et rollback.
> **Pre-requis** : Docker Compose v2+ installé ; les fichiers `compose.base.yaml` et `compose.green.yaml` sont présents ; HAProxy est déployé sous le nom de conteneur `app-lb-haproxy`.

```bash
# --- Démarrer/mettre à jour une stack nommée ---
# Démarre la stack green (ou met à jour si elle existe déjà) en arrière-plan
docker compose -p app-green -f compose.base.yaml -f compose.green.yaml up -d

# --- Santé & logs ---
# Affiche l'état de tous les services de la stack green (statut, ports, santé)
docker compose -p app-green ps
# Suit en continu les logs du service API (dernières 200 lignes puis temps réel)
docker compose -p app-green logs -f --tail=200 api

# --- Jobs migrations ---
# Exécute les migrations de schéma (DDL) dans un conteneur éphémère
docker compose -p app-green run --rm migrate
# Exécute le rétro-remplissage des données (DML) dans un conteneur éphémère
docker compose -p app-green run --rm backfill

# --- Reload LB après changement de poids ---
# Recharge la config HAProxy à chaud (applique les nouveaux weights sans downtime)
docker kill -s HUP app-lb-haproxy

# --- Rollback immédiat = poids blue=100 / green=0 + reload ---
# (utiliser le script §10.1 : ./switch-weights.sh 100 0)
```

> **Résultat attendu** :
> ```
> # up -d       → Conteneurs green démarrés, healthchecks en cours
> # ps          → api (healthy), db (healthy), web (running)
> # logs -f     → Flux de logs temps réel de l'API
> # run migrate → "Applied N migration(s) successfully"
> # kill -s HUP → HAProxy rechargé, nouveaux poids actifs
> ```
> **Vérification** : Chaque commande doit se terminer sans erreur (code retour 0) ; `docker compose -p app-green ps` confirme l'état healthy des services ; les logs HAProxy confirment chaque rechargement.

---

## 13) Checklist de clôture (release "prête-prod")

**Avant**

* Images **signées** + **SBOM/provenance** publiés ; **digest** consigné.
* **Migrations expand** prêtes, jobs testés sur environnement miroir.
* LB & santé : **healthchecks** définis, dashboard comparatif prêt.

**Pendant**

* Déploiement **green** isolé, **canary 10%**, observation métriques & logs.
* **Backfill** terminé et idempotent, erreurs < seuil, latence P95 OK.

**Bascule**

* Poids LB → **100% green**, **0% blue**, surveillance rapprochée.
* **Rollback** scripté et **répété** en test (RTO court).

**Après**

* **Contract** effectué (schéma nettoyé), feature flags retirés.
* Stack blue retirée quand validé, **artefacts archivés** (digest, configs).
* Post-mortem / compte-rendu de release avec mesures avant/après.
