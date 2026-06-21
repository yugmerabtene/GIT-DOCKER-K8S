# Chapitre-03 — Storage (volumes, bind mounts, tmpfs)

## Objectifs d'apprentissage

* Choisir et configurer le **bon type de montage** (bind, volume, tmpfs) selon le besoin.
* Maîtriser les **permissions** (UID/GID), **SELinux** (`:Z/:z`) et les options de montage (`ro`, propagation).
* Savoir **sauvegarder/restaurer/migrer** des données de conteneurs proprement.
* Durcir l'exécution avec **rootfs en lecture seule** (`--read-only`) et points d'écriture contrôlés.

## Pré-requis

* Docker Engine/CLI opérationnel, bases Linux (permissions, chemins).
* Notions réseau si NFS/SMB sont utilisés.

---

## 1) Panorama : bind vs volume vs tmpfs

| Type       | Déclaration (exemples)                                                            | Cas d'usage typiques                                  | Avantages                              | Points d'attention                         |
| ---------- | --------------------------------------------------------------------------------- | ----------------------------------------------------- | -------------------------------------- | ------------------------------------------ |
| **Bind**   | `-v /host/path:/ctr/path[:opts]` ou `--mount type=bind,src=/host,dst=/ctr[:opts]` | Dev, config partagée, logs, fichiers hôte ↔ conteneur | Simple, direct                         | Permissions hôte, masquage, sécurité       |
| **Volume** | `-v volname:/ctr/path` ou `--mount type=volume,src=volname,dst=/ctr`              | Données applicatives (DB, blobs)                      | Isolé de l'arbo hôte, lifecycle Docker | Visible via Docker, pas de chemin "humain" |
| **tmpfs**  | `--tmpfs /ctr/path[:opts]` ou `--mount type=tmpfs,dst=/ctr/path,tmpfs-size=64m`   | Caches, fichiers temporaires sensibles/perf           | En RAM, rapide, disparaît à l'arrêt    | Volatile, limite mémoire                   |

**Règle d'or :**

* **Volume** pour **données persistantes** (DB, state applicatif).
* **Bind** pour **fichiers du projet** (dev) ou dépôts de **configs/logs**.
* **tmpfs** pour **temporaire** et **performances** (cache, `/tmp`, `/run`).

---

## 2) Syntaxe `-v` vs `--mount`

* **Court (`-v`)** : historique, compact, pratique.
  `-v SRC:DST[:OPTIONS]`
* **Verbeux (`--mount`)** : lisible, options explicites, recommandé en prod.
  `--mount type=bind,source=/src,destination=/dst,ro,bind-propagation=rshared`

**Synonymes** : `source` = `src`, `destination` = `dst` = `target`.

---

## 3) Volumes nommés (cycle de vie complet)

### 3.1 Créer / lister / inspecter / supprimer

> **Objectif** : Gérer le cycle de vie complet d'un volume Docker nommé — création avec label, recherche par label, inspection des métadonnées, suppression unitaire et nettoyage global des volumes orphelins.
> **Pré-requis** : Docker Engine démarré, aucun conteneur en cours d'exécution utilisant le volume `data_pg`.

```bash
# Créer un volume nommé "data_pg" avec un label "app=db" pour faciliter le filtrage
docker volume create --label app=db data_pg

# Lister tous les volumes portant le label "app=db" (filtrage par label)
docker volume ls --filter label=app=db

# Afficher les métadonnées complètes du volume (chemin hôte, driver, labels, etc.)
docker volume inspect data_pg

# Supprimer le volume "data_pg" — échoue si un conteneur l'utilise encore
docker volume rm data_pg               # échoue si utilisé

# Supprimer tous les volumes non référencés par un conteneur (nettoyage orphelins)
docker volume prune -f                 # supprime volumes orphelins
```

> **Résultat attendu** :
> ```
> $ docker volume create --label app=db data_pg
> data_pg
>
> $ docker volume ls --filter label=app=db
> DRIVER    VOLUME NAME
> local     data_pg
>
> $ docker volume inspect data_pg
> [
>   {
>     "CreatedAt": "2025-06-21T10:00:00Z",
>     "Driver": "local",
>     "Labels": { "app": "db" },
>     "Mountpoint": "/var/lib/docker/volumes/data_pg/_data",
>     "Name": "data_pg",
>     "Options": {},
>     "Scope": "local"
>   }
> ]
>
> $ docker volume rm data_pg
> data_pg
>
> $ docker volume prune -f
> Deleted Volumes:
> local/orphan_vol_1
> local/orphan_vol_2
> ```
> **Vérification** : Après `create`, le volume apparaît dans `docker volume ls`. Après `rm`, il disparaît. `prune` ne supprime que les volumes non liés à un conteneur.

### 3.2 Monter un volume

> **Objectif** : Monter un volume nommé dans un conteneur pour y persister les données de PostgreSQL, en comparant les deux syntaxes (`-v` et `--mount`).
> **Pré-requis** : Volume `data_pg` créé au préalable (ou Docker le créera automatiquement), image `postgres:16` disponible localement.

```bash
# Syntaxe courte : monter le volume "data_pg" sur le chemin de données PostgreSQL
# Docker crée le volume automatiquement s'il n'existe pas encore
docker run -d --name pg -v data_pg:/var/lib/postgresql/data postgres:16

# Syntaxe --mount (équivalente) : plus explicite, recommandée en production
# type=volume indique un volume nommé, src=source, dst=destination dans le conteneur
docker run -d --name pg \
  --mount type=volume,src=data_pg,dst=/var/lib/postgresql/data \
  postgres:16
```

> **Résultat attendu** :
> ```
> $ docker run -d --name pg -v data_pg:/var/lib/postgresql/data postgres:16
> a1b2c3d4e5f6...
>
> $ docker ps
> CONTAINER ID   IMAGE         STATUS         NAMES
> a1b2c3d4e5f6   postgres:16   Up 2 seconds   pg
> ```
> **Vérification** : `docker ps` affiche le conteneur `pg` en cours d'exécution. `docker volume inspect data_pg` montre qu'un conteneur référence ce volume.

### 3.3 Pré-population d'un volume

> **Objectif** : Illustrer le mécanisme de pré-population : lorsqu'un volume **vide** est monté pour la première fois sur un chemin contenant des fichiers dans l'image, Docker copie automatiquement ces fichiers dans le volume.
> **Pré-requis** : Image `ghcr.io/acme/app:1.0` disponible, contenant des fichiers dans `/app/defaults`.

Un volume **vide** monté sur un chemin contenant des fichiers **copie** le contenu de l'image **dans le volume** au premier montage.

```bash
# Lancer un conteneur éphémère (--rm) qui monte "myvol" sur /app
# Comme myvol est vide au premier montage, Docker copie le contenu de /app
# depuis l'image vers le volume, y compris /app/defaults
docker run --rm -v myvol:/app ghcr.io/acme/app:1.0
# myvol est désormais pré-populé avec /app depuis l'image
```

> **Résultat attendu** :
> ```
> $ docker run --rm -v myvol:/app ghcr.io/acme/app:1.0
> (le conteneur s'exécute et se termine)
>
> $ docker run --rm -v myvol:/data alpine ls /data/defaults
> config.yaml
> schema.sql
> ```
> **Vérification** : Après l'exécution, `myvol` contient les fichiers qui étaient dans `/app` de l'image. Un second montage confirme la persistance des données copiées.

### 3.4 Initialiser depuis un répertoire local

> **Objectif** : Copier des fichiers depuis un répertoire de l'hôte (`$PWD/seed`) vers un volume Docker nommé (`data_app`) en utilisant un conteneur utilitaire Alpine éphémère.
> **Pré-requis** : Un répertoire `seed/` existe dans le répertoire courant avec les fichiers à copier, volume `data_app` créé ou auto-créé.

```bash
# Lancer un conteneur Alpine éphémère (--rm) avec deux montages :
#   1. data_app monté en lecture/écriture sur /dest (destination)
#   2. $PWD/seed monté en lecture seule sur /seed (source)
# Puis copier récursivement tout le contenu de /seed/ vers /dest/
# L'option -a préserve les permissions, timestamps, liens symboliques
docker run --rm \
  -v data_app:/dest \
  -v $PWD/seed:/seed:ro \
  alpine sh -c "cp -a /seed/. /dest/"
```

> **Résultat attendu** :
> ```
> $ ls seed/
> init.sql  config.yaml  seed-data.csv
>
> $ docker run --rm -v data_app:/dest -v $PWD/seed:/seed:ro \
>   alpine sh -c "cp -a /seed/. /dest/"
> (pas de sortie en cas de succès)
>
> $ docker run --rm -v data_app:/data alpine ls /data
> config.yaml
> init.sql
> seed-data.csv
> ```
> **Vérification** : Le volume `data_app` contient maintenant les fichiers du répertoire `seed/`. Les permissions d'origine sont préservées grâce à `cp -a`.

---

## 4) Bind mounts (montages hôte ↔ conteneur)

### 4.1 Base et options

> **Objectif** : Monter un répertoire de l'hôte dans un conteneur en lecture/écriture, puis en lecture seule, et montrer l'équivalence avec la syntaxe `--mount`.
> **Pré-requis** : Un répertoire `config/` existe dans le répertoire courant (`$PWD/config`), image `ghcr.io/acme/app:1.0` disponible.

```bash
# Montage bind en lecture/écriture (mode par défaut)
# Le répertoire $PWD/config de l'hôte est accessible en /app/config dans le conteneur
# Toute modification côté hôte est visible dans le conteneur et inversement
docker run -v $PWD/config:/app/config ghcr.io/acme/app:1.0

# Montage bind en lecture seule (:ro)
# Le conteneur peut lire /app/config mais ne peut PAS y écrire
# Utile pour des fichiers de configuration qui ne doivent pas être modifiés par l'app
docker run -v $PWD/config:/app/config:ro ghcr.io/acme/app:1.0

# Version --mount équivalente au montage bind en lecture seule
# Plus explicite : type=bind, src=source hôte, dst=destination conteneur, ro=lecture seule
docker run --mount type=bind,src=$PWD/config,dst=/app/config,ro ghcr.io/acme/app:1.0
```

> **Résultat attendu** :
> ```
> $ docker run -v $PWD/config:/app/config:ro ghcr.io/acme/app:1.0
> (le conteneur démarre et peut lire /app/config/app.conf)
>
> # Si l'app tente d'écrire :
> Error: EROFS: read-only file system, open '/app/config/app.conf'
> ```
> **Vérification** : Les fichiers de `$PWD/config` sont accessibles dans le conteneur. En mode `:ro`, toute tentative d'écriture échoue avec une erreur `EROFS`.

### 4.2 Propagation (bind-propagation)

> **Objectif** : Configurer la propagation des montages entre l'hôte et le conteneur. Par défaut `rprivate` (aucune propagation), ici `rshared` pour propager les montages enfants dans les deux sens.
> **Pré-requis** : Le point de montage hôte `/mnt/parent` doit lui-même être monté en `rshared` au niveau du système hôte. Cas avancé, rare hors orchestrateurs.

* **Par défaut** : `rprivate` (pas de propagation).
* Pour propager des montages enfants (cas avancés) :

```bash
# Monter /mnt/parent de l'hôte dans le conteneur avec propagation "rshared"
# bind-propagation=rshared : tout montage créé dans /mnt/parent (hôte OU conteneur)
# sera visible de l'autre côté — propagation récursive dans les deux sens
docker run --mount \
  type=bind,src=/mnt/parent,dst=/mnt/parent,bind-propagation=rshared \
  ghcr.io/acme/app:1.0
```

> Le point **hôte** doit lui-même être monté en **rshared** (côté système). Cas rares hors orchestrateur.

> **Résultat attendu** :
> ```
> $ docker run --mount type=bind,src=/mnt/parent,dst=/mnt/parent,bind-propagation=rshared ...
> (le conteneur démarre)
>
> # Si on monte un périphérique sur l'hôte dans /mnt/parent/usb :
> mount /dev/sdb1 /mnt/parent/usb
> # → /mnt/parent/usb est automatiquement visible dans le conteneur
> ```
> **Vérification** : Un montage créé côté hôte sous `/mnt/parent/` apparaît automatiquement dans le conteneur, et vice-versa. `findmnt -o TARGET,PROPAGATION` confirme le type de propagation.

### 4.3 Masquage (gotcha)

Un bind sur `/ctr/path` **masque** ce que l'image avait à cet emplacement.
→ **Vérifier** que le conteneur ne dépend pas de fichiers de l'image à ce chemin.

---

## 5) tmpfs (mémoire)

### 5.1 Montage tmpfs simple

> **Objectif** : Monter un système de fichiers temporaire en RAM sur `/tmp` dans le conteneur. Les données sont volatiles et disparaissent à l'arrêt du conteneur.
> **Pré-requis** : Image `ghcr.io/acme/app:1.0` disponible.

```bash
# Monter un tmpfs sur /tmp dans le conteneur
# Les écritures dans /tmp vont en RAM (pas sur disque), rapides et volatiles
# Le tmpfs disparaît complètement quand le conteneur est arrêté/supprimé
docker run --tmpfs /tmp -d ghcr.io/acme/app:1.0
```

> **Résultat attendu** :
> ```
> $ docker run --tmpfs /tmp -d ghcr.io/acme/app:1.0
> f7a8b9c0d1e2...
>
> $ docker exec f7a8b9c0d1e2 df -h /tmp
> Filesystem   Size  Used Avail Use% Mounted on
> tmpfs        3.9G     0  3.9G   0% /tmp
> ```
> **Vérification** : `df -h /tmp` dans le conteneur montre un filesystem de type `tmpfs` en RAM. Après `docker stop`, les données dans `/tmp` sont perdues.

### 5.2 Taille et mode

> **Objectif** : Monter un tmpfs avec des options avancées : taille limitée à 64 Mo et permissions `1777` (sticky bit, accessible à tous en écriture mais suppression restreinte).
> **Pré-requis** : Image `ghcr.io/acme/app:1.0` disponible.

```bash
# Monter un tmpfs sur /run avec :
#   tmpfs-size=64m  → limite la taille à 64 Mo (évite la consommation RAM illimitée)
#   tmpfs-mode=1777 → permissions : tous peuvent écrire, sticky bit (comme /tmp standard)
docker run --mount type=tmpfs,dst=/run,tmpfs-size=64m,tmpfs-mode=1777 \
  -d ghcr.io/acme/app:1.0
```

> **Résultat attendu** :
> ```
> $ docker exec <container> df -h /run
> Filesystem   Size  Used Avail Use% Mounted on
> tmpfs         64M     0   64M   0% /run
>
> $ docker exec <container> stat -c "%a" /run
> 1777
> ```
> **Vérification** : `df -h /run` confirme la taille limitée à 64 Mo. `stat -c "%a" /run` affiche `1777`. Écrire plus de 64 Mo provoque une erreur `No space left on device`.

* **Volatile** : disparaît à l'arrêt.
* **Idéal** pour caches/temp (rapide, pas sur disque).

---

## 6) Permissions & UID/GID

### 6.1 Alignement hôte ↔ conteneur

> **Objectif** : Exécuter un conteneur avec un utilisateur non-root (UID/GID 10001) et monter un volume. Le noyau appliquant les UID/GID directement, les permissions du volume doivent correspondre.
> **Pré-requis** : Volume `data_app` créé, image `ghcr.io/acme/app:1.0` configurée pour fonctionner avec l'UID 10001.

Le noyau applique les **UID/GID** : si l'app tourne en `10001:10001`, l'hôte doit **autoriser** ces UID/GID.

```bash
# Exécuter l'app en tant qu'utilisateur non-root (UID=10001, GID=10001)
# Le volume data_app est monté sur /data
# ATTENTION : si /data appartient à root, l'UID 10001 n'aura pas accès → EACCES
docker run -u 10001:10001 -v data_app:/data ghcr.io/acme/app:1.0
```

> **Résultat attendu** :
> ```
> $ docker run -u 10001:10001 -v data_app:/data ghcr.io/acme/app:1.0
> (si le volume n'a pas le bon owner)
> Error: EACCES: permission denied, open '/data/app.db'
>
> (si le volume a le bon owner — voir 6.2)
> (l'application démarre normalement)
> ```
> **Vérification** : `docker exec <ctr> id` affiche `uid=10001 gid=10001`. `docker exec <ctr> ls -la /data` montre le propriétaire des fichiers.

### 6.2 Ajuster l'ownership

> **Objectif** : Initialiser les permissions d'un volume pour que l'utilisateur non-root (UID/GID 10001) puisse y lire et écrire. Utilise un conteneur utilitaire Alpine éphémère pour exécuter `chown`.
> **Pré-requis** : Volume `data_app` existant.

```bash
# Lancer un conteneur Alpine éphémère (--rm) en root (par défaut)
# Monter data_app sur /data, puis changer récursivement le propriétaire
# pour que UID 10001 et GID 10001 soient propriétaires de tout le contenu
docker run --rm -v data_app:/data alpine chown -R 10001:10001 /data
```

> **Résultat attendu** :
> ```
> $ docker run --rm -v data_app:/data alpine chown -R 10001:10001 /data
> (pas de sortie en cas de succès)
>
> $ docker run --rm -v data_app:/data alpine ls -la /data
> total 8
> drwxr-xr-x    2 10001    10001         4096 Jun 21 10:00 .
> drwxr-xr-x    1 root     root          4096 Jun 21 10:00 ..
> ```
> **Vérification** : `ls -la /data` dans un conteneur montre que les fichiers appartiennent à `10001:10001`. L'application peut maintenant lire/écrire sans erreur `EACCES`.

### 6.3 userns-remap (aperçu)

La remap d'UID/GID hôte/ctr change la vue des IDs. À planifier **avant** l'exploitation (impacts sur permissions et sauvegardes).

---

## 7) SELinux (`:Z` / `:z`) sur Fedora/CentOS/RHEL

* `:Z` : étiquette **privée** (confinée à ce conteneur).
* `:z` : étiquette **partagée** (plusieurs conteneurs y accèdent).

> **Objectif** : Monter un bind avec re-étiquetage SELinux automatique (`:Z`) pour que le conteneur MySQL puisse accéder au répertoire hôte `/srv/data` malgré les restrictions SELinux.
> **Pré-requis** : Système avec SELinux en mode `enforcing` (Fedora, CentOS, RHEL). Le répertoire `/srv/data` existe sur l'hôte.

```bash
# Monter /srv/data de l'hôte sur /var/lib/mysql dans le conteneur
# Le suffixe :Z demande à Docker de re-étiqueter le répertoire hôte
# avec un label SELinux privé, accessible uniquement par CE conteneur
# (utiliser :z si plusieurs conteneurs doivent y accéder)
docker run -v /srv/data:/var/lib/mysql:Z -d mysql:8
```

> Sur distributions **sans SELinux** (ex. Ubuntu), ces suffixes sont ignorés.
> Avec **AppArmor**, gérer plutôt des profils/abstractions (pas d'option `:Z`).

> **Résultat attendu** :
> ```
> $ docker run -v /srv/data:/var/lib/mysql:Z -d mysql:8
> c3d4e5f6a7b8...
>
> $ ls -Z /srv/data
> system_u:object_r:container_file_t:s0:c123,c456 data/
>
> # Sans :Z sur SELinux enforcing :
> $ docker run -v /srv/data:/var/lib/mysql -d mysql:8
> (le conteneur démarre mais MySQL ne peut pas écrire)
> mysqld: Permission denied (SELinux)
> ```
> **Vérification** : `ls -Z /srv/data` montre le label SELinux `container_file_t`. Sans `:Z`, `audit2allow` ou `dmesg | grep denied` révèle les refus SELinux.

---

## 8) Réseaux de fichiers : NFS & SMB (via driver `local`)

### 8.1 NFS (exemple)

> **Objectif** : Créer un volume Docker qui pointe vers un partage NFS distant, puis le monter dans un conteneur. Utilise le driver `local` de Docker avec les options NFS intégrées.
> **Pré-requis** : Un serveur NFS accessible à `10.0.0.50` exportant `/export/data` (NFS v4.1). Le paquet `nfs-common` (Debian/Ubuntu) ou `nfs-utils` (RHEL) doit être installé sur l'hôte Docker.

```bash
# Créer un volume Docker nommé "nfs_data" utilisant le driver local
# --opt type=nfs        : indique au driver local d'utiliser le protocole NFS
# --opt o=addr=...      : options de montage NFS :
#   addr=10.0.0.50      → adresse IP du serveur NFS
#   nfsvers=4.1         → version du protocole NFS
#   rw                  → montage en lecture/écriture
# --opt device=:/export/data : chemin exporté par le serveur NFS
docker volume create \
  --driver local \
  --opt type=nfs \
  --opt o=addr=10.0.0.50,nfsvers=4.1,rw \
  --opt device=:/export/data \
  nfs_data

# Monter le volume NFS dans un conteneur sur le chemin /data
# Le conteneur accède au partage NFS de manière transparente
docker run -d --name app \
  --mount type=volume,src=nfs_data,dst=/data \
  ghcr.io/acme/app:1.0
```

> **Résultat attendu** :
> ```
> $ docker volume create --driver local \
>   --opt type=nfs --opt o=addr=10.0.0.50,nfsvers=4.1,rw \
>   --opt device=:/export/data nfs_data
> nfs_data
>
> $ docker volume inspect nfs_data
> [
>   {
>     "Driver": "local",
>     "Mountpoint": "/var/lib/docker/volumes/nfs_data/_data",
>     "Name": "nfs_data",
>     "Options": {
>       "device": ":/export/data",
>       "o": "addr=10.0.0.50,nfsvers=4.1,rw",
>       "type": "nfs"
>     }
>   }
> ]
>
> $ docker exec app ls /data
> (contenu du partage NFS)
> ```
> **Vérification** : `docker volume inspect nfs_data` confirme les options NFS. `mount | grep nfs` sur l'hôte montre le montage NFS actif. Les fichiers écrits dans `/data` par le conteneur apparaissent sur le serveur NFS.

### 8.2 SMB/CIFS (exemple)

> **Objectif** : Créer un volume Docker pointant vers un partage SMB/CIFS distant (type Windows Share / Samba). Utilise le driver `local` avec le type `cifs` et les identifiants d'authentification.
> **Pré-requis** : Un serveur SMB accessible à `10.0.0.60` partageant `share`. Le paquet `cifs-utils` doit être installé sur l'hôte Docker.

```bash
# Créer un volume Docker nommé "smb_data" utilisant le driver local avec CIFS
# --opt type=cifs              : protocole CIFS/SMB
# --opt device=//10.0.0.60/share : chemin UNC du partage SMB
# --opt o=username=user,password=secret,uid=10001,gid=10001
#   → identifiants SMB + mapping UID/GID pour les fichiers montés
# ATTENTION : le mot de passe en clair dans la commande est un risque de sécurité
#   → préférer un fichier credentials en production
docker volume create \
  --driver local \
  --opt type=cifs \
  --opt device=//10.0.0.60/share \
  --opt o=username=user,password=secret,uid=10001,gid=10001 \
  smb_data
```

> Performance & permissions dépendent du serveur distant ; privilégier **volumes** locaux pour DBs critiques (latence/fiabilité).

> **Résultat attendu** :
> ```
> $ docker volume create --driver local \
>   --opt type=cifs --opt device=//10.0.0.60/share \
>   --opt o=username=user,password=secret,uid=10001,gid=10001 smb_data
> smb_data
>
> $ docker run --rm -v smb_data:/mnt alpine ls /mnt
> (contenu du partage SMB)
> ```
> **Vérification** : `mount | grep cifs` sur l'hôte montre le montage CIFS. Les fichiers sont accessibles avec les UID/GID mappés. Vérifier la latence avec `dd if=/dev/zero of=/mnt/test bs=1M count=100`.

---

## 9) Rootfs en lecture seule (`--read-only`) + points d'écriture

### 9.1 Patron sécurisé

> **Objectif** : Lancer un conteneur avec le système de fichiers racine en lecture seule (`--read-only`), tout en autorisant l'écriture sur des chemins spécifiques via `tmpfs` (pour `/tmp` et `/run`) et un volume nommé (pour les données applicatives). C'est un pattern de durcir (hardening) fondamental.
> **Pré-requis** : Image `ghcr.io/acme/web:1.4.2` disponible, volume `data_web` créé ou auto-créé.

```bash
# Lancer le conteneur "web" en mode sécurisé :
#   --read-only        → le rootfs (système de fichiers de l'image) est en lecture seule
#   --tmpfs /tmp       → /tmp est en RAM (nécessaire car beaucoup d'apps écrivent dans /tmp)
#   --tmpfs /run       → /run est en RAM (nécessaire pour les PID files, sockets)
#   -v data_web:/var/lib/app → seul /var/lib/app est persisté sur disque via un volume
docker run -d --name web \
  --read-only \
  --tmpfs /tmp --tmpfs /run \
  -v data_web:/var/lib/app \
  ghcr.io/acme/web:1.4.2
```

> **Résultat attendu** :
> ```
> $ docker run -d --name web --read-only --tmpfs /tmp --tmpfs /run -v data_web:/var/lib/app ghcr.io/acme/web:1.4.2
> d4e5f6a7b8c9...
>
> $ docker exec web touch /etc/test
> touch: /etc/test: Read-only file system
>
> $ docker exec web touch /tmp/test    # OK — tmpfs
> $ docker exec web touch /var/lib/app/test  # OK — volume RW
> ```
> **Vérification** : `docker exec web touch /etc/anything` échoue avec `Read-only file system`. Les écritures dans `/tmp`, `/run` et `/var/lib/app` fonctionnent. `docker inspect web` confirme `"ReadonlyRootfs": true`.

* Le rootfs devient **RO** ; seuls **tmpfs** et **volumes** restent écrits.
* Identifier **tous** les chemins que l'app veut écrire (`/tmp`, `/run`, `/var/lib/app`…).

### 9.2 Variante bind RO + volume RW

> **Objectif** : Combiner un bind mount en lecture seule (pour la configuration) avec un volume en lecture/écriture (pour les données), le tout sur un rootfs en lecture seule. Pattern courant pour les apps qui lisent une config fixe et écrivent des données variables.
> **Pré-requis** : Répertoire `$PWD/config` existant sur l'hôte, volume `data_app` créé ou auto-créé.

```bash
# Lancer un conteneur avec rootfs en lecture seule + deux montages :
#   $PWD/config → /app/config :ro  → configuration en lecture seule (bind)
#   data_app    → /app/data   :rw  → données applicatives persistantes (volume)
docker run -d \
  --read-only \
  -v $PWD/config:/app/config:ro \
  -v data_app:/app/data \
  ghcr.io/acme/app:1.0
```

> **Résultat attendu** :
> ```
> $ docker exec <ctr> touch /app/config/test
> touch: /app/config/test: Read-only file system
>
> $ docker exec <ctr> touch /app/data/test   # OK — volume RW
> ```
> **Vérification** : La config est lisible mais non modifiable. Les données applicatives sont persistées dans le volume. Le rootfs est entièrement verrouillé.

---

## 10) Sauvegarde / Restauration de volumes

### 10.1 Sauvegarder un volume (tar)

> **Objectif** : Créer une archive `.tar.gz` du contenu d'un volume Docker (`data_app`) en utilisant un conteneur utilitaire Alpine éphémère. L'archive est écrite dans le répertoire courant de l'hôte.
> **Pré-requis** : Volume `data_app` existant avec des données, le répertoire courant (`$PWD`) doit avoir assez d'espace pour l'archive.

```bash
# Lancer un conteneur Alpine éphémère avec deux montages :
#   data_app → /data    : le volume à sauvegarder (lecture)
#   $PWD     → /backup  : le répertoire de destination sur l'hôte (écriture)
# Puis : se placer dans /data, créer une archive tar.gz datée dans /backup
# $(date +%F) génère la date au format YYYY-MM-DD dans le nom de fichier
docker run --rm -v data_app:/data -v $PWD:/backup \
  alpine sh -c "cd /data && tar czf /backup/data_app_$(date +%F).tgz ."
```

> **Résultat attendu** :
> ```
> $ docker run --rm -v data_app:/data -v $PWD:/backup \
>   alpine sh -c "cd /data && tar czf /backup/data_app_$(date +%F).tgz ."
> (pas de sortie en cas de succès)
>
> $ ls -lh data_app_*.tgz
> -rw-r--r-- 1 user user 42M Jun 21 10:30 data_app_2025-06-21.tgz
> ```
> **Vérification** : Le fichier `data_app_YYYY-MM-DD.tgz` existe dans le répertoire courant. `tar tzf data_app_*.tgz` liste le contenu de l'archive pour vérifier son intégrité.

### 10.2 Restaurer un volume

> **Objectif** : Restaurer le contenu d'une archive `.tar.gz` dans un volume Docker (`data_app`). Attention : cette opération **écrase** les données existantes du volume.
> **Pré-requis** : L'archive `data_app_2025-11-01.tgz` doit exister dans le répertoire courant. Le volume `data_app` doit exister (ou sera créé automatiquement).

```bash
# Lancer un conteneur Alpine éphémère avec les mêmes montages que la sauvegarde
# Puis : se placer dans /data (le volume) et extraire l'archive depuis /backup
# tar xzf = eXtract, gZip, File — extrait et écrase les fichiers existants
docker run --rm -v data_app:/data -v $PWD:/backup \
  alpine sh -c "cd /data && tar xzf /backup/data_app_2025-11-01.tgz"
```

> **Résultat attendu** :
> ```
> $ docker run --rm -v data_app:/data -v $PWD:/backup \
>   alpine sh -c "cd /data && tar xzf /backup/data_app_2025-11-01.tgz"
> (pas de sortie en cas de succès)
>
> $ docker run --rm -v data_app:/data alpine ls /data
> app.db
> config.yaml
> uploads/
> ```
> **Vérification** : Le volume `data_app` contient à nouveau les données de l'archive. Comparer avec `tar tzf` pour vérifier que tous les fichiers sont présents.

### 10.3 Migration volume → volume

> **Objectif** : Copier le contenu d'un volume (`data_app`) vers un autre volume (`data_new`) en utilisant un conteneur utilitaire Alpine. Utile pour renommer, cloner ou migrer des volumes.
> **Pré-requis** : Les deux volumes `data_app` et `data_new` existent (ou seront auto-créés).

```bash
# Lancer un conteneur Alpine éphémère avec deux montages :
#   data_app → /src : volume source (lecture)
#   data_new → /dst : volume destination (écriture)
# cp -a : copie récursive en préservant permissions, timestamps, liens symboliques
# /src/. : le "/." copie le CONTENU de /src (pas le répertoire /src lui-même)
docker run --rm -v data_app:/src -v data_new:/dst alpine sh -c "cp -a /src/. /dst/"
```

> **Résultat attendu** :
> ```
> $ docker run --rm -v data_app:/src -v data_new:/dst alpine sh -c "cp -a /src/. /dst/"
> (pas de sortie en cas de succès)
>
> $ diff <(docker run --rm -v data_app:/data alpine find /data -type f | sort) \
>        <(docker run --rm -v data_new:/data alpine find /data -type f | sort)
> (aucune différence — les deux volumes sont identiques)
> ```
> **Vérification** : Les deux volumes ont le même contenu. `diff` ne montre aucune différence entre les listes de fichiers.

> **DBs** : préférer les **outils natifs** (ex. `pg_dump`, `mysqldump`) pour cohérence logique.

---

## 11) Compose : déclarer volumes/bind/tmpfs

### 11.1 Volumes nommés

> **Objectif** : Déclarer un service PostgreSQL dans Docker Compose avec un volume nommé pour persister les données de la base. Le volume est déclaré dans la section top-level `volumes:` pour que Docker Compose le gère (création/suppression).
> **Pré-requis** : Fichier `docker-compose.yml` dans le répertoire courant, Docker Compose v2 installé.

```yaml
services:
  db:
    image: postgres:16
    volumes:
      # Monter le volume nommé "data_pg" sur le chemin de données PostgreSQL
      # Le volume est créé automatiquement au premier "docker compose up"
      - data_pg:/var/lib/postgresql/data

volumes:
  # Déclarer "data_pg" comme volume géré par Compose
  # {} signifie "utiliser les options par défaut" (driver: local)
  # "docker compose down -v" supprimera ce volume
  data_pg: {}
```

> **Résultat attendu** :
> ```
> $ docker compose up -d
> ✔ Network project_default  Created
> ✔ Volume "project_data_pg" Created
> ✔ Container project-db-1   Started
>
> $ docker volume ls
> DRIVER    VOLUME NAME
> local     project_data_pg
> ```
> **Vérification** : `docker compose ps` montre le service `db` en cours d'exécution. `docker volume ls` affiche le volume `project_data_pg` (préfixé par le nom du projet).

### 11.2 Bind mounts

> **Objectif** : Déclarer un bind mount dans Docker Compose pour monter un répertoire `config/` du projet en lecture seule dans le conteneur web. Le chemin relatif `./config` est résolu par rapport au fichier `docker-compose.yml`.
> **Pré-requis** : Répertoire `config/` existant dans le même dossier que le `docker-compose.yml`.

```yaml
services:
  web:
    image: ghcr.io/acme/web:1.4.2
    volumes:
      # Bind mount : le répertoire ./config (relatif au compose file)
      # est monté en /app/config dans le conteneur, en lecture seule (:ro)
      # Les modifications côté hôte sont visibles immédiatement dans le conteneur
      - ./config:/app/config:ro
```

> **Résultat attendu** :
> ```
> $ docker compose up -d
> ✔ Container project-web-1  Started
>
> $ docker exec project-web-1 ls /app/config
> app.conf
> nginx.conf
> ```
> **Vérification** : Les fichiers de `./config` sont accessibles dans le conteneur. Modifier un fichier côté hôte se reflète immédiatement dans le conteneur (pas de rebuild nécessaire).

### 11.3 tmpfs & rootfs RO

> **Objectif** : Déclarer un service avec rootfs en lecture seule, des tmpfs pour `/run` et `/tmp`, et un volume nommé pour les données applicatives — le tout via Docker Compose. Combine les patterns de durcissement vus précédemment.
> **Pré-requis** : Fichier `docker-compose.yml` dans le répertoire courant.

```yaml
services:
  app:
    image: ghcr.io/acme/app:1.0
    read_only: true          # Rootfs en lecture seule (équivalent --read-only)
    tmpfs:
      # Monter des tmpfs pour les chemins nécessitant l'écriture :
      - /run                 # tmpfs simple pour /run (PID files, sockets)
      - /tmp:size=64m,mode=1777  # tmpfs pour /tmp avec taille max 64 Mo et sticky bit
    volumes:
      # Seul /var/lib/app reste persisté sur disque via un volume nommé
      - data_app:/var/lib/app
volumes:
  data_app: {}               # Volume nommé géré par Compose (options par défaut)
```

> **Résultat attendu** :
> ```
> $ docker compose up -d
> ✔ Volume "project_data_app" Created
> ✔ Container project-app-1   Started
>
> $ docker exec project-app-1 touch /etc/test
> touch: /etc/test: Read-only file system
>
> $ docker exec project-app-1 touch /tmp/test   # OK
> $ docker exec project-app-1 touch /var/lib/app/test  # OK
> ```
> **Vérification** : Le rootfs est en lecture seule. `/tmp` et `/run` sont accessibles en écriture (tmpfs en RAM). `/var/lib/app` est persisté dans le volume. `docker inspect` confirme `"ReadonlyRootfs": true`.

---

## 12) Diagnostic & bonnes pratiques

### 12.1 Vérifier les montages effectifs

> **Objectif** : Inspecter les montages actifs d'un conteneur nommé `app` au format JSON lisible, en combinant `docker inspect` avec un template Go et `jq` pour le formatage.
> **Pré-requis** : Un conteneur nommé `app` en cours d'exécution, l'outil `jq` installé sur l'hôte.

```bash
# Utiliser docker inspect avec un template Go pour extraire uniquement .Mounts
# puis pipe vers jq pour formater le JSON de manière lisible
# Affiche : type de montage, source, destination, mode, options, etc.
docker inspect -f '{{json .Mounts}}' app | jq
```

> **Résultat attendu** :
> ```
> $ docker inspect -f '{{json .Mounts}}' app | jq
> [
>   {
>     "Type": "volume",
>     "Name": "data_app",
>     "Source": "/var/lib/docker/volumes/data_app/_data",
>     "Destination": "/data",
>     "Driver": "local",
>     "Mode": "z",
>     "RW": true,
>     "Propagation": ""
>   },
>   {
>     "Type": "bind",
>     "Source": "/home/user/project/config",
>     "Destination": "/app/config",
>     "Mode": "ro",
>     "RW": false,
>     "Propagation": "rprivate"
>   }
> ]
> ```
> **Vérification** : Chaque entrée montre le type (`volume`, `bind`, `tmpfs`), la source, la destination, et si le montage est en lecture/écriture (`RW: true/false`).

### 12.2 Pièges courants

* **Masquage** d'un chemin important par un bind → l'app ne trouve plus ses fichiers d'image.
* **Permissions** : UID/GID non alignés → `EACCES`.
* **SELinux** : oubli de `:Z/:z` sur Fedora/CentOS/RHEL → `permission denied`.
* **Net FS** : NFS/SMB non disponibles → montée en erreur au démarrage.
* **Nettoyage agressif** : `docker volume prune` supprime un volume **non référencé** (attention au Compose down avec `-v`).

### 12.3 Do & Don't

**Do**

* Préférer **volumes** pour la **persistance** applicative.
* Définir des **UID/GID** cohérents, initialiser l'ownership.
* Utiliser `--read-only` + `tmpfs` pour durcir.
* Sauvegarder via **tar** ou **outils natifs DB**, tester la **restauration**.

**Don't**

* Éviter de monter tout `/` : `-v /:/host` (dangereux).
* Ne stockez pas de secrets sur volume partagé sans contrôle.
* N'exposez pas des sockets/chemins sensibles au conteneur inutilement.

---

## 13) Aide-mémoire (cheat-sheet)

> **Objectif** : Récapitulatif rapide de toutes les commandes essentielles pour la gestion du stockage Docker — volumes, bind mounts, tmpfs, SELinux, NFS, sauvegarde et inspection. Ce bloc sert de référence rapide pour un usage quotidien.
> **Pré-requis** : Docker Engine/CLI opérationnel. Adapter les chemins, noms de volumes et adresses IP à votre environnement.

```bash
# === VOLUMES ===
# Créer un volume nommé avec un label pour le filtrage
docker volume create --label app=db data_pg
# Lister les volumes filtrés par label
docker volume ls --filter label=app=db
# Inspecter un volume (affiche chemin hôte, driver, options, labels)
docker volume inspect data_pg
# Supprimer un volume (échoue si encore utilisé par un conteneur)
docker volume rm data_pg
# Supprimer tous les volumes orphelins (non référencés par un conteneur)
docker volume prune -f

# === BIND MOUNTS ===
# Monter un répertoire hôte en lecture seule dans le conteneur
docker run -v $PWD/config:/app/config:ro ghcr.io/acme/app:1.0

# === TMPFS ===
# Monter un tmpfs de 64 Mo sur /run (en RAM, volatil)
docker run --mount type=tmpfs,dst=/run,tmpfs-size=64m ghcr.io/acme/app:1.0

# === SELINUX ===
# Monter un bind avec re-étiquetage SELinux privé (:Z)
docker run -v /srv/data:/data:Z ghcr.io/acme/app:1.0

# === NFS ===
# Créer un volume Docker pointant vers un serveur NFS
docker volume create --driver local \
  --opt type=nfs --opt o=addr=10.0.0.50,nfsvers=4.1,rw \
  --opt device=:/export/data nfs_data

# === BACKUP VOLUME ===
# Sauvegarder un volume dans une archive tar.gz datée
docker run --rm -v data_app:/data -v $PWD:/backup \
  alpine sh -c "cd /data && tar czf /backup/data_app_$(date +%F).tgz ."

# === INSPECTION ===
# Afficher les montages d'un conteneur au format JSON formaté
docker inspect -f '{{json .Mounts}}' app | jq
```

> **Résultat attendu** :
> ```
> $ docker volume create --label app=db data_pg
> data_pg
>
> $ docker volume ls --filter label=app=db
> DRIVER    VOLUME NAME
> local     data_pg
>
> $ docker volume inspect data_pg | jq '.[0].Mountpoint'
> "/var/lib/docker/volumes/data_pg/_data"
>
> $ docker volume rm data_pg
> data_pg
> ```
> **Vérification** : Chaque commande produit le résultat décrit dans les sections précédentes du chapitre. Ce cheat-sheet est conçu pour être copié-collé et adapté.

---

## 14) Checklist de clôture (qualité du stockage)

* Type de montage **adapté** (volume/bind/tmpfs) et **documenté**.
* **Permissions** correctes (UID/GID alignés), SELinux `:Z/:z` si nécessaire.
* Rootfs **read-only** quand possible, **tmpfs** pour `/tmp` et `/run`.
* **Sauvegardes** testées + plan de **restauration** documenté.
* Éviter le **masquage** involontaire de chemins critiques.
* Compose : volumes nommés déclarés, pas de `-v` absolu non maîtrisé.