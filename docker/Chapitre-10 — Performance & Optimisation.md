# Chapitre-10 — Performance & Optimisation

## Objectifs d'apprentissage

* Mesurer avant d'optimiser : identifier les **goulets d'étranglement** (CPU, mémoire, I/O, réseau, démarrage).
* Réduire **taille** et **temps de build/pull** des images (couches, BuildKit, caches, registry).
* Améliorer les **temps de démarrage** (cold/warm start) et le **runtime** (cgroups, CPU pinning, NUMA, logs).
* Optimiser le **stockage** (overlay2 vs volumes), le **réseau** (MTU, NAT), et les **bind mounts** (WSL2/Windows).
* Mettre en place une **méthodologie** reproductible (benchmarks, budgets de perf, checklists CI/CD).

## Pré-requis

* Chap. 01–09 maîtrisés (images, conteneurs, storage, réseau, build, compose, sécurité, observabilité).
* Linux/WSL2 conseillé pour les mesures fines.

---

## 1) Mesurer d'abord (profilage rapide et budgets)

### 1.1 Indicateurs de base (par conteneur)

> **Objectif** : Collecter en une passe les métriques vitales d'un conteneur — CPU, mémoire, réseau, I/O, date de démarrage, événements récents et logs applicatifs — pour établir un état des lieux avant optimisation.
> **Pre-requis** : Un conteneur nommé `NAME` doit être en cours d'exécution (`docker run` ou `docker compose up`).

```bash
# Affiche un instantané des ressources consommées (CPU %, MEM usage/limit, NET I/O, BLOCK I/O)
# --no-stream : une seule ligne au lieu du flux continu
docker stats --no-stream NAME

# Récupère la date/heure exacte de démarrage du conteneur au format ISO 8601
# Utile pour calculer l'uptime et le temps de cold start
docker inspect -f '{{.State.StartedAt}}' NAME

# Filtre les événements Docker de la dernière heure pour ce conteneur
# Permet de détecter redémarrages, OOM kills, échecs de healthcheck
docker events --since=1h | grep NAME

# Affiche les 200 dernières lignes de logs en suivi continu
# Sert à repérer latences applicatives, erreurs, timeouts
docker logs -f --tail=200 NAME
```

> **Résultat attendu** :
> ```
> CONTAINER ID   NAME   CPU %   MEM USAGE / LIMIT   MEM %   NET I/O         BLOCK I/O
> abc123def456   NAME   12.34%  256MiB / 512MiB     50.00%  1.2kB / 800B    0B / 0B
> 2026-06-21T08:15:32.123456789Z
> 2026-06-21T09:00:12.000000000Z container abc123 health_status: healthy
> 2026-06-21T09:01:00.000000000Z 200 GET /api/health 12ms
> ```
> **Vérification** : S'assurer que MEM % est stable (pas de fuite), CPU % cohérent avec la charge, aucun OOM ou restart dans les événements, et des temps de réponse applicatifs < SLO.

### 1.2 Benchmarks synthétiques

* **Démarrage** : mesurer T0→Tready (port ouvert + healthcheck **OK**).
* **Throughput** : `wrk`, `ab`, `hey` sur endpoint critique.
* **Réseau** : `iperf3`, `curl -w`, `dig +trace` pour DNS.
* **I/O** : `fio` (sur volume), `dd` (indicatif), `iostat/iotop` côté hôte.

### 1.3 Budgets & objectifs

* Taille d'image **max** (ex. ≤ 150 MB runtime).
* Cold start **Tready** (ex. ≤ 2 s web, ≤ 10 s JVM/CDS).
* P95 latence & erreurs < SLO (suivi Grafana).
* Pull time (Région/proxy cache) ≤ X s.

---

## 2) Optimiser la **taille** d'image (build-time)

### 2.1 Multi-stage obligatoire

* **Builder → Runtime** : ne copier que l'artefact final.
* Bases **minimales** : `alpine`, `debian-slim`, **distroless** pour bins statiques.

### 2.2 Ordre des couches & cache

* Copier d'abord fichiers **stables** (ex. `package*.json`, `go.mod`) pour maximiser le cache.
* Grouper les `RUN` et nettoyer **dans la même couche** :

> **Objectif** : Installer des paquets système et nettoyer les caches APT **dans une seule couche** pour que les fichiers supprimés (`/var/lib/apt/lists/*`) ne persistent pas dans le layer final — réduisant la taille de l'image.
> **Pre-requis** : Image de base Debian/Ubuntu (`FROM debian:bookworm-slim` ou similaire).

```dockerfile
# apt-get update + install + nettoyage en une seule couche (&&)
# rm -rf /var/lib/apt/lists/* supprime les index APT téléchargés
# Sans ce nettoyage, ~30-80 MB restent dans la couche inutilement
RUN apt-get update && apt-get install -y curl \
 && rm -rf /var/lib/apt/lists/*
```

> **Résultat attendu** :
> ```
> Step 3/5 : RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
>  ---> abc123def456
> Successfully built abc123def456
> ```
> **Vérification** : Comparer la taille de l'image avec et sans `rm -rf` : `docker images NOM` — l'écart doit être de 30 à 80 MB. Vérifier aussi avec `docker history NOM` que la couche est bien consolidée.

### 2.3 Dépôts & dépendances

* **Pinning** versions ; `npm ci` / `pip install --no-cache-dir` / `mvn -B -DskipTests`.
* Pour Go : `-ldflags="-s -w"` + `strip` pour binaire compact.

### 2.4 Choix de base (compat vs taille)

* `alpine` (musl) : petite, parfois moins perf/compat que glibc.
* `debian:bookworm-slim` : plus lourde, meilleure compatibilité.
* **distroless** : surface minimale (pas de shell) + très rapide au démarrage pour bins statiques.

---

## 3) BuildKit & caches (vitesse de build)

### 3.1 Activer BuildKit

> **Objectif** : Activer BuildKit, le moteur de build moderne de Docker, qui permet le cache mount, le parallélisme des étapes, et des builds plus rapides et plus sûrs.
> **Pre-requis** : Docker 18.09+ installé. BuildKit est activé par défaut depuis Docker 23.0.

```bash
# Active BuildKit via variable d'environnement pour la session courante
export DOCKER_BUILDKIT=1
# Alternative permanente : ajouter dans /etc/docker/daemon.json :
# { "features": { "buildkit": true } }
# Puis redémarrer le daemon : sudo systemctl restart docker
```

> **Résultat attendu** :
> ```
# Aucun affichage direct ; les builds suivants afficheront le format BuildKit :
# [+] Building 2.3s (8/8) FINISHED
#  => [internal] load build definition from Dockerfile
#  => [internal] load .dockerignore
#  => ...
> ```
> **Vérification** : Lancer `docker build .` — si l'affichage montre `[internal] load` et des étapes en parallèle, BuildKit est actif (vs l'ancien affichage `Step 1/10 : ...`).

### 3.2 Caches persistants

> **Objectif** : Monter des répertoires de cache (npm, apt) en tant que volumes temporaires pendant le build pour réutiliser les dépendances téléchargées entre deux builds, sans les inclure dans l'image finale.
> **Pre-requis** : BuildKit activé (section 3.1). Syntaxe `--mount=type=cache` disponible uniquement avec BuildKit.

```dockerfile
# Monte le cache npm (~/.npm) entre les builds : npm ci réutilise les paquets déjà téléchargés
# Le cache persiste sur le hôte, mais n'entre PAS dans l'image finale
RUN --mount=type=cache,target=/root/.npm npm ci

# Monte le cache APT (/var/cache/apt) pour éviter de re-télécharger les .deb
# Combiné avec apt-get update dans la même couche
RUN --mount=type=cache,target=/var/cache/apt apt-get update && ...
```

> **Résultat attendu** :
> ```
# Premier build :
#  => [3/5] RUN --mount=type=cache,target=/root/.npm npm ci
#  => npm ci a téléchargé ~500 paquets (30s)
#
# Deuxième build (après modif du code, mêmes dépendances) :
#  => [3/5] RUN --mount=type=cache,target=/root/.npm npm ci
#  => npm ci a réutilisé le cache (2s)
> ```
> **Vérification** : Mesurer le temps de build avant/après. Le deuxième build doit être nettement plus rapide si les dépendances n'ont pas changé. Confirmer avec `docker system df` que le cache BuildKit existe.

### 3.3 Caches distants (CI/CD)

> **Objectif** : Partager le cache de build entre plusieurs machines CI/CD via un registre Docker distant, pour que chaque build profite du travail des builds précédents même sur des runners différents.
> **Pre-requis** : Accès en écriture à un registre (ghcr.io, Docker Hub, etc.). `docker buildx` configuré avec un builder supportant le cache registry.

```bash
# Construit l'image en exportant ET important le cache depuis le registre
docker buildx build \
  # Exporte TOUTES les couches vers le registre (mode=max) pour un cache complet
  --cache-to=type=registry,ref=ghcr.io/acme/cache:web,mode=max \
  # Importe le cache existant depuis le registre (couches réutilisées si inchangées)
  --cache-from=type=registry,ref=ghcr.io/acme/cache:web \
  # Tag de l'image finale
  -t ghcr.io/acme/web:1.4.3 .
```

> **Résultat attendu** :
> ```
# [+] Building 45.2s (12/12) FINISHED
#  => [internal] importing cache manifest from ghcr.io/acme/cache:web
#  => [internal] exporting cache to ghcr.io/acme/cache:web
#  => => => writing layer sha256:abc123...
#  => exporting to image
#  => => naming to ghcr.io/acme/web:1.4.3
> ```
> **Vérification** : Vérifier que l'image `ghcr.io/acme/cache:web` existe dans le registre. Au build suivant, observer la ligne `importing cache manifest` et un temps de build réduit.

### 3.4 Contexte de build minimal

* `.dockerignore` strict (éviter `.git`, artefacts lourds, secrets).
* `build --pull` pour ne pas traîner une base obsolète (sécurité + perf de diff).

---

## 4) Registry & distribution (vitesse de pull/push)

* **Proxy cache** local (Chap. 07) pour Docker Hub → réduit **latence** et **rate-limit**.
* **CDN/registres proches** de l'hôte (région).
* **Manifest list** multi-arch = un seul nom, tirage **arch** adaptée (pas d'échec QEMU).
* Si supporté par votre registry : couches **OCI + zstd** (réduction taille/temps). *Vérifier compatibilité avant d'activer.*

---

## 5) Démarrage rapide (cold/warm start)

### 5.1 Général

* **Images légères**, moins de couches, **ENTRYPOINT exec** (pas de shell).
* Préparer **répertoires en écriture** (tmpfs/volumes) et activer **read_only** si possible pour accélérer checks.
* **Healthcheck** rapide (HTTP local, délai court).

### 5.2 Langage/Runtime (exemples)

* **Go** : binaire statique → démarrage ~instantané.
* **Node.js** : `npm ci --omit=dev`, éviter transpile à l'exécution, pré-build.
* **Python** : pré-compiler (`python -m compileall`) ; serveurs **uvicorn+uvloop** ; `--workers` calibrés.
* **Java** : réduire classpath ; CDS (Class Data Sharing) / AppCDS ; JIT warmup à l'amorçage si besoin ; heap initial adapté (`-Xms`).
* **.NET** : trimming + ReadyToRun (AOT partiel).

---

## 6) Runtime CPU : quotas, pinning, NUMA

### 6.1 Quotas & poids (cgroups v2)

> **Objectif** : Limiter et pondérer l'utilisation CPU d'un conteneur via cgroups v2 — quota dur (`--cpus`) et poids relatif (`--cpu-shares`) pour arbitrer entre conteneurs en cas de contention.
> **Pre-requis** : Docker avec support cgroups v2 (Linux 5.8+). Le conteneur doit exister ou être lancé.

```bash
# --cpus=2.0       : quota CFS = 2 CPU max (limite dure, throttle au-delà)
# --cpu-shares=512 : poids relatif (défaut=1024). En cas de contention,
#                    ce conteneur obtient ~50% du CPU par rapport à un conteneur à 1024
docker run --cpus=2.0 --cpu-shares=512 IMAGE
```

> **Résultat attendu** :
> ```
# Le conteneur démarre normalement
# docker stats affiche :
# CONTAINER ID   NAME     CPU %   MEM USAGE
# abc123         eager    0.05%   64MiB / 512MiB
#
# Sous charge, CPU % plafonne à ~200% (= 2 cores)
# En cas de contention avec un autre conteneur, le ratio 512:1024 s'applique
> ```
> **Vérification** : `docker inspect NAME --format '{{.HostConfig.NanoCpus}} {{.HostConfig.CpuShares}}'` doit afficher `2000000000 512`. Sous charge, `docker stats` montre le CPU plafonné.

### 6.2 Affinité CPU (réduction de migrations)

> **Objectif** : Épingler le conteneur à des cores CPU spécifiques pour éviter les migrations de contexte inter-CPU, réduisant la latence et améliorant la prédictibilité des performances.
> **Pre-requis** : Connaître la topologie CPU de l'hôte (`lscpu`, `htop`). Les cores indiqués doivent exister.

```bash
# --cpuset-cpus="0-3,6" : le conteneur ne s'exécute QUE sur les cores 0, 1, 2, 3 et 6
# Réduit les migrations inter-core → meilleur cache L1/L2, latence prédictible
docker run --cpuset-cpus="0-3,6" IMAGE
```

> **Résultat attendu** :
> ```
# Le conteneur démarre. Sous charge :
# htop (filtré par container) montre de l'activité uniquement sur CPU 0-3 et 6
# Les autres cores restent inactifs pour ce conteneur
> ```
> **Vérification** : `docker inspect NAME --format '{{.HostConfig.CpusetCpus}}'` → `0-3,6`. Sous charge, `htop` ou `pidstat -t` confirme l'activité uniquement sur les cores épinglés.

### 6.3 NUMA (mémoire locale aux CPU)

> **Objectif** : Aligner l'allocation mémoire et les cores CPU sur le même nœud NUMA pour éviter les accès mémoire distant (cross-socket), réduisant la latence mémoire de ~30-50% sur serveurs bi-socket.
> **Pre-requis** : Serveur multi-socket avec NUMA activé (`numactl --hardware`). Connaître la correspondance cores ↔ nœuds NUMA.

```bash
# --cpuset-mems="0"    : alloue la mémoire uniquement depuis le nœud NUMA 0
# --cpuset-cpus="0-7"  : épingle sur les cores 0 à 7 (qui appartiennent au nœud NUMA 0)
# Les deux doivent être cohérents : cores et mémoire du même nœud
docker run --cpuset-mems="0" --cpuset-cpus="0-7" IMAGE
```

> **Résultat attendu** :
> ```
# Le conteneur démarre avec mémoire et CPU sur le même nœud NUMA 0
# numactl --show (depuis le conteneur si numactl est installé) :
# policy: default
# preferred node: 0
# physcpubind: 0 1 2 3 4 5 6 7
# membind: 0
> ```
> **Vérification** : `numastat -p <PID>` montre >95% des allocations sur le nœud 0. Comparer la latence (bench) avec/sans pinning NUMA.

* Utile sur serveurs bi-socket. **Mesurer** avant/après (latence).

---

## 7) Runtime Mémoire : limites & OOM

### 7.1 Limites & réservations

> **Objectif** : Définir un plafond mémoire dur, une limite swap, et une réservation souple pour éviter les OOMKill tout en garantissant un minimum de mémoire au conteneur et en permettant des pics temporaires.
> **Pre-requis** : Docker avec cgroups v1 ou v2. Connaître les besoins mémoire de l'application.

```bash
# --memory=1g              : plafond mémoire RAM = 1 Go (limite dure)
# --memory-swap=2g         : mémoire + swap combinés = 2 Go (donc 1 Go de swap max)
# --memory-reservation=512m : limite souple — Docker tente de garder ≥ 512 Mo dispo
#                            En cas de contention, ce conteneur sera réduit en premier
docker run --memory=1g --memory-swap=2g --memory-reservation=512m IMAGE
```

> **Résultat attendu** :
> ```
# Le conteneur démarre normalement
# docker stats affiche :
# CONTAINER ID   NAME    MEM USAGE / LIMIT   MEM %
# abc123         eager   384MiB / 1GiB       37.5%
#
# Si l'app tente d'allouer > 1 Go → OOMKill (exit code 137)
# Entre 512 Mo et 1 Go : fonctionne mais peut être throttled sous contention hôte
> ```
> **Vérification** : `docker inspect NAME --format '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{.HostConfig.MemoryReservation}}'` → `1073741824 2147483648 536870912`. `docker inspect NAME --format '{{.State.OOMKilled}}'` → `false` en fonctionnement normal.

### 7.2 File descriptors & PIDs

> **Objectif** : Augmenter la limite de descripteurs de fichiers (sockets, fichiers ouverts) et limiter le nombre de PIDs pour éviter l'épuisement de FD sous haute charge tout en empêchant les forks incontrôlés.
> **Pre-requis** : L'hôte doit supporter la limite demandée (`ulimit -n` côté hôte ≥ valeur souhaitée).

```bash
# --ulimit nofile=65535:65535 : soft et hard limit de FD ouverts à 65535
#                              (défaut Docker = 1024, insuffisant pour serveurs web/DB)
# --pids-limit=512            : max 512 processus/thread dans le conteneur
#                              Empêche les fork bombs et fuites de processus
docker run --ulimit nofile=65535:65535 --pids-limit=512 IMAGE
```

> **Résultat attendu** :
> ```
# Le conteneur démarre
# Depuis le conteneur : ulimit -n → 65535
# Si l'app tente de créer > 512 PIDs : erreur "resource temporarily unavailable"
> ```
> **Vérification** : `docker inspect NAME --format '{{.HostConfig.Ulimits}}'` affiche `[{nofile 65535 65535}]`. `docker inspect NAME --format '{{.HostConfig.PidsLimit}}'` → `512`. Sous charge, `lsof -p <PID> | wc -l` reste < 65535.

---

## 8) Stockage & I/O (overlay2 vs volumes)

### 8.1 overlay2 (copy-on-write)

* **Écrire lourdement** dans le layer overlay = **lent** (COW).
  → Monter les répertoires **écrits** sur **volumes** (ext4/xfs) :

> **Objectif** : Monter un volume nommé pour les données écrites par l'application, contournant la pénalité copy-on-write du filesystem overlay2 de Docker — les écritures vont directement sur le filesystem hôte (ext4/xfs).
> **Pre-requis** : Le volume Docker `data` doit exister ou sera créé automatiquement au premier `docker run -v`.

```bash
# -v data:/var/lib/app : monte le volume nommé "data" sur /var/lib/app dans le conteneur
# Les écritures vont directement sur le disque hôte (pas de COW overlay)
# Le volume persiste entre les redémarrages du conteneur
docker run -v data:/var/lib/app ...
```

> **Résultat attendu** :
> ```
# Le conteneur démarre avec le volume monté
# docker inspect NAME --format '{{json .Mounts}}' :
# [{"Type":"volume","Name":"data","Source":"/var/lib/docker/volumes/data/_data","Destination":"/var/lib/app",...}]
#
# Les écritures dans /var/lib/app sont visibles dans /var/lib/docker/volumes/data/_data/
> ```
> **Vérification** : `docker volume ls` montre le volume `data`. `docker volume inspect data` affiche le mountpoint hôte. Écrire un fichier dans le conteneur (`touch /var/lib/app/test.txt`) et vérifier sa présence côté hôte.

### 8.2 Volumes sur disques rapides

* Placer `/var/lib/docker` (ou `data-root`) sur SSD/NVMe.
* Éviter NFS/SMB pour DBs critiques (latence). Si NFS requis : `nfsvers=4.1`, rsize/wsize adaptés.

### 8.3 Logs & rotation (I/O)

* `json-file` avec `max-size/max-file` pour réduire I/O disque (Chap. 09).
* Driver `local` (compaction) peut réduire footprint.

---

## 9) Réseau & latence

### 9.1 MTU & hairpin

* Adapter MTU des bridges si VLAN/PPPoE → éviter fragmentation.
* Tester l'accès **depuis un conteneur** à un service exposé via l'hôte (hairpin NAT).

### 9.2 Publication de ports

* Lier sur IP **spécifique** (`127.0.0.1:PORT`) si local uniquement (évite parcours réseau inutile).
* Pour **très** haut débit/latence minimale : `--network host` (à évaluer **sécurité**), sinon macvlan.

### 9.3 DNS

* Serveur DNS **proche** et fiable ; éviter timeouts → forte incidence perf.

---

## 10) Bind mounts & WSL2 (Windows 10)

* Sous Windows, les bind mounts **depuis NTFS** sont plus lents.
* **WSL2** : placez le projet **dans le FS Linux** (ex. `/home/…`), pas sous `\\wsl$` ni `C:\…` monté → gros gain I/O.
* Préférez **volumes nommés** pour caches/données ; limitez les binds aux **configs** RO.

---

## 11) Journaux & observabilité : coût minimal

* Logs **structurés** mais **pas verbeux** en prod (`info`), **debug** activé **temporairement**.
* **Échantillonnage** des traces (OTEL) à 1–10 % si trafic élevé.
* Export via **Fluent Bit** (léger) plutôt que stacks lourdes co-localisées.

---

## 12) Parallelisme & scale

* Préférer **horizontal scaling** (plusieurs réplicas) à un seul conteneur géant.
* **Load balancer** (Nginx/HAProxy/Traefik) en frontal ; stratégies **keep-alive** et **timeouts** adaptés.
* **Workers** app (gunicorn, node cluster) calibrés = `nb_cores × (1..2)` (mesurer).

---

## 13) Méthodologie d'optimisation (boucle)

1. **Mesurer** (baseline) → 2) **Formuler une hypothèse** →
2. **Modifier un seul paramètre** → 4) **Re-mesurer** →
3. **Valider/Revenir** → 6) **Documenter** (valeurs, gains, risques).

---

## 14) Exemples "prod-like" optimisés

### 14.1 Service web durci & performant

> **Objectif** : Lancer un service web en mode production avec toutes les optimisations cumulées — limites CPU/mémoire strictes, filesystem read-only, tmpfs pour les répertoires volatils, volume pour les données, logs rotés, et référence par digest pour l'immutabilité.
> **Pre-requis** : Image `ghcr.io/acme/web` poussée et signée. Volume `data_web` créé (`docker volume create data_web`). Ressources hôte suffisantes (≥ 2 cores, ≥ 1 Go RAM libre).

```bash
# Lance le conteneur en mode détaché avec un nom fixe
docker run -d --name web \
  # Publie le port 8080 du conteneur sur 8080 de l'hôte
  -p 8080:8080 \
  # CPU : quota de 1.5 core, poids relatif 512 (moitié d'un conteneur standard)
  # Épinglé sur les cores 0, 1 et 2 pour la prédictibilité
  --cpus=1.5 --cpu-shares=512 --cpuset-cpus="0-2" \
  # Mémoire : 512 Mo RAM max, 1 Go total (RAM+swap), soft limit à 256 Mo
  --memory=512m --memory-swap=1g --memory-reservation=256m \
  # FD : 65535 fichiers ouverts max, max 512 processus dans le conteneur
  --ulimit nofile=65535:65535 --pids-limit=512 \
  # Sécurité : FS read-only, tmpfs pour /tmp et /run (seuls répertoires inscriptibles)
  --read-only --tmpfs /tmp --tmpfs /run \
  # Volume nommé pour les données applicatives (écritures hors overlay)
  -v data_web:/var/lib/app \
  # Logs : driver json-file avec rotation (max 10 Mo × 3 fichiers = 30 Mo max disque)
  --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 \
  # Image référencée par digest SHA256 (immutabilité, pas de surprise au pull)
  ghcr.io/acme/web@sha256:<digest>
```

> **Résultat attendu** :
> ```
# abc123def456... (ID du conteneur)
#
# docker stats --no-stream web :
# CONTAINER ID   NAME   CPU %   MEM USAGE / LIMIT   MEM %
# abc123def456   web    0.12%   128MiB / 512MiB     25.0%
#
# docker inspect web --format '{{.HostConfig.ReadonlyRootfs}}' → true
# docker inspect web --format '{{.HostConfig.LogConfig.Type}}' → json-file
> ```
> **Vérification** : `curl http://localhost:8080/health` répond 200. `docker exec web touch /test` échoue avec "Read-only file system". `docker logs web` affiche des logs structurés. `docker inspect web` confirme toutes les limites.

### 14.2 Compose avec réseaux séparés & caches de build

> **Objectif** : Définir un stack Docker Compose avec un service API buildé avec caches BuildKit distants, un reverse proxy Nginx, des réseaux isolés (frontend/backend) pour la sécurité, et des options runtime performantes (read-only, tmpfs, ulimits).
> **Pre-requis** : Docker Compose v2+. Un `Dockerfile` multi-stage avec une cible `runtime`. Accès au registre `ghcr.io` pour les caches.

```yaml
services:
  # Service API — application backend construite depuis le Dockerfile
  api:
    build:
      context: .              # Répertoire de contexte de build (courant)
      dockerfile: Dockerfile  # Fichier Dockerfile à utiliser
      target: runtime         # Cible multi-stage : uniquement l'étape "runtime" (pas le builder)
      # Cache distant : importe les couches depuis le registre (réutilise si inchangées)
      cache_from: [ "type=registry,ref=ghcr.io/acme/cache:api" ]
      # Cache distant : exporte TOUTES les couches (mode=max) vers le registre
      cache_to:   [ "type=registry,ref=ghcr.io/acme/cache:api,mode=max" ]
    deploy: {}            # ignoré par Compose, cf. Chap. 06
    read_only: true       # Filesystem root en lecture seule (sécurité + prédictibilité)
    tmpfs: [ /run, /tmp ] # Seuls /run et /tmp sont inscriptibles (en RAM, perdus au restart)
    ulimits:
      nofile: 65535       # 65535 descripteurs de fichiers ouverts (sockets, fichiers)
    networks: [ frontend, backend ]  # API accessible depuis frontend ET backend
  # Service web — reverse proxy Nginx, seule porte d'entrée exposée
  web:
    image: nginx:1.27     # Image Nginx officielle, version pinée
    ports: [ "80:80" ]    # Expose le port 80 de l'hôte → port 80 du conteneur
    networks: [ frontend ] # Nginx uniquement sur le réseau frontend (pas d'accès direct au backend)
# Définition des réseaux isolés
networks:
  frontend: { driver: bridge }                  # Réseau externe : web ↔ api
  backend:  { driver: bridge, internal: true }  # Réseau interne : api ↔ DB (pas d'accès internet)
```

> **Résultat attendu** :
> ```
# [+] Running 3/3
#  ✓ Network chapitre14_frontend   Created
#  ✓ Network chapitre14_backend    Created
#  ✓ Container chapitre14-web-1    Started
#  ✓ Container chapitre14-api-1    Started
#
# docker compose ps :
# NAME                SERVICE   STATUS    PORTS
# chapitre14-api-1    api       running   8080/tcp
# chapitre14-web-1    web       running   0.0.0.0:80->80/tcp
> ```
> **Vérification** : `curl http://localhost:80` répond via Nginx → API. `docker exec chapitre14-api-1 touch /test` échoue (read-only). `docker network inspect chapitre14_backend` montre `internal: true`. Le build API réutilise le cache registry si disponible.

---

## 15) Dépannage perf — cas fréquents & remèdes

* **CPU throttling** (latence en dents de scie) → réduire `--cpus` ? non : **augmenter** ou **retirer** le quota ; utiliser `--cpu-shares` pour priorité relative.
* **OOMKill (137)** → augmenter `--memory`, abaisser caches applicatifs, vérifier **fuites**.
* **I/O lents** → éviter overlay pour données, basculer sur **volumes**, déplacer `/var/lib/docker` sur SSD/NVMe.
* **Pull très long** → proxy cache, image trop grosse (multi-stage, distroless), réseau/MTU.
* **Cold start long** → pré-build (AOT, artefacts), healthcheck rapide, réduire init (migrations DB en **job séparé**).
* **DNS intermittents** → `--dns` stable, éviter résolveurs distants, TTL.

---

## 16) Aide-mémoire (commandes clés)

> **Objectif** : Regrouper les commandes essentielles de diagnostic et d'ajustement performance en un seul bloc de référence rapide, couvrant mesure, limites CPU/MEM, filesystem, réseau et BuildKit.
> **Pre-requis** : Docker installé et en cours d'exécution. Les commandes `sudo` nécessitent les droits root. Un conteneur `NAME` ou `IMAGE` doit être disponible selon la commande.

```bash
# === MESURE ===
# Instantané des ressources (CPU, MEM, NET, BLOCK I/O) sans flux continu
docker stats --no-stream NAME

# Mesure le temps de démarrage brut d'un conteneur (overhead Docker pur)
# "true" = le conteneur démarre et s'arrête immédiatement → on mesure uniquement le overhead
time docker run --rm IMAGE true

# Liste les événements Docker des 10 dernières minutes (restarts, OOM, health)
docker events --since 10m | grep NAME

# === CPU/MEM LIMITES ===
# Modifie à chaud les limites CPU et mémoire d'un conteneur en cours d'exécution
# Pas besoin de recréer le conteneur — s'applique immédiatement via cgroups
docker update --cpus=2 --memory=1g NAME

# === FS & DISQUE ===
# Affiche l'espace disque utilisé par les images, conteneurs et volumes Docker
docker system df

# Affiche la taille de chaque sous-répertoire de /var/lib/docker (exclut les cross-fs)
# -x = même filesystem, -h = lisible, -d1 = profondeur 1
sudo du -xhd1 /var/lib/docker/

# Affiche l'espace disque de tous les filesystems montés (hôte)
df -h

# === RÉSEAU ===
# Liste les ports publiés d'un conteneur et leur mapping hôte
docker port NAME

# Lance un conteneur de diagnostic réseau (netshoot) connecté au réseau NET
# Contient : curl, dig, ping, tcpdump, iperf3, nc, etc.
docker run --rm -it --network NET nicolaka/netshoot

# === BUILDKIT ===
# Build avec cache distant (import + export) pour CI/CD
# Remplacer "..." par les références registry appropriées
docker buildx build --cache-from=type=registry,ref=... --cache-to=type=registry,ref=...,mode=max -t IMG .
```

> **Résultat attendu** :
> ```
# docker stats --no-stream web :
# CONTAINER ID   NAME   CPU %   MEM USAGE / LIMIT   NET I/O
# abc123         web    1.23%   256MiB / 512MiB     1.2kB / 800B
#
# time docker run --rm alpine true :
# real 0m0.456s  user 0m0.012s  sys 0m0.008s
#
# docker system df :
# TYPE       TOTAL   ACTIVE   SIZE      RECLAIMABLE
# Images     12      3        2.5GB     1.8GB (72%)
# Containers 3       2        150MB     50MB (33%)
# Local Vol  5       3        800MB     200MB (25%)
> ```
> **Vérification** : Chaque commande doit produire une sortie exploitable. `docker system df` montre l'espace reclaimable. `docker port` affiche le mapping `8080/tcp -> 0.0.0.0:8080`. `time docker run` donne le temps de cold start overhead.

---

## 17) Checklist de clôture (perf "prête-prod")

**Images & build**

* Multi-stage, `.dockerignore` strict, base **minimale**, dépendances **pinnées**.
* Caches BuildKit **activés** (local/registry) ; proxy cache registry **en place**.
* Taille et couches **raisonnées** ; healthcheck **léger**.

**Runtime**

* Limites **cgroups** définies ; pinning CPU/NUMA si utile ; ulimits **nofile** suffisants.
* Répertoires écrits sur **volumes** ; **overlay** réservé au code/RO.
* **Logs** rotés et peu verbeux ; traces échantillonnées.

**Réseau**

* Réseaux **séparés** ; MTU et hairpin **testés** ; DNS local fiable.
* Publication de ports **explicite** et sur IP nécessaire uniquement.

**Plateforme**

* `/var/lib/docker` sur disque rapide ; monitoring de capacité.
* Benchmarks **avant/après** + budgets documentés ; runbooks prêts.
