# Chapitre-07 — Registry & Distribution

## Objectifs d'apprentissage

* Maîtriser l'**écosystème OCI registry** (pousser/tirer des images, authentification, namespaces, tags, digests).
* Déployer un **registry privé sécurisé** (TLS, authentification), configurer **proxy cache / mirroring**, et gérer **GC (garbage collect)**.
* Mettre en place des **politiques de gouvernance** (immutabilité, rétention, conventions de nommage), **scans**, **signatures** (cosign) et **SBOM/provenance**.
* Intégrer le registry à vos **pipelines CI/CD** (tokens, permissions minimales, promotion par digest).

## Pré-requis

* Compréhension des images (Ch.-01), du build (Ch.-05) et de Compose (Ch.-06).
* Nocions TLS/PKI et reverse-proxy (Nginx/Traefik/Caddy).

---

## 1) Rappels : identité d'une image & registres

* **Nom complet** : `[registry]/[namespace]/repo[:tag]` ou `@[digest]`
  Ex. `ghcr.io/acme/api:1.4.2`, `registry.example.com/prod/web@sha256:…`
* **Tag** = alias **mutable** ; **digest** = identifiant **immuable**.
* **Bonnes pratiques** : publier des **tags versionnés** (SemVer + canaux) et **déployer par digest** en prod.

---

## 2) Authentification côté client

> **Objectif** : S'authentifier auprès d'un registry OCI puis pousser/tirer des images.
> **Pré-requis** : Docker installé, accès réseau au registry, identifiants (PAT/token) valides.

```bash
# --- Authentification auprès des registries ---
# Connexion interactive à GitHub Container Registry (ghcr.io)
# Le token/mot de passe est saisi interactivement et stocké dans ~/.docker/config.json
docker login ghcr.io
# Connexion à un registry privé (ex. auto-hébergé)
docker login registry.example.com

# --- Opérations push / pull ---
# Pousse l'image locale taguée vers le registry privé, namespace "team/app", tag "1.0"
docker push registry.example.com/team/app:1.0
# Tire l'image par son digest immuable (recommandé en production pour la reproductibilité)
docker pull registry.example.com/team/app@sha256:...
```

> **Résultat attendu** :
> ```
> $ docker login ghcr.io
> Username: <votre-user>
> Password: <token>
> Login Succeeded
> $ docker push registry.example.com/team/app:1.0
> The push refers to repository [registry.example.com/team/app]
> abc12345: Pushed
> 1.0: digest: sha256:a1b2c3... size: 1234
> ```
> **Vérification** : Le login affiche `Login Succeeded`. Le push affiche un digest `sha256:...`. Vérifier `~/.docker/config.json` contient l'`auth` encodée en base64.

* Utilisez des **PAT / tokens CI** à portée **minimale** (scopes lecture/écriture par repo).
* Évitez de stocker des identifiants en clair ; préférez **OIDC** quand supporté par le CI.

---

## 3) Quick start : registry privé basique (filesystem)

### 3.1 En Compose (dev/lab)

> **Objectif** : Déployer un registry Docker minimal en local (dev/lab) avec stockage filesystem, sans TLS ni auth.
> **Pré-requis** : Docker et Docker Compose installés. Port 5000 libre sur la machine hôte.

```yaml
services:
  registry:
    image: registry:2                        # Image officielle Docker Registry v2
    container_name: registry                 # Nom fixe du conteneur pour faciliter les commandes docker exec
    environment:
      REGISTRY_STORAGE_FILESYSTEM_ROOTDIRECTORY: /var/lib/registry  # Répertoire de stockage des blobs/manifests
      REGISTRY_HTTP_ADDR: :5000              # Adresse d'écoute interne du registry (port 5000)
      REGISTRY_STORAGE_DELETE_ENABLED: "true"   # nécessaire pour GC — autorise la suppression de manifests/blobs
    volumes:
      - registry-data:/var/lib/registry      # Volume named pour persister les données entre redémarrages
    ports:
      - "5000:5000"                          # Exposition du port 5000 hôte → conteneur (HTTP non sécurisé)
volumes:
  registry-data: {}                          # Déclaration du volume named (créé automatiquement au premier up)
```

> **Résultat attendu** :
> ```
> $ docker compose up -d
> ✔ Network chapitre-07_default  Created
> ✔ Container registry           Started
> $ docker ps
> CONTAINER ID  IMAGE        COMMAND                  PORTS                    NAMES
> abcdef123456  registry:2   "/entrypoint.sh /etc…"   0.0.0.0:5000->5000/tcp   registry
> ```
> **Vérification** : `curl http://localhost:5000/v2/` retourne `{}`. `docker tag myapp localhost:5000/myapp && docker push localhost:5000/myapp` fonctionne.

* En l'état : **HTTP** sans auth (lab uniquement).
* En production : **placer derrière un reverse-proxy TLS** + **authentification**.

---

## 4) Production : TLS + authentification

### 4.1 Registry config.yml (auth `htpasswd`, headers, proxy)

`config.yml`

> **Objectif** : Configuration complète du registry pour la production : stockage filesystem, en-têtes de sécurité, authentification htpasswd, et support reverse-proxy.
> **Pré-requis** : Fichier `auth/htpasswd` existant (généré avec `htpasswd -Bbn`), répertoire `/var/lib/registry` monté en volume.

```yaml
version: 0.1                               # Version du format de configuration (0.1 est la seule supportée)
log:
  fields: { service: registry }            # Champ ajouté à chaque log (utile pour l'agrégation centralisée)
storage:
  filesystem:
    rootdirectory: /var/lib/registry       # Racine du stockage des blobs et manifests sur le filesystem
http:
  addr: :5000                              # Port d'écoute interne du registry
  headers:
    X-Content-Type-Options: [nosniff]      # Empêche le MIME-sniffing (sécurité anti-injection)
  # Si derrière un reverse-proxy :
  relativeurls: true                       # Génère des URLs relatives (nécessaire quand le proxy réécrit les chemins)
  host: https://registry.example.com       # URL publique du registry (utilisée dans les réponses Location)
auth:
  htpasswd:
    realm: basic-realm                     # Nom du realm affiché lors de l'authentification HTTP Basic
    path: /auth/htpasswd                   # Chemin vers le fichier htpasswd (bcrypt) dans le conteneur
delete:
  enabled: true                            # Active la suppression de manifests (requis pour le garbage collect)
```

> **Résultat attendu** :
> ```
> # Le registry démarre sans erreur et exige une authentification :
> $ curl -s https://registry.example.com/v2/
> {"errors":[{"code":"UNAUTHORIZED","message":"authentication required",...}]}
> $ curl -s -u user:pass https://registry.example.com/v2/
> {}
> ```
> **Vérification** : Un `curl` sans auth retourne `401 UNAUTHORIZED`. Avec les bons identifiants, `/v2/` retourne `{}`.

### 4.2 Compose avec Nginx TLS (exemple)

> **Objectif** : Orchestration du registry + Nginx en reverse-proxy TLS dans un réseau Docker isolé.
> **Pré-requis** : Fichiers `config.yml`, `nginx.conf`, certificats `certs/fullchain.pem` et `certs/privkey.pem`, et répertoire `auth/` avec `htpasswd`.

```yaml
services:
  registry:
    image: registry:2                      # Image officielle du registry Docker v2
    environment:
      REGISTRY_CONFIGURATION_PATH: /etc/docker/registry/config.yml  # Pointe vers le fichier de config monté
    volumes:
      - ./config.yml:/etc/docker/registry/config.yml:ro   # Montage de la config en lecture seule
      - ./auth:/auth:ro                    # Fichier htpasswd monté en lecture seule
      - registry-data:/var/lib/registry    # Persistance des données du registry
    networks: [ net ]                      # Réseau isolé (non exposé directement à l'hôte)
  nginx:
    image: nginx:alpine                    # Nginx léger (Alpine) comme reverse-proxy TLS
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro   # Configuration Nginx personnalisée
      - ./certs:/etc/nginx/certs:ro   # fullchain.pem / privkey.pem — certificats TLS
    ports:
      - "443:443"                          # Exposition du port HTTPS vers l'extérieur
    depends_on: [ registry ]               # Nginx attend que le registry soit démarré
    networks: [ net ]                      # Même réseau que le registry pour la communication interne
networks: { net: {} }                      # Réseau Docker bridge isolé
volumes:   { registry-data: {} }           # Volume named pour les données du registry
```

> **Résultat attendu** :
> ```
> $ docker compose up -d
> ✔ Network net             Created
> ✔ Volume registry-data    Created
> ✔ Container registry      Started
> ✔ Container nginx         Started
> $ curl -sk https://registry.example.com/v2/
> {"errors":[{"code":"UNAUTHORIZED",...}]}
> ```
> **Vérification** : `docker compose ps` montre les deux conteneurs `Up`. `curl -sk https://localhost:443/v2/` répond (401 sans auth). Le port 5000 n'est **pas** exposé directement.

`nginx.conf` (extrait minimal TLS + proxy)

> **Objectif** : Configurer Nginx comme reverse-proxy TLS terminant le HTTPS et relayant vers le registry en HTTP interne.
> **Pré-requis** : Certificats TLS valides (`fullchain.pem` + `privkey.pem`) dans le dossier `certs/`.

```nginx
events {}                                # Bloc requis par Nginx (aucun événement personnalisé ici)
http {
  server {
    listen 443 ssl;                      # Écoute sur le port 443 en mode TLS
    server_name registry.example.com;    # Nom de domaine attendu (SNI)

    ssl_certificate     /etc/nginx/certs/fullchain.pem;    # Chaîne complète de certificats (serveur + intermédiaires)
    ssl_certificate_key /etc/nginx/certs/privkey.pem;      # Clé privée associée au certificat

    client_max_body_size 0;               # 0 = pas de limite — nécessaire pour les gros blobs d'images
    chunked_transfer_encoding on;         # Active le transfert chunked (requis par le protocole registry v2)

    location /v2/ {                       # Route uniquement les appels à l'API v2 du registry
      proxy_set_header Host $http_host;              # Transmet le Host original (important pour les URLs signées)
      proxy_set_header X-Real-IP $remote_addr;       # Transmet l'IP réelle du client dans les logs du registry
      proxy_set_header X-Forwarded-Proto https;      # Indique au registry que la connexion client était en HTTPS
      proxy_pass http://registry:5000;               # Relaye vers le service "registry" du réseau Docker sur le port 5000
      add_header Docker-Distribution-Api-Version registry/2.0 always;  # Header requis par le client Docker
    }
  }
}
```

> **Résultat attendu** :
> ```
> $ docker exec nginx nginx -t
> nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
> nginx: configuration file /etc/nginx/nginx.conf test is successful
> $ curl -sk https://registry.example.com/v2/
> {"errors":[{"code":"UNAUTHORIZED",...}]}
> ```
> **Vérification** : `nginx -t` passe. Le header `Docker-Distribution-Api-Version: registry/2.0` est présent dans les réponses (`curl -sI`). Les pushes de grosses images ne retournent pas `413`.

Créer l'**auth** :

> **Objectif** : Générer un fichier `htpasswd` avec un utilisateur `user` et un mot de passe `pass` hashé en bcrypt.
> **Pré-requis** : Docker installé (pour exécuter l'image `httpd:2.4-alpine` qui contient l'outil `htpasswd`).

```bash
# Crée le répertoire qui sera monté dans le registry et Nginx
mkdir -p auth
# Utilise l'image httpd (contenant htpasswd) pour générer un hash bcrypt (-Bbn) du couple user/pass
# -B = bcrypt, -b = batch (non-interactif), -n = sortie stdout
docker run --rm --entrypoint htpasswd httpd:2.4-alpine -Bbn user pass > auth/htpasswd
```

> **Résultat attendu** :
> ```
> $ cat auth/htpasswd
> user:$2y$05$XM...bcryptHash...
> ```
> **Vérification** : Le fichier `auth/htpasswd` existe et contient une ligne au format `user:$2y$...`. `docker login localhost:5000` avec `user`/`pass` réussit.

> Alternative facile : **Traefik/Caddy** avec ACME (Let's Encrypt) automatique.

---

## 5) Proxy cache (pull-through cache) & mirrors

### 5.1 Registry comme proxy cache de Docker Hub

`config.yml` (extrait)

> **Objectif** : Configurer le registry comme miroir proxy (pull-through cache) de Docker Hub pour réduire la bande passante et éviter les rate-limits.
> **Pré-requis** : Un registry déployé avec cette configuration. Les images tirées via ce registry seront mises en cache localement.

```yaml
proxy:
  remoteurl: https://registry-1.docker.io  # URL du registry amont (Docker Hub) à mettre en cache
```

> **Résultat attendu** :
> ```
> # Premier pull (lent, télécharge depuis Docker Hub et met en cache)
> $ docker pull registry.example.com/library/nginx:latest
> latest: Pulling from library/nginx
> a2abf6c4d291: Pull complete
> # Pull suivant (rapide, servi depuis le cache local)
> $ docker pull registry.example.com/library/nginx:latest
> latest: Pulling from library/nginx
> Digest: sha256:...
> Status: Image is up to date
> ```
> **Vérification** : Le premier pull d'une image est plus lent. Les pulls suivants sont quasi-instantanés. Vérifier les logs du registry : `docker logs registry | grep "pulling"`.

* Le registry **cache** les blobs tirés.
* Configurez les clients Docker pour utiliser ce **miroir**.

### 5.2 Côté clients (`/etc/docker/daemon.json`)

> **Objectif** : Configurer le daemon Docker pour utiliser le registry comme miroir de Docker Hub, réduisant les rate-limits.
> **Pré-requis** : Le registry proxy cache est opérationnel et accessible en HTTPS. Redémarrage de `dockerd` nécessaire après modification.

```json
{
  "registry-mirrors": ["https://registry.example.com"],  // Liste des miroirs pour Docker Hub (essayés dans l'ordre)
  "insecure-registries": []                               // Registries autorisés sans TLS — laisser vide en production
}
```

> **Résultat attendu** :
> ```
> $ sudo systemctl restart docker
> $ docker info | grep -A2 "Registry Mirrors"
>  Registry Mirrors:
>   https://registry.example.com/
> ```
> **Vérification** : `docker info` affiche le miroir sous `Registry Mirrors`. Les `docker pull` d'images Docker Hub transitent par le miroir (visible dans les logs du registry proxy).

> Ne mettez **insecure-registries** que pour des lab **sans TLS** (à proscrire en prod).

---

## 6) Stockage : filesystem vs S3/objets

### 6.1 S3 backend (exemple)

`config.yml` (extrait)

> **Objectif** : Utiliser Amazon S3 (ou compatible) comme backend de stockage pour le registry, permettant la haute disponibilité et la scalabilité horizontale.
> **Pré-requis** : Bucket S3 créé, clés d'accès IAM avec permissions `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket`. Variables d'environnement `S3_ACCESS_KEY` et `S3_SECRET_KEY` définies.

```yaml
storage:
  s3:
    region: eu-west-3                    # Région AWS du bucket (ici Paris)
    bucket: my-registry-bucket           # Nom du bucket S3 dédié au registry
    accesskey: ${S3_ACCESS_KEY}          # Clé d'accès IAM (lue depuis une variable d'environnement)
    secretkey: ${S3_SECRET_KEY}          # Clé secrète IAM (lue depuis une variable d'environnement)
    encrypt: true                        # Chiffrement côté serveur (SSE-S3 ou SSE-KMS)
    secure: true                         # Communication HTTPS vers S3 (ne jamais désactiver en prod)
    rootdirectory: /registry             # Préfixe/clé racine dans le bucket (isole les données du registry)
```

> **Résultat attendu** :
> ```
> # Après push d'une image, le bucket contient les blobs et manifests :
> $ aws s3 ls s3://my-registry-bucket/registry/docker/registry/v2/blobs/sha256/
> PRE aa/
> PRE bb/
> PRE cc/
> ```
> **Vérification** : `aws s3 ls s3://my-registry-bucket/registry/` montre la structure de stockage. Les blobs sont chiffrés (vérifier les métadonnées S3 : `x-amz-server-side-encryption`).

* Pour **HA/scalabilité** : répliquer plusieurs instances derrière un **LB**, stockage partagé (S3/Swift/GCS…), optionnellement un cache **Redis**.
* Pensez **versioning** côté bucket (rétention), chiffrement et **lifecycle**.

---

## 7) Suppression & Garbage Collect (GC)

* Activer `delete.enabled: true` (vu plus haut).
* Supprimer un **manifeste** (par **digest**, pas par tag) puis **GC**.

Avec **crane** :

> **Objectif** : Lister le digest d'un tag puis supprimer l'image correspondante du registry via l'outil `crane`.
> **Pré-requis** : `crane` installé (`go install github.com/google/go-containerregistry/cmd/crane@latest` ou binaire pré-compilé). Authentification préalable via `docker login` ou `crane auth login`.

```bash
# Affiche le digest SHA256 associé au tag "1.0" (nécessaire pour la suppression)
crane digest registry.example.com/team/app:1.0
# Supprime le manifeste identifié par son digest (pas par tag — le tag ne pointe plus vers rien après)
crane delete registry.example.com/team/app@sha256:...
```

> **Résultat attendu** :
> ```
> $ crane digest registry.example.com/team/app:1.0
> sha256:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
> $ crane delete registry.example.com/team/app@sha256:a1b2c3...
> 2024/01/15 10:30:00 DELETE registry.example.com/v2/team/app/manifests/sha256:a1b2c3...
> ```
> **Vérification** : `crane ls registry.example.com/team/app` ne montre plus le tag `1.0`. Le blob existe toujours sur disque jusqu'au GC.

Lancer le **GC** (arrêt d'écriture recommandé) :

> **Objectif** : Exécuter le garbage collector du registry pour supprimer les blobs orphelins (non référencés par un manifeste) et libérer l'espace disque.
> **Pré-requis** : Idéalement, stopper les pushes pendant le GC. Le conteneur `registry` doit être en cours d'exécution. `delete.enabled: true` dans la config.

```bash
# Exécute le GC dans le conteneur registry existant
# --delete-untagged=true supprime aussi les manifests sans tag (en plus des blobs orphelins)
docker exec -it registry registry garbage-collect --delete-untagged=true /etc/docker/registry/config.yml
```

> **Résultat attendu** :
> ```
> $ docker exec -it registry registry garbage-collect --delete-untagged=true /etc/docker/registry/config.yml
> time="2024-01-15T10:35:00Z" level=info msg="deleting blob: /var/lib/registry/docker/registry/v2/blobs/sha256/aa/aabb..."
> time="2024-01-15T10:35:01Z" level=info msg="deleting blob: /var/lib/registry/docker/registry/v2/blobs/sha256/cc/ccdd..."
> time="2024-01-15T10:35:01Z" level=info msg="progress: 2 blobs deleted, 150 MB freed"
> ```
> **Vérification** : L'espace disque diminue (`df -h` ou `docker system df`). Les blobs supprimés ne sont plus dans `/var/lib/registry/docker/registry/v2/blobs/`.

> Le GC libère le disque des blobs **orphelins**. Enregistrez une fenêtre de maintenance.

---

## 8) Gouvernance : nommage, immutabilité, rétention

* **Nommage** : `org/projet/service` ; préfixes d'environnements (`dev/`, `prod/`) au besoin.
* **Tags** : SemVer (`1.4.2`), canaux (`rc`, `stable`), politique **anti-écrasement** des tags prod.
* **Immutabilité** : **déployer par digest** ; activer immutabilité côté registry (Harbor/Nexus) si possible.
* **Rétention** : règles d'expiration (Harbor/Nexus) ou procédures de **GC** + nettoyage des tags.
* **Licences** : scans en CI, blocage si licence interdite.
* Documenter un **annuaire des images** (qui produit ? cadence ? PO ?).

*(Voir aussi **Annexe C** du syllabus pour une politique prête à l'emploi.)*

---

## 9) Sécurité supply-chain : scans, signatures, SBOM/provenance

### 9.1 Scans (CVE & licences)

* **Trivy** / **Docker Scout** en CI : échouer au-delà d'un **seuil** (ex. CVE HIGH).
* Harbor/Artifactory/Nexus : scans intégrés + **politiques** d'admission.

### 9.2 Signatures (cosign / Sigstore)

> **Objectif** : Signer une image avec une clé locale cosign puis vérifier la signature avant déploiement, garantissant l'intégrité et l'origine de l'image.
> **Pré-requis** : `cosign` installé (`go install github.com/sigstore/cosign/v2/cmd/cosign@latest`). Une paire de clés générée (`cosign generate-key-pair`). L'image est déjà poussée dans le registry.

```bash
# Signe l'image avec la clé privée locale (cosign.key) — crée un artefact de signature OCI dans le registry
cosign sign registry.example.com/team/app:1.4.2

# Vérifie la signature de l'image avec la clé publique (cosign.pub) — échoue si non signée ou altérée
cosign verify registry.example.com/team/app:1.4.2
```

> **Résultat attendu** :
> ```
> $ cosign sign registry.example.com/team/app:1.4.2
> Enter password for private key:
> Pushing signature to: registry.example.com/team/app:sha256-a1b2c3...sig
> $ cosign verify registry.example.com/team/app:1.4.2
> Verification successful
> [{"critical":{"identity":{...},"image":{...},"type":"cosign container image signature"},...}]
> ```
> **Vérification** : `cosign sign` crée un tag de signature `sha256-<digest>.sig` dans le registry. `cosign verify` retourne `Verification successful` avec le payload JSON.

* **Keyless** (OIDC) possible ; stocke signatures comme **artefacts OCI** reliés.

### 9.3 SBOM & provenance (buildx)

> **Objectif** : Construire et pousser une image avec SBOM (Software Bill of Materials) et provenance attachés comme artefacts OCI, pour la traçabilité et la conformité.
> **Pré-requis** : Docker Buildx avec un builder supportant les attestations (driver `docker-container`). L'image est construite depuis un `Dockerfile` dans le répertoire courant.

```bash
docker buildx build \
  --provenance=true \       # Attache les métadonnées de provenance (builder, source, paramètres de build)
  --sbom=true \             # Génère et attache un SBOM (SPDX) listant tous les paquets de l'image
  -t registry.example.com/team/app:1.4.2 \  # Tag complet de l'image dans le registry
  --push \                  # Pousse l'image ET les artefacts d'attestation vers le registry
  .                         # Contexte de build (répertoire courant contenant le Dockerfile)
```

> **Résultat attendu** :
> ```
> $ docker buildx build --provenance=true --sbom=true -t registry.example.com/team/app:1.4.2 --push .
> #1 [internal] load build definition from Dockerfile
> ...
> #23 exporting to image
> #23 pushing layers 3.5s done
> #23 pushing manifest for registry.example.com/team/app:1.4.2
> #23 DONE
> #24 pushing attestation manifests 1.2s done
> ```
> **Vérification** : `cosign tree registry.example.com/team/app:1.4.2` montre les artefacts attachés (SBOM + provenance). `docker buildx imagetools inspect registry.example.com/team/app:1.4.2` affiche les attestations.

* Les artefacts (SPDX/CycloneDX, provenance) sont **associés** à l'image dans le registry.
* Publiez et **conservez** ces preuves (audit/compliance).

---

## 10) Intégration CI/CD (promotion par digest)

* **Build & push** vers un registry **interne** (dev) ; scanner, signer, attester.
* **Promouvoir** l'**exact digest** validé vers staging/prod (retag/push contrôlé) :

> **Objectif** : Promouvoir une image d'un environnement dev vers prod par copier-coller du digest exact (sans re-upload des blobs), garantissant que le même binaire est déployé.
> **Pré-requis** : `crane` installé. L'image `dev/app:1.4.2` existe dans le registry et a été scannée/signée. Le namespace `prod/app` existe dans le registry.

```bash
# Capture le digest SHA256 du tag dev dans une variable (garantit qu'on promeut exactement cette version)
DIGEST=$(crane digest registry.example.com/dev/app:1.4.2)
# Copie l'image identifiée par son digest vers le namespace prod (sans re-upload des blobs — simple ré-référencement)
crane copy registry.example.com/dev/app@${DIGEST} registry.example.com/prod/app:1.4.2
```

> **Résultat attendu** :
> ```
> $ DIGEST=$(crane digest registry.example.com/dev/app:1.4.2)
> $ echo $DIGEST
> sha256:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
> $ crane copy registry.example.com/dev/app@${DIGEST} registry.example.com/prod/app:1.4.2
> 2024/01/15 11:00:00 Copying registry.example.com/dev/app@sha256:a1b2c3... to registry.example.com/prod/app:1.4.2
> 2024/01/15 11:00:01 Copied registry.example.com/prod/app:1.4.2
> ```
> **Vérification** : `crane digest registry.example.com/prod/app:1.4.2` retourne le **même digest** que `dev/app:1.4.2`. Aucun blob n'a été re-téléversé (copie côté registry).

* Déploiements **par digest** ; **deny** si non signé / non scanné / SBOM manquant.

---

## 11) Exemple complet : Registry privé + Traefik (ACME auto) + Auth

`compose.yaml`

> **Objectif** : Déployer un registry privé complet avec Traefik comme reverse-proxy, TLS automatique via Let's Encrypt (ACME), et authentification htpasswd native du registry.
> **Pré-requis** : Domaine `registry.example.com` pointant vers le serveur. Port 443 ouvert. Docker et Docker Compose installés. Répertoire `auth/` avec `htpasswd` (voir section 4.2).

```yaml
services:
  traefik:
    image: traefik:v3.1                    # Traefik v3.1 comme reverse-proxy et gestionnaire TLS
    command:
      - "--providers.docker=true"          # Active la découverte automatique des services via les labels Docker
      - "--entrypoints.websecure.address=:443"  # Définit un point d'entrée HTTPS sur le port 443
      - "--certificatesresolvers.le.acme.tlschallenge=true"   # Résolveur ACME via challenge TLS (pas besoin de port 80)
      - "--certificatesresolvers.le.acme.email=admin@example.com"  # Email pour Let's Encrypt (notifications expiration)
      - "--certificatesresolvers.le.acme.storage=/letsencrypt/acme.json"  # Fichier de stockage des certificats obtenus
    ports:
      - "443:443"                          # Exposition du port HTTPS
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro  # Accès à l'API Docker pour la découverte de services (lecture seule)
      - ./letsencrypt:/letsencrypt         # Persistance des certificats ACME entre redémarrages
    restart: unless-stopped                # Redémarrage automatique sauf arrêt manuel

  registry:
    image: registry:2                      # Image officielle Docker Registry v2
    environment:
      REGISTRY_HTTP_ADDR: :5000            # Port d'écoute interne du registry
      REGISTRY_HTTP_HEADERS_Access-Control-Allow-Origin: '[*]'  # CORS activé (utile pour les UIs tierces)
      REGISTRY_STORAGE_DELETE_ENABLED: "true"  # Active la suppression (requis pour GC)
      REGISTRY_AUTH_HTPASSWD_REALM: "basic-realm"  # Realm d'authentification HTTP Basic
      REGISTRY_AUTH_HTPASSWD_PATH: /auth/htpasswd  # Chemin du fichier htpasswd dans le conteneur
    labels:
      - "traefik.enable=true"              # Active la découverte Traefik pour ce conteneur
      - "traefik.http.routers.registry.rule=Host(`registry.example.com`)"  # Route uniquement le domaine registry.example.com
      - "traefik.http.routers.registry.entrypoints=websecure"  # Utilise le point d'entrée HTTPS (443)
      - "traefik.http.routers.registry.tls.certresolver=le"  # Demande un certificat TLS via le résolveur ACME "le"
      - "traefik.http.services.registry.loadbalancer.server.scheme=http"  # Protocole interne vers le registry (HTTP)
      - "traefik.http.services.registry.loadbalancer.server.port=5000"    # Port interne du registry
    volumes:
      - registry-data:/var/lib/registry    # Persistance des données du registry
      - ./auth:/auth:ro                    # Fichier htpasswd monté en lecture seule
    restart: unless-stopped                # Redémarrage automatique sauf arrêt manuel

volumes:
  registry-data: {}                        # Volume named pour les données du registry
```

> **Résultat attendu** :
> ```
> $ docker compose up -d
> ✔ Network root_default     Created
> ✔ Volume letsencrypt       Created
> ✔ Volume registry-data     Created
> ✔ Container root-traefik-1 Started
> ✔ Container root-registry-1 Started
> $ curl -sk https://registry.example.com/v2/
> {"errors":[{"code":"UNAUTHORIZED","message":"authentication required",...}]}
> ```
> **Vérification** : `docker compose ps` montre les deux conteneurs `Up`. Le certificat Let's Encrypt est obtenu automatiquement (vérifier `./letsencrypt/acme.json`). `docker login registry.example.com` avec les bons identifiants réussit. `docker push registry.example.com/team/app:1.0` fonctionne en HTTPS.

* Avantages : TLS **automatique**, config simple, **auth htpasswd** native du registry.

---

## 12) Outils pratiques autour des registries

* **crane / gcrane** (google/go-containerregistry) : `crane ls`, `crane digest`, `crane copy`, `crane delete`.
* **skopeo** : inspect/copy/sign (multi-backends).
* **oras** : gérer **artefacts OCI** (push/pull SBOM, attestions, charts, etc.).
* **regctl** : client Docker Distribution (delete/GC friendly).
* **Harbor/Nexus/Artifactory** : GUIs, RBAC, scans, immutabilité, réplication, rétention.

---

## 13) Dépannage courant

* **401 Unauthorized** : vérifier `docker login` (bon host), horloge (TLS/ACME), header `Host` côté proxy.
* **413 Request Entity Too Large** : augmenter `client_max_body_size` (Nginx) / `traefik.http.middlewares.compress` côté Traefik.
* **Manifest unknown** : tag absent, mauvais repo, ou **cache** pas encore rempli.
* **SSL / certificats** : chaîne incomplète → fournir **fullchain** ; horloge/NTP.
* **GC inefficace** : digest non supprimé, `delete.enabled=false`, ou writes toujours en cours.
* **Rate-limit Docker Hub** : configurer un **mirror/proxy cache** côté clients.

---

## 14) Do & Don't

**Do**

* Toujours **TLS** + **auth** (même interne).
* **Déployer par digest** ; **signer** (cosign) ; **SBOM & provenance** activés.
* **Proxy cache** pour Docker Hub ; **mirrors** côté clients.
* **Politiques** : immutabilité des tags prod, rétention, nettoyage + **GC**.
* CI/CD : tokens **scopés**, **promotion par digest**, scans bloquants.

**Don't**

* Pas d'**insecure registry** en prod.
* Ne pas **écraser** des tags stables publiés sans politique claire.
* Éviter d'exposer directement le registry sur Internet **sans** reverse-proxy durci.
* Ne stockez pas de **secrets** dans les images / tags publics.

---

## 15) Aide-mémoire (commandes clés)

> **Objectif** : Récapitulatif des commandes essentielles pour l'administration quotidienne d'un registry OCI.
> **Pré-requis** : `docker`, `crane`, `cosign` installés. Authentification préalable au registry (`docker login`).

```bash
# === Auth & push ===
# Connexion au registry privé
docker login registry.example.com
# Taggage de l'image locale "app:1.0" vers le registry (obligatoire avant push)
docker tag app:1.0 registry.example.com/team/app:1.0
# Pousse l'image taguée vers le registry
docker push registry.example.com/team/app:1.0

# === Digests & copies ===
# Récupère le digest SHA256 d'un tag (pour déploiement immuable)
crane digest registry.example.com/team/app:1.0
# Copie une image d'un namespace à l'autre par digest (promotion, sans re-upload des blobs)
crane copy registry.example.com/team/app@sha256:... registry.example.com/prod/app:1.0

# === Delete & GC ===
# Supprime un manifeste par digest (les blobs restent jusqu'au GC)
crane delete registry.example.com/team/app@sha256:...
# Lance le garbage collector pour libérer les blobs orphelins
docker exec -it registry registry garbage-collect --delete-untagged=true /etc/docker/registry/config.yml

# === Signatures & vérif ===
# Signe l'image avec la clé privée cosign (crée un artefact .sig dans le registry)
cosign sign registry.example.com/team/app:1.0
# Vérifie la signature avec la clé publique (échoue si invalide ou absente)
cosign verify registry.example.com/team/app:1.0

# === SBOM/provenance lors du build ===
# Build avec SBOM + provenance attachés, puis push vers le registry
docker buildx build --sbom --provenance -t registry.example.com/team/app:1.0 --push .
```

> **Résultat attendu** :
> ```
> $ docker login registry.example.com
> Login Succeeded
> $ docker push registry.example.com/team/app:1.0
> The push refers to repository [registry.example.com/team/app]
> abc12345: Pushed
> 1.0: digest: sha256:a1b2c3... size: 1234
> $ crane digest registry.example.com/team/app:1.0
> sha256:a1b2c3d4e5f6...
> $ cosign verify registry.example.com/team/app:1.0
> Verification successful
> ```
> **Vérification** : Chaque commande se termine sans erreur. `docker push` affiche un digest. `crane digest` retourne un `sha256:...`. `cosign verify` affiche `Verification successful`.

---

## 16) Checklist de clôture (qualité d'un registry)

* **TLS** valide (ACME/LE ou PKI interne), **auth** activée, en-têtes sûrs.
* **Delete.enabled** actif ; procédure **GC** documentée + fenêtre de maintenance.
* **Proxy cache** / **mirrors** configurés pour les clients ; **rate-limit** éliminé.
* **Politiques** : nommage, immutabilité des tags prod, **rétention** (Harbor/Nexus) ou GC programmé.
* **Sécurité** : scans CVE/licences en CI, **cosign** (sign & verify), **SBOM/provenance** publiés.
* **CI/CD** : tokens à **moindre privilège**, promotion **par digest**, traçabilité complète.
* **Supervision** : logs, capacité stockage, latence pushes/pulls, alertes expiration de certificats.
