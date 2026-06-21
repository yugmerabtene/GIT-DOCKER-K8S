# Chapitre-02 — Conteneurs (cycle de vie & exécution)

## Objectifs d'apprentissage

* Gérer **tout le cycle de vie** d'un conteneur : créer, démarrer, arrêter, redémarrer, supprimer.
* Exploiter les **modes d'exécution** (interactif/détaché), **journaux**, **exec**, **stats**, **healthchecks**.
* Appliquer des **limites de ressources** (CPU, mémoire, PIDs, ulimit) et des **politiques de redémarrage**.
* Savoir **diagnostiquer** (inspect/top/logs/events) et **paramétrer** l'arrêt propre (signaux, délais).

## Pré-requis

* Docker Engine/CLI opérationnel.
* Bases Linux (shell), notions de processus et signaux.

---

## 1) Cycle de vie : commandes essentielles

### 1.1 Créer vs exécuter

> **Objectif** : Illustrer la différence entre `docker create` (préparation seule du conteneur) et `docker run` (création + démarrage immédiat).
> **Pré-requis** : Docker Engine démarré ; l'image `nginx:1.27` sera tirée automatiquement si absente.

```bash
# Crée un conteneur stoppé (pas encore lancé)
# → Le conteneur est enregistré dans Docker mais son processus n'est PAS démarré.
# → L'image nginx:1.27 est téléchargée si elle n'est pas en local.
docker create --name web nginx:1.27

# Lance un conteneur (crée + démarre en une seule commande)
# → --name web       : nomme le conteneur "web"
# → -d               : mode détaché (arrière-plan)
# → -p 8080:80       : mappe le port 8080 de l'hôte vers le port 80 du conteneur
# → nginx:1.27       : image utilisée
docker run --name web -d -p 8080:80 nginx:1.27
```

> **Résultat attendu** :
> ```
> # docker create --name web nginx:1.27
> a1b2c3d4e5f6...   # ID du conteneur créé (stoppé)
>
> # docker run --name web -d -p 8080:80 nginx:1.27
> b7c8d9e0f1a2...   # ID du conteneur lancé en arrière-plan
> ```
> **Vérification** : `docker ps -a` montre le premier conteneur avec le statut `Created` et le second avec `Up`.

### 1.2 Démarrer / arrêter / redémarrer / tuer / supprimer

> **Objectif** : Maîtriser les commandes de gestion du cycle de vie d'un conteneur existant.
> **Pré-requis** : Un conteneur nommé `web` doit exister (créé via `docker create` ou `docker run`).

```bash
docker start web                 # démarre un conteneur existant (précédemment créé ou arrêté)
docker stop -t 20 web            # envoie SIGTERM, attend 20s, puis SIGKILL si toujours actif
docker restart web               # enchaîne stop + start (redémarre le conteneur)
docker kill --signal SIGUSR1 web # envoie un signal personnalisé (ici SIGUSR1) immédiatement, sans délai
docker rm web                    # supprime le conteneur (doit être à l'arrêt, sinon erreur)
docker rm -f web                 # force la suppression : équivaut à kill + rm en une commande
```

> **Résultat attendu** :
> ```
> # docker start web
> web
> # docker stop -t 20 web
> web
> # docker restart web
> web
> # docker kill --signal SIGUSR1 web
> web
> # docker rm web
> web
> # docker rm -f web
> web
> ```
> **Vérification** : Après `docker rm`, le conteneur n'apparaît plus dans `docker ps -a`.

### 1.3 Lister / filtrer / formater

> **Objectif** : Afficher les conteneurs avec différents filtres et formats de sortie pour le scripting.
> **Pré-requis** : Au moins un conteneur existant (en cours ou arrêté).

```bash
docker ps                        # affiche uniquement les conteneurs en cours d'exécution
docker ps -a                     # affiche TOUS les conteneurs, y compris ceux arrêtés ou créés
# Filtre les conteneurs arrêtés et formate la sortie :
# --filter "status=exited" : ne montre que les conteneurs terminés
# --format '{{.Names}}\t{{.Status}}' : affiche seulement le nom et le statut, séparés par une tabulation
docker ps --filter "status=exited" --format '{{.Names}}\t{{.Status}}'
```

> **Résultat attendu** :
> ```
> # docker ps
> CONTAINER ID   IMAGE        COMMAND                  STATUS         PORTS                  NAMES
> b7c8d9e0f1a2   nginx:1.27   "/docker-entrypoint.…"   Up 2 minutes   0.0.0.0:8080->80/tcp   web
>
> # docker ps -a
> CONTAINER ID   IMAGE        COMMAND                  STATUS                     PORTS   NAMES
> b7c8d9e0f1a2   nginx:1.27   "/docker-entrypoint.…"   Up 2 minutes                       web
> a1b2c3d4e5f6   nginx:1.27   "/docker-entrypoint.…"   Created                            web2
>
> # docker ps --filter "status=exited" --format '{{.Names}}\t{{.Status}}'
> web2    Exited (0) 5 minutes ago
> ```
> **Vérification** : Le filtre `status=exited` ne retourne que les conteneurs arrêtés ; le format limite les colonnes affichées.

### 1.4 Pause / reprise / attente

> **Objectif** : Suspendre/reprendre les processus d'un conteneur sans l'arrêter, et attendre sa fin.
> **Pré-requis** : Un conteneur nommé `web` en cours d'exécution.

```bash
docker pause web                 # gèle tous les processus du conteneur via cgroup freezer (ils restent en mémoire)
docker unpause web               # reprend l'exécution des processus précédemment gelés
docker wait web                  # bloque le terminal jusqu'à l'arrêt du conteneur, puis renvoie son code de sortie
```

> **Résultat attendu** :
> ```
> # docker pause web
> web
> # docker unpause web
> web
> # docker wait web
> 0    # code de sortie du conteneur (0 = succès)
> ```
> **Vérification** : Pendant `pause`, `docker ps` affiche le statut `Up (Paused)`. `wait` bloque tant que le conteneur tourne.

---

## 2) Modes d'exécution & options courantes

### 2.1 Interactif vs détaché

> **Objectif** : Montrer les deux modes d'exécution : interactif (terminal) et détaché (arrière-plan).
> **Pré-requis** : Images `alpine:3.20` et `busybox` disponibles ou pullables.

```bash
# Mode interactif : ouvre un shell dans le conteneur avec un pseudo-terminal
# -i : garde STDIN ouvert (permet de taper des commandes)
# -t : alloue un pseudo-TTY (affichage formaté)
docker run -it --name shell alpine:3.20 sh

# Mode détaché : le conteneur tourne en arrière-plan sans interaction terminal
# -d : détaché (le terminal rend la main immédiatement)
docker run -d  --name job busybox sleep 3600
```

> **Résultat attendu** :
> ```
> # docker run -it --name shell alpine:3.20 sh
> / #   # invite de commande du conteneur Alpine
>
> # docker run -d --name job busybox sleep 3600
> c3d4e5f6a7b8...   # ID du conteneur en arrière-plan
> ```
> **Vérification** : Le premier offre un shell interactif (`/ #`). Le second rend la main immédiatement ; `docker ps` montre `job` avec `Up`.

### 2.2 Nom, redémarrage, nettoyage

> **Objectif** : Configurer le nom, la politique de redémarrage et le nettoyage automatique des conteneurs.
> **Pré-requis** : Accès au registre `ghcr.io` pour l'image `acme/api:1.4.2` (ou utiliser une image locale).

```bash
# Conteneur service : nommé, redémarrage automatique sauf si stoppé manuellement
# --name api                  : nom fixe du conteneur
# --restart=unless-stopped    : redémarre automatiquement (sauf après un "docker stop" manuel)
# -d                          : mode détaché
docker run --name api --restart=unless-stopped -d ghcr.io/acme/api:1.4.2

# Conteneur éphémère : supprimé automatiquement dès qu'il s'arrête
# --rm : auto-suppression à l'arrêt (utile pour les sessions de debug/test)
docker run --rm -it alpine sh
```

> **Résultat attendu** :
> ```
> # docker run --name api --restart=unless-stopped -d ghcr.io/acme/api:1.4.2
> d4e5f6a7b8c9...
>
> # docker run --rm -it alpine sh
> / # exit   # après avoir tapé "exit", le conteneur est automatiquement supprimé
> ```
> **Vérification** : Après `exit` du conteneur `--rm`, `docker ps -a` ne le montre plus. Le conteneur `api` a sa restart policy visible dans `docker inspect`.

### 2.3 Entrypoint / commande / répertoire / utilisateur

> **Objectif** : Personnaliser le point d'entrée, le répertoire de travail et l'utilisateur du conteneur.
> **Pré-requis** : Une image avec `/bin/mywrap` existant (exemple théorique) ou adapter avec un binaire réel.

```bash
# Remplace l'ENTRYPOINT défini dans le Dockerfile par /bin/mywrap
docker run --entrypoint /bin/mywrap    image ...

# Change le répertoire de travail interne au conteneur (comme cd avant exécution)
docker run --workdir /app              image ...

# Exécute le processus avec un UID:GID spécifique (non-root)
docker run -u 10001:10001              image ...

# Remplace le CMD défini dans le Dockerfile par "args..."
docker run image args...
```

> **Résultat attendu** :
> ```
> # docker run --workdir /app alpine pwd
> /app
> # docker run -u 10001:10001 alpine id
> uid=10001 gid=10001
> ```
> **Vérification** : `--entrypoint` remplace l'ENTRYPOINT du Dockerfile ; les arguments en fin de ligne remplacent/écrasent le CMD.

### 2.4 Variables d'environnement

> **Objectif** : Injecter des variables d'environnement dans le conteneur au démarrage.
> **Pré-requis** : Un fichier `.env` existant pour la seconde commande (format `CLE=valeur` par ligne).

```bash
# Passe des variables une par une avec -e
docker run -e APP_ENV=prod -e TZ=Europe/Paris image

# Charge toutes les variables depuis un fichier .env
docker run --env-file .env image
```

> **Résultat attendu** :
> ```
> # docker run -e APP_ENV=prod alpine env | grep APP_ENV
> APP_ENV=prod
> ```
> **Vérification** : `docker exec <conteneur> env` liste toutes les variables d'environnement injectées.

### 2.5 Réseau, ports, DNS, hosts (aperçu — détails au Chapitre Réseau)

> **Objectif** : Configurer l'exposition de ports, le réseau, le DNS et les entrées hôtes du conteneur.
> **Pré-requis** : Réseau Docker `my-net` créé (`docker network create my-net`) pour l'exemple avec `--ip`.

```bash
# Publie le port 80 du conteneur sur le port 8080 de l'hôte
docker run -p 8080:80 nginx

# Connecte le conteneur à un réseau personnalisé avec une IP fixe
# --network my-net : réseau Docker user-defined
# --ip 172.18.0.10 : adresse IP statique dans ce réseau
docker run --network my-net --ip 172.18.0.10 image

# Configure les serveurs DNS et le domaine de recherche
# --dns 1.1.1.1       : résolveur DNS (ici Cloudflare)
# --dns-search corp.local : ajoute "corp.local" comme domaine de recherche
docker run --dns 1.1.1.1 --dns-search corp.local image

# Ajoute une entrée statique dans /etc/hosts du conteneur
# Résout "db.internal" vers 10.0.0.10 sans DNS externe
docker run --add-host db.internal:10.0.0.10 image
```

> **Résultat attendu** :
> ```
> # docker run -p 8080:80 -d nginx
> e5f6a7b8c9d0...
> # curl http://localhost:8080   → page d'accueil nginx
> ```
> **Vérification** : `docker port <conteneur>` affiche les mappings ; `docker exec <conteneur> cat /etc/resolv.conf` montre les DNS ; `cat /etc/hosts` montre les `--add-host`.

> Montages (volumes/bind/tmpfs) → Chapitre **Storage**.

---

## 3) Journaux, exec, stats, top, inspect, events

### 3.1 Logs

> **Objectif** : Consulter les journaux (stdout/stderr) d'un conteneur avec différents filtres temporels et de volume.
> **Pré-requis** : Un conteneur nommé `web` en cours d'exécution produisant des logs.

```bash
# Affiche tous les logs depuis le démarrage du conteneur
docker logs web

# Suit les logs en temps réel, depuis les 10 dernières minutes, max 100 lignes
# -f            : mode "follow" (stream en continu, comme tail -f)
# --since=10m   : ne montre que les entrées des 10 dernières minutes
# --tail=100    : affiche au maximum les 100 dernières lignes
docker logs -f --since=10m --tail=100 web

# Affiche les logs avec l'horodatage de chaque ligne
docker logs --timestamps web
```

> **Résultat attendu** :
> ```
> # docker logs web
> 2026/06/21 10:00:01 [notice] nginx/1.27 ...
> 2026/06/21 10:00:01 [notice] start worker processes
>
> # docker logs -f --since=10m --tail=100 web
> 10.0.0.1 - - [21/Jun/2026:10:05:00 +0000] "GET / HTTP/1.1" 200 ...
> ^C   # Ctrl+C pour quitter le follow
>
> # docker logs --timestamps web
> 2026-06-21T10:00:01.000000000Z 2026/06/21 10:00:01 [notice] nginx/1.27 ...
> ```
> **Vérification** : Les timestamps apparaissent avec `--timestamps` ; `--tail` limite le nombre de lignes affichées.

* Paramétrage du **driver de logs** par conteneur :

> **Objectif** : Configurer la rotation des fichiers de logs pour éviter qu'ils ne remplissent le disque.
> **Pré-requis** : Aucun pré-requis spécifique ; le driver `json-file` est le driver par défaut de Docker.

```bash
# Configure le driver de log json-file avec rotation
# --log-driver=json-file          : driver par défaut (logs en JSON dans /var/lib/docker/containers/)
# --log-opt max-size=10m          : taille max d'un fichier de log avant rotation (10 Mo)
# --log-opt max-file=3            : conserve au maximum 3 fichiers de logs (rotation circulaire)
docker run --log-driver=json-file \
           --log-opt max-size=10m --log-opt max-file=3 \
           -d nginx
```

> **Résultat attendu** :
> ```
> # docker run --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 -d nginx
> f6a7b8c9d0e1...
> ```
> **Vérification** : `docker inspect -f '{{.HostConfig.LogConfig}}' <conteneur>` affiche la configuration de log. Les fichiers de log sont limités en taille sur le disque.

> Centralisation & métriques → Chapitre **Observabilité**.

### 3.2 Exec (ouvrir une session / lancer une commande)

> **Objectif** : Exécuter des commandes dans un conteneur déjà en cours d'exécution.
> **Pré-requis** : Un conteneur nommé `web` en cours d'exécution.

```bash
# Ouvre un shell interactif dans le conteneur (comme SSH)
# -i : STDIN ouvert, -t : pseudo-TTY
docker exec -it web sh

# Exécute "id" en tant qu'utilisateur spécifique (UID:GID)
# -u 10001:10001 : lance la commande avec cet utilisateur/groupe
docker exec -u 10001:10001 web id

# Exécute "ls" avec une variable d'environnement et un répertoire de travail spécifiques
# -e DEBUG=1 : injecte la variable DEBUG=1
# -w /app    : se place dans /app avant d'exécuter la commande
docker exec -e DEBUG=1 -w /app web ls
```

> **Résultat attendu** :
> ```
> # docker exec -it web sh
> / #   # shell dans le conteneur
>
> # docker exec -u 10001:10001 web id
> uid=10001 gid=10001
>
> # docker exec -e DEBUG=1 -w /app web ls
> config.yml  index.html  ...
> ```
> **Vérification** : `docker exec` ne crée PAS de nouveau conteneur ; il ajoute un processus dans le conteneur existant.

### 3.3 Stats (ressources) & top (processus)

> **Objectif** : Surveiller la consommation de ressources et les processus d'un ou tous les conteneurs.
> **Pré-requis** : Au moins un conteneur en cours d'exécution.

```bash
# Affiche en continu la consommation CPU/MEM/NET/IO de tous les conteneurs
docker stats

# Affiche un instantané des ressources pour un seul conteneur (sans suivi continu)
# --no-stream : ne montre qu'un seul écran de résultats, puis quitte
docker stats --no-stream web

# Liste les processus en cours dans le conteneur (équivalent de "ps aux" dans le conteneur)
docker top web
```

> **Résultat attendu** :
> ```
> # docker stats --no-stream web
> CONTAINER ID   NAME   CPU %   MEM USAGE / LIMIT     MEM %   NET I/O         BLOCK I/O
> b7c8d9e0f1a2   web    0.05%   25.6MiB / 512MiB      5.0%    1.2kB / 600B    0B / 0B
>
> # docker top web
> UID   PID   PPID   C   STIME   TIME   CMD
> root  1234  1200   0   10:00   0:00   nginx: master process nginx -g daemon off;
> ```
> **Vérification** : `stats` montre la consommation en temps réel ; `top` montre les processus avec leur PID hôte.

### 3.4 Inspect (métadonnées) & formatage

> **Objectif** : Extraire les métadonnées détaillées d'un conteneur au format JSON, avec filtrage Go template.
> **Pré-requis** : Un conteneur nommé `web` existant ; `jq` installé pour le formatage JSON.

```bash
# Affiche toutes les métadonnées du conteneur en JSON formaté
# | jq : pipe vers jq pour un affichage lisible (indentation, couleurs)
docker inspect web | jq

# Extrait des champs spécifiques avec le template Go de Docker
# .State.Status     : état actuel (running, exited, ...)
# .State.Health.Status : statut du healthcheck (healthy, unhealthy, ...)
docker inspect -f '{{.State.Status}} {{.State.Health.Status}}' web

# Extrait la configuration réseau des ports et formate en JSON avec jq
# .NetworkSettings.Ports : mapping des ports exposés
docker inspect -f '{{json .NetworkSettings.Ports}}' web | jq
```

> **Résultat attendu** :
> ```
> # docker inspect -f '{{.State.Status}} {{.State.Health.Status}}' web
> running healthy
>
> # docker inspect -f '{{json .NetworkSettings.Ports}}' web | jq
> {
>   "80/tcp": [
>     {
>       "HostIp": "0.0.0.0",
>       "HostPort": "8080"
>     }
>   ]
> }
> ```
> **Vérification** : Les champs extraits correspondent bien à l'état réel du conteneur. `jq` formate le JSON.

### 3.5 Events (chronologie des événements)

> **Objectif** : Observer en temps réel les événements Docker (création, arrêt, OOM, etc.) sur la machine.
> **Pré-requis** : Docker Engine en cours d'exécution.

```bash
# Affiche les événements Docker de la dernière heure
# --since 1h : ne montre que les événements survenus dans les 60 dernières minutes
# Utile pour auditer : créer, kill, oom, die, start, stop, etc.
docker events --since 1h
```

> **Résultat attendu** :
> ```
> # docker events --since 1h
> 2026-06-21T09:30:00.000000000Z container create b7c8d9e0f1a2 (image=nginx:1.27, name=web)
> 2026-06-21T09:30:01.000000000Z container start b7c8d9e0f1a2 (image=nginx:1.27, name=web)
> 2026-06-21T10:00:00.000000000Z container stop b7c8d9e0f1a2 (image=nginx:1.27, name=web)
> ```
> **Vérification** : Chaque action (create, start, stop, kill, die) génère un événement horodaté.

---

## 4) Healthchecks (runtime)

### 4.1 Définir au lancement

> **Objectif** : Configurer un healthcheck Docker pour que l'engine surveille automatiquement la santé du conteneur.
> **Pré-requis** : L'image `ghcr.io/acme/api:1.4.2` doit contenir `curl` et exposer un endpoint `/health` sur le port 8080.

```bash
# Lance un conteneur avec un healthcheck complet
docker run -d --name api \
  # Commande de vérification : curl sur /health, échoue (exit 1) si la requête échoue
  # -fsS : fail silencieux, afficher les erreurs
  --health-cmd='curl -fsS http://localhost:8080/health || exit 1' \
  # Fréquence de vérification : toutes les 30 secondes
  --health-interval=30s \
  # Délai max pour que la commande de check réponde (timeout)
  --health-timeout=5s \
  # Nombre d'échecs consécutifs avant de marquer "unhealthy"
  --health-retries=3 \
  # Période de grâce au démarrage avant de commencer les checks
  --health-start-period=20s \
  ghcr.io/acme/api:1.4.2
```

> **Résultat attendu** :
> ```
> # docker run -d --name api --health-cmd='...' ... ghcr.io/acme/api:1.4.2
> a1b2c3d4e5f6...
> # Après ~20s : statut "starting" → puis "healthy" si /health répond 200
> ```
> **Vérification** : `docker ps` affiche `(healthy)` dans la colonne STATUS après la période de démarrage.

* Statut dans `.State.Health.Status` : `starting` → `healthy` / `unhealthy`.
* Sur échec, **Docker ne redémarre pas** automatiquement (sauf si votre superviseur/policy le fait).
* **Priorité** : un healthcheck défini en ligne de commande **écrase** celui du Dockerfile.

### 4.2 Lire l'état

> **Objectif** : Consulter le statut de santé actuel d'un conteneur via `docker inspect`.
> **Pré-requis** : Un conteneur nommé `api` avec un healthcheck configuré.

```bash
# Extrait uniquement le statut de santé du conteneur
# Valeurs possibles : starting, healthy, unhealthy, null (pas de healthcheck)
docker inspect -f '{{.State.Health.Status}}' api
```

> **Résultat attendu** :
> ```
> # docker inspect -f '{{.State.Health.Status}}' api
> healthy
> ```
> **Vérification** : La valeur retournée est `healthy`, `unhealthy` ou `starting` selon l'état actuel.

---

## 5) Limites de ressources & ulimit

### 5.1 CPU & mémoire (cgroups v2)

> **Objectif** : Limiter les ressources CPU et mémoire d'un conteneur via les cgroups pour éviter qu'il ne monopolise l'hôte.
> **Pré-requis** : Docker Engine avec support cgroups v2 activé.

```bash
# Limite CPU et mémoire de manière stricte
# --cpus=1.5          : max 1.5 cœurs CPU (quota/period)
# --memory=512m       : limite de RAM à 512 Mo
# --memory-swap=1g    : limite combinée RAM+swap à 1 Go (donc 512 Mo de swap max ici)
docker run --cpus=1.5 --memory=512m --memory-swap=1g image

# Affinité CPU et poids relatif (ordonnancement)
# --cpuset-cpus="0,2"  : n'utilise que les cœurs physiques 0 et 2
# --cpu-shares=512     : poids relatif (défaut=1024) ; proportion de CPU en cas de contention
docker run --cpuset-cpus="0,2" --cpu-shares=512 image
```

> **Résultat attendu** :
> ```
> # docker run --cpus=1.5 --memory=512m --memory-swap=1g -d nginx
> b7c8d9e0f1a2...
> ```
> **Vérification** : `docker stats --no-stream <conteneur>` montre la MEM LIMIT à 512MiB et le CPU à 150%.

* `--cpus` : quota/period simplifié.
* `--memory` : limite stricte ; `--memory-swap` : mémoire + swap.
* `--cpu-shares` : poids relatif (meilleur effort).
* `--cpuset-cpus` : affinité CPU (ex: "0-3,6").

### 5.2 Limites de PIDs & ulimit

> **Objectif** : Restreindre le nombre de processus et les limites de fichiers/descripteurs pour éviter les forks bombs et l'épuisement de ressources.
> **Pré-requis** : Aucun pré-requis spécifique.

```bash
# Limite le nombre maximum de processus/PIDs dans le conteneur
# --pids-limit=256 : max 256 processus (protection contre fork bomb)
docker run --pids-limit=256 image

# Configure les ulimits (limites système par utilisateur)
# --ulimit nofile=4096:8192  : max 4096 fichiers ouverts (soft), 8192 (hard)
# --ulimit nproc=512:1024    : max 512 processus par utilisateur (soft), 1024 (hard)
docker run --ulimit nofile=4096:8192 --ulimit nproc=512:1024 image
```

> **Résultat attendu** :
> ```
> # docker run --pids-limit=256 -d nginx
> c9d0e1f2a3b4...
> ```
> **Vérification** : `docker inspect -f '{{.HostConfig.PidsLimit}}' <conteneur>` retourne `256`.

### 5.3 Mettre à jour un conteneur en cours

> **Objectif** : Modifier les limites de ressources et la politique de redémarrage d'un conteneur SANS le recréer.
> **Pré-requis** : Un conteneur nommé `api` en cours d'exécution.

```bash
# Met à jour les limites CPU, mémoire et PIDs à chaud (pas de redémarrage nécessaire)
# --cpus=2        : nouvelle limite CPU
# --memory=1g     : nouvelle limite mémoire
# --pids-limit=512 : nouvelle limite de processus
docker update --cpus=2 --memory=1g --pids-limit=512 api

# Change la politique de redémarrage d'un conteneur existant
# --restart=always : redémarrage systématique (même après "docker stop" → redémarre au reboot Docker)
docker update --restart=always api
```

> **Résultat attendu** :
> ```
> # docker update --cpus=2 --memory=1g --pids-limit=512 api
> api
> # docker update --restart=always api
> api
> ```
> **Vérification** : `docker inspect -f '{{.HostConfig.CpuQuota}} {{.HostConfig.Memory}}' api` montre les nouvelles valeurs.

---

## 6) Signaux, arrêt propre & PID1

### 6.1 Arrêt propre

* `docker stop` envoie **SIGTERM**, puis **SIGKILL** après `--time` secondes.
* Si votre process PID1 **ignore SIGTERM**, il risque d'être tué (143 = TERM, 137 = KILL).

> **Objectif** : Accorder un délai suffisant au conteneur pour se terminer proprement (fermer connexions, sauvegarder).
> **Pré-requis** : Un conteneur nommé `api` en cours d'exécution.

```bash
# Arrête le conteneur avec un délai de grâce de 30 secondes
# SIGTERM est envoyé immédiatement ; SIGKILL envoyé après 30s si le processus n'a pas quitté
docker stop -t 30 api
```

> **Résultat attendu** :
> ```
> # docker stop -t 30 api
> api
> ```
> **Vérification** : Le conteneur est arrêté. S'il a répondu à SIGTERM dans les 30s, le code de sortie est 0 (pas 137).

### 6.2 PID1 & init

* PID1 ne relaie pas toujours les signaux et ne "reap" pas les zombies.
* Utilisez un init léger :

> **Objectif** : Injecter un processus init léger (Tini) comme PID1 pour correctement relayer les signaux et nettoyer les zombies.
> **Pré-requis** : Aucun ; `--init` utilise Tini intégré à Docker.

```bash
# Active Tini comme sous-processus init (PID1 relayeur)
# Tini capture SIGTERM/SIGINT et les transmet au processus enfant
# Tini récupère aussi les processus zombies (reap)
docker run --init ... image
```

> **Résultat attendu** :
> ```
> # docker run --init -d nginx
> d0e1f2a3b4c5...
> # docker top d0e1f2a3b4c5
> UID   PID  PPID  CMD
> root  5000 4990  /sbin/docker-init -- nginx -g daemon off;
> root  5044 5000  nginx: master process nginx -g daemon off;
> ```
> **Vérification** : `docker top` montre `/sbin/docker-init` comme PID1 et votre application comme enfant.

### 6.3 Personnaliser le signal/timeout

> **Objectif** : Remplacer le signal d'arrêt par défaut (SIGTERM) et le délai de grâce par des valeurs adaptées à votre application.
> **Pré-requis** : Image configurée pour répondre au signal choisi (ex: SIGQUIT).

```bash
# --stop-signal=SIGQUIT   : envoie SIGQUIT au lieu de SIGTERM pour l'arrêt
# --stop-timeout=20       : délai de grâce de 20s avant SIGKILL
docker run --stop-signal=SIGQUIT --stop-timeout=20 image
```

> **Résultat attendu** :
> ```
> # docker run --stop-signal=SIGQUIT --stop-timeout=20 -d nginx
> e1f2a3b4c5d6...
> ```
> **Vérification** : `docker inspect -f '{{.Config.StopSignal}} {{.Config.StopTimeout}}' <conteneur>` affiche `SIGQUIT 20`.

---

## 7) Copie de fichiers & renommage

> **Objectif** : Transférer des fichiers entre l'hôte et un conteneur, et renommer un conteneur existant.
> **Pré-requis** : Un conteneur nommé `api` en cours d'exécution ; fichier `./config.yml` présent sur l'hôte.

```bash
# Copie un fichier de l'hôte VERS le conteneur
# ./config.yml (hôte) → /app/config.yml (dans le conteneur "api")
docker cp ./config.yml api:/app/config.yml

# Copie un fichier du conteneur VERS l'hôte
# /var/log/app.log (conteneur "api") → ./app.log (hôte)
docker cp api:/var/log/app.log ./app.log

# Renomme un conteneur existant
# "api" devient "api-v1" (utile pour le versioning ou la lisibilité)
docker rename api api-v1
```

> **Résultat attendu** :
> ```
> # docker cp ./config.yml api:/app/config.yml
> # (pas de sortie en cas de succès)
> # docker cp api:/var/log/app.log ./app.log
> # (pas de sortie en cas de succès)
> # docker rename api api-v1
> # (pas de sortie en cas de succès)
> ```
> **Vérification** : `docker exec api-v1 cat /app/config.yml` confirme la copie ; `docker ps` montre le nom `api-v1`.

> Pour déplacer des **données applicatives**, préférez les **volumes** (Chapitre Storage).

---

## 8) Sécurité d'exécution (rappels rapides)

*(Détails au Chapitre **Sécurité & Durcissement**)*

> **Objectif** : Appliquer les principes de base du durcissement de sécurité : non-root, lecture seule, réduction des capacités, prévention d'élévation.
> **Pré-requis** : Image configurée pour fonctionner en non-root (ou adapter les permissions).

```bash
# Exécuter en utilisateur non-root avec système de fichiers en lecture seule
# -u 10001:10001  : UID:GID non-root
# --read-only     : filesystem root en lecture seule (empêche toute écriture)
# --tmpfs /tmp    : monte /tmp en mémoire (seul endroit inscriptible, volatil)
docker run -u 10001:10001 --read-only --tmpfs /tmp image

# Réduire les privilèges : retire TOUTES les capacités Linux, puis rajoute uniquement celle nécessaire
# --cap-drop=ALL             : retire toutes les capabilities (principe du moindre privilège)
# --cap-add=NET_BIND_SERVICE : rajoute uniquement la capacité de binder sur les ports < 1024
docker run --cap-drop=ALL --cap-add=NET_BIND_SERVICE image

# Empêcher toute élévation de privilèges dans le conteneur
# --security-opt no-new-privileges:true : bloque setuid, capabilities, etc. même si le binaire les demande
docker run --security-opt no-new-privileges:true image
```

> **Résultat attendu** :
> ```
> # docker run -u 10001:10001 --read-only --tmpfs /tmp -d nginx
> f2a3b4c5d6e7...
> # docker exec f2a3b4c5d6e7 touch /test
> touch: /test: Read-only file system
> ```
> **Vérification** : Le filesystem est en lecture seule (sauf /tmp) ; `id` dans le conteneur montre UID 10001 ; les capabilities sont réduites.

> Évitez `--privileged`. Montez uniquement ce qui est nécessaire (volumes/bind précis).

---

## 9) Dépannage & diagnostics rapides

### 9.1 Classiques

> **Objectif** : Fournir une batterie de commandes de diagnostic pour investiguer un conteneur en difficulté.
> **Pré-requis** : Remplacer `nom` par le nom ou l'ID réel du conteneur à diagnostiquer.

```bash
# Liste tous les conteneurs (y compris arrêtés) pour vérifier l'état global
docker ps -a

# Suit les logs en temps réel, 200 dernières lignes (point de départ pour le debug)
docker logs -f --tail=200 nom

# Inspecte les sections clés du conteneur en JSON :
# .State          : état, code de sortie, OOM, healthcheck
# .HostConfig     : limites, restart policy, binds
# .NetworkSettings : ports, réseaux, DNS
docker inspect nom | jq '.State, .HostConfig, .NetworkSettings'

# Affiche les processus actifs dans le conteneur
docker top nom

# Instantané de la consommation de ressources (CPU, MEM, IO)
docker stats --no-stream nom

# Chronologie des événements Docker des 30 dernières minutes
docker events --since 30m
```

> **Résultat attendu** :
> ```
> # docker ps -a
> CONTAINER ID   IMAGE    STATUS                     PORTS    NAMES
> b7c8d9e0f1a2   nginx    Exited (137) 5 min ago              web
>
> # docker inspect nom | jq '.State, .HostConfig, .NetworkSettings'
> { "Status": "exited", "ExitCode": 137, "OOMKilled": false, ... }
> { "Memory": 536870912, "Cpus": 1.5, "RestartPolicy": { "Name": "unless-stopped" }, ... }
> { "Ports": { "80/tcp": [{ "HostPort": "8080" }] }, ... }
> ```
> **Vérification** : Combiner ces commandes permet d'identifier la cause : OOM, crash, problème réseau, port en conflit, etc.

### 9.2 Cas fréquents

* **Port déjà utilisé** : vérifier `docker ps`, `ss -lntp`.
* **OOMKill (137)** : voir `docker inspect -f '{{.State.OOMKilled}}'`.
* **DNS** : tester `--dns`/`--add-host`, vérifier /etc/resolv.conf du conteneur.
* **Fichier introuvable (127/126)** : vérifier `ENTRYPOINT/CMD`, droits d'exécution, `WORKDIR`.
* **Healthcheck en échec** : exécuter la même commande avec `docker exec` pour diagnostiquer.

---

## 10) Exit codes utiles

* **0** : succès.
* **125** : erreur Docker (échec `docker run` lui-même).
* **126** : commande trouvée mais **non exécutable**.
* **127** : commande **introuvable**.
* **137** : **SIGKILL** (souvent OOMKill).
* **143** : **SIGTERM** (arrêt normal via `docker stop`).

> **Objectif** : Récupérer le code de sortie d'un conteneur pour diagnostiquer la cause de son arrêt.
> **Pré-requis** : Un conteneur nommé `job` terminé (exécuté ou arrêté).

```bash
# Attend la fin du conteneur "job" et affiche son code de sortie
# docker wait : bloque jusqu'à l'arrêt et renvoie le code de sortie
# echo $?     : affiche le code de retour de la dernière commande
docker wait job && echo $?
```

> **Résultat attendu** :
> ```
> # docker wait job && echo $?
> 0
> 0
> ```
> **Vérification** : Le premier `0` est le code de sortie du conteneur (renvoyé par `docker wait`). Le second `0` est le code de retour de `echo`.

---

## 11) Bonnes pratiques (Do & Don't)

**Do**

* Utiliser `--restart=unless-stopped` ou `always` pour les services.
* Préférer `--init` si votre process PID1 ne gère pas bien les signaux.
* Fixer **des limites** (`--cpus`, `--memory`, `--pids-limit`, `--ulimit`).
* Centraliser les **logs** et configurer la **rotation**.
* Lancer en **utilisateur non-root** et lecture seule (`--read-only` + `--tmpfs`).

**Don't**

* Ne pas dépendre d'un **shell** comme PID1 si votre app peut être PID1 directement.
* Éviter `--privileged` (sauf cas exceptionnel et maîtrisé).
* Éviter de monter `-v /:/host` ou des chemins hôte sensibles.
* Ne pas ignorer un **healthcheck** rouge ; investiguer d'abord.

---

## 12) Exemples synthèse

### 12.1 Service web "prod-like" (sécurisé & limité)

> **Objectif** : Combiner toutes les bonnes pratiques en une seule commande de lancement pour un service de production.
> **Pré-requis** : Image `ghcr.io/acme/web:1.4.2` disponible ; endpoint `/health` sur le port 8080.

```bash
# Lancement d'un service web complet pour la production
docker run -d --name web \
  # Exposition du port applicatif
  -p 8080:8080 \
  # Redémarrage automatique sauf si stoppé manuellement
  --restart=unless-stopped \
  # Limites de ressources : 1 CPU, 512 Mo RAM, max 256 processus
  --cpus=1.0 --memory=512m --pids-limit=256 \
  # Sécurité : filesystem en lecture seule + tmpfs pour les répertoires nécessitant l'écriture
  --read-only --tmpfs /tmp --tmpfs /run \
  # Exécution en tant qu'utilisateur non-root (UID:GID 10001)
  -u 10001:10001 \
  # Healthcheck : vérifie /health toutes les 30s, timeout 5s, 3 essais avant unhealthy
  --health-cmd='curl -fsS http://localhost:8080/health || exit 1' \
  --health-interval=30s --health-timeout=5s --health-retries=3 \
  ghcr.io/acme/web:1.4.2
```

> **Résultat attendu** :
> ```
> # docker run -d --name web ... ghcr.io/acme/web:1.4.2
> a3b4c5d6e7f8...
> # docker ps
> CONTAINER ID   IMAGE                  STATUS                   PORTS                      NAMES
> a3b4c5d6e7f8   ghcr.io/acme/web:1.4.2 Up 1 minute (healthy)    0.0.0.0:8080->8080/tcp     web
> ```
> **Vérification** : `docker ps` montre `(healthy)` ; `docker inspect` confirme les limites, le non-root et le read-only.

### 12.2 Conteneur de debug éphémère

> **Objectif** : Lancer un conteneur temporaire sur un réseau spécifique pour déboguer, auto-supprimé à la sortie.
> **Pré-requis** : Réseau Docker `app-net` existant (`docker network create app-net`).

```bash
# Conteneur de debug : interactif, éphémère, connecté au réseau applicatif
# --rm              : auto-suppression à la sortie
# -it               : mode interactif avec TTY
# --network app-net : connecté au réseau "app-net" (peut joindre les autres conteneurs de ce réseau)
# --entrypoint sh   : remplace l'entrypoint par un shell (pour naviguer librement)
docker run --rm -it --network app-net --entrypoint sh alpine:3.20
```

> **Résultat attendu** :
> ```
> # docker run --rm -it --network app-net --entrypoint sh alpine:3.20
> / # ping api
> PING api (172.18.0.5): 56 data bytes
> 64 bytes from 172.18.0.5: seq=0 ttl=64 time=0.042 ms
> / # exit
> # Le conteneur est automatiquement supprimé après "exit"
> ```
> **Vérification** : Après `exit`, `docker ps -a` ne montre plus le conteneur debug.

### 12.3 Ajuster à chaud une limite

> **Objectif** : Modifier les limites de ressources d'un conteneur en production sans interruption de service.
> **Pré-requis** : Un conteneur nommé `web` en cours d'exécution.

```bash
# Augmente la mémoire à 768 Mo et le CPU à 1.5 cœurs, à chaud
# Pas de redémarrage du conteneur nécessaire
docker update --memory=768m --cpus=1.5 web
```

> **Résultat attendu** :
> ```
> # docker update --memory=768m --cpus=1.5 web
> web
> ```
> **Vérification** : `docker stats --no-stream web` confirme les nouvelles limites (MEM LIMIT = 768MiB, CPU = 150%).

---

## 13) Aide-mémoire (cheat-sheet minimal)

> **Objectif** : Récapitulatif rapide des commandes les plus utilisées pour la gestion quotidienne des conteneurs.
> **Pré-requis** : Remplacer `NAME` par le nom ou l'ID réel du conteneur.

```bash
# === Lister / filtrer ===
# Affiche tous les conteneurs (y compris arrêtés)
docker ps -a
# Filtre uniquement les conteneurs arrêtés
docker ps --filter "status=exited"

# === Démarrer / arrêter / supprimer ===
# Démarre un conteneur existant
docker start NAME
# Arrête avec 20s de délai de grâce
docker stop -t 20 NAME
# Force l'arrêt et la suppression
docker rm -f NAME

# === Logs / Exec ===
# Suit les logs (200 dernières lignes + follow)
docker logs -f --tail=200 NAME
# Ouvre un shell interactif dans le conteneur
docker exec -it NAME sh

# === Ressources / Process / État ===
# Instantané de la consommation de ressources
docker stats --no-stream NAME
# Liste les processus du conteneur
docker top NAME
# Affiche toutes les métadonnées JSON du conteneur
docker inspect NAME

# === Health ===
# Consulte le statut du healthcheck
docker inspect -f '{{.State.Health.Status}}' NAME

# === Update / Restart policy ===
# Modifie les limites CPU et mémoire à chaud
docker update --cpus=2 --memory=1g NAME
# Change la politique de redémarrage
docker update --restart=always NAME
```

> **Résultat attendu** :
> ```
> # docker ps -a
> CONTAINER ID   IMAGE    STATUS                     PORTS    NAMES
> b7c8d9e0f1a2   nginx    Up 5 minutes                        web
> c3d4e5f6a7b8   alpine   Exited (0) 10 minutes ago           debug
>
> # docker inspect -f '{{.State.Health.Status}}' web
> healthy
> ```
> **Vérification** : Chaque commande produit le résultat décrit dans les sections précédentes du chapitre.

---

## 14) Checklist de clôture (qualité d'exécution d'un service)

* Politique `--restart` définie et adaptée au rôle du service.
* **Healthcheck** pertinent ; état **healthy** observé.
* **Limites** cgroups définies (CPU/MEM/PIDs/ulimit).
* Journaux lisibles et **rotation** configurée.
* **Arrêt propre** testé (`stop -t` suffisant ; pas de KILL systématique).
* **Utilisateur non-root**, système de fichiers **read-only** + `tmpfs` nécessaires.
* Commandes de dépannage documentées (logs/exec/inspect/stats/top/events).
