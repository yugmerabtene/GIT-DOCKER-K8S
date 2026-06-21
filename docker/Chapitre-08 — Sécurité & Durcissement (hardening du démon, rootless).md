# Chapitre-08 — Sécurité & Durcissement

*(hardening du démon, rootless, userns-remap, seccomp/AppArmor/SELinux, socket proxy, secrets, policies)*

## Objectifs d'apprentissage

* Définir un **modèle de menace** et appliquer le **moindre privilège** à tous les niveaux (images, runtime, hôte, supply chain).
* Durcir **dockerd** (configuration, journaux, API TLS fermée ou proxy, iptables, rotation des logs).
* Maîtriser les modes **rootless** et **userns-remap** (isolation UID/GID) et leurs impacts.
* Renforcer l'exécution : **non-root**, **capabilities minimales**, **seccomp/AppArmor/SELinux**, **read-only**, **tmpfs**, **sysctl**.
* Gérer **secrets**, **politiques d'images** (signatures, SBOM, scans), et **auditer** (journaux, commandes, accès).

## Pré-requis

* Connaissances des chapitres 01–07 (images, conteneurs, storage, réseau, build, compose, registry).
* Accès root sur l'hôte pour la partie démon (sauf mode rootless).

---

## 1) Principes & modèle de menace

* **Réduire la surface** : moins de paquets sur l'hôte, pas de services inutiles, noyau à jour.
* **Moindre privilège** : pas de `--privileged`, réduire **capabilities**, exécuter **non-root**.
* **Compartimenter** : réseaux séparés, `--internal` pour backends, volumes spécifiques RO/RW.
* **Vérité des artefacts** : images signées, **SBOM**, scans CVE/licences, déploiement **par digest**.
* **Visibilité** : journaux, métriques, traces ; audit des accès à la **socket Docker**.

---

## 2) Hardening du démon Docker (dockerd)

### 2.1 `daemon.json` (exemples commentés)

`/etc/docker/daemon.json`

> **Objectif** : Configurer le démon Docker avec des options de sécurité : rotation des logs, isolation réseau entre conteneurs, persistance au redémarrage, remapping UID/GID, limites de descripteurs de fichiers, BuildKit et registre miroir interne.
> **Pre-requis** : Docker installé, fichier `/etc/docker/daemon.json` existant (ou à créer), accès root. Le miroir de registre doit être accessible depuis l'hôte.

```json
{
  // --- Journaux : driver json-file avec rotation pour éviter la saturation disque ---
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },  // max 10 Mo par fichier, 3 fichiers max (30 Mo total par conteneur)

  // --- Réseau : désactive la communication inter-conteneurs sur le bridge docker0 ---
  "icc": false,                        // false = les conteneurs sur docker0 ne peuvent pas communiquer entre eux (user-defined bridges restent préférables)
  "iptables": true,                    // true = Docker gère automatiquement les règles iptables (sinon il faut les gérer manuellement)
  "live-restore": true,                // true = les conteneurs restent actifs même si le démon Docker redémarre

  // --- Isolation UID/GID : mappe root du conteneur vers un UID non-root sur l'hôte ---
  "userns-remap": "default",           // active le remapping via l'utilisateur "dockremap" (voir §4)

  // --- Limites système par défaut appliquées à tous les conteneurs ---
  "default-ulimits": {                 // limite le nombre de descripteurs de fichiers ouverts
    "nofile": { "Name": "nofile", "Hard": 65536, "Soft": 65536 }  // 65536 fichiers ouverts max (soft = hard)
  },

  // --- BuildKit : moteur de build moderne (couches parallèles, cache avancé, secrets) ---
  "features": { "buildkit": true },    // active BuildKit pour "docker build"

  // --- Registres : aucun registre non-sécurisé (HTTP sans TLS) autorisé ---
  "insecure-registries": [],           // liste vide = proscrire en prod tout registre sans TLS
  "registry-mirrors": ["https://<miroir>"]  // proxy cache interne pour réduire la bande passante et accélérer les pulls (voir Ch-07)
}
```

> **Resultat attendu** :
> ```
> $ systemctl reload docker
> $ docker info | grep -A5 "Security Options"
> Security Options:
>  userns:           true
>  ...
> $ docker info | grep "Logging Driver"
> Logging Driver: json-file
> ```
> **Verification** : `docker info` affiche `userns: true`, le log driver est `json-file`, et `icc` est désactivé.

> Redémarrer : `systemctl reload docker` (ou restart).

### 2.2 API Docker (REST) — fermer ou chiffrer

* **Par défaut** : socket Unix `unix:///var/run/docker.sock` (OK, local).
* **Éviter** l'exposition **TCP**. Si obligation : **TLS mutuel** + pare-feu.
  Exemple (unit file `dockerd` ou `/etc/docker/daemon.json`) :

> **Objectif** : Configurer le démon Docker pour exposer l'API sur une socket Unix locale ET sur TCP chiffré en TLS mutuel (client + serveur authentifiés). Cela permet un accès distant sécurisé tout en limitant les connexions aux seuls clients possédant un certificat valide.
> **Pre-requis** : Certificats TLS générés (CA, serveur, client) placés dans `/etc/docker/pki/`. Le fichier `ca.pem` est l'autorité de certification, `server.pem`/`server-key.pem` sont le certificat et la clé du serveur.

```bash
# Exemples d'arguments dockerd (à placer dans le ExecStart de l'unité systemd ou dans daemon.json)
-H unix:///var/run/docker.sock \           # socket Unix locale (accès root obligatoire)
-H tcp://0.0.0.0:2376 \                    # écoute TCP sur le port 2376 (port standard Docker TLS)
--tlsverify \                              # active la vérification TLS mutuelle (client ET serveur)
--tlscacert=/etc/docker/pki/ca.pem \       # certificat de l'AC pour vérifier les certificats clients
--tlscert=/etc/docker/pki/server.pem \     # certificat du serveur présenté aux clients
--tlskey=/etc/docker/pki/server-key.pem    # clé privée du serveur (doit avoir des permissions restrictives : 0400)
```

> **Resultat attendu** :
> ```
> $ docker -H tcp://<ip>:2376 --tlsverify \
>     --tlscacert=ca.pem --tlscert=client.pem --tlskey=client-key.pem info
> Client: Docker Engine - Community
>  Version:           24.x.x
>  ...
> Server: Docker Engine - Community
>  ...
> ```
> **Verification** : Une connexion sans certificat client est refusée. Seuls les clients avec un certificat signé par `ca.pem` peuvent accéder à l'API.

> Viser **réseau privé** + ACL/IPTables ; pas d'expo Internet.

### 2.3 Hardening systemd (dockerd service)

`systemctl edit docker` → override (extraits utiles) :

> **Objectif** : Durcir le service systemd de Docker en appliquant des restrictions au processus dockerd lui-même : limite de descripteurs de fichiers, protection du noyau, isolation du tmp, et interdiction d'élévation de privilèges. Cela réduit l'impact d'une compromission du démon.
> **Pre-requis** : systemd comme init system, Docker installé et actif en tant que service systemd.

```
[Service]
# --- Limites et protections système pour le processus dockerd ---
LimitNOFILE=1048576            # augmente la limite de descripteurs de fichiers ouverts (1M au lieu de 1024 par défaut)
ProtectKernelTunables=yes      # rend /proc/sys, /sys readonly → empêche la modification de paramètres noyau
ProtectKernelModules=yes       # interdit le chargement de modules noyau (empêche insmod/rmmod)
ProtectControlGroups=yes       # rend le système de cgroups en lecture seule (empêche la modification des hiérarchies)
PrivateTmp=yes                 # crée un /tmp privé isolé (invisible depuis les autres unités)
NoNewPrivileges=yes            # empêche dockerd et ses enfants d'acquérir de nouveaux privilèges (setuid, capabilities, etc.)
```

> **Resultat attendu** :
> ```
> $ systemctl edit docker
> $ systemctl restart docker
> $ systemctl show docker -p LimitNOFILE,ProtectKernelTunables,NoNewPrivileges
> LimitNOFILE=1048576
> ProtectKernelTunables=yes
> NoNewPrivileges=yes
> ```
> **Verification** : `systemctl show docker` confirme les directives. Le service Docker démarre sans erreur. Certaines options peuvent gêner selon la distribution ; tester en lab.

> Certaines options peuvent gêner selon distro ; tester en lab.

### 2.4 Journaux & rotation

* `log-driver=json-file` **avec rotation** (ci-dessus) ou **journald/syslog/fluentd** selon centralisation (cf. Observabilité).
* Surveillez `/var/lib/docker` (taille, inodes) et programmez des **prunes** maîtrisés.

---

## 3) Socket Docker & contrôle d'accès

* **Ne montez jamais** `-v /var/run/docker.sock:/var/run/docker.sock` dans des applis (équivaut à root sur l'hôte).
* Si un conteneur doit piloter Docker, interposez un **docker-socket-proxy** (filtres sur API, lecture seule quand possible).
* Groupe `docker` = **root logique**. Préférez :

  * **Pas** d'ajout d'utilisateurs non privilégiés au groupe.
  * Commandes **sudo** ciblées (sudoers) si besoin :
    `Cmnd_Alias DOCKER_SAFE = /usr/bin/docker ps, /usr/bin/docker logs *`
    `user ALL=(root) NOPASSWD: DOCKER_SAFE`
* Journaliser **qui** utilise la socket (auditd sur `/var/run/docker.sock`).

---

## 4) Isolation UID/GID : **userns-remap** vs **rootless**

### 4.1 `userns-remap`

* Mappe le `root` du conteneur vers un **UID non-root** sur l'hôte.
* Pré-requis : entrées dans `/etc/subuid` & `/etc/subgid` (ex. `dockremap:100000:65536`).
* Activer : `"userns-remap": "default"` (voir §2.1).
  **Impacts :**
* UID/GID vus depuis l'hôte → **décalés** (ex. 100000+).
* Volumes/binds : vérifiez l'ownership (peut nécessiter `chown` via conteneur utilitaire).
* Bon compromis si rootless non envisageable.

### 4.2 **Rootless Docker**

* Dockerd & conteneurs tournent **sans privilèges root** (user unprivileged).
* Installation (Linux) :

> **Objectif** : Installer et activer Docker en mode rootless, où le démon et les conteneurs s'exécutent entièrement en espace utilisateur sans aucun privilège root. Cela élimine les risques liés à une évasion de conteneur vers l'hôte.
> **Pre-requis** : Linux avec cgroups v2 activé, paquets `uidmap` et `dbus-user-session` installés. L'utilisateur courant doit avoir des entrées dans `/etc/subuid` et `/etc/subgid`.

```bash
# Installe les unités systemd utilisateur pour dockerd rootless
# Crée la configuration nécessaire (socket, namespaces, etc.)
dockerd-rootless-setuptool.sh install

# Définit la variable d'environnement pour que le client Docker
# communique avec le démon rootless via sa socket utilisateur
# (1000 = UID de l'utilisateur, à adapter si différent)
export DOCKER_HOST=unix:///run/user/1000/docker.sock
```

> **Resultat attendu** :
> ```
> $ dockerd-rootless-setuptool.sh install
> [INFO] Installed docker.service successfully.
> [INFO] Make sure the following environment variable(s) are set:
>   DOCKER_HOST=unix:///run/user/1000/docker.sock
> $ docker info | grep "Rootless"
>  Rootless: true
> ```
> **Verification** : `docker info` affiche `Rootless: true`. Les conteneurs sont visibles via `docker ps` sans sudo.

* **Limites** typiques : besoin de cgroups v2, **pas** de `--privileged`, mapping ports <1024 via redirection userland, accès matériels restreints, overlayfs selon kernel.
* Excellent pour **postes dev** et environnements restreints.

> Choix pratique : **prod** → `userns-remap` + bonnes pratiques ; **dev**/CI ou hôtes partagés → **rootless**.

---

## 5) Durcissement **runtime** des conteneurs

### 5.1 Exécuter **non-root**

Dans l'image (Dockerfile) :

> **Objectif** : Créer un utilisateur et un groupe non-privilégiés dans l'image Docker, puis basculer sur cet utilisateur pour que le processus du conteneur ne s'exécute pas en tant que root. Cela limite les dégâts en cas d'exploitation d'une vulnérabilité applicative.
> **Pre-requis** : Dockerfile basé sur une image Alpine (pour les commandes `addgroup`/`adduser` ; adapter pour Debian/Ubuntu avec `groupadd`/`useradd`).

```dockerfile
# Crée un groupe système "app" et un utilisateur système "app" (UID 10001)
# -S = utilisateur système (pas de home, pas de shell de login)
# -G app = groupe principal "app"
# -u 10001 = UID fixe pour la reproductibilité
RUN addgroup -S app && adduser -S -G app -u 10001 app

# Bascule tous les processus suivants (CMD, ENTRYPOINT) sur cet utilisateur
# Format UID:GID pour éviter toute ambiguïté de résolution de noms
USER 10001:10001
```

> **Resultat attendu** :
> ```
> $ docker build -t app-secure .
> $ docker run --rm app-secure whoami
> app
> $ docker run --rm app-secure id
> uid=10001(app) gid=10001(app) groups=10001(app)
> ```
> **Verification** : `whoami` retourne `app` (pas `root`), `id` confirme l'UID 10001.

Au run :

> **Objectif** : Forcer l'exécution du conteneur avec un UID/GID spécifique au runtime, sans modifier le Dockerfile. Utile pour les images tierces où l'on ne maîtrise pas le Dockerfile.
> **Pre-requis** : L'UID/GID 10001 doit exister dans l'image ou les permissions des fichiers doivent être compatibles.

```bash
# Lance le conteneur en forçant l'utilisateur 10001 et le groupe 10001
# Écrase toute directive USER du Dockerfile
docker run -u 10001:10001 ...
```

> **Resultat attendu** :
> ```
> $ docker run --rm -u 10001:10001 monimage id
> uid=10001 gid=10001 groups=10001
> ```
> **Verification** : `id` dans le conteneur confirme l'UID/GID 10001.

### 5.2 **Capabilities** (drop all + ajout minimal)

> **Objectif** : Supprimer TOUTES les capabilities Linux du conteneur puis n'ajouter que celle strictement nécessaire. Ici `NET_BIND_SERVICE` permet de lier un port privilégié (<1024). C'est l'application du principe de moindre privilège au niveau noyau.
> **Pre-requis** : Docker installé. L'application dans le conteneur doit nécessiter `NET_BIND_SERVICE` (typiquement un service web écoutant sur le port 80 ou 443).

```bash
# --cap-drop=ALL  : supprime toutes les capabilities (approche "deny by default")
# --cap-add=NET_BIND_SERVICE : rajoute uniquement la capacité de binder sur les ports <1024
docker run --cap-drop=ALL --cap-add=NET_BIND_SERVICE ...
```

> **Resultat attendu** :
> ```
> $ docker run --rm --cap-drop=ALL --cap-add=NET_BIND_SERVICE monimage capsh --print
> Current: =
> Bounding set =cap_net_bind_service
> Securebits: ...
> ```
> **Verification** : `capsh --print` montre que seule `cap_net_bind_service` est dans le bounding set. Toutes les autres capabilities sont absentes.

Réduire à : `CHOWN`, `DAC_OVERRIDE` si strict nécessaire, **jamais** `SYS_ADMIN` par défaut.

### 5.3 **seccomp** (profil)

* Le profil **par défaut** de Docker bloque de nombreux appels à risque.
* Fournir un profil custom si l'app a des besoins spécifiques :

> **Objectif** : Appliquer un profil seccomp (Secure Computing Mode) personnalisé qui restreint les appels système disponibles dans le conteneur. Le profil JSON définit une liste blanche ou noire de syscalls, réduisant la surface d'attaque au niveau noyau.
> **Pre-requis** : Fichier JSON de profil seccomp valide (`/path/seccomp-profile.json`). Le profil peut être basé sur le profil par défaut de Docker avec des ajustements.

```bash
# --security-opt seccomp=... : applique le profil seccomp personnalisé au conteneur
# Le profil JSON définit les syscalls autorisés/interdits
docker run --security-opt seccomp=/path/seccomp-profile.json ...
```

> **Resultat attendu** :
> ```
> $ docker run --rm --security-opt seccomp=/path/seccomp-profile.json monimage
> # Le conteneur démarre normalement si le profil est compatible
> # Si un syscall interdit est appelé : "Bad system call" ou "Operation not permitted"
> ```
> **Verification** : Tester l'application ; si un syscall nécessaire est bloqué, ajuster le profil. `grep Seccomp /proc/1/status` dans le conteneur doit afficher `Seccomp: 2` (mode filter).

### 5.4 **AppArmor** / **SELinux**

* **AppArmor** (Ubuntu/Debian) : profil `docker-default` par défaut.
  Personnaliser :

> **Objectif** : Appliquer un profil AppArmor personnalisé au conteneur pour restreindre les opérations autorisées (accès fichiers, réseau, montage, etc.) au-delà du profil `docker-default`. AppArmor est un MAC (Mandatory Access Control) basé sur les chemins.
> **Pre-requis** : AppArmor activé sur l'hôte (Ubuntu/Debian). Profil AppArmor chargé via `apparmor_parser -r /etc/apparmor.d/my-profile`.

```bash
# --security-opt apparmor=... : applique le profil AppArmor nommé "my-profile"
# Le profil doit être préalablement chargé dans le noyau
docker run --security-opt apparmor=my-profile ...
```

> **Resultat attendu** :
> ```
> $ docker run --rm --security-opt apparmor=my-profile monimage
> # Le conteneur démarre ; les actions interdites par le profil sont bloquées
> $ cat /proc/1/attr/current
> docker-my-profile
> ```
> **Verification** : `/proc/1/attr/current` affiche le nom du profil AppArmor appliqué.

* **SELinux** (RHEL/Fedora) :

  * Montages hôte : suffixes `:Z` (privé) / `:z` (partagé).
  * Éviter `spc_t` (super-priv) ; rester sur `container_t` si possible.

### 5.5 FS **read-only** + **tmpfs**

> **Objectif** : Monter le système de fichiers du conteneur en lecture seule pour empêcher toute modification des fichiers de l'image. Les répertoires nécessitant un accès en écriture (tmp, run) sont montés en tmpfs (RAM). Les données persistantes sont gérées via des volumes nommés.
> **Pre-requis** : Identifier tous les chemins où l'application écrit (logs, caches, sockets, PID files) pour les monter en tmpfs ou en volumes.

```bash
# --read-only       : monte le rootfs du conteneur en lecture seule
# --tmpfs /run      : monte /run en tmpfs (RAM, isolé au conteneur) pour sockets, PID
# --tmpfs /tmp      : monte /tmp en tmpfs pour les fichiers temporaires
# -v data:/var/lib/app : monte un volume nommé pour les données persistantes (seul chemin en écriture)
docker run --read-only --tmpfs /tmp --tmpfs /run \
  -v data:/var/lib/app ...
```

> **Resultat attendu** :
> ```
> $ docker run --rm --read-only --tmpfs /tmp --tmpfs /run -v data:/var/lib/app monimage
> $ docker exec ct touch /etc/test
> touch: /etc/test: Read-only file system
> $ docker exec ct touch /tmp/test   # OK, /tmp est en tmpfs
> $ docker exec ct touch /var/lib/app/test  # OK, volume monté RW
> ```
> **Verification** : Toute écriture hors tmpfs/volume échoue avec "Read-only file system". Les répertoires tmpfs et volumes fonctionnent en écriture.

> Identifiez tous les chemins en écriture (logs, caches, sockets) et isolez-les.

### 5.6 **no-new-privileges**

> **Objectif** : Activer le flag `no_new_privs` du noyau Linux qui empêche le conteneur et ses processus enfants d'acquérir de nouveaux privilèges via `setuid`, `setgid`, capabilities de fichiers, ou tout autre mécanisme d'élévation. C'est une protection contre les escalades de privilèges.
> **Pre-requis** : Docker installé. Aucune dépendance supplémentaire.

```bash
# --security-opt no-new-privileges:true : active le flag no_new_privs
# Empêche setuid binaries, file capabilities, etc. de fonctionner
docker run --security-opt no-new-privileges:true ...
```

> **Resultat attendu** :
> ```
> $ docker run --rm --security-opt no-new-privileges:true monimage
> $ grep NoNewPrivs /proc/1/status
> NoNewPrivs:       1
> # Un binaire setuid comme "passwd" ne pourra pas élever les privilèges
> ```
> **Verification** : `NoNewPrivs: 1` dans `/proc/1/status` confirme l'activation. Les binaires setuid s'exécutent mais sans élévation effective.

### 5.7 **sysctl** et limites

* Docker autorise quelques `--sysctl` (réseau, noyau restreint) :

> **Objectif** : Configurer des paramètres noyau (sysctl) au niveau du conteneur pour durcir la pile réseau : désactiver le forwarding IP (le conteneur n'est pas un routeur) et activer les SYN cookies (protection contre les attaques SYN flood).
> **Pre-requis** : Docker installé. Les sysctl réseau (`net.*`) sont autorisés dans les namespaces réseau des conteneurs. Les sysctl noyau (`kernel.*`) ne sont pas autorisés par défaut.

```bash
# --sysctl net.ipv4.ip_forward=0     : désactive le forwarding IP (pas de routage entre interfaces)
# --sysctl net.ipv4.tcp_syncookies=1 : active les SYN cookies (protection anti SYN flood)
docker run --sysctl net.ipv4.ip_forward=0 --sysctl net.ipv4.tcp_syncookies=1 ...
```

> **Resultat attendu** :
> ```
> $ docker run --rm --sysctl net.ipv4.ip_forward=0 --sysctl net.ipv4.tcp_syncookies=1 monimage
> $ docker exec ct sysctl net.ipv4.ip_forward net.ipv4.tcp_syncookies
> net.ipv4.ip_forward = 0
> net.ipv4.tcp_syncookies = 1
> ```
> **Verification** : Les valeurs sysctl sont appliquées dans le namespace réseau du conteneur.

* Toujours combiner avec **limites cgroup** (`--cpus`, `--memory`, `--pids-limit`, `--ulimit`).

### 5.8 **Devices** & host features

* Éviter `--device` ; si requis, cibler **un device précis** et **RO** si possible.
* **Jamais** `--privileged` en prod (sauf cas d'outillage isolé, court et contrôlé).

---

## 6) Sécurité **build** & secrets

### 6.1 Secrets **pendant le build** (BuildKit)

> **Objectif** : Injecter un secret (ici un token NPM) pendant le build sans qu'il ne soit stocké dans les couches de l'image. Le secret est monté temporairement en mémoire via BuildKit et n'est accessible que pendant l'exécution de la commande `RUN`.
> **Pre-requis** : BuildKit activé (`DOCKER_BUILDKIT=1` ou `docker buildx build`). Le fichier `.npm_token` doit exister localement. Utiliser `--secret` à la commande `docker build`.

```dockerfile
# Commande de build : docker build --secret id=npm_token,src=.npm_token .
# Le secret est identifié par "npm_token" et sa source est le fichier .npm_token

# --mount=type=secret,id=npm_token : monte le secret en lecture seule à /run/secrets/npm_token
# Le secret n'existe que pendant cette instruction RUN, jamais dans une couche
RUN --mount=type=secret,id=npm_token \
    # Lit le token depuis le fichier secret monté et l'exporte comme variable d'environnement
    # npm ci utilise ce token pour accéder aux packages privés du registre
    export NPM_TOKEN=$(cat /run/secrets/npm_token) && npm ci
```

> **Resultat attendu** :
> ```
> $ docker build --secret id=npm_token,src=.npm_token -t monapp .
> [+] Building 12.3s (8/8) FINISHED
>  => [internal] load build definition from Dockerfile
>  => [build 4/5] RUN --mount=type=secret,id=npm_token ...
> # L'image finale ne contient AUCUNE trace du token
> $ docker history monapp  # aucune couche ne contient le secret
> ```
> **Verification** : `docker history` et `docker save` ne révèlent aucun secret. Le fichier `.npm_token` n'apparaît dans aucune couche.

> Les secrets **ne finissent pas** dans les couches.

### 6.2 Secrets **au runtime** (Compose)

> **Objectif** : Injecter des secrets au runtime via Docker Compose. Les secrets sont définis comme des fichiers locaux et montés dans le conteneur sous `/run/secrets/` en tant que fichiers temporaires (tmpfs). Cela évite d'exposer les secrets via des variables d'environnement (visibles dans `docker inspect`, les logs, etc.).
> **Pre-requis** : Docker Compose v2+. Le fichier `./secrets/jwt.key` doit exister sur l'hôte.

```yaml
services:
  api:
    # Liste des secrets à monter dans le conteneur
    # Chaque secret devient un fichier dans /run/secrets/<nom_du_secret>
    secrets: [ jwt_key ]
# Définition des secrets : source = fichier local sur l'hôte
secrets:
  jwt_key:
    file: ./secrets/jwt.key  # chemin relatif au docker-compose.yml
```

> **Resultat attendu** :
> ```
> $ docker compose up -d
> $ docker compose exec api cat /run/secrets/jwt_key
> <contenu_de_la_clé_jwt>
> # Le secret est monté en tmpfs, invisible depuis l'extérieur du conteneur
> ```
> **Verification** : Le fichier `/run/secrets/jwt_key` est accessible dans le conteneur. `docker inspect` ne montre pas la valeur du secret.

* Montés **comme fichiers** sous `/run/secrets/...`.
* Éviter les **variables d'environnement** pour secrets (dump faciles, journaux).

### 6.3 Coffres & gestion centralisée

* **Vault**, **AWS/GCP/Azure Secrets**, **SOPS/age** (décryptage à l'exécution).
* Rotation, révocation, principe **pull** par l'app (token court).

---

## 7) Réseau & exposition

* **Aucun** port inutile ; lier sur **127.0.0.1** et exposer via un **reverse-proxy** TLS.
* Backends sur réseau **`--internal`** (pas d'egress), frontaux sur réseau dédié.
* Éviter `--network host` en prod ; le réserver à des agents techniques si besoin prouvé.

---

## 8) Supply chain : **signatures, SBOM, scans, policies**

### 8.1 Scans & seuils

* **Trivy / Docker Scout** en CI : échouer si CVE **HIGH/CRITICAL** au-dessus d'un seuil.
* Scans **licences** (bloquer GPL-3 si politique interne, p.ex.).

### 8.2 Signatures

* **Docker Content Trust** (Notary v1) :
  `export DOCKER_CONTENT_TRUST=1` (sign/verify sur `docker pull/push`).
* **cosign (Sigstore)** :

> **Objectif** : Signer une image container avec cosign (Sigstore) pour garantir son authenticité et son intégrité, puis vérifier la signature avant déploiement. Cela permet de s'assurer que l'image provient bien de la source attendue et n'a pas été altérée.
> **Pre-requis** : `cosign` installé. Une paire de clés cosign générée (`cosign generate-key-pair`) ou un certificat OIDC pour le mode keyless. Le registre doit supporter les artefacts OCI.

```bash
# Signe l'image avec la clé privée cosign
# La signature est stockée comme artefact OCI dans le registre (à côté de l'image)
cosign sign registry.example.com/team/app:1.4.2

# Vérifie la signature de l'image avec la clé publique
# Échoue si la signature est invalide ou absente
cosign verify registry.example.com/team/app:1.4.2
```

> **Resultat attendu** :
> ```
> $ cosign sign registry.example.com/team/app:1.4.2
> Pushing signature to: registry.example.com/team/app:sha256-<digest>.sig
> $ cosign verify registry.example.com/team/app:1.4.2
> Verification is done -- digest: sha256:<digest>
> ```
> **Verification** : `cosign verify` affiche "Verification is done" avec le digest de l'image signée.

*Keyless OIDC* possible ; signatures stockées comme artefacts OCI.

### 8.3 SBOM & provenance

* Buildx :

> **Objectif** : Générer un SBOM (Software Bill of Materials) et des attestations de provenance lors du build. Le SBOM liste tous les composants logiciels inclus dans l'image (dépendances, versions, licences). La provenance atteste de l'origine du build (Dockerfile, contexte, paramètres). Les deux sont stockés comme attestations OCI dans le registre.
> **Pre-requis** : Docker Buildx avec support des attestations (BuildKit v0.11+). Accès en push vers le registre.

```bash
# --sbom        : génère un SBOM au format SPDX et l'attache à l'image
# --provenance  : génère une attestation de provenance (source, build args, etc.)
# -t ... --push : tag et pousse l'image avec ses attestations vers le registre
docker buildx build --sbom --provenance \
  -t registry.example.com/team/app:1.4.2 --push .
```

> **Resultat attendu** :
> ```
> $ docker buildx build --sbom --provenance -t registry.example.com/team/app:1.4.2 --push .
> [+] Building 45.2s (12/12) FINISHED
>  => [internal] pushing registry.example.com/team/app:1.4.2
>  => [internal] attaching sbom
>  => [internal] attaching provenance
> # Les attestations sont visibles dans le registre
> ```
> **Verification** : `docker buildx imagetools inspect registry.example.com/team/app:1.4.2` affiche les attestations SBOM et provenance.

* Conserver SBOM/attestations au registry ; politiques **deny** si manquants.

### 8.4 Politiques d'admission (standalone)

* Contrôles **pré-déploiement** en CI : **conftest/OPA** (Dockerfile/Compose) pour refuser :

  * `latest`, `--privileged`, absence de `USER`, pas de `healthcheck`, ports wildcard, etc.
* **Promotion par digest** uniquement (voir Ch-07).

---

## 9) Journalisation, audit & supervision

* **Audit des commandes Docker** :

  * surveiller `/var/run/docker.sock` (auditd),
  * centraliser les logs `dockerd` (journald/syslog),
  * tracer les **images tirées** / **tags déployés** (digests).
* **Logs des conteneurs** : rotation (`json-file`), export vers **Fluent Bit/ELK**.
* **Métriques** : cAdvisor/Node Exporter → Prometheus/Grafana ; alertes sur OOMKill, redémarrages, disque.

---

## 10) Hardening de l'hôte (rappels)

* Kernel & paquets **à jour**, reboot sécurité planifié.
* **Pare-feu** par défaut DROP (ou politique claire), SSH durci (MFA, clés).
* **FS chiffré** (LUKS) pour `/var/lib/docker` si sensible ; sauvegardes chiffrées.
* **NTP** fiable (horloge = TLS, signatures, journaux cohérents).
* Minimiser les **composants** sur l'hôte (pas d'apps superflues).

---

## 11) Exemples "prod-like" (runtime & compose)

### 11.1 `docker run` durci

> **Objectif** : Lancer un conteneur en production avec un durcissement maximal : limites de ressources (CPU, mémoire, PIDs), filesystem read-only avec tmpfs, capabilities minimales, profil seccomp custom, exécution non-root, réseau isolé, et image épinglée par digest SHA256 pour garantir l'intégrité.
> **Pre-requis** : Image poussée sur le registre avec un digest SHA256 connu. Réseau Docker `backend` créé (`docker network create backend`). Profil seccomp disponible en `/etc/docker/seccomp-restrict.json`.

```bash
docker run -d --name api \
  # --- Limites de ressources cgroup ---
  --cpus=1.0 \              # limite à 1 CPU (évite la monopolisation du processeur)
  --memory=512m \           # limite la RAM à 512 Mo (protection OOM)
  --pids-limit=256 \        # limite le nombre de processus/PIDs à 256 (anti fork-bomb)
  # --- Filesystem ---
  --read-only \             # rootfs en lecture seule (empêche toute modification)
  --tmpfs /run \            # /run en RAM (sockets, PID files)
  --tmpfs /tmp \            # /tmp en RAM (fichiers temporaires)
  # --- Capabilities ---
  --cap-drop=ALL \          # supprime TOUTES les capabilities
  --cap-add=NET_BIND_SERVICE \  # ajoute uniquement le bind sur ports <1024
  # --- Sécurité noyau ---
  --security-opt no-new-privileges:true \  # empêche l'élévation de privilèges
  --security-opt seccomp=/etc/docker/seccomp-restrict.json \  # profil seccomp personnalisé
  # --- Utilisateur ---
  -u 10001:10001 \          # exécute en tant qu'utilisateur non-root (UID:GID 10001)
  # --- Réseau ---
  --network backend \       # connecte au réseau isolé "backend"
  # --- Image par digest (intégrité garantie, pas de tag mutable) ---
  ghcr.io/acme/api@sha256:<digest>
```

> **Resultat attendu** :
> ```
> $ docker run -d --name api --cpus=1.0 --memory=512m --pids-limit=256 \
>   --read-only --tmpfs /run --tmpfs /tmp \
>   --cap-drop=ALL --cap-add=NET_BIND_SERVICE \
>   --security-opt no-new-privileges:true \
>   --security-opt seccomp=/etc/docker/seccomp-restrict.json \
>   -u 10001:10001 --network backend \
>   ghcr.io/acme/api@sha256:abc123...
> a1b2c3d4e5f6...
> $ docker inspect api --format '{{.State.Status}}'
> running
> ```
> **Verification** : Le conteneur est `running`. `docker inspect api` confirme les limites, le read-only, les capabilities, le profil seccomp, l'UID 10001 et le réseau backend.

### 11.2 Compose durci (extrait)

> **Objectif** : Définir un service Docker Compose avec toutes les bonnes pratiques de sécurité : image épinglée par digest, utilisateur non-root, filesystem read-only, tmpfs, capabilities minimales, profil seccomp, healthcheck pour la détection de panne, et réseau bridge interne (pas d'accès Internet sortant).
> **Pre-requis** : Docker Compose v2+. Profil seccomp disponible en `/etc/docker/seccomp-restrict.json` sur l'hôte. L'image est accessible sur le registre avec son digest.

```yaml
services:
  api:
    # --- Image épinglée par digest SHA256 (intégrité garantie) ---
    image: ghcr.io/acme/api@sha256:...
    # --- Exécution non-root : UID:GID 10001 ---
    user: "10001:10001"
    # --- Filesystem en lecture seule ---
    read_only: true
    # --- Répertoires temporaires en RAM (seuls chemins en écriture) ---
    tmpfs: [ /run, /tmp ]
    # --- Capabilities : tout supprimer, puis ajouter uniquement le nécessaire ---
    cap_drop: [ "ALL" ]              # supprime TOUTES les capabilities
    cap_add: [ "NET_BIND_SERVICE" ]  # ajoute uniquement le bind sur ports <1024
    # --- Options de sécurité noyau ---
    security_opt:
      - no-new-privileges:true                              # empêche l'élévation de privilèges
      - seccomp:/etc/docker/seccomp-restrict.json           # profil seccomp personnalisé
      # - apparmor:my-profile          # si profil custom (décommenter si utilisé)
    # --- Healthcheck : détection automatique des conteneurs défaillants ---
    healthcheck:
      # Teste le endpoint /health toutes les 30s via curl
      test: ["CMD-SHELL","curl -fsS http://localhost:8080/health || exit 1"]
      interval: 30s    # vérification toutes les 30 secondes
      timeout: 5s      # échec si pas de réponse en 5 secondes
      retries: 3       # 3 échecs consécutifs = conteneur marqué "unhealthy"
    # --- Réseau : isolé sur le bridge "backend" ---
    networks:
      - backend
networks:
  backend:
    driver: bridge
    internal: true    # réseau interne : pas d'accès Internet sortant (egress bloqué)
```

> **Resultat attendu** :
> ```
> $ docker compose up -d
> ✔ Network api_backend  Created
> ✔ Container api-api-1  Started
> $ docker compose ps
> NAME        STATUS                   PORTS
> api-api-1   Up (healthy)             8080/tcp
> $ docker inspect api-api-1 --format '{{.State.Health.Status}}'
> healthy
> ```
> **Verification** : Le conteneur est `Up (healthy)`. `docker inspect` confirme `read_only`, `no-new-privileges`, `cap_drop: ALL`, le réseau `internal: true`, et l'`user: 10001:10001`.

---

## 12) Dépannage sécurité — cas fréquents

* **Permission denied** sur volume (SELinux) → utiliser `:Z/:z` (RHEL/Fedora) ; vérifier UID/GID (userns-remap).
* **Syscall bloqué** (seccomp) → valider le besoin réel ; ajuster **profil** minimal.
* **Service inaccessible** depuis l'extérieur → vérifier que l'app écoute sur `0.0.0.0` (pas `127.0.0.1`), règles iptables, IP de bind `-p`.
* **Rootless** : ports <1024 indisponibles → publier via reverse-proxy/port >1024.

---

## 13) Aide-mémoire (cheat-sheet)

> **Objectif** : Regrouper les commandes les plus courantes pour le durcissement Docker en une référence rapide. Couvre la vérification de configuration, l'activation de userns-remap, le mode rootless, un run durci, la vérification des capabilities, la signature cosign et le scan Trivy.
> **Pre-requis** : Docker installé. `cosign` et `trivy` installés pour les sections correspondantes. Accès root pour les commandes `sudo`.

```bash
# ============================
# VÉRIFIER LA CONFIGURATION DU DÉMON
# ============================

# Affiche les informations globales du démon (drivers, sécurité, version, etc.)
docker info

# Affiche la configuration complète du démon (daemon.json)
cat /etc/docker/daemon.json

# ============================
# ACTIVER USERNS-REMAP
# ============================

# Modifie daemon.json pour ajouter "userns-remap": "default" avant l'accolade fermante
# sed remplace "}" par ', "userns-remap": "default"}'
sudo sed -i 's/}/, "userns-remap": "default"}/' /etc/docker/daemon.json
# Redémarre Docker pour appliquer la configuration
# ATTENTION : tous les conteneurs en cours seront arrêtés
sudo systemctl restart docker

# ============================
# LANCER EN MODE ROOTLESS (session utilisateur)
# ============================

# Installe les unités systemd utilisateur pour dockerd rootless
dockerd-rootless-setuptool.sh install
# Configure le client Docker pour communiquer avec le démon rootless
# (1000 = UID de l'utilisateur courant, adapter si nécessaire)
export DOCKER_HOST=unix:///run/user/1000/docker.sock

# ============================
# RUN DURCI (commande complète)
# ============================

# Lance un conteneur avec tous les durcissements :
# --read-only     : rootfs en lecture seule
# --tmpfs /tmp    : /tmp en RAM
# --cap-drop=ALL  : supprime toutes les capabilities
# --cap-add=NET_BIND_SERVICE : ajoute uniquement bind ports <1024
# --security-opt no-new-privileges:true : empêche élévation de privilèges
# -u 10001:10001  : exécute en non-root
# IMAGE@sha256:... : image épinglée par digest
docker run -d --read-only --tmpfs /tmp --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE --security-opt no-new-privileges:true \
  -u 10001:10001 IMAGE@sha256:...

# ============================
# VÉRIFIER LES CAPABILITIES EFFECTIVES
# ============================

# Exécute capsh dans le conteneur "ct" pour afficher les capabilities
# capsh --print montre : Current, Bounding, Inheritable, Permitted, Effective
docker exec ct capsh --print

# ============================
# COSIGN (SIGNER / VÉRIFIER UNE IMAGE)
# ============================

# Signe l'image avec la clé privée cosign (la signature est stockée dans le registre)
cosign sign registry.example.com/team/app:1.4.2
# Vérifie la signature de l'image avec la clé publique
# Retourne "Verification is done" si valide, erreur sinon
cosign verify registry.example.com/team/app:1.4.2

# ============================
# TRIVY (SCAN DE VULNÉRABILITÉS)
# ============================

# Scanne l'image et affiche uniquement les vulnérabilités HIGH et CRITICAL
# Utile en CI pour bloquer le déploiement si des CVEs critiques sont détectées
trivy image --severity HIGH,CRITICAL registry.example.com/team/app:1.4.2
```

> **Resultat attendu** :
> ```
> $ docker info | grep -E "Security|userns|Rootless"
>  Security Options: seccomp, cgroupns
>  userns: true
> $ docker exec ct capsh --print
> Current: = cap_net_bind_service
> Bounding set =cap_net_bind_service
> $ trivy image --severity HIGH,CRITICAL registry.example.com/team/app:1.4.2
> Total: 0 (HIGH: 0, CRITICAL: 0)
> ```
> **Verification** : Chaque commande produit le résultat attendu. `docker info` confirme la configuration de sécurité, `capsh` montre les capabilities restreintes, `trivy` ne trouve aucune CVE HIGH/CRITICAL sur une image saine.

---

## 14) Checklist de clôture (sécurité opérationnelle)

**Hôte & démon**

* `dockerd` à jour, `live-restore: true`, `log-driver` + **rotation**.
* API **non exposée** ou **TLS mutuel** + pare-feu.
* **userns-remap** activé **ou** Docker **rootless** si adapté.

**Images & build**

* **.dockerignore**, multi-stage, **USER non-root**, labels OCI.
* BuildKit : `--mount=type=secret/ssh` (zéro secret dans les couches).
* **SBOM + provenance** générés ; scans CVE/licences en CI.

**Registry & déploiement**

* TLS + auth, **proxy cache**, politique **immutabilité** des tags prod.
* **Signatures** (DCT/cosign) **vérifiées** ; déploiement **par digest**.

**Runtime**

* **read-only**, **tmpfs**, **cap-drop=ALL** + ajouts ciblés, **no-new-privileges**.
* **seccomp** (défaut/custom), **AppArmor/SELinux** actifs.
* Limites cgroup (CPU/MEM/PIDs), healthchecks, restart policy.

**Réseau & secrets**

* Réseaux séparés, backends en `--internal`, ports explicitement mappés.
* Secrets en **fichiers** (Compose) ou coffre externe ; rotation.

**Observabilité & audit**

* Logs centralisés, métriques/alertes, audit de la **socket** Docker.
* Procédures d'IR (forensic) et PRA testées (sauvegardes/restores de volumes).
