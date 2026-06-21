# Chapitre-09 — Observabilité & Diagnostic

## Objectifs d'apprentissage

* Mettre en place une **observabilité** complète : **logs** (collecte/rotation/centralisation), **métriques** (ressources & services), **traces** (requêtes) et **événements** (lifecycle).
* Utiliser efficacement les **outils de diagnostic** Docker/OS : `logs`, `stats`, `events`, `inspect`, `top`, `diff`, `port`, `nsenter`, `tcpdump`, `strace`, `lsof`.
* Écrire des **runbooks** d'incident (CPU/MEM/IO, réseau, DNS, disque, permissions, healthchecks, crash loops) et des **alertes** (Prometheus).

## Pré-requis

* Chap. 01–08 maîtrisés (images, conteneurs, storage, réseau, build, compose, sécurité).
* Notions Linux (processus, cgroups, journaux, réseau).

---

## 1) Piliers de l'observabilité

* **Logs** : événements applicatifs structurés (JSON/logfmt), journaux système, logs conteneurs.
* **Métriques** : compteurs/jauges (CPU, MEM, IO, latence, erreurs), séries temporelles.
* **Traces** : cheminement d'une requête **end-to-end** (span/trace id).
* **Événements** : chronologie Docker (create, start, die, oom, health_status…).

---

## 2) Journaux Docker (drivers & rotation)

### 2.1 Drivers de logs

* `json-file` (par défaut) / `local` (compaction) — simples, locaux.
* `journald` / `syslog` — intégrés à l'OS.
* `fluentd` / `gelf` / `awslogs` / `splunk` — vers une stack externe.
* `none` — à proscrire sauf cas très particuliers.

### 2.2 Rotation & configuration globale

`/etc/docker/daemon.json` :

> **Objectif** : Configurer globalement le driver de logs Docker et activer la rotation pour éviter le remplissage du disque par les logs de tous les conteneurs.
> **Pre-requis** : Avoir les droits root pour éditer `/etc/docker/daemon.json`. Le daemon Docker doit être redémarré après modification (`sudo systemctl restart docker`).

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

> **Resultat attendu** :
> ```
> Après redémarrage de dockerd, tous les conteneurs (sans override) utilisent json-file
> avec une rotation : chaque fichier log max 10 Mo, 3 fichiers conservés (30 Mo max par conteneur).
> ```
> **Verification** : `docker info | grep -A5 "Logging Driver"` doit afficher `json-file` avec `max-size=10m max-file=3`.

> Évite le remplissage disque par un conteneur trop verbeux.

### 2.3 Override par conteneur

> **Objectif** : Lancer un conteneur nginx en overrideant la configuration globale de logs, avec des limites de rotation plus larges (20 Mo / 5 fichiers), et ajouter un label et une variable d'environnement.
> **Pre-requis** : Docker daemon en cours d'exécution. L'image `nginx:1.27` doit être disponible localement ou pull-able.

```bash
docker run -d \
  --log-driver=json-file \          # Force le driver json-file pour ce conteneur
  --log-opt max-size=20m \          # Taille max d'un fichier log : 20 Mo
  --log-opt max-file=5 \            # Conserve 5 fichiers de logs (100 Mo max total)
  --label app=web \                 # Label pour identification/filtrage
  --env LOG_LEVEL=info \            # Variable d'env pour le niveau de log de l'app
  nginx:1.27                        # Image nginx version 1.27
```

> **Resultat attendu** :
> ```
> a1b2c3d4e5f6... (ID du conteneur)
> ```
> **Verification** : `docker inspect -f '{{json .HostConfig.LogConfig}}' <conteneur> | jq` doit afficher `max-size=20m`, `max-file=5`.

### 2.4 Bonnes pratiques de logs

* **Structurés** (JSON/logfmt), inclure `service`, `env`, `version`, **correlation/trace id**.
* Ne pas loguer de **secrets**.
* Limiter le verbiage par **niveau** (`info/warn/error`) + rotation.

---

## 3) Centraliser les logs (exemple minimal Fluent Bit)

`compose.logging.yaml`

> **Objectif** : Déployer Fluent Bit via Compose pour collecter les logs bruts des conteneurs Docker depuis le filesystem hôte et les router vers un backend (HTTP/Elasticsearch/Loki).
> **Pre-requis** : Docker Compose installé. Le fichier `fluent-bit.conf` doit exister dans le répertoire courant. L'utilisateur doit avoir accès en lecture à `/var/lib/docker/containers`.

```yaml
services:
  fluentbit:
    image: cr.fluentbit.io/fluent/fluent-bit:2    # Image officielle Fluent Bit v2
    volumes:
      - ./fluent-bit.conf:/fluent-bit/etc/fluent-bit.conf:ro  # Montage config (lecture seule)
      - /var/lib/docker/containers:/var/lib/docker/containers:ro  # Accès aux logs JSON des conteneurs
    ports: ["24224:24224"]                         # Exposition port Forward (Fluent Bit protocol)
    restart: unless-stopped                        # Redémarrage auto sauf arrêt manuel
```

> **Resultat attendu** :
> ```
> ✔ Container compose-logging-fluentbit-1  Started
> ```
> **Verification** : `docker compose -f compose.logging.yaml logs fluentbit` doit afficher les logs de Fluent Bit indiquant qu'il "tail" les fichiers `*.log` des conteneurs.

`fluent-bit.conf` (idée) : tail des `*.log` → sortie HTTP/ES/Loki.
Astuce : taguer par **labels** conteneur (`app`, `env`) pour filtres côté SIEM/observabilité.

---

## 4) Métriques (cAdvisor/Node Exporter → Prometheus/Grafana)

### 4.1 cAdvisor & Node Exporter (Compose extrait)

> **Objectif** : Déployer cAdvisor (métriques par conteneur : CPU, mémoire, IO, réseau, restarts) et Node Exporter (métriques de l'hôte : CPU, disque, réseau) pour alimenter Prometheus.
> **Pre-requis** : Docker Compose installé. Les ports 8088 (cAdvisor) et 9100 (node-exporter) doivent être libres. Les chemins `/`, `/var/run`, `/sys`, `/var/lib/docker` doivent être accessibles en lecture.

```yaml
services:
  cadvisor:
    image: gcr.io/cadvisor/cadvisor:v0.49.2       # cAdvisor : collecte métriques conteneurs
    ports: ["8088:8080"]                           # Expose l'UI/API cAdvisor sur le port 8088
    volumes:
      - /:/rootfs:ro                               # Lecture seule du filesystem racine (info disque/process)
      - /var/run:/var/run:ro                       # Accès au socket Docker (info conteneurs)
      - /sys:/sys:ro                               # Accès cgroups/sysfs (métriques kernel)
      - /var/lib/docker/:/var/lib/docker:ro        # Accès aux données Docker (storage drivers)

  nodeexporter:
    image: prom/node-exporter:v1.8.1               # Node Exporter : métriques hôte pour Prometheus
    pid: host                                      # Partage le namespace PID de l'hôte (accès /proc)
    network_mode: host                             # Partage le réseau hôte (mesure réseau réelle)
```

> **Resultat attendu** :
> ```
> ✔ Container compose-metrics-cadvisor-1         Started
> ✔ Container compose-metrics-nodeexporter-1    Started
> ```
> **Verification** : Accéder à `http://localhost:8088` pour cAdvisor. Accéder à `http://localhost:9100/metrics` pour Node Exporter — des métriques Prometheus doivent s'afficher.

> cAdvisor : métriques par conteneur (CPU, mémoire, IO, restarts). Node Exporter : hôte.

### 4.2 Prometheus (scrape) & alertes de base (idées)

* **Alertes** utiles :

  * `container_memory_usage_bytes / container_spec_memory_limit_bytes > 0.9`
  * Restarts > N sur 10 min
  * Disque `/var/lib/docker` > 85 %
  * OOMKills > 0
  * Latence P95 service > S

---

## 5) Tracing (OpenTelemetry + Jaeger/Tempo)

### 5.1 Variables OTEL côté service

> **Objectif** : Lancer un conteneur applicatif configuré pour exporter des traces OpenTelemetry (OTLP) vers un collector, avec un échantillonnage à 10 % des traces (ratio 0.1) pour limiter la charge.
> **Pre-requis** : L'image `ghcr.io/acme/api:1.4.2` doit exister. Un OpenTelemetry Collector doit être accessible sur `otel-collector:4317` (réseau Docker). L'application doit intégrer le SDK OpenTelemetry.

```bash
docker run -d --name api \
  -e OTEL_SERVICE_NAME=api \                              # Nom du service dans les traces
  -e OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 \ # Endpoint du collector OTLP (gRPC)
  -e OTEL_TRACES_SAMPLER=parentbased_traceidratio \       # Stratégie d'échantillonnage basée sur le parent
  -e OTEL_TRACES_SAMPLER_ARG=0.1 \                        # 10 % des traces sont échantillonnées
  ghcr.io/acme/api:1.4.2                                  # Image de l'application
```

> **Resultat attendu** :
> ```
> f7a8b9c0d1e2... (ID du conteneur)
> ```
> **Verification** : Ouvrir l'UI Jaeger (`http://localhost:16686`) et vérifier que des traces du service `api` apparaissent avec le bon taux d'échantillonnage.

### 5.2 Compose (collector + jaeger, aperçu)

* `otel-collector` (recevoir OTLP, exporter vers Jaeger/Grafana Tempo).
* `jaeger` UI pour visualiser les traces.

---

## 6) CLI Docker pour diagnostiquer

> **Objectif** : Passer en revue les commandes Docker essentielles pour diagnostiquer l'état d'un conteneur : état, logs, processus, ressources, modifications filesystem, ports mappés, événements et usage disque.
> **Pre-requis** : Docker installé et un ou plusieurs conteneurs en cours d'exécution. Remplacer `NAME` par le nom ou l'ID du conteneur cible.

```bash
docker ps -a                              # Liste tous les conteneurs (y compris arrêtés) avec état et ports
docker inspect NAME                       # Affiche toutes les métadonnées du conteneur (JSON complet)
docker logs -f --tail=200 NAME            # Affiche les 200 dernières lignes de logs et suit en live
docker top NAME                           # Affiche les processus en cours dans le conteneur
docker stats --no-stream NAME             # Snapshot des ressources (CPU, MEM, NET, IO) — sans suivi continu
docker diff NAME                          # Liste les modifications du filesystem (A=Added, C=Changed, D=Deleted)
docker port NAME                          # Affiche les mappings de ports (conteneur → hôte)
docker events --since=1h                  # Chronologie des événements Docker depuis 1 heure
docker system df                          # Résumé de l'espace disque utilisé par Docker (images, conteneurs, volumes)
```

> **Resultat attendu** :
> ```
> docker ps -a → tableau avec CONTAINER ID, IMAGE, COMMAND, STATUS, PORTS, NAMES
> docker stats → tableau avec CPU %, MEM USAGE/LIMIT, NET I/O, BLOCK I/O
> docker system df → TYPE, TOTAL, ACTIVE, SIZE, RECLAIMABLE
> ```
> **Verification** : Chaque commande doit retourner des informations cohérentes avec l'état du conteneur. `docker diff` montre les fichiers modifiés depuis la création du conteneur.

**Formatage ciblé**

> **Objectif** : Extraire des champs spécifiques des métadonnées du conteneur via des templates Go (`-f`) et les formater avec `jq` pour un affichage lisible.
> **Pre-requis** : `jq` installé sur l'hôte. Le conteneur `NAME` doit exister.

```bash
docker inspect -f '{{.State.Status}} {{.State.Health.Status}}' NAME
# Extrait le statut du conteneur (running/exited) et le statut du healthcheck (healthy/unhealthy)

docker inspect -f '{{json .HostConfig.LogConfig}}' NAME | jq
# Extrait la configuration complète des logs (driver + options) et la formate en JSON lisible

docker inspect -f '{{json .Mounts}}' NAME | jq
# Extrait la liste des montages (binds, volumes, tmpfs) avec source, destination, mode
```

> **Resultat attendu** :
> ```
> running healthy
> { "Type": "json-file", "Config": { "max-file": "5", "max-size": "20m" } }
> [ { "Type": "bind", "Source": "/data", "Destination": "/app/data", "Mode": "ro", ... } ]
> ```
> **Verification** : Les valeurs retournées doivent correspondre à la configuration réelle du conteneur.

---

## 7) Diagnostic réseau (interne & externe)

### 7.1 Container "trousse à outils" (netshoot)

> **Objectif** : Lancer un conteneur éphémère avec l'image `netshoot` (qui contient tous les outils réseau) connecté au réseau Docker `app-net` pour diagnostiquer la connectivité interne : DNS, HTTP, ports écoute, routage.
> **Pre-requis** : Le réseau Docker `app-net` doit exister (`docker network create app-net`). Des services nommés `db` et `api` doivent tourner sur ce réseau.

```bash
docker run --rm -it --network app-net nicolaka/netshoot
# Lance un shell interactif dans le réseau app-net, supprimé à la sortie

# inside:
dig db                                     # Résolution DNS du service "db" via l'embedded DNS Docker
curl -sv http://api:8080/health            # Test HTTP vers le service "api" sur le port 8080 (verbose)
ss -lntp                                 # Liste les sockets TCP en écoute avec processus associés
traceroute 1.1.1.1                         # Trace la route vers l'extérieur (vérifie la connectivité sortante)
```

> **Resultat attendu** :
> ```
> dig db → ANSWER SECTION: db. IN A 172.18.0.3
> curl → HTTP/1.1 200 OK  {"status":"ok"}
> ss -lntp → LISTEN  0  128  0.0.0.0:8080  users:(("api",pid=1,fd=5))
> traceroute → 1 172.18.0.1 ... → 1.1.1.1
> ```
> **Verification** : `dig db` doit résoudre une IP interne Docker. `curl` doit retourner 200. `ss` doit montrer les ports en écoute. `traceroute` confirme la route sortante.

### 7.2 `tcpdump` ciblé

> **Objectif** : Capturer le trafic réseau sur le port 8080 depuis l'espace réseau de l'hôte (`--net=host`) pour inspecter les paquets échangés avec un service, sans entrer dans le conteneur.
> **Pre-requis** : Le port 8080 doit être actif sur l'hôte ou un conteneur en mode host. Les privilèges `--privileged` sont nécessaires pour tcpdump (accès raw sockets).

```bash
docker run --rm --net=host --privileged nicolaka/netshoot \
  tcpdump -nni any port 8080
# -nn : ne pas résoudre les noms/IPs (affichage rapide)
# -i any : écoute sur toutes les interfaces
# port 8080 : filtre uniquement le trafic sur le port 8080
```

> **Resultat attendu** :
> ```
> tcpdump: verbose output suppressed, use -v[v]... for full protocol decode
> listening on any, link-type LINUX_SLL, capture size 262144 bytes
> 12:34:56.789 IP 172.18.0.5.43210 > 172.18.0.2.8080: Flags [S], seq 1234567
> 12:34:56.790 IP 172.18.0.2.8080 > 172.18.0.5.43210: Flags [S.], seq 7654321, ack 1234568
> ```
> **Verification** : On doit voir les paquets SYN/SYN-ACK/ACK du handshake TCP. Si aucun paquet, le service ne reçoit pas de trafic.

### 7.3 `nsenter` (espace réseau du conteneur)

> **Objectif** : Entrer dans l'espace réseau (network namespace) d'un conteneur en cours d'exécution depuis l'hôte, pour inspecter ses interfaces IP, routes et ports en écoute comme si on était "à l'intérieur".
> **Pre-requis** : Le conteneur `NAME` doit être en cours d'exécution. `sudo` est nécessaire pour `nsenter` (accès aux namespaces du kernel).

```bash
PID=$(docker inspect -f '{{.State.Pid}}' NAME)
# Récupère le PID du processus principal du conteneur côté hôte

sudo nsenter -t $PID -n sh -lc 'ip a; ip route; ss -lntp'
# -t $PID : cible le namespace du processus
# -n : entre dans le network namespace uniquement
# sh -lc : lance un shell login qui exécute les commandes :
#   ip a      → affiche les interfaces réseau du conteneur
#   ip route  → affiche la table de routage
#   ss -lntp  → affiche les sockets TCP en écoute
```

> **Resultat attendu** :
> ```
> 1: lo: <LOOPBACK,UP> ... inet 127.0.0.1/8
> 2: eth0: <BROADCAST,MULTICAST,UP> ... inet 172.18.0.4/16
> default via 172.18.0.1 dev eth0
> LISTEN 0 128  0.0.0.0:8080  0.0.0.0:*  users:(("nginx",pid=1,fd=6))
> ```
> **Verification** : L'interface `eth0` doit avoir une IP du réseau Docker. La route par défaut pointe vers la passerelle du réseau. `ss` doit montrer les mêmes ports que `docker port`.

**Pièges courants**

* Service qui écoute sur `127.0.0.1` (au lieu de `0.0.0.0`).
* MTU/hairpin NAT : symptoms = timeouts aléatoires.
* DNS : mauvais `search`/serveur, TTLs trop longs, split-DNS.

---

## 8) Stockage & disque (overlay2/logs)

> **Objectif** : Diagnostiquer l'utilisation du disque par Docker : vue globale Docker, capacité de la partition, répartition par sous-répertoire, et erreurs récentes du daemon.
> **Pre-requis** : Docker en cours d'exécution. Accès `sudo` pour `du` sur `/var/lib/docker` et `journalctl`.

```bash
docker system df                      # Vue Docker : espace utilisé par images, conteneurs, volumes, build cache
df -h /var/lib/docker                 # Capacité et occupation de la partition contenant les données Docker
sudo du -xhd1 /var/lib/docker/        # Taille de chaque sous-répertoire de /var/lib/docker (sans traverser les mounts)
journalctl -u docker --since "1h ago" # Logs du daemon Docker de la dernière heure (erreurs, warnings)
```

> **Resultat attendu** :
> ```
> docker system df → Images: 5 (2.3GB), Containers: 3 (150MB), Volumes: 2 (800MB), Local Build Cache: (50MB)
> df -h → /dev/sda1  50G  38G  12G  77% /var/lib/docker
> du -xhd1 → 2.3G /var/lib/docker/overlay2, 800M /var/lib/docker/volumes, 150M /var/lib/docker/containers
> journalctl → (lignes de logs du daemon)
> ```
> **Verification** : Si `df -h` montre > 85 % d'occupation, agir (prune, rotation, agrandissement). `du` identifie le sous-répertoire le plus gourmand.

* Logs conteneurs : `/var/lib/docker/containers/<id>/<id>-json.log` (si `json-file`).
* Overlay2 : `upperdir` volumineux = écritures importantes (cache, build, temp).

---

## 9) CPU/Mémoire/PIDs (cgroups & OOMKill)

### 9.1 Détection OOMKill

> **Objectif** : Vérifier si un conteneur a été tué par le kernel (Out-Of-Memory Killer) et consulter les événements OOM récents.
> **Pre-requis** : Le conteneur `NAME` doit avoir existé (même arrêté). Les événements Docker sont conservés tant que le daemon tourne.

```bash
docker inspect -f '{{.State.OOMKilled}}' NAME
# Retourne true si le conteneur a été tué par OOMKill, false sinon

docker events --since=2h | grep -i oom
# Liste tous les événements OOM des 2 dernières heures (filtrés par grep)
```

> **Resultat attendu** :
> ```
> true
> 2025-06-21T10:15:30.000000000Z container oom abc123def456 (image=nginx:1.27, name=web)
> ```
> **Verification** : Si `OOMKilled=true`, le conteneur a dépassé sa limite mémoire. Augmenter `--memory` ou corriger la fuite mémoire.

### 9.2 Inspecter processus & FD

> **Objectif** : Lister les processus dans le conteneur et vérifier les limites de descripteurs de fichiers (FD) ainsi que le nombre de FD actuellement ouverts par le processus PID 1.
> **Pre-requis** : Le conteneur `NAME` doit être en cours d'exécution.

```bash
docker top NAME
# Affiche les processus du conteneur (PID hôte, PID conteneur, CMD, CPU, MEM)

docker exec NAME sh -lc 'ulimit -n; ls /proc/1/fd | wc -l'
# ulimit -n         → limite max de descripteurs de fichiers ouverts (soft limit)
# ls /proc/1/fd | wc -l → compte les FD actuellement ouverts par le processus principal (PID 1)
```

> **Resultat attendu** :
> ```
> USER  PID  PPID  C  STIME  TIME  CMD
> root  1    0     0  10:00  0:01  nginx: master process
> root  15   1     0  10:00  0:00  nginx: worker process
>
> 1024       (ulimit -n : limite soft)
> 42         (FD ouverts par PID 1)
> ```
> **Verification** : Si le nombre de FD ouverts approche la limite (`ulimit -n`), le conteneur risque des erreurs "Too many open files". Augmenter la limite ou investiguer les fuites de FD.

### 9.3 Profilage rapide (selon image)

* `strace -fp <pid>` pour syscalls.
* `lsof -p <pid>` descripteurs ouverts.
* Applis instrumentées (pprof/py-spy/async-profiler) si disponible.

---

## 10) Healthchecks & crash loops

* Lire `State.Health.Log` via `inspect`, récupérer **les messages** d'échec.
* `depends_on: condition: service_healthy` (Compose) pour l'ordre de démarrage.
* Crash loop : vérifier **exit code** (`docker wait`), fichiers manquants, **port en usage**, **secret** non monté, **permissions**.

---

## 11) Runbooks d'incident (exemples concrets)

### 11.1 **Port déjà utilisé / service inaccessible**

1. `docker ps`, `docker port NAME`, `ss -lntp | grep :8080`
2. Vérifier que l'app écoute `0.0.0.0:8080` dans le conteneur.
3. Conflit : changer `-p`, arrêter le service fautif, ou lier sur `127.0.0.1`.

### 11.2 **CPU anormalement élevé**

1. `docker stats --no-stream NAME`, `top`/`htop` dans le conteneur.
2. Activer logs debug **temporairement** ; vérifier boucles/log spam.
3. Profiler (pprof/py-spy) si possible ; limiter via `--cpus`, alerter.

### 11.3 **Fuite mémoire / OOMKill (137)**

1. `inspect .State.OOMKilled`, `events`.
2. `stats` (MEM) & taille du **working set**.
3. Augmenter `--memory` si besoin **temporaire**, corriger la fuite.

### 11.4 **DNS / résolutions intermittentes**

1. `docker exec` → `cat /etc/resolv.conf`.
2. `dig name`, `nslookup`, vérifier `--dns`/`--dns-search`.
3. TTL, split-DNS, latence vers résolveur ; mettre un résolveur local fiable.

### 11.5 **Timeouts réseau / MTU**

1. `curl -v` vs `telnet host port`.
2. `tcpdump` voir SYN/SYN-ACK, ICMP frag needed, PMTU.
3. Ajuster **MTU** bridges/VM, vérifier hairpin NAT.

### 11.6 **Disque plein (logs ou overlay2)**

1. `df -h`, `docker system df`, `du -xhd1 /var/lib/docker`.
2. Rotation logs (`max-size/max-file`), `docker system prune` **maîtrisé**.
3. Agrandir partition, déplacer `data-root`, nettoyer images orphelines.

### 11.7 **Permission denied (SELinux/UID)**

1. SELinux : ajouter `:Z`/`:z` sur binds RHEL/Fedora.
2. UID/GID : aligner avec `-u` et `chown` le volume.
3. AppArmor : profil custom si nécessaire.

### 11.8 **TLS/Certificats (clients ou proxys)**

1. Horloge/NTP, chaîne **fullchain**, CN/SAN.
2. CAs dans trust store de l'image ; tester `openssl s_client`.
3. Renouvellement automatique (ACME) opérationnel.

---

## 12) Boîte à outils "diagnostic"

* **Images** : `nicolaka/netshoot` (réseau), `alpine`, `busybox`.
* **CLI utiles** : `curl`, `dig`, `nc`, `iproute2`, `ss`, `tcpdump`, `jq`, `strace`, `lsof`.
* **Hôte** : `journalctl`, `dmesg`, `iptables/nft`, `conntrack`, `iostat`, `iotop`, `pidstat`.

---

## 13) "Support bundle" (collecte standardisée)

Script (extrait bash) :

> **Objectif** : Générer automatiquement un bundle de diagnostic complet (archive `.tgz`) contenant toutes les informations pertinentes sur l'état de Docker, de l'hôte et de chaque conteneur, pour faciliter le support/debugging à distance.
> **Pre-requis** : Bash 4+, Docker en cours d'exécution, `sudo` pour certaines commandes (journalctl). Espace disque suffisant pour le bundle.

```bash
#!/usr/bin/env bash
set -euo pipefail
# set -e : sort en cas d'erreur
# set -u : erreur si variable non définie
# set -o pipefail : erreur si un élément d'un pipe échoue

OUT="support_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ)"
# Nom du dossier de sortie : support_<hostname>_<timestamp UTC>

mkdir -p "$OUT"
# Crée le répertoire de collecte

docker info > "$OUT/docker_info.txt"
# Capture les informations globales du daemon Docker (version, driver, storage, etc.)

docker ps -a > "$OUT/docker_ps_a.txt"
# Liste complète de tous les conteneurs (running + arrêtés)

docker system df > "$OUT/docker_system_df.txt"
# Résumé de l'utilisation disque par Docker

journalctl -u docker --since "24 hours ago" > "$OUT/journal_docker_24h.log"
# Logs du daemon Docker des dernières 24 heures

df -h > "$OUT/df_h.txt"
# Occupation de toutes les partitions montées

free -m > "$OUT/free_m.txt"
# Mémoire RAM et swap disponible/utilisée (en Mo)

ss -lntp > "$OUT/ss_lntp.txt"
# Tous les sockets TCP en écoute avec processus associés

for c in $(docker ps --format '{{.Names}}'); do
  # Boucle sur chaque conteneur en cours d'exécution (par nom)
  mkdir -p "$OUT/ct_$c"
  # Crée un sous-dossier par conteneur
  docker inspect "$c" > "$OUT/ct_$c/inspect.json"
  # Export complet des métadonnées du conteneur en JSON
  docker logs --since=12h "$c" > "$OUT/ct_$c/logs_12h.txt" || true
  # Logs des 12 dernières heures (|| true pour ne pas échouer si pas de logs)
  docker stats --no-stream "$c" > "$OUT/ct_$c/stats.txt" || true
  # Snapshot des ressources (CPU, MEM, IO) — || true évite l'échec si conteneur stoppé entre-temps
done

tar czf "$OUT.tgz" "$OUT"
# Compresse le dossier complet en archive .tgz

echo "Bundle: $OUT.tgz"
# Affiche le chemin du bundle généré
```

> **Resultat attendu** :
> ```
> Bundle: support_monhost_20250621T143022Z.tgz
> ```
> **Verification** : `tar tzf support_*.tgz | head -20` doit lister les fichiers : `docker_info.txt`, `docker_ps_a.txt`, `ct_<nom>/inspect.json`, etc. Le fichier est prêt à être envoyé au support.

---

## 14) Aide-mémoire (commandes clés)

> **Objectif** : Récapitulatif rapide des commandes les plus utiles pour le diagnostic Docker, organisées par catégorie : vue rapide, événements/réseau, réseau avancé, disque, OOM/exit codes.
> **Pre-requis** : Docker installé. Remplacer `NAME` par le nom du conteneur et `NET` par le nom du réseau Docker.

```bash
# Vue rapide
docker ps -a                                                        # Tous les conteneurs avec état
docker logs -f --tail=200 NAME                                      # Logs live (200 dernières lignes)
docker stats --no-stream NAME                                       # Snapshot CPU/MEM/IO/NET
docker inspect -f '{{.State.Status}} {{.State.Health.Status}}' NAME # Statut + healthcheck en une ligne

# Événements & ports
docker events --since=1h                                            # Timeline des événements (1h)
docker port NAME                                                    # Mapping ports du conteneur

# Réseau
docker run --rm -it --network NET nicolaka/netshoot                 # Shell réseau éphémère dans NET
# Hôte & netns
PID=$(docker inspect -f '{{.State.Pid}}' NAME); sudo nsenter -t $PID -n ip a
# Entre dans le namespace réseau du conteneur depuis l'hôte et affiche les interfaces

# Disque
docker system df                                                    # Usage disque global Docker
sudo du -xhd1 /var/lib/docker                                       # Détail par sous-répertoire

# OOM & exit codes
docker inspect -f '{{.State.OOMKilled}} {{.State.ExitCode}}' NAME   # OOMKill + code de sortie
```

> **Resultat attendu** :
> ```
> running healthy
> false 0
> TYPE       TOTAL  ACTIVE  SIZE    RECLAIMABLE
> Images     5      3       2.3GB   1.1GB (47%)
> ```
> **Verification** : Chaque commande doit s'exécuter sans erreur. Les valeurs retournées donnent un instantané de l'état du système Docker.

---

## 15) Checklist de clôture (observabilité "prête prod")

* **Logs** : driver choisi, **rotation** configurée, **centralisation** opérationnelle, logs **structurés** + corrélation id.
* **Métriques** : cAdvisor + Node Exporter scrappés ; dashboards de base ; **alertes** CPU/MEM/IO, restarts, disque, latence/erreurs.
* **Traces** : OTEL activé vers collector (Jaeger/Tempo) sur les services critiques.
* **Événements** : procédure de lecture/archivage des `docker events`.
* **Runbooks** : incidents types documentés, commandes & critères de sortie clairs.
* **Support bundle** : script validé pour collecter preuves en 1 commande.
* **NTP** fiable, capacité `/var/lib/docker` surveillée, MTU/hairpin testés.
* **Sécurité** respectée pendant le diag (pas de `--privileged` par défaut, secrets masqués).
