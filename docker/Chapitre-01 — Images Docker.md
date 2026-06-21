# Chapitre-01 — Images Docker (version enrichie, **pas-à-pas**)

Objectif : repartir des bases **avec méthode** et t'amener jusqu'à des images **propres, traçables, reproductibles et prêtes prod** (tags + digest), tout en comprenant *exactement* ce que Docker manipule.

---

## Objectifs d'apprentissage (affinés)

* Comprendre le **modèle OCI** (layers, manifeste, digest, index multi-arch) et savoir **lire** ces infos.
* Savoir **nommer** correctement une image, **tirer** (`pull`), **construire** (`build`), **taguer**, **publier** (`push`) et **nettoyer**.
* Savoir **inspecter** (métadonnées / couches), **lire l'historique**, **sauvegarder/restaurer** (save/load vs export/import).
* Appliquer les bonnes pratiques : **.dockerignore**, **multi-stage**, **labels OCI**, **USER non-root**, **pinning**, **digest** en déploiement.

---

## Pré-requis & vérifications rapides

> **Objectif** : Vérifier que Docker est correctement installé et fonctionnel (client, serveur, stockage, occupation disque).
> **Pre-requis** : Docker Engine ou Docker Desktop installé sur la machine.

```bash
# Affiche les versions du client et du serveur Docker pour confirmer la communication
docker version            # client/serveur
# Affiche les informations système : storage driver, cgroup, nombre de conteneurs/images
docker info               # storage driver, cgroup driver, etc.
# Résume l'espace disque occupé par les images, conteneurs et volumes
docker system df          # occupation disque (images/containers/volumes)
```

> **Resultat attendu** :
> ```
> $ docker version
> Client: Docker Engine - Community
>  Version:           27.x.x
>  API version:       1.47
> Server: Docker Engine - Community
>  Version:           27.x.x
>  API version:       1.47
>
> $ docker info
> Server:
>  Storage Driver: overlay2
>  Cgroup Driver: systemd
>  ...
>
> $ docker system df
> TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
> Images          5         2         1.2GB     800MB (66%)
> Containers      2         1         50MB      25MB (50%)
> Local Volumes   1         0         100MB     100MB (100%)
> ```
> **Verification** : Le client et le serveur affichent la même API version. Le storage driver est `overlay2` (recommandé). Aucune erreur de connexion.

> Si tu es sur Windows, assure-toi que **WSL2** est activé et que Docker Desktop utilise WSL2.

---

## Plan d'apprentissage (étapes)

1. **Concepts OCI** → 2) **Nommage** → 3) **Lister / chercher** → 4) **Tirer** →
2. **Construire** → 6) **Tagger & pousser** → 7) **Inspecter / history** →
3. **Save/Load vs Export/Import** → 9) **Multi-arch** → 10) **Nettoyage** →
4. **Bonnes pratiques** → 12) **Parcours guidé** → 13) **FAQ & erreurs** → 14) **Checklist**

---

## 1) Concepts fondamentaux (OCI)

* **Image** : empilement de **couches** en lecture seule (layers). Chaque instruction Dockerfile produit (souvent) une couche.
* **Manifeste** : JSON décrivant **config** + **liste des couches**.
* **Digest** : empreinte **SHA-256** du manifeste → identifiant **immuable** (`@sha256:…`).
* **Tag** : alias **mutable** (ex. `:1.4.2`, `:stable`, `:latest`) → pratique mais **non garanti**.
* **Index (manifest list)** : "pointeur" vers plusieurs manifestes (amd64, arm64, …) pour une même **référence**.

Une *référence d'image* peut être un **tag** (`repo:1.4.2`) *ou* un **digest** (`repo@sha256:…`). En production, **préférer le digest**.

---

## 2) Nommage correct d'une image

**Grammaire**

> **Objectif** : Comprendre la syntaxe officielle de nommage d'une image Docker (registre, namespace, dépôt, tag ou digest).
> **Pre-requis** : Aucun, c'est de la théorie.

```
# Format complet : [REGISTRE avec port optionnel]/[ESPACE NOM]/NOM_DEPOT[:TAG] ou [@DIGEST]
[REGISTRY[:PORT]]/[NAMESPACE]/REPOSITORY[:TAG]   ou   [ ... ]@[DIGEST]
```

> **Resultat attendu** :
> ```
> Exemples de références valides :
>   nginx:1.27                          → Hub implicite, library/nginx, tag 1.27
>   ghcr.io/monorg/monapp:web           → GHCR, namespace monorg, tag web
>   registry.example.com/team/api@sha256:deadbeef…  → Registre privé, par digest
> ```
> **Verification** : Toute référence suit le pattern [registry/][namespace/]repo[:tag|@digest].

**Exemples**

* `ubuntu:22.04` → registre **Docker Hub** implicite + namespace `library/`.
* `ghcr.io/monorg/monapp:web` → GitHub Container Registry.
* `registry.example.com/team/api@sha256:deadbeef…` → par **digest** (immutabilité).

**Règles utiles**

* Si tu omets `:tag`, Docker suppose `:latest` (⚠️ **éviter** en prod).
* **Minuscules** et noms concis.
* **SemVer** : `1.4.2` + canaux (`1.4`, `rc`, `stable`) pour le confort humain ; **digest** pour déployer.

---

## 3) Lister / filtrer / chercher

> **Objectif** : Lister les images stockées localement, les filtrer par état ou par référence, et formater la sortie. Ajouter une recherche sur le Docker Hub.
> **Pre-requis** : Docker installé et quelques images déjà tirées (ex. `docker pull nginx`).

```bash
# Liste toutes les images présentes sur la machine locale
# Lister images locales
docker image ls                       # alias: docker images
# Affiche en plus le digest (empreinte SHA256) de chaque image
docker image ls --digests
# Filtre pour n'afficher que les images "dangling" (sans tag, orphelines)
docker image ls --filter dangling=true
# Filtre par motif sur le nom du dépôt (ici tout ce qui vient de ghcr.io/monorg/)
docker image ls --filter reference='ghcr.io/monorg/*'
# Formate la sortie avec des champs précis (Go template), puis trie alphabétiquement
docker image ls --format '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}' | sort
```

> **Resultat attendu** :
> ```
> $ docker image ls
> REPOSITORY    TAG       IMAGE ID       CREATED        SIZE
> nginx         1.27      a8758716bb6a   2 weeks ago    187MB
> alpine        3.20      b8df26a2c81e   3 weeks ago    7.8MB
>
> $ docker image ls --digests
> REPOSITORY    TAG       DIGEST                                                                    IMAGE ID       SIZE
> nginx         1.27      sha256:abcd1234...                                                        a8758716bb6a   187MB
>
> $ docker image ls --format '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}' | sort
> alpine:3.20        b8df26a2c81e    7.8MB
> nginx:1.27         a8758716bb6a    187MB
> ```
> **Verification** : Les images listées correspondent à celles tirées précédemment. Le filtre `dangling` ne montre que les `<none>:<none>`. Le `--format` produit les colonnes attendues.

> `dangling=true` = couches "orphelines" (tags supprimés).
> `--format` accepte les **Go templates** pour extraire des champs précis.

Recherche (Docker Hub uniquement) :

> **Objectif** : Rechercher des images publiques sur le Docker Hub par mot-clé.
> **Pre-requis** : Connexion Internet.

```bash
# Recherche "nginx" sur le Docker Hub et limite à 15 résultats
docker search nginx --limit 15
```

> **Resultat attendu** :
> ```
> NAME                             DESCRIPTION                                     STARS     OFFICIAL
> nginx                            Official build of Nginx.                        18000+    [OK]
> nginxproxy/nginx-proxy           Automated Nginx reverse proxy for docker...     1500+
> nginxinc/nginx-unprivileged      Unprivileged NGINX Dockerfiles                  200+
> ...
> ```
> **Verification** : Une liste d'images correspondant à "nginx" s'affiche avec étoiles, description et badge [OFFICIAL].

---

## 4) Tirer (pull) des images

> **Objectif** : Télécharger des images depuis un registre vers le cache local, éventuellement pour une architecture spécifique ou tous les tags.
> **Pre-requis** : Connexion Internet, Docker installé.

```bash
# Télécharge l'image nginx taguée 1.27 depuis le Docker Hub
docker pull nginx:1.27
# Télécharge spécifiquement la variante ARM64 (utile pour Raspberry Pi, Apple Silicon, etc.)
docker pull --platform linux/arm64 nginx:1.27   # variante ARM64 si index multi-arch
# Télécharge TOUS les tags du dépôt alpine (⚠️ peut être volumineux)
docker pull --all-tags alpine                    # ⚠️ tire *tous* les tags du repo 'alpine'
```

> **Resultat attendu** :
> ```
> $ docker pull nginx:1.27
> 1.27: Pulling from library/nginx
> a2abf6c4d29d: Pull complete
> a9edb18cadd1: Pull complete
> Digest: sha256:abcd1234...
> Status: Downloaded newer image for nginx:1.27
> docker.io/library/nginx:1.27
>
> $ docker pull --platform linux/arm64 nginx:1.27
> linux/arm64: Pulling from library/nginx
> ...
> Status: Downloaded newer image for nginx:1.27
>
> $ docker pull --all-tags alpine
> 3.18: Pulling from library/alpine
> 3.19: Pulling from library/alpine
> ...
> ```
> **Verification** : Chaque pull affiche les couches téléchargées et le digest final. `docker image ls` montre les images téléchargées.

**Points d'attention**

* `--platform` **tire** une variante spécifique. Pour **exécuter** une arch différente de la tienne, il faut l'émulation (QEMU/binfmt).
* `--all-tags` peut télécharger **beaucoup** de données : utilise-le avec précaution.

---

## 5) Construire (build) — bases indispensables

> Le chapitre "Dockerfile & Build" couvre le détail. Ici, on pose le **minimum vital**.

> **Objectif** : Construire une image Docker à partir d'un Dockerfile dans le répertoire courant, avec différentes options (tag, Dockerfile alternatif, build sans cache).
> **Pre-requis** : Un fichier `Dockerfile` (ou `Dockerfile.prod`) présent dans le répertoire courant.

```bash
# Construit l'image en la taguant myapp:1.0, utilise le Dockerfile du répertoire courant (.)
# Build avec tag
docker build -t myapp:1.0 .

# Construit en spécifiant un Dockerfile alternatif nommé Dockerfile.prod
# Dockerfile alternatif
docker build -t myapp:1.0 -f Dockerfile.prod .

# Construit sans utiliser le cache et en rafraîchissant l'image de base depuis le registre
# Build propre (ignore cache, rafraîchit l'image de base)
docker build --no-cache --pull -t myapp:clean .
```

> **Resultat attendu** :
> ```
> $ docker build -t myapp:1.0 .
> [+] Building 12.3s (8/8) FINISHED
>  => [internal] load build definition from Dockerfile
>  => [internal] load .dockerignore
>  => [1/4] FROM docker.io/library/alpine:3.20
>  => [2/4] RUN adduser -D app
>  => [3/4] WORKDIR /app
>  => [4/4] COPY . .
>  => exporting to image
>  => => naming to docker.io/library/myapp:1.0
> ```
> **Verification** : L'image `myapp:1.0` apparaît dans `docker image ls`. Chaque étape du Dockerfile est exécutée (ou restaurée depuis le cache).

**Options clés**

* `-t repo:tag` : nommage.
* `-f` : chemin Dockerfile.
* `--build-arg KEY=VAL` : variables **ARG** du Dockerfile.
* `--pull` : rafraîchit l'image de base.
* `--platform` : cible d'arch (multi-arch réel via **Buildx**).

**.dockerignore** (exemple)

> **Objectif** : Exclure fichiers/dossiers du contexte de build pour réduire la taille envoyée au daemon Docker et éviter d'inclure des fichiers inutiles (.git, node_modules, etc.).
> **Pre-requis** : Créer un fichier `.dockerignore` à la racine du projet (même niveau que le Dockerfile).

```
# Exclut le répertoire .git (historique non nécessaire dans l'image)
.git
# Exclut les dépendances Node (seront réinstallées dans l'image)
node_modules
# Exclut les artefacts de compilation Java/Rust
target
# Exclut le cache Python
__pycache__/
# Exclut tous les fichiers de log
*.log
```

> **Resultat attendu** :
> ```
# Aucun affichage direct. Le fichier est lu automatiquement par `docker build`.
# Les fichiers listés ne seront PAS envoyés dans le contexte de build.
> ```
> **Verification** : Lors du build, le contexte envoyé est plus petit. Vérifier avec `docker build` que les fichiers exclus n'apparaissent pas dans l'image finale.

---

## 6) Tagger & pousser (push)

> **Objectif** : Ajouter des tags supplémentaires à une image existante (pour la préparer à un registre) puis la pousser vers un registre distant.
> **Pre-requis** : Une image locale `myapp:1.0` construite précédemment. Un registre accessible (ex. `registry.example.com`) avec des droits d'écriture.

```bash
# Crée un alias (tag) pointant vers la même image pour le registre de production
# Ajouter des tags
docker tag myapp:1.0 registry.example.com/prod/myapp:1.0
# Crée un tag "stable" local pour identifier cette version comme stable
docker tag myapp:1.0 myapp:stable

# S'authentifie auprès du registre privé (demande login/password)
# Authentification et push
docker login registry.example.com
# Pousse l'image taguée vers le registre distant
docker push registry.example.com/prod/myapp:1.0
```

> **Resultat attendu** :
> ```
> $ docker tag myapp:1.0 registry.example.com/prod/myapp:1.0
> (aucune sortie en cas de succès)
>
> $ docker login registry.example.com
> Username: monuser
> Password: ********
> Login Succeeded
>
> $ docker push registry.example.com/prod/myapp:1.0
> The push refers to repository [registry.example.com/prod/myapp]
> abc123: Pushed
> def456: Layer already exists
> 1.0: digest: sha256:efgh5678... size: 1234
> ```
> **Verification** : L'image apparaît dans `docker image ls` avec le nouveau tag. Le push affiche le digest du manifeste poussé.

> **Astuce** : publie **toujours** un tag **versionné** (SemVer). Tu pourras **déployer par digest**.

---

## 7) Inspecter & lire l'historique

**Inspect**

> **Objectif** : Extraire des métadonnées détaillées d'une image : identifiant, OS, architecture, couches du RootFS, labels OCI.
> **Pre-requis** : L'image `myapp:1.0` existe localement. L'outil `jq` est installé pour formater le JSON.

```bash
# Extrait l'ID complet, l'OS cible et l'architecture de l'image
docker image inspect myapp:1.0 | jq '.[0].Id, .[0].Os, .[0].Architecture'
# Extrait et affiche la liste des couches (layers) du système de fichiers
docker image inspect --format '{{json .RootFS.Layers}}' myapp:1.0 | jq
# Extrait et affiche les labels (métadonnées) associés à l'image
docker image inspect --format '{{json .Config.Labels}}' myapp:1.0 | jq
```

> **Resultat attendu** :
> ```
> $ docker image inspect myapp:1.0 | jq '.[0].Id, .[0].Os, .[0].Architecture'
> "sha256:a1b2c3d4e5f6..."
> "linux"
> "amd64"
>
> $ docker image inspect --format '{{json .RootFS.Layers}}' myapp:1.0 | jq
> [
>   "sha256:layer1...",
>   "sha256:layer2..."
> ]
>
> $ docker image inspect --format '{{json .Config.Labels}}' myapp:1.0 | jq
> {
>   "org.opencontainers.image.version": "1.0",
>   "org.opencontainers.image.revision": "abc1234"
> }
> ```
> **Verification** : L'OS est `linux`, l'architecture correspond à la machine (ou celle ciblée). Les layers listés correspondent aux instructions du Dockerfile.

**Historique**

> **Objectif** : Afficher les instructions qui ont construit l'image, couche par couche, avec leur taille.
> **Pre-requis** : L'image `myapp:1.0` existe localement.

```bash
# Affiche l'historique des couches (instructions, taille, date)
docker image history myapp:1.0
# Affiche l'historique sans tronquer les lignes (commandes complètes)
docker image history --no-trunc myapp:1.0
```

> **Resultat attendu** :
> ```
> $ docker image history myapp:1.0
> IMAGE          CREATED       CREATED BY                                      SIZE
> a1b2c3d4e5f6   2 hours ago   RUN /bin/sh -c adduser -D app                   4.5kB
> <missing>      2 hours ago   WORKDIR /app                                     0B
> <missing>      2 hours ago   COPY . .                                         12kB
> <missing>      3 days ago    /bin/sh -c #(nop) CMD ["/bin/sh"]               0B
> <missing>      3 days ago    /bin/sh -c #(nop) ADD file:xyz in /              7.8MB
> ```
> **Verification** : Chaque ligne correspond à une instruction du Dockerfile (ou de l'image de base). La taille cumulée donne la taille de l'image.

> `history` révèle les **instructions** (RUN/COPY/…) et la **taille** par couche.
> Utile pour **optimiser** (fusionner RUN, nettoyer caches) et **auditer** ce qui compose l'image.

---

## 8) Sauvegarder/Restaurer vs Exporter/Importer

**Images** (avec métadonnées OCI) :

> **Objectif** : Sauvegarder une image complète (avec toutes ses couches, tags et métadonnées) dans un fichier tar, puis la restaurer sur une autre machine ou plus tard.
> **Pre-requis** : L'image `ghcr.io/acme/api:1.4.2` existe localement.

```bash
# Exporte l'image complète (manifeste + couches + tags) dans un fichier tar
docker save ghcr.io/acme/api:1.4.2 > api_1.4.2.tar
# Restaure l'image depuis le fichier tar (reconstitue l'image avec ses tags)
docker load < api_1.4.2.tar
```

> **Resultat attendu** :
> ```
> $ docker save ghcr.io/acme/api:1.4.2 > api_1.4.2.tar
> (aucune sortie, le fichier est créé — vérifier sa taille avec ls -lh)
>
> $ docker load < api_1.4.2.tar
> abc123def456: Loading layer  12.3MB/12.3MB
> Loaded image: ghcr.io/acme/api:1.4.2
> ```
> **Verification** : `ls -lh api_1.4.2.tar` montre un fichier non vide. Après `docker load`, l'image réapparaît dans `docker image ls` avec son tag d'origine.

**Rootfs d'un conteneur** (sans l'historique Dockerfile) :

> **Objectif** : Exporter le système de fichiers aplati d'un conteneur (sans historique ni métadonnées), puis le réimporter comme nouvelle image.
> **Pre-requis** : L'image `ubuntu:22.04` existe localement.

```bash
# Crée un conteneur nommé "t" sans le démarrer (sleep infinity le maintient)
docker create --name t ubuntu:22.04 sleep infinity
# Exporte le rootfs complet du conteneur dans un fichier tar (une seule couche, pas d'historique)
docker export t > rootfs.tar
# Importe le rootfs tar comme nouvelle image nommée ubuntu:min
cat rootfs.tar | docker import - ubuntu:min
```

> **Resultat attendu** :
> ```
> $ docker create --name t ubuntu:22.04 sleep infinity
> 8a7b3c9d2e1f...
>
> $ docker export t > rootfs.tar
> (aucune sortie, fichier créé)
>
> $ cat rootfs.tar | docker import - ubuntu:min
> sha256:f1e2d3g4h5i6...
> ```
> **Verification** : `docker image ls` montre `ubuntu:min` avec une seule couche. `docker image history ubuntu:min` ne montre qu'une seule entrée "import" (pas l'historique Dockerfile).

> `save/load` ≠ `export/import` : le premier conserve le **manifeste + layers**, le second **aplati** un rootfs en **une** image (sans historique).

---

## 9) Multi-architecture (aperçu utile)

* Les images modernes publient un **index** multi-arch.
* Tu peux voir quelle arch est tirée :

> **Objectif** : Vérifier quelle architecture a été téléchargée pour une image et confirmer la correspondance avec la machine hôte.
> **Pre-requis** : Connexion Internet pour tirer l'image.

```bash
# Télécharge l'image node:20 (l'index multi-arch sélectionne automatiquement la bonne variante)
docker pull node:20
# Affiche l'OS et l'architecture de l'image téléchargée
docker image inspect --format '{{.Os}}/{{.Architecture}}' node:20
```

> **Resultat attendu** :
> ```
> $ docker pull node:20
> 20: Pulling from library/node
> ...
> Status: Downloaded newer image for node:20
>
> $ docker image inspect --format '{{.Os}}/{{.Architecture}}' node:20
> linux/amd64
> ```
> **Verification** : L'architecture affichée correspond à celle de la machine hôte (ou celle forcée via `--platform`).

* Inspection d'un **index** (via Buildx) :

> **Objectif** : Inspecter le manifeste multi-arch d'une image pour voir toutes les architectures disponibles sans les télécharger.
> **Pre-requis** : Docker Buildx disponible (inclus dans Docker Desktop et Docker Engine récent).

```bash
# Affiche l'index multi-arch (toutes les plateformes disponibles) pour nginx:1.27
docker buildx imagetools inspect nginx:1.27
```

> **Resultat attendu** :
> ```
> Name: docker.io/library/nginx:1.27
> Manifests:
>   Name: docker.io/library/nginx:1.27@sha256:aaa111...
>   Platform: linux/amd64
>
>   Name: docker.io/library/nginx:1.27@sha256:bbb222...
>   Platform: linux/arm/v7
>
>   Name: docker.io/library/nginx:1.27@sha256:ccc333...
>   Platform: linux/arm64
> ```
> **Verification** : Plusieurs plateformes sont listées (amd64, arm64, arm/v7, etc.), chacune avec son propre digest.

---

## 10) Nettoyage & gestion d'espace

> **Objectif** : Identifier et supprimer les images inutilisées (dangling, non référencées) pour libérer de l'espace disque.
> **Pre-requis** : Docker installé avec des images/conteneurs potentiellement obsolètes.

```bash
# Liste les images dangling (sans tag, orphelines après un rebuild par exemple)
docker image ls --filter dangling=true
# Supprime uniquement les images dangling (les plus sûres à retirer)
docker image prune -f                # supprime dangling
# Affiche un résumé de l'espace utilisé par images, conteneurs et volumes
docker system df                     # récapitulatif espace
# ⚠️ Supprime TOUT ce qui n'est pas utilisé par un conteneur en cours (images, cache, réseaux)
docker system prune -a               # agressif : supprime tout ce qui n'est pas référencé
```

> **Resultat attendu** :
> ```
> $ docker image ls --filter dangling=true
> REPOSITORY   TAG       IMAGE ID       CREATED        SIZE
> <none>       <none>    abc123def456   2 days ago     150MB
>
> $ docker image prune -f
> Deleted Images:
> deleted: sha256:abc123...
> Total reclaimed space: 150MB
>
> $ docker system df
> TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
> Images          3         2         500MB     150MB (30%)
> Containers      2         1         50MB      25MB
> Local Volumes   0         0         0B        0B
>
> $ docker system prune -a
> WARNING! This will remove:
>   - all stopped containers
>   - all networks not used by at least one container
>   - all images without at least one container associated to them
>   - all build cache
> Are you sure you want to continue? [y/N] y
> Deleted Images:
> ...
> Total reclaimed space: 1.2GB
> ```
> **Verification** : L'espace reclaimé est affiché. `docker system df` après nettoyage montre des valeurs réduites.

> Si `rm` échoue : l'image est **utilisée** par au moins un conteneur (même arrêté). Supprime d'abord le conteneur.

---

## 11) Bonnes pratiques (niveau image)

* **Pinning** : versions OS/paquets/langages **fixées** (idéalement par **digest** de base).
* **Multi-stage** : une phase "build" lourde → une **runtime** **minimale**.
* **Nettoyage dans la même couche** :

  > **Objectif** : Installer un paquet et nettoyer le cache dans la même instruction RUN pour éviter que le cache ne reste dans une couche précédente (gain d'espace).
  > **Pre-requis** : Dockerfile utilisant une base Alpine.

  ```Dockerfile
  # Installe curl sans mettre en cache (--no-cache) puis supprime le cache apk résiduel
  # Le && assure que les deux opérations sont dans la MÊME couche
  RUN apk add --no-cache curl \
   && rm -rf /var/cache/apk/*
  ```

  > **Resultat attendu** :
  > ```
  > # Lors du build :
  > => [3/5] RUN apk add --no-cache curl && rm -rf /var/cache/apk/*
  > fetch https://dl-cdn.alpinelinux.org/...
  > Installing curl (8.x.x)
  > OK: 15 MiB in 20 packages
  > ```
  > **Verification** : `docker image history` montre une seule couche pour l'install + nettoyage. La taille de cette couche est minimale (pas de cache résiduel).

* **USER non-root** :

  > **Objectif** : Créer un utilisateur non-privilégié et basculer dessus pour que le conteneur ne s'exécute pas en root (bonne pratique de sécurité).
  > **Pre-requis** : Dockerfile utilisant une base Alpine.

  ```Dockerfile
  # Crée un utilisateur système "app" sans mot de passe, avec UID 10001
  RUN adduser -D -u 10001 app
  # Bascule sur cet utilisateur (UID:GID) pour toutes les instructions suivantes
  USER 10001:10001
  ```

  > **Resultat attendu** :
  > ```
  > => [4/5] RUN adduser -D -u 10001 app
  > => [5/5] USER 10001:10001
  > # À l'exécution : $ whoami → app, $ id → uid=10001(app) gid=10001(app)
  > ```
  > **Verification** : `docker run --rm <image> whoami` affiche `app`. `docker run --rm <image> id` affiche `uid=10001(app) gid=10001(app)`.

* **Labels OCI** (traçabilité) :

  > **Objectif** : Ajouter des métadonnées standardisées (OCI) à l'image pour la traçabilité : titre, version, commit Git, source.
  > **Pre-requis** : Les variables `$VERSION` et `$GIT_SHA` doivent être passées via `--build-arg` lors du build.

  ```Dockerfile
  # Définit des labels OCI standard pour la traçabilité de l'image
  LABEL org.opencontainers.image.title="api" \
        org.opencontainers.image.version="$VERSION" \
        org.opencontainers.image.revision="$GIT_SHA" \
        org.opencontainers.image.source="https://github.com/acme/api"
  ```

  > **Resultat attendu** :
  > ```
  > => [5/5] LABEL org.opencontainers.image.title="api" ...
  > # Après build, les labels sont visibles via :
  > # docker inspect --format '{{json .Config.Labels}}' <image>
  > ```
  > **Verification** : `docker image inspect --format '{{json .Config.Labels}}' <image> | jq` affiche les labels avec les bonnes valeurs.

* **Base minimale** : `alpine`, `distroless`, `scratch` (selon besoin).

  > Attention aux libs (`glibc` vs `musl`) : certaines apps requièrent `glibc`.

---

## 12) Parcours guidé (pas-à-pas concret)

> On va : **tirer** → **lire digest** → **démarrer par digest** → **construire** → **tagger** → **pousser** → **inspecter** → **sauver/restaurer**.

**Étape 1 — Tirer & identifier le digest**

> **Objectif** : Télécharger nginx:1.27 et récupérer son digest SHA256 pour un déploiement immuable.
> **Pre-requis** : Connexion Internet, Docker installé.

```bash
# Télécharge l'image nginx:1.27 depuis le Docker Hub
docker pull nginx:1.27
# Extrait le premier digest du dépôt (format registry/repo@sha256:...)
docker image inspect --format '{{index .RepoDigests 0}}' nginx:1.27
# → nginx@sha256:ABCD...
```

> **Resultat attendu** :
> ```
> $ docker pull nginx:1.27
> 1.27: Pulling from library/nginx
> ...
> Status: Downloaded newer image for nginx:1.27
>
> $ docker image inspect --format '{{index .RepoDigests 0}}' nginx:1.27
> nginx@sha256:a8758716bb6a71e1dd3f4f3a3a5c6e8d9f0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d
> ```
> **Verification** : Le digest affiché est un hash SHA256 complet. Noter ce digest pour l'étape suivante.

**Étape 2 — Exécuter par digest (immutabilité)**

> **Objectif** : Démarrer un conteneur en référençant l'image par son digest (garantie d'immutabilité — on sait exactement quelle image tourne).
> **Pre-requis** : Le digest récupéré à l'étape 1. Le port 8080 est libre sur la machine.

```bash
# Démarre un conteneur nommé "web" en arrière-plan, en mappant le port 8080 hôte → 80 conteneur
# Utilise le digest (et non le tag) pour garantir l'image exacte
docker run -d --name web -p 8080:80 nginx@sha256:ABCD...
# Envoie une requête HEAD au conteneur pour vérifier qu'il répond
curl -I http://localhost:8080
```

> **Resultat attendu** :
> ```
> $ docker run -d --name web -p 8080:80 nginx@sha256:ABCD...
> e1f2g3h4i5j6...
>
> $ curl -I http://localhost:8080
> HTTP/1.1 200 OK
> Server: nginx/1.27.x
> Content-Type: text/html
> ...
> ```
> **Verification** : Le conteneur démarre sans erreur. `curl -I` retourne un HTTP 200. `docker ps` montre le conteneur `web` actif.

**Étape 3 — Construire une mini image**
`Dockerfile` :

> **Objectif** : Construire une image minimale Alpine avec un utilisateur non-root qui exécute un script shell au démarrage.
> **Pre-requis** : Le fichier `hello.sh` existe dans le répertoire courant (voir ci-dessous).

```Dockerfile
# Utilise Alpine 3.20 comme image de base (minimale, ~7MB)
FROM alpine:3.20
# Crée un utilisateur système "app" sans mot de passe, UID 10001
RUN adduser -D -u 10001 app
# Bascule sur l'utilisateur non-root pour les instructions suivantes
USER 10001:10001
# Définit le répertoire de travail dans le conteneur
WORKDIR /app
# Copie le script hello.sh depuis le contexte de build vers /app dans l'image
COPY hello.sh .
# Rend le script exécutable
RUN chmod +x hello.sh
# Point d'entrée : exécute le script au démarrage du conteneur
ENTRYPOINT ["./hello.sh"]
```

> **Resultat attendu** :
> ```
> => [internal] load build definition from Dockerfile
> => [1/5] FROM docker.io/library/alpine:3.20
> => [2/5] RUN adduser -D -u 10001 app
> => [3/5] WORKDIR /app
> => [4/5] COPY hello.sh .
> => [5/5] RUN chmod +x hello.sh
> => exporting to image
> => => naming to docker.io/library/demo/hello:1.0 (après tag)
> ```
> **Verification** : Le build se termine sans erreur. L'image utilise bien l'utilisateur 10001 (vérifiable avec `docker run --rm <image> id`).

`hello.sh` :

> **Objectif** : Script shell simple affiché au démarrage du conteneur, montrant l'architecture et l'UID utilisateur.
> **Pre-requis** : Aucun.

```sh
#!/bin/sh
# Affiche un message avec l'architecture CPU et l'UID de l'utilisateur courant
echo "Hello from $(uname -m) as user $(id -u)"
```

> **Resultat attendu** :
> ```
> Hello from x86_64 as user 10001
> ```
> **Verification** : L'architecture correspond à la plateforme. L'UID est 10001 (pas 0/root).

Build & run :

> **Objectif** : Créer le script hello.sh, construire l'image et l'exécuter pour vérifier le résultat.
> **Pre-requis** : Docker installé, répertoire courant vide (ou du moins sans conflit de nom).

```bash
# Génère le fichier hello.sh avec son contenu (shebang + echo)
echo '#!/bin/sh\necho "Hello from $(uname -m) as user $(id -u)"' > hello.sh
# Construit l'image à partir du Dockerfile courant et la tague demo/hello:1.0
docker build -t demo/hello:1.0 .
# Exécute le conteneur (se supprime automatiquement après grâce à --rm)
docker run --rm demo/hello:1.0
```

> **Resultat attendu** :
> ```
> $ echo '#!/bin/sh\necho "Hello from $(uname -m) as user $(id -u)"' > hello.sh
> (fichier créé)
>
> $ docker build -t demo/hello:1.0 .
> [+] Building 3.2s (9/9) FINISHED
> ...
> => => naming to docker.io/demo/hello:1.0
>
> $ docker run --rm demo/hello:1.0
> Hello from x86_64 as user 10001
> ```
> **Verification** : Le script affiche bien "Hello from x86_64 as user 10001" (ou aarch64 selon la machine). Le conteneur est supprimé après exécution (`docker ps -a` ne le montre pas).

**Étape 4 — Tagger & pousser (ex. GHCR)**

> **Objectif** : Préparer l'image pour le GitHub Container Registry (GHCR), s'authentifier et la publier.
> **Pre-requis** : Un compte GitHub avec un Personal Access Token (PAT) ayant les scopes `write:packages`. Remplacer `<org>` et `<user>` par les valeurs réelles.

```bash
# Crée un tag compatible GHCR (registre/nom_dépôt:version)
docker tag demo/hello:1.0 ghcr.io/<org>/hello:1.0
# S'authentifie auprès de GHCR en utilisant le token GitHub (méthode sécurisée via stdin)
echo "$GITHUB_TOKEN" | docker login ghcr.io -u <user> --password-stdin
# Pousse l'image vers GHCR
docker push ghcr.io/<org>/hello:1.0
```

> **Resultat attendu** :
> ```
> $ docker tag demo/hello:1.0 ghcr.io/<org>/hello:1.0
> (aucune sortie)
>
> $ echo "$GITHUB_TOKEN" | docker login ghcr.io -u <user> --password-stdin
> Login Succeeded
>
> $ docker push ghcr.io/<org>/hello:1.0
> The push refers to repository [ghcr.io/<org>/hello]
> abc123: Pushed
> 1.0: digest: sha256:xyz789... size: 1234
> ```
> **Verification** : Le login affiche "Login Succeeded". Le push affiche un digest. L'image est visible sur https://github.com/orgs/<org>/packages.

**Étape 5 — Inspecter l'historique & les labels**

> **Objectif** : Vérifier les couches de l'image construite et les labels qui y sont associés.
> **Pre-requis** : L'image `demo/hello:1.0` existe localement.

```bash
# Affiche l'historique des couches (chaque instruction du Dockerfile)
docker image history demo/hello:1.0
# Extrait et affiche les labels au format JSON
docker image inspect --format '{{json .Config.Labels}}' demo/hello:1.0 | jq
```

> **Resultat attendu** :
> ```
> $ docker image history demo/hello:1.0
> IMAGE          CREATED       CREATED BY                          SIZE
> a1b2c3d4       5 min ago     ENTRYPOINT ["./hello.sh"]           0B
> <missing>      5 min ago     RUN /bin/sh -c chmod +x hello.sh    35B
> <missing>      5 min ago     COPY hello.sh .                     65B
> <missing>      5 min ago     WORKDIR /app                        0B
> <missing>      5 min ago     USER 10001:10001                    0B
> <missing>      5 min ago     RUN adduser -D -u 10001 app         4.5kB
> <missing>      3 weeks ago   /bin/sh -c #(nop) CMD ["/bin/sh"]   0B
> <missing>      3 weeks ago   ADD alpine-minirootfs... in /       7.8MB
>
> $ docker image inspect --format '{{json .Config.Labels}}' demo/hello:1.0 | jq
> null
> ```
> **Verification** : L'historique montre chaque instruction du Dockerfile. `null` pour les labels car aucun LABEL n'a été défini dans ce Dockerfile minimal.

**Étape 6 — Save/Load (transfert offline)**

> **Objectif** : Sauvegarder l'image dans un fichier tar pour la transférer sur une machine sans accès au registre, puis la recharger.
> **Pre-requis** : L'image `demo/hello:1.0` existe localement.

```bash
# Exporte l'image complète dans un fichier tar (transportable par clé USB, scp, etc.)
docker save demo/hello:1.0 > hello.tar
# ... copier sur une autre machine ...
# Restaure l'image depuis le fichier tar sur la machine cible
docker load < hello.tar
```

> **Resultat attendu** :
> ```
> $ docker save demo/hello:1.0 > hello.tar
> (fichier créé, taille ~8MB pour une image Alpine)
>
> $ docker load < hello.tar
> abc123: Loading layer  7.8MB/7.8MB
> Loaded image: demo/hello:1.0
> ```
> **Verification** : `ls -lh hello.tar` montre un fichier non vide. Après `docker load`, l'image réapparaît dans `docker image ls` avec son tag `demo/hello:1.0`.

**Étape 7 — Nettoyer proprement**

> **Objectif** : Arrêter et supprimer le conteneur web, nettoyer les images dangling et vérifier l'espace disque.
> **Pre-requis** : Le conteneur `web` est en cours d'exécution (étape 2).

```bash
# Arrête le conteneur "web" puis le supprime
docker stop web && docker rm web
# Supprime les images dangling (orphelines, sans tag)
docker image prune -f
# Affiche le récapitulatif de l'espace disque utilisé par Docker
docker system df
```

> **Resultat attendu** :
> ```
> $ docker stop web && docker rm web
> web
> web
>
> $ docker image prune -f
> Deleted Images:
> deleted: sha256:orphan123...
> Total reclaimed space: 0B (ou variable selon les images dangling)
>
> $ docker system df
> TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
> Images          4         0         250MB     250MB (100%)
> Containers      0         0         0B        0B
> Local Volumes   0         0         0B        0B
> ```
> **Verification** : Le conteneur `web` n'apparaît plus dans `docker ps -a`. L'espace reclaimable est à 100% car aucun conteneur n'est actif.

---

## 13) FAQ & erreurs fréquentes (solutions rapides)

* **`denied: requested access to the resource is denied` (push)**
  → Mauvais `docker login` ou droits insuffisants sur le registre.

* **`manifest unknown` / `pull access denied`**
  → Tag inexistant, repo privé, faute de frappe sur le nom.

* **`no space left on device`**
  → `docker system df` puis `docker system prune -a` (⚠️), ou agrandir le disque.

* **Je tire `arm64` sur une machine `amd64`, et ça ne démarre pas**
  → Il faut l'émulation (QEMU/binfmt) ou une cible `amd64`.

* **J'ai oublié `.dockerignore`, mon image est énorme**
  → Ajoute-le et reconstruis ; vérifie `docker history` pour localiser les couches lourdes.

---

## 14) Checklist finale (qualité image)

* [ ] **.dockerignore** précis (pas de `.git`, `node_modules`, artefacts build).
* [ ] **Multi-stage** si build d'app (runtime **léger**).
* [ ] **USER non-root**, pas de secrets en dur, **labels OCI** complets.
* [ ] **Pinning** des versions ; base image raisonnable (`alpine`/`distroless`/`debian-slim`).
* [ ] **History** cohérent ; caches nettoyés **dans la même couche**.
* [ ] **Tag SemVer** publié ; **digest** noté pour déploiement.
* [ ] Image poussée sur un **registre de confiance** ; espace local **nettoyé**.

---

### Aide-mémoire (condensé)

> **Objectif** : Condensé de toutes les commandes essentielles pour une référence rapide (listage, pull, build, tag, push, inspect, save/load, nettoyage).
> **Pre-requis** : Docker installé. Les valeurs `org/app:1.0` et `ghcr.io/org/app:1.0` sont des exemples à adapter.

```bash
# ===== LISTAGE ET FILTRAGE =====
# Liste les images locales avec leur digest (empreinte SHA256)
docker images --digests
# Filtre les images par motif de référence (ici tout ce qui vient de ghcr.io/org/)
docker images --filter reference='ghcr.io/org/*'

# ===== PULL (téléchargement) =====
# Télécharge l'image Alpine 3.20 pour la plateforme ARM64
docker pull --platform linux/arm64 alpine:3.20

# ===== BUILD (construction) =====
# Construit une image à partir du Dockerfile spécifié et la tague org/app:1.0
docker build -t org/app:1.0 -f Dockerfile .

# ===== TAG & PUSH (publication) =====
# Ajoute un tag GHCR à l'image locale pour la préparer au push
docker tag org/app:1.0 ghcr.io/org/app:1.0
# S'authentifie puis pousse l'image vers GHCR
docker login ghcr.io && docker push ghcr.io/org/app:1.0

# ===== INSPECT & HISTORY (analyse) =====
# Affiche toutes les métadonnées de l'image au format JSON
docker inspect org/app:1.0
# Affiche l'historique des couches (instructions ayant construit l'image)
docker history org/app:1.0

# ===== SAVE & LOAD (transfert offline) =====
# Sauvegarde l'image dans un fichier tar
docker save org/app:1.0 > app.tar
# Restaure l'image depuis le fichier tar
docker load < app.tar

# ===== NETTOYAGE =====
# Supprime les images dangling (orphelines sans tag)
docker image prune -f
# Affiche le résumé de l'espace disque utilisé par Docker
docker system df
```

> **Resultat attendu** :
> ```
> $ docker images --digests
> REPOSITORY    TAG    DIGEST           IMAGE ID       SIZE
> org/app       1.0    sha256:abc123...  a1b2c3d4e5f6   50MB
>
> $ docker build -t org/app:1.0 -f Dockerfile .
> [+] Building 5.0s (8/8) FINISHED
> ...
>
> $ docker inspect org/app:1.0
> [
>   {
>     "Id": "sha256:a1b2c3d4...",
>     "Os": "linux",
>     "Architecture": "amd64",
>     ...
>   }
> ]
>
> $ docker system df
> TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
> Images          3         1         200MB     100MB (50%)
> Containers      1         1         10MB      0B (0%)
> Local Volumes   0         0         0B        0B
> ```
> **Verification** : Chaque commande produit le résultat décrit dans les sections précédentes du chapitre. Ce condensé couvre le cycle de vie complet d'une image Docker.