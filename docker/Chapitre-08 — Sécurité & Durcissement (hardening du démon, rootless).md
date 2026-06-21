# Chapitre-08 — Sécurité & Durcissement

*(hardening du démon, rootless, userns-remap, seccomp/AppArmor/SELinux, socket proxy, secrets, policies)*

## Objectifs d’apprentissage

* Définir un **modèle de menace** et appliquer le **moindre privilège** à tous les niveaux (images, runtime, hôte, supply chain).
* Durcir **dockerd** (configuration, journaux, API TLS fermée ou proxy, iptables, rotation des logs).
* Maîtriser les modes **rootless** et **userns-remap** (isolation UID/GID) et leurs impacts.
* Renforcer l’exécution : **non-root**, **capabilities minimales**, **seccomp/AppArmor/SELinux**, **read-only**, **tmpfs**, **sysctl**.
* Gérer **secrets**, **politiques d’images** (signatures, SBOM, scans), et **auditer** (journaux, commandes, accès).

## Pré-requis

* Connaissances des chapitres 01–07 (images, conteneurs, storage, réseau, build, compose, registry).
* Accès root sur l’hôte pour la partie démon (sauf mode rootless).

---

## 1) Principes & modèle de menace

* **Réduire la surface** : moins de paquets sur l’hôte, pas de services inutiles, noyau à jour.
* **Moindre privilège** : pas de `--privileged`, réduire **capabilities**, exécuter **non-root**.
* **Compartimenter** : réseaux séparés, `--internal` pour backends, volumes spécifiques RO/RW.
* **Vérité des artefacts** : images signées, **SBOM**, scans CVE/licences, déploiement **par digest**.
* **Visibilité** : journaux, métriques, traces ; audit des accès à la **socket Docker**.

---

## 2) Hardening du démon Docker (dockerd)

### 2.1 `daemon.json` (exemples commentés)

`/etc/docker/daemon.json`

```json
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },

  "icc": false,                        // coupe la comm. inter-ctr sur docker0 (user-defined bridges restent préférables)
  "iptables": true,                    // laisser Docker gérer son pare-feu (sinon gérer soi-même)
  "live-restore": true,                // conteneurs restent up si dockerd redémarre
  "userns-remap": "default",           // isolation UID/GID (voir §4)
  "default-ulimits": {                 // limites de base
    "nofile": { "Name": "nofile", "Hard": 65536, "Soft": 65536 }
  },
  "features": { "buildkit": true },    // BuildKit on
  "insecure-registries": [],           // proscrire en prod
  "registry-mirrors": ["https://<miroir>"]  // proxy cache interne (voir Ch-07)
}
```

> Redémarrer : `systemctl reload docker` (ou restart).

### 2.2 API Docker (REST) — fermer ou chiffrer

* **Par défaut** : socket Unix `unix:///var/run/docker.sock` (OK, local).
* **Éviter** l’exposition **TCP**. Si obligation : **TLS mutuel** + pare-feu.
  Exemple (unit file `dockerd` ou `/etc/docker/daemon.json`) :

```bash
# Exemples d’arguments dockerd
-H unix:///var/run/docker.sock \
-H tcp://0.0.0.0:2376 \
--tlsverify \
--tlscacert=/etc/docker/pki/ca.pem \
--tlscert=/etc/docker/pki/server.pem \
--tlskey=/etc/docker/pki/server-key.pem
```

> Viser **réseau privé** + ACL/IPTables ; pas d’expo Internet.

### 2.3 Hardening systemd (dockerd service)

`systemctl edit docker` → override (extraits utiles) :

```
[Service]
LimitNOFILE=1048576
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
PrivateTmp=yes
NoNewPrivileges=yes
```

> Certaines options peuvent gêner selon distro ; tester en lab.

### 2.4 Journaux & rotation

* `log-driver=json-file` **avec rotation** (ci-dessus) ou **journald/syslog/fluentd** selon centralisation (cf. Observabilité).
* Surveillez `/var/lib/docker` (taille, inodes) et programmez des **prunes** maîtrisés.

---

## 3) Socket Docker & contrôle d’accès

* **Ne montez jamais** `-v /var/run/docker.sock:/var/run/docker.sock` dans des applis (équivaut à root sur l’hôte).
* Si un conteneur doit piloter Docker, interposez un **docker-socket-proxy** (filtres sur API, lecture seule quand possible).
* Groupe `docker` = **root logique**. Préférez :

  * **Pas** d’ajout d’utilisateurs non privilégiés au groupe.
  * Commandes **sudo** ciblées (sudoers) si besoin :
    `Cmnd_Alias DOCKER_SAFE = /usr/bin/docker ps, /usr/bin/docker logs *`
    `user ALL=(root) NOPASSWD: DOCKER_SAFE`
* Journaliser **qui** utilise la socket (auditd sur `/var/run/docker.sock`).

---

## 4) Isolation UID/GID : **userns-remap** vs **rootless**

### 4.1 `userns-remap`

* Mappe le `root` du conteneur vers un **UID non-root** sur l’hôte.
* Pré-requis : entrées dans `/etc/subuid` & `/etc/subgid` (ex. `dockremap:100000:65536`).
* Activer : `"userns-remap": "default"` (voir §2.1).
  **Impacts :**
* UID/GID vus depuis l’hôte → **décalés** (ex. 100000+).
* Volumes/binds : vérifiez l’ownership (peut nécessiter `chown` via conteneur utilitaire).
* Bon compromis si rootless non envisageable.

### 4.2 **Rootless Docker**

* Dockerd & conteneurs tournent **sans privilèges root** (user unprivileged).
* Installation (Linux) :

  ```bash
  dockerd-rootless-setuptool.sh install
  export DOCKER_HOST=unix:///run/user/1000/docker.sock
  ```
* **Limites** typiques : besoin de cgroups v2, **pas** de `--privileged`, mapping ports <1024 via redirection userland, accès matériels restreints, overlayfs selon kernel.
* Excellent pour **postes dev** et environnements restreints.

> Choix pratique : **prod** → `userns-remap` + bonnes pratiques ; **dev**/CI ou hôtes partagés → **rootless**.

---

## 5) Durcissement **runtime** des conteneurs

### 5.1 Exécuter **non-root**

Dans l’image (Dockerfile) :

```dockerfile
RUN addgroup -S app && adduser -S -G app -u 10001 app
USER 10001:10001
```

Au run :

```bash
docker run -u 10001:10001 ...
```

### 5.2 **Capabilities** (drop all + ajout minimal)

```bash
# Service web liant un port <1024
docker run --cap-drop=ALL --cap-add=NET_BIND_SERVICE ...
```

Réduire à : `CHOWN`, `DAC_OVERRIDE` si strict nécessaire, **jamais** `SYS_ADMIN` par défaut.

### 5.3 **seccomp** (profil)

* Le profil **par défaut** de Docker bloque de nombreux appels à risque.
* Fournir un profil custom si l’app a des besoins spécifiques :

```bash
docker run --security-opt seccomp=/path/seccomp-profile.json ...
```

### 5.4 **AppArmor** / **SELinux**

* **AppArmor** (Ubuntu/Debian) : profil `docker-default` par défaut.
  Personnaliser :

  ```bash
  docker run --security-opt apparmor=my-profile ...
  ```
* **SELinux** (RHEL/Fedora) :

  * Montages hôte : suffixes `:Z` (privé) / `:z` (partagé).
  * Éviter `spc_t` (super-priv) ; rester sur `container_t` si possible.

### 5.5 FS **read-only** + **tmpfs**

```bash
docker run --read-only --tmpfs /tmp --tmpfs /run \
  -v data:/var/lib/app ...
```

> Identifiez tous les chemins en écriture (logs, caches, sockets) et isolez-les.

### 5.6 **no-new-privileges**

```bash
docker run --security-opt no-new-privileges:true ...
```

### 5.7 **sysctl** et limites

* Docker autorise quelques `--sysctl` (réseau, noyau restreint) :

```bash
docker run --sysctl net.ipv4.ip_forward=0 --sysctl net.ipv4.tcp_syncookies=1 ...
```

* Toujours combiner avec **limites cgroup** (`--cpus`, `--memory`, `--pids-limit`, `--ulimit`).

### 5.8 **Devices** & host features

* Éviter `--device` ; si requis, cibler **un device précis** et **RO** si possible.
* **Jamais** `--privileged` en prod (sauf cas d’outillage isolé, court et contrôlé).

---

## 6) Sécurité **build** & secrets

### 6.1 Secrets **pendant le build** (BuildKit)

```dockerfile
# build: docker build --secret id=npm_token,src=.npm_token .
RUN --mount=type=secret,id=npm_token \
    export NPM_TOKEN=$(cat /run/secrets/npm_token) && npm ci
```

> Les secrets **ne finissent pas** dans les couches.

### 6.2 Secrets **au runtime** (Compose)

```yaml
services:
  api:
    secrets: [ jwt_key ]
secrets:
  jwt_key:
    file: ./secrets/jwt.key
```

* Montés **comme fichiers** sous `/run/secrets/...`.
* Éviter les **variables d’environnement** pour secrets (dump faciles, journaux).

### 6.3 Coffres & gestion centralisée

* **Vault**, **AWS/GCP/Azure Secrets**, **SOPS/age** (décryptage à l’exécution).
* Rotation, révocation, principe **pull** par l’app (token court).

---

## 7) Réseau & exposition

* **Aucun** port inutile ; lier sur **127.0.0.1** et exposer via un **reverse-proxy** TLS.
* Backends sur réseau **`--internal`** (pas d’egress), frontaux sur réseau dédié.
* Éviter `--network host` en prod ; le réserver à des agents techniques si besoin prouvé.

---

## 8) Supply chain : **signatures, SBOM, scans, policies**

### 8.1 Scans & seuils

* **Trivy / Docker Scout** en CI : échouer si CVE **HIGH/CRITICAL** au-dessus d’un seuil.
* Scans **licences** (bloquer GPL-3 si politique interne, p.ex.).

### 8.2 Signatures

* **Docker Content Trust** (Notary v1) :
  `export DOCKER_CONTENT_TRUST=1` (sign/verify sur `docker pull/push`).
* **cosign (Sigstore)** :

  ```bash
  cosign sign registry.example.com/team/app:1.4.2
  cosign verify registry.example.com/team/app:1.4.2
  ```

  *Keyless OIDC* possible ; signatures stockées comme artefacts OCI.

### 8.3 SBOM & provenance

* Buildx :

  ```bash
  docker buildx build --sbom --provenance \
    -t registry.example.com/team/app:1.4.2 --push .
  ```
* Conserver SBOM/attestations au registry ; politiques **deny** si manquants.

### 8.4 Politiques d’admission (standalone)

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

## 10) Hardening de l’hôte (rappels)

* Kernel & paquets **à jour**, reboot sécurité planifié.
* **Pare-feu** par défaut DROP (ou politique claire), SSH durci (MFA, clés).
* **FS chiffré** (LUKS) pour `/var/lib/docker` si sensible ; sauvegardes chiffrées.
* **NTP** fiable (horloge = TLS, signatures, journaux cohérents).
* Minimiser les **composants** sur l’hôte (pas d’apps superflues).

---

## 11) Exemples “prod-like” (runtime & compose)

### 11.1 `docker run` durci

```bash
docker run -d --name api \
  --cpus=1.0 --memory=512m --pids-limit=256 \
  --read-only --tmpfs /run --tmpfs /tmp \
  --cap-drop=ALL --cap-add=NET_BIND_SERVICE \
  --security-opt no-new-privileges:true \
  --security-opt seccomp=/etc/docker/seccomp-restrict.json \
  -u 10001:10001 \
  --network backend \
  ghcr.io/acme/api@sha256:<digest>
```

### 11.2 Compose durci (extrait)

```yaml
services:
  api:
    image: ghcr.io/acme/api@sha256:...
    user: "10001:10001"
    read_only: true
    tmpfs: [ /run, /tmp ]
    cap_drop: [ "ALL" ]
    cap_add: [ "NET_BIND_SERVICE" ]
    security_opt:
      - no-new-privileges:true
      - seccomp:/etc/docker/seccomp-restrict.json
      # - apparmor:my-profile          # si profil custom
    healthcheck:
      test: ["CMD-SHELL","curl -fsS http://localhost:8080/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - backend
networks:
  backend:
    driver: bridge
    internal: true
```

---

## 12) Dépannage sécurité — cas fréquents

* **Permission denied** sur volume (SELinux) → utiliser `:Z/:z` (RHEL/Fedora) ; vérifier UID/GID (userns-remap).
* **Syscall bloqué** (seccomp) → valider le besoin réel ; ajuster **profil** minimal.
* **Service inaccessible** depuis l’extérieur → vérifier que l’app écoute sur `0.0.0.0` (pas `127.0.0.1`), règles iptables, IP de bind `-p`.
* **Rootless** : ports <1024 indisponibles → publier via reverse-proxy/port >1024.

---

## 13) Aide-mémoire (cheat-sheet)

```bash
# Vérifier la conf du démon
docker info
cat /etc/docker/daemon.json

# Activer userns-remap
sudo sed -i 's/}/, "userns-remap": "default"}/' /etc/docker/daemon.json
sudo systemctl restart docker

# Lancer rootless (session user)
dockerd-rootless-setuptool.sh install
export DOCKER_HOST=unix:///run/user/1000/docker.sock

# Run durci
docker run -d --read-only --tmpfs /tmp --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE --security-opt no-new-privileges:true \
  -u 10001:10001 IMAGE@sha256:...

# Vérifier capabilities effectives
docker exec ct capsh --print

# Cosign (sign/verify)
cosign sign registry.example.com/team/app:1.4.2
cosign verify registry.example.com/team/app:1.4.2

# Trivy (scan)
trivy image --severity HIGH,CRITICAL registry.example.com/team/app:1.4.2
```

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
* Procédures d’IR (forensic) et PRA testées (sauvegardes/restores de volumes).

