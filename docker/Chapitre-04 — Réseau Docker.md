# Chapitre-04 — Réseau Docker

## Objectifs d'apprentissage

* Concevoir et administrer des réseaux Docker **user-defined** (isolation, DNS interne, IPAM).
* Maîtriser la **publication de ports** (`-p/-P`, TCP/UDP, bind d'IP), l'attachement **multi-réseaux**, et les **alias** DNS.
* Appliquer des **contrôles egress/ingress** simples (réseaux `--internal`, séparation front/back, règles pare-feu).
* Comprendre les **modes réseau** (`bridge`, `host`, `none`, notions `macvlan/ipvlan`, IPv6) et diagnostiquer les problèmes (NAT, MTU, hairpin).

## Pré-requis

* Docker Engine/CLI opérationnel.
* Notions IP/CIDR/ports/DNS/iptables.

---

## 1) Les drivers réseau Docker (panorama)

| Driver      | Usage principal                                            | Particularités                                                    |
| ----------- | ---------------------------------------------------------- | ----------------------------------------------------------------- |
| **bridge**  | Par défaut (Linux). Réseaux L2 isolés avec NAT vers l'hôte | DNS embarqué, IPAM configurable, port-mapping `-p`                |
| **host**    | Partage la pile réseau de l'hôte                           | Pas de `-p` (tout est "sur l'hôte"), risques de conflits de ports |
| **none**    | Isolation complète                                         | Pas d'accès réseau, pas de DNS interne                            |
| **macvlan** | Donner une IP **de votre LAN** au conteneur                | Besoin d'un plan d'adressage, mode promisc/commutateur, pièges L2 |
| **ipvlan**  | Variante L3/L2 plus simple que macvlan selon cas           | Moins "promisc" que macvlan, exigences routeur                    |

> Les **overlays** (réseaux distribués multi-hôtes) relèvent de **Swarm/K8s** (voir Chapitre 13).

---

## 2) Réseaux `bridge` user-defined : le standard quotidien

### 2.1 Créer / lister / inspecter

> **Objectif** : Créer un réseau bridge personnalisé nommé `app-net`, lister tous les réseaux Docker, puis inspecter `app-net` pour afficher sa configuration IPAM, les conteneurs connectés et son mode internal.
> **Pré-requis** : Docker Engine démarré, aucun réseau nommé `app-net` préexistant.

```bash
# Créer un réseau bridge user-defined nommé "app-net" (sous-réseau attribué automatiquement)
docker network create app-net
# Lister tous les réseaux Docker disponibles (bridge, host, none + user-defined)
docker network ls
# Inspecter "app-net" et extraire via jq : la config IPAM, les conteneurs connectés, et le flag Internal
docker network inspect app-net | jq '.[0].IPAM, .[0].Containers, .[0].Internal'
```

> **Résultat attendu** :
> ```
> # docker network create app-net
> a1b2c3d4e5f6...
> # docker network ls
> NETWORK ID     NAME        DRIVER    SCOPE
> xxxxxxxxxxxx   bridge      bridge    local
> yyyyyyyyyyyy   app-net     bridge    local
> zzzzzzzzzzzz   host        host      local
> ...
> # docker network inspect app-net | jq '.[0].IPAM, .[0].Containers, .[0].Internal'
> {
>   "Driver": "default",
>   "Config": [{"Subnet": "172.19.0.0/16", "Gateway": "172.19.0.1"}]
> }
> {}
> false
> ```
> **Vérification** : Le réseau `app-net` apparaît dans `docker network ls` avec le driver `bridge`. L'inspect montre un sous-réseau auto-attribué, aucun conteneur connecté, et `Internal: false`.

* Les **user-defined bridges** offrent un **DNS interne** : les **noms de conteneurs** deviennent résolvables *sur le même réseau*.

### 2.2 Attacher / détacher un conteneur

> **Objectif** : Démarrer un conteneur `web` directement sur le réseau `app-net`, puis attacher et détacher dynamiquement un autre conteneur (`another-container`) à ce réseau.
> **Pré-requis** : Le réseau `app-net` doit exister (section 2.1). L'image `nginx:1.27` doit être disponible.

```bash
# Démarrer un conteneur "web" avec l'image nginx, attaché au réseau "app-net" dès le lancement
docker run -d --name web --network app-net nginx:1.27
# Attacher dynamiquement un conteneur existant "another-container" au réseau "app-net"
docker network connect app-net another-container
# Détacher dynamiquement "another-container" du réseau "app-net"
docker network disconnect app-net another-container
```

> **Résultat attendu** :
> ```
> # docker run -d --name web --network app-net nginx:1.27
> 3a4b5c6d7e8f...
> # docker network connect app-net another-container
> # (pas de sortie si succès)
> # docker network disconnect app-net another-container
> # (pas de sortie si succès)
> ```
> **Vérification** : `docker network inspect app-net | jq '.[0].Containers'` doit montrer `web` (et temporairement `another-container` entre connect et disconnect). `docker inspect -f '{{.NetworkSettings.Networks}}' web` confirme que `web` est sur `app-net`.

### 2.3 IPAM (adresses/IP statiques)

> **Objectif** : Créer un réseau avec un plan d'adressage IP personnalisé (subnet, plage d'IP, passerelle), puis démarrer un conteneur avec une adresse IP statique fixe dans ce réseau.
> **Pré-requis** : Aucun réseau `app-net` préexistant. Le sous-réseau `172.18.0.0/16` ne doit pas chevaucher d'autres réseaux Docker existants.

```bash
# Crée un réseau avec plan d'adressage précis
# --subnet : définit le sous-réseau global du réseau
# --ip-range : restreint la plage d'IPs attribuables dynamiquement
# --gateway : fixe l'adresse de la passerelle (gateway) du réseau
docker network create \
  --subnet 172.18.0.0/16 \
  --ip-range 172.18.5.0/24 \
  --gateway 172.18.0.1 app-net

# Attribuer une IP fixe au conteneur
# --ip 172.18.5.10 : force l'adresse IP statique du conteneur dans le réseau app-net
docker run -d --name db \
  --network app-net --ip 172.18.5.10 \
  postgres:16
```

> **Résultat attendu** :
> ```
> # docker network create --subnet 172.18.0.0/16 --ip-range 172.18.5.0/24 --gateway 172.18.0.1 app-net
> b1c2d3e4f5a6...
> # docker run -d --name db --network app-net --ip 172.18.5.10 postgres:16
> 7d8e9f0a1b2c...
> ```
> **Vérification** : `docker inspect db | jq '.[0].NetworkSettings.Networks."app-net".IPAddress'` retourne `"172.18.5.10"`. `docker network inspect app-net | jq '.[0].IPAM'` montre le subnet `172.18.0.0/16` et l'ip-range `172.18.5.0/24`.

* `--subnet` et `--ip-range` doivent **ne pas** chevaucher d'autres réseaux.
* `aux-addresses` (via `--ipam-opt`) réserve des IPs (ex. pour le gateway virtuel).

### 2.4 Multi-réseaux (front/back)

> **Objectif** : Créer deux réseaux isolés (`frontend` exposé, `backend` interne sans egress), puis démarrer un conteneur `api` connecté aux deux réseaux avec un alias DNS, simulant une architecture front/back.
> **Pré-requis** : Docker Engine démarré. L'image `ghcr.io/acme/api:1.4.2` doit être accessible (ou remplacer par une image disponible).

```bash
# Créer un réseau "frontend" bridge standard (avec egress Internet)
docker network create frontend
# Créer un réseau "backend" en mode --internal (pas d'accès Internet / egress bloqué)
docker network create backend --internal   # egress bloqué (pas d'accès Internet)

# Démarrer le conteneur "api" connecté aux DEUX réseaux simultanément
# --network frontend : premier réseau (peut communiquer avec l'extérieur)
# --network backend  : second réseau (peut communiquer avec les services internes)
# --network-alias api-svc : alias DNS supplémentaire sur le réseau (résolvable par les autres conteneurs)
docker run -d --name api \
  --network frontend \
  --network backend \
  --network-alias api-svc \
  ghcr.io/acme/api:1.4.2
```

> **Résultat attendu** :
> ```
> # docker network create frontend
> c1d2e3f4a5b6...
> # docker network create backend --internal
> d2e3f4a5b6c7...
> # docker run -d --name api --network frontend --network backend --network-alias api-svc ghcr.io/acme/api:1.4.2
> e3f4a5b6c7d8...
> ```
> **Vérification** : `docker inspect api | jq '.[0].NetworkSettings.Networks | keys'` retourne `["backend", "frontend"]`. `docker network inspect backend | jq '.[0].Internal'` retourne `true`. Depuis un conteneur sur `frontend`, `ping api-svc` fonctionne.

* Un conteneur peut être **sur plusieurs réseaux**.
* Un réseau `--internal` **n'a pas d'egress** : utile pour cacher une DB/queue.

---

## 3) DNS interne, alias, hosts & nommage

### 3.1 Résolution par nom de conteneur

* Sur un **user-defined bridge**, `ping db` (ou `curl http://db:5432`) fonctionne **entre conteneurs** du même réseau.

### 3.2 Alias DNS

> **Objectif** : Démarrer un conteneur `payments` sur le réseau `backend` avec un alias DNS `pay-svc`, permettant aux autres conteneurs du réseau de le résoudre sous les deux noms (`payments` et `pay-svc`).
> **Pré-requis** : Le réseau `backend` doit exister. L'image `ghcr.io/acme/payments:2.1` doit être accessible.

```bash
# Démarrer le conteneur "payments" sur le réseau "backend"
# --network-alias pay-svc : ajoute un alias DNS "pay-svc" en plus du nom de conteneur "payments"
# Les autres conteneurs du réseau peuvent résoudre "pay-svc" ET "payments" vers l'IP de ce conteneur
docker run -d --name payments \
  --network backend \
  --network-alias pay-svc \
  ghcr.io/acme/payments:2.1
```

> **Résultat attendu** :
> ```
> # docker run -d --name payments --network backend --network-alias pay-svc ghcr.io/acme/payments:2.1
> f4a5b6c7d8e9...
> ```
> **Vérification** : Depuis un autre conteneur du réseau `backend`, `dig pay-svc` et `dig payments` retournent tous deux l'IP du conteneur. `docker network inspect backend | jq '.[0].Containers'` montre l'entrée avec le nom `payments`.

* `pay-svc` devient un **alias** DNS (en plus de `payments`).

### 3.3 Paramètres DNS & hosts

> **Objectif** : Configurer des paramètres DNS personnalisés (serveur DNS, domaine de recherche, options DNS), ajouter des entrées hôtes statiques, et définir le hostname/domaine d'un conteneur.
> **Pré-requis** : Docker Engine démarré. Les images utilisées doivent exister localement ou être pullables.

```bash
# --dns 1.1.1.1         : utilise le DNS Cloudflare comme résolveur au lieu du DNS par défaut
# --dns-search corp.local : ajoute "corp.local" comme domaine de recherche DNS (ex: "ping redis" résout "redis.corp.local")
# --dns-option ndots:1   : nombre minimum de points avant de tenter une recherche absolue (optimise les requêtes)
docker run --dns 1.1.1.1 --dns-search corp.local --dns-option ndots:1 image
# --add-host : ajoute une entrée statique dans /etc/hosts du conteneur (résolution locale sans DNS)
docker run --add-host redis.internal:10.0.0.10 image
# --hostname   : définit le nom d'hôte du conteneur (visible dans son shell et via DNS)
# --domainname : définit le domaine DNS associé au hostname (FQDN = api-01.lab.local)
docker run --hostname api-01 --domainname lab.local image
```

> **Résultat attendu** :
> ```
> # docker run --dns 1.1.1.1 --dns-search corp.local --dns-option ndots:1 image
> # (le conteneur démarre avec ces paramètres DNS dans /etc/resolv.conf)
> # cat /etc/resolv.conf → nameserver 1.1.1.1 / search corp.local / options ndots:1
> # docker run --add-host redis.internal:10.0.0.10 image
> # (entrée ajoutée dans /etc/hosts : 10.0.0.10 redis.internal)
> # docker run --hostname api-01 --domainname lab.local image
> # (hostname = api-01, FQDN = api-01.lab.local)
> ```
> **Vérification** : `docker exec <container> cat /etc/resolv.conf` montre les serveurs DNS. `docker exec <container> cat /etc/hosts` montre l'entrée ajoutée. `docker exec <container> hostname -f` retourne `api-01.lab.local`.

> Le DNS interne **ne traverse pas** les réseaux : si deux conteneurs ne partagent **aucun** réseau, la résolution par nom échoue.

---

## 4) EXPOSE vs publication de ports

* **`EXPOSE`** (Dockerfile) = **métadonnée** (port(s) sur lesquels l'app écoute).
* **Publication** réelle = option `-p` (ou `-P`) à `docker run`.

### 4.1 `-p` (port mapping explicite)

> **Objectif** : Démontrer les différentes syntaxes de publication de ports avec `-p` : TCP par défaut, UDP, liaison sur une IP spécifique de l'hôte, et plage de ports.
> **Pré-requis** : Docker Engine démarré. Les images `nginx` et `coredns/coredns` doivent être disponibles.

```bash
# TCP par défaut : mappe le port 8080 de l'hôte vers le port 80 du conteneur (TCP)
docker run -d -p 8080:80 nginx

# UDP explicite : le suffixe /udp précise le protocole (ici DNS UDP sur le port 53)
docker run -d -p 53:53/udp coredns/coredns

# Lier sur une IP précise de l'hôte : seul 127.0.0.1 (localhost) peut accéder au port 8080
# Empêche l'accès depuis les interfaces réseau externes (sécurité)
docker run -d -p 127.0.0.1:8080:80 nginx

# Plage de ports : mappe les ports 3000-3005 de l'hôte vers 3000-3005 du conteneur
docker run -d -p 3000-3005:3000-3005 myapp
```

> **Résultat attendu** :
> ```
> # docker run -d -p 8080:80 nginx
> a1b2c3d4e5f6...
> # docker run -d -p 53:53/udp coredns/coredns
> b2c3d4e5f6a7...
> # docker run -d -p 127.0.0.1:8080:80 nginx
> c3d4e5f6a7b8...
> # docker run -d -p 3000-3005:3000-3005 myapp
> d4e5f6a7b8c9...
> ```
> **Vérification** : `docker port <container>` affiche les mappings. `curl http://localhost:8080` retourne la page nginx. `ss -lntp | grep 8080` montre l'écoute sur `127.0.0.1:8080` pour le conteneur bindé.

* `HOST_IP:HOST_PORT:CONTAINER_PORT[/proto]`
* Lier sur `127.0.0.1` limite l'accès **au seul hôte** (sécurité).

### 4.2 `-P` (publish all)

> **Objectif** : Utiliser `-P` (majuscule) pour publier automatiquement tous les ports EXPOSE de l'image sur des ports aléatoires de l'hôte, puis consulter le mapping généré.
> **Pré-requis** : L'image `myimage` doit avoir des instructions `EXPOSE` dans son Dockerfile.

```bash
# -P (majuscule) : publie automatiquement TOUS les ports EXPOSE de l'image
# Docker attribue des ports aléatoires sur l'hôte pour chaque port exposé
docker run -d -P myimage
# Affiche la correspondance entre les ports exposés du conteneur et les ports aléatoires de l'hôte
docker port <container>   # affiche les ports exposés et leur mapping aléatoire
```

> **Résultat attendu** :
> ```
> # docker run -d -P myimage
> e5f6a7b8c9d0...
> # docker port <container>
> 80/tcp -> 0.0.0.0:32768
> 443/tcp -> 0.0.0.0:32769
> ```
> **Vérification** : `docker port <container>` liste chaque port EXPOSE avec son port hôte aléatoire attribué. Les ports sont dans la plage 32768-32767+ (plage éphémère).

* Publie **tous** les ports présents dans **EXPOSE** (ou détectés par l'image).

### 4.3 Vérifier les ports

> **Objectif** : Vérifier les ports publiés d'un conteneur et confirmer les écoutes réseau au niveau de l'hôte via `ss`.
> **Pré-requis** : Un conteneur nommé `web` doit être en cours d'exécution avec des ports publiés.

```bash
# Affiche le mapping de ports du conteneur "web" (ports conteneur -> ports hôte)
docker port web
# Liste les sockets TCP en écoute sur l'hôte, filtrées sur le processus dockerd
# Permet de voir quels ports sont effectivement ouverts par Docker
ss -lntp | grep dockerd
```

> **Résultat attendu** :
> ```
> # docker port web
> 80/tcp -> 0.0.0.0:8080
> # ss -lntp | grep dockerd
> LISTEN  0  4096  0.0.0.0:8080  0.0.0.0:*  users:(("dockerd",pid=1234,fd=...))
> ```
> **Vérification** : Le port affiché par `docker port` correspond à une ligne LISTEN dans `ss`. Si le bind est `0.0.0.0`, le port est accessible depuis toutes les interfaces ; si `127.0.0.1`, uniquement en local.

**Piège courant** : dans le conteneur, si votre service écoute **seulement sur `127.0.0.1`**, il **ne sera pas atteignable** par le NAT externe. Il doit écouter sur `0.0.0.0` (ou l'IP du conteneur).

---

## 5) Modes réseau spéciaux

### 5.1 `host`

> **Objectif** : Démarrer un conteneur en mode `host`, partageant directement la pile réseau de l'hôte (pas d'isolation réseau, pas de NAT, pas de `-p`).
> **Pré-requis** : Docker Engine sur Linux (le mode `host` n'est pas supporté de la même manière sur macOS/Windows Desktop). Aucun service ne doit écouter sur les ports utilisés par le conteneur.

```bash
# --network host : le conteneur partage l'espace réseau de l'hôte
# Pas de port-mapping (-p) nécessaire ni possible : les ports du conteneur sont directement sur l'hôte
docker run --network host ghcr.io/acme/agent:latest
```

> **Résultat attendu** :
> ```
> # docker run --network host ghcr.io/acme/agent:latest
> f6a7b8c9d0e1...
> ```
> **Vérification** : `docker inspect <container> | jq '.[0].HostConfig.NetworkMode'` retourne `"host"`. `ss -lntp` sur l'hôte montre les ports ouverts par le conteneur directement (pas de mapping). `ip netns` ne montre pas de namespace séparé pour ce conteneur.

* Le conteneur **partage l'interface** de l'hôte : **pas** de `-p`.
* **Pros** : latence minimale, découverte multicast, accès ports host.
* **Cons** : conflits de ports, **surface d'attaque** plus large, moins d'isolation.
* (Sur macOS/Windows Desktop, le support diffère car VM sous-jacente.)

### 5.2 `none`

> **Objectif** : Démarrer un conteneur sans aucun accès réseau (mode `none`), utile pour des tâches offline, du traitement par lots, ou de l'analyse forensique.
> **Pré-requis** : Docker Engine démarré. L'image ne doit pas nécessiter de connexion réseau au démarrage.

```bash
# --network none : aucune interface réseau n'est configurée dans le conteneur
# Le conteneur est complètement isolé réseau (seulement loopback 127.0.0.1)
docker run --network none ghcr.io/acme/job:latest
```

> **Résultat attendu** :
> ```
> # docker run --network none ghcr.io/acme/job:latest
> a7b8c9d0e1f2...
> ```
> **Vérification** : `docker inspect <container> | jq '.[0].NetworkSettings.Networks'` retourne `{}`. `docker exec <container> ip a` ne montre que `lo` (loopback). Aucune connectivité externe n'est possible.

* Aucun accès réseau. Utile pour lots offline/forensic.

### 5.3 `macvlan` (aperçu)

> **Objectif** : Créer un réseau `macvlan` qui attribue au conteneur une adresse MAC propre et une IP du LAN physique, le rendant visible comme un appareil distinct sur le réseau local.
> **Pré-requis** : L'interface réseau `eth0` doit exister sur l'hôte. Le sous-réseau `192.168.10.0/24` doit correspondre au LAN physique. Le routeur/commutateur doit accepter le mode promiscuous ou les MACs multiples. Attention : l'hôte ne peut pas toujours communiquer directement avec le conteneur en macvlan.

```bash
# Donne une IP L2 sur le LAN au conteneur
# -d macvlan         : utilise le driver macvlan (le conteneur apparaît comme un hôte physique sur le LAN)
# --subnet           : sous-réseau du LAN physique
# --gateway          : passerelle du LAN (généralement le routeur)
# -o parent=eth0     : interface physique de l'hôte à laquelle le macvlan est rattaché
# pub-net            : nom du réseau créé
docker network create -d macvlan \
  --subnet 192.168.10.0/24 \
  --gateway 192.168.10.1 \
  -o parent=eth0 pub-net

# Démarrer un conteneur avec une IP statique dans le LAN
# Le conteneur est joignable directement depuis n'importe quel appareil du LAN sur 192.168.10.50
docker run -d --network pub-net --ip 192.168.10.50 nginx
```

> **Résultat attendu** :
> ```
> # docker network create -d macvlan --subnet 192.168.10.0/24 --gateway 192.168.10.1 -o parent=eth0 pub-net
> b8c9d0e1f2a3...
> # docker run -d --network pub-net --ip 192.168.10.50 nginx
> c9d0e1f2a3b4...
> ```
> **Vérification** : `docker inspect <container> | jq '.[0].NetworkSettings.Networks."pub-net".IPAddress'` retourne `"192.168.10.50"`. Depuis un autre appareil du LAN, `ping 192.168.10.50` fonctionne. `ip link show` sur l'hôte montre une sous-interface macvlan sur `eth0`.

* **Contraintes** : commutateur/routeur, mode promisc, l'hôte **ne voit** pas toujours bien le conteneur (besoin d'un macvlan "bridge" ou route). À tester **en lab** avant prod.

### 5.4 `ipvlan` (aperçu)

* Plus "route-centric". Moins de promisc ; dépend de la topologie L3.
* Utilisation similaire à `macvlan` avec driver `ipvlan`.

---

## 6) IPv6 (aperçu utile)

### 6.1 Activer IPv6 côté démon

> **Objectif** : Activer le support IPv6 dans le démon Docker en configurant `daemon.json`, puis créer un réseau avec un sous-réseau IPv6 et y lancer un conteneur.
> **Pré-requis** : Accès root pour modifier `/etc/docker/daemon.json`. Capacité à redémarrer le service Docker. Le préfixe IPv6 `fd00:dead:beef::/48` est un ULA (Unique Local Address) utilisable en lab.

`/etc/docker/daemon.json` :

> **Objectif** : Configuration du démon Docker pour activer IPv6 et définir une plage d'adresses IPv6 fixes pour les réseaux bridge par défaut.
> **Pré-requis** : Fichier `/etc/docker/daemon.json` existant (ou à créer). Les adresses `fd00::/48` sont des ULA (non routables sur Internet, usage interne).

```json
{
  "ipv6": true,
  "fixed-cidr-v6": "fd00:dead:beef::/48"
}
```

> **Résultat attendu** :
> ```
> # Après redémarrage de Docker (systemctl restart docker),
> # docker network inspect bridge | jq '.[0].IPAM.Config' montre une entrée IPv6
> # avec un Gateway et Subnet en fd00:dead:beef::/48
> ```
> **Vérification** : `docker info | grep -i ipv6` montre que l'IPv6 est activé. `docker network inspect bridge` affiche une config IPAM avec une entrée IPv6.

Redémarrer Docker, puis créer un réseau **IPv6** :

> **Objectif** : Créer un réseau bridge avec un sous-réseau IPv6 dédié, puis y démarrer un conteneur pour vérifier la connectivité IPv6.
> **Pré-requis** : Docker redémarré avec `ipv6: true` dans daemon.json. Le sous-réseau `fd00:dead:beef:1::/64` est un sous-réseau du pool ULA défini dans daemon.json.

```bash
# Crée un réseau bridge "v6net" avec le flag --ipv6 et un sous-réseau IPv6 /64
docker network create --ipv6 --subnet fd00:dead:beef:1::/64 v6net
# Démarre un conteneur sur ce réseau IPv6
docker run -d --network v6net myimage
```

> **Résultat attendu** :
> ```
> # docker network create --ipv6 --subnet fd00:dead:beef:1::/64 v6net
> c0d1e2f3a4b5...
> # docker run -d --network v6net myimage
> d1e2f3a4b5c6...
> ```
> **Vérification** : `docker network inspect v6net | jq '.[0].IPAM.Config'` montre une entrée avec `"Subnet": "fd00:dead:beef:1::/64"`. `docker inspect <container> | jq '.[0].NetworkSettings.Networks."v6net".GlobalIPv6Address'` retourne une adresse IPv6 dans ce sous-réseau.

* Vérifier MTU et pare-feu sur IPv6 (filtrage `ip6tables/nftables`).

---

## 7) Contrôles egress/ingress (sans orchestrateur)

### 7.1 Réseaux internes (egress off)

> **Objectif** : Créer un réseau `--internal` qui bloque tout trafic sortant vers Internet (egress), tout en permettant la communication inter-conteneurs.
> **Pré-requis** : Docker Engine démarré.

```bash
# --internal : crée un réseau sans passerelle externe (pas de NAT sortant)
# Les conteneurs sur ce réseau peuvent communiquer entre eux mais ne peuvent PAS accéder à Internet
docker network create --internal backend
# Rien sur Internet depuis ce réseau (mais inter-conteneurs OK)
```

> **Résultat attendu** :
> ```
> # docker network create --internal backend
> e2f3a4b5c6d7...
> ```
> **Vérification** : `docker network inspect backend | jq '.[0].Internal'` retourne `true`. Depuis un conteneur sur ce réseau, `ping 8.8.8.8` échoue, mais `ping <autre-conteneur-sur-backend>` fonctionne.

### 7.2 Séparation front/back

* **frontend** (exposé par `-p`) ↔ **backend** (`--internal`).
* Les services partagent **uniquement** les réseaux nécessaires.

### 7.3 Pare-feu hôte (rappels)

* Docker gère des règles **NAT** automatiques (POSTROUTING MASQUERADE).
* Si vous **désactivez** `--iptables=false`, **vous devez** gérer toutes les règles.

> Pour de la micro-segmentation plus fine : séparer par réseaux, puis ajouter des règles iptables/nftables **par interface bridge** (`br-xxxx`).

---

## 8) MTU, NAT & hairpin (dépannage réseau)

* **MTU** : décalages (ex. VLAN/PPPoE/VM) ⇒ paquets fragmentés/perdus.
  → Ajuster MTU du **bridge** Docker ou des interfaces hôte.
* **Hairpin NAT** : accéder à `localhost:HOST_PORT` **depuis un conteneur**.
  → En général OK, mais parfois bloqué par pare-feu/conntrack. Tester.
* **Connexions refusées vs timeouts** :

  * **Refused** = rien n'écoute au port cible (ou listen `127.0.0.1` seulement).
  * **Timeout** = filtrage/routage/pare-feu/DNS/MTU.

---

## 9) Diagnostic pratique

### 9.1 Inspecter réseau & conteneur

> **Objectif** : Inspecter la configuration complète d'un réseau Docker, vérifier les paramètres réseau d'un conteneur spécifique, et lister les ports publiés.
> **Pré-requis** : Un réseau `app-net` et un conteneur `web` doivent exister. L'outil `jq` doit être installé pour le formatage JSON.

```bash
# Inspecte le réseau "app-net" et affiche le JSON complet formaté par jq
# Montre : IPAM, conteneurs connectés, options, internal, labels, etc.
docker network inspect app-net | jq
# Affiche les paramètres réseau du conteneur "web" (réseaux attachés, IPs, MAC, gateways)
# Utilise le format Go template pour extraire uniquement les NetworkSettings.Networks
docker inspect -f '{{.NetworkSettings.Networks}}' web
# Liste les ports publiés du conteneur "web" (mapping port conteneur -> port hôte)
docker port web
```

> **Résultat attendu** :
> ```
> # docker network inspect app-net | jq
> [
>   {
>     "Name": "app-net",
>     "Driver": "bridge",
>     "IPAM": { "Config": [{"Subnet": "172.19.0.0/16", "Gateway": "172.19.0.1"}] },
>     "Containers": {
>       "abc123": { "Name": "web", "IPv4Address": "172.19.0.2/16" }
>     },
>     "Internal": false
>   }
> ]
> # docker inspect -f '{{.NetworkSettings.Networks}}' web
> map[app-net:0xc0001a2000]
> # docker port web
> 80/tcp -> 0.0.0.0:8080
> ```
> **Vérification** : L'inspect réseau montre les conteneurs connectés avec leurs IPs. `docker port` confirme les mappings actifs. Les IPs sont cohérentes avec le subnet du réseau.

### 9.2 Netshoot (trousse à outils réseau)

> **Objectif** : Démarrer un conteneur éphémère `nicolaka/netshoot` (boîte à outils réseau : dig, curl, ss, traceroute, tcpdump, etc.) attaché au réseau `app-net` pour diagnostiquer la connectivité, la résolution DNS et le routage.
> **Pré-requis** : Le réseau `app-net` doit exister avec des conteneurs (ex: `web`, `db`). L'image `nicolaka/netshoot` doit être pullable.

```bash
# Démarre un conteneur interactif éphémère (--rm = supprimé à la sortie)
# Attaché au réseau "app-net" pour accéder au DNS interne et aux conteneurs du réseau
docker run --rm -it --network app-net nicolaka/netshoot
# depuis ce shell :
# Résout le nom DNS "db" via le DNS interne Docker (montre l'IP du conteneur "db")
dig db
# Teste la connectivité HTTP vers le conteneur "web" sur le port 80 (verbose)
curl -v http://web:80
# Liste les sockets TCP en écoute dans le conteneur netshoot
ss -lntp
# Trace la route vers 1.1.1.1 pour diagnostiquer le routage/egress
traceroute 1.1.1.1
```

> **Résultat attendu** :
> ```
> # dig db
> ;; ANSWER SECTION:
> db.   600 IN  A  172.19.0.3
> # curl -v http://web:80
> * Connected to web (172.19.0.2) port 80
> < HTTP/1.1 200 OK
> < Server: nginx/1.27
> # ss -lntp
> State   Recv-Q  Send-Q  Local Address:Port  Peer Address:Port
> LISTEN  0       128     0.0.0.0:80          0.0.0.0:*
> # traceroute 1.1.1.1
>  1  172.19.0.1  0.5 ms  0.3 ms  0.2 ms
>  2  ...
> ```
> **Vérification** : `dig db` résout bien l'IP du conteneur `db` (DNS interne fonctionnel). `curl http://web:80` retourne HTTP 200. `traceroute` montre le chemin vers l'extérieur (gateway du réseau puis Internet). Si le réseau est `--internal`, `traceroute 1.1.1.1` échouera.

### 9.3 Sur l'hôte

> **Objectif** : Diagnostiquer la configuration réseau Docker depuis l'hôte : lister les interfaces bridge, inspecter les règles NAT iptables gérées par Docker, et vérifier les processus écoutant sur des ports.
> **Pré-requis** : Accès root ou sudo sur l'hôte. Docker Engine en cours d'exécution avec des conteneurs actifs.

```bash
# Liste toutes les interfaces réseau de l'hôte correspondant aux bridges Docker
# docker0 = bridge par défaut, br-xxxx = bridges user-defined (réseaux créés manuellement)
ip a | grep -E 'docker0|br-'
# Affiche les règles NAT (table nat) de la chaîne DOCKER dans iptables
# Montre les règles DNAT/POSTROUTING pour le port-mapping et le masquerading
iptables -t nat -S | grep DOCKER
# Liste les sockets TCP en écoute sur l'hôte, filtrées sur les processus Docker ou applicatifs
# Permet de voir quels ports sont ouverts par dockerd, nginx, java, etc.
ss -lntp | grep -E 'dockerd|nginx|java'
```

> **Résultat attendu** :
> ```
> # ip a | grep -E 'docker0|br-'
> 3: docker0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
> 5: br-a1b2c3d4e5f6: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
> # iptables -t nat -S | grep DOCKER
> -N DOCKER
> -A PREROUTING -m addrtype --dst-type LOCAL -j DOCKER
> -A OUTPUT ! -d 127.0.0.0/8 -m addrtype --dst-type LOCAL -j DOCKER
> -A POSTROUTING -s 172.19.0.0/16 ! -o br-a1b2c3d4e5f6 -j MASQUERADE
> -A DOCKER -i docker0 -j RETURN
> -A DOCKER ! -i docker0 -p tcp -m tcp --dport 8080 -j DNAT --to-destination 172.19.0.2:80
> # ss -lntp | grep -E 'dockerd|nginx|java'
> LISTEN 0 4096 0.0.0.0:8080 0.0.0.0:* users:(("dockerd",...))
> ```
> **Vérification** : Les interfaces `br-*` correspondent aux réseaux user-defined. Les règles DNAT dans iptables correspondent aux `-p` de `docker run`. Les règles MASQUERADE permettent le NAT sortant. `ss` confirme les ports effectivement en écoute.

---

## 10) Exemples synthèse

### 10.1 Stack front/back avec réseau interne

> **Objectif** : Déployer une architecture complète à 3 tiers : une base de données PostgreSQL isolée sur un réseau `backend` (internal, sans Internet), une API connectée aux deux réseaux (front et back), et un reverse-proxy nginx exposé sur le port 80 du réseau `frontend`.
> **Pré-requis** : Docker Engine démarré. Les images `postgres:16`, `ghcr.io/acme/api:1.4.2`, et `nginx:1.27` doivent être disponibles. Un fichier `nginx.conf` doit exister dans le répertoire courant.

```bash
# === Création des réseaux ===
# Réseau frontend : bridge standard, les conteneurs sont accessibles via -p
docker network create frontend
# Réseau backend : --internal = pas d'accès Internet, isolation maximale pour les données
docker network create --internal backend

# === Backend (DB), non exposée ===
# Le conteneur "db" est UNIQUEMENT sur le réseau backend (isolé d'Internet)
# -e POSTGRES_PASSWORD=secret : variable d'env pour initialiser le mot de passe PostgreSQL
docker run -d --name db --network backend \
  -e POSTGRES_PASSWORD=secret postgres:16

# === API sur les deux réseaux ===
# Le conteneur "api" est connecté à frontend ET backend :
#   - frontend : accessible par le reverse-proxy
#   - backend  : peut communiquer avec la DB "db" par son nom DNS
# --network-alias api-svc : alias DNS pour que le reverse-proxy puisse utiliser "api-svc"
docker run -d --name api \
  --network frontend \
  --network backend \
  --network-alias api-svc \
  ghcr.io/acme/api:1.4.2

# === Reverse-proxy exposé ===
# Le conteneur "web" (nginx) est le SEUL exposé sur le port 80 de l'hôte (-p 80:80)
# -v monte le fichier nginx.conf local en lecture seule dans le conteneur
# Il est sur le réseau frontend pour pouvoir joindre l'API via "api-svc"
docker run -d --name web \
  --network frontend -p 80:80 \
  -v $PWD/nginx.conf:/etc/nginx/nginx.conf:ro \
  nginx:1.27
```

> **Résultat attendu** :
> ```
> # docker network create frontend
> aabbccdd1122...
> # docker network create --internal backend
> ccddee334455...
> # docker run -d --name db --network backend -e POSTGRES_PASSWORD=secret postgres:16
> 112233445566...
> # docker run -d --name api --network frontend --network backend --network-alias api-svc ghcr.io/acme/api:1.4.2
> 223344556677...
> # docker run -d --name web --network frontend -p 80:80 -v $PWD/nginx.conf:/etc/nginx/nginx.conf:ro nginx:1.27
> 334455667788...
> ```
> **Vérification** : `curl http://localhost:80` répond via nginx. Depuis `web`, `curl http://api-svc` atteint l'API. Depuis `api`, `pg_isready -h db` atteint PostgreSQL. `db` n'a PAS d'accès Internet (`ping 8.8.8.8` échoue depuis `db`). `docker inspect db | jq '.[0].NetworkSettings.Networks | keys'` montre uniquement `["backend"]`.

### 10.2 Bind sur IP locale (sécuriser l'accès)

> **Objectif** : Démarrer un conteneur dont le port publié est lié uniquement à `127.0.0.1` (localhost), empêchant tout accès depuis le réseau externe.
> **Pré-requis** : Docker Engine démarré. L'image `ghcr.io/acme/admin-ui:latest` doit être accessible.

```bash
# Accessible seulement depuis l'hôte
# -p 127.0.0.1:8080:8080 : lie le port 8080 uniquement sur l'interface loopback de l'hôte
# Aucune machine externe ne peut atteindre ce port (sécurité pour les interfaces d'admin)
docker run -d -p 127.0.0.1:8080:8080 ghcr.io/acme/admin-ui:latest
```

> **Résultat attendu** :
> ```
> # docker run -d -p 127.0.0.1:8080:8080 ghcr.io/acme/admin-ui:latest
> 445566778899...
> ```
> **Vérification** : `curl http://127.0.0.1:8080` fonctionne (depuis l'hôte). `curl http://<IP-externe>:8080` échoue (Connection refused). `ss -lntp | grep 8080` montre `127.0.0.1:8080` (et non `0.0.0.0:8080`).

### 10.3 IP statique pour une DB

> **Objectif** : Créer un réseau avec un plan d'adressage fixe et y démarrer une base de données PostgreSQL avec une IP statique, pour une configuration prévisible (ex: pare-feu, documentation).
> **Pré-requis** : Docker Engine démarré. Le sous-réseau `172.22.0.0/24` ne doit pas être utilisé par d'autres réseaux Docker.

```bash
# Crée un réseau "dbnet" avec un sous-réseau /24 et une passerelle définis
# --subnet 172.22.0.0/24 : 254 adresses disponibles (172.22.0.1 à 172.22.0.254)
# --gateway 172.22.0.1   : passerelle du réseau (interface bridge Docker)
docker network create --subnet 172.22.0.0/24 --gateway 172.22.0.1 dbnet
# Démarre PostgreSQL avec une IP statique 172.22.0.10 dans le réseau "dbnet"
# L'IP reste fixe même si le conteneur est redémarré (tant que le réseau existe)
docker run -d --name db --network dbnet --ip 172.22.0.10 postgres:16
```

> **Résultat attendu** :
> ```
> # docker network create --subnet 172.22.0.0/24 --gateway 172.22.0.1 dbnet
> 556677889900...
> # docker run -d --name db --network dbnet --ip 172.22.0.10 postgres:16
> 667788990011...
> ```
> **Vérification** : `docker inspect db | jq '.[0].NetworkSettings.Networks."dbnet".IPAddress'` retourne `"172.22.0.10"`. L'IP reste identique après `docker stop db && docker start db`. `docker network inspect dbnet | jq '.[0].IPAM.Config'` montre le subnet et gateway configurés.

---

## 11) Compose : réseaux, alias, internal, IPAM

> **Objectif** : Définir une stack Docker Compose complète avec 3 services (db, api, web) répartis sur 2 réseaux (frontend bridge, backend internal avec IPAM personnalisé), incluant des alias DNS et un plan d'adressage statique.
> **Pré-requis** : Docker Compose v2 installé. Les images référencées doivent être pullables. Le fichier doit être nommé `docker-compose.yml` (ou `compose.yaml`).

```yaml
# Version du format Compose (3.9 pour compatibilité maximale avec Docker Compose v2)
version: "3.9"
services:
  # Service base de données PostgreSQL
  db:
    image: postgres:16          # Image PostgreSQL 16
    networks:
      backend:                  # Connecté uniquement au réseau backend (isolé)
        aliases: [ db, pg ]     # Alias DNS : résolvable par "db" ET "pg" sur le réseau backend
  # Service API
  api:
    image: ghcr.io/acme/api:1.4.2  # Image de l'API
    networks:
      frontend:                    # Connecté au frontend (joignable par le reverse-proxy)
      backend:                     # Connecté au backend (peut accéder à la DB)
        aliases: [ api-svc ]       # Alias DNS "api-svc" sur le réseau backend
  # Service reverse-proxy nginx
  web:
    image: nginx:1.27           # Image nginx
    ports:
      - "80:80"                 # Publie le port 80 du conteneur sur le port 80 de l'hôte
    networks:
      frontend:                 # Connecté uniquement au frontend

# Définition des réseaux personnalisés
networks:
  frontend:
    driver: bridge              # Réseau bridge standard (avec egress Internet)
  backend:
    driver: bridge              # Réseau bridge
    internal: true              # Pas d'egress Internet (isolation maximale)
    ipam:
      config:
        - subnet: 172.31.0.0/24    # Sous-réseau personnalisé pour le backend
          gateway: 172.31.0.1      # Passerelle du réseau backend
```

> **Résultat attendu** :
> ```
> # docker compose up -d
> ✔ Network proj_frontend   Created
> ✔ Network proj_backend    Created
> ✔ Container proj-db-1     Started
> ✔ Container proj-api-1    Started
> ✔ Container proj-web-1    Started
> ```
> **Vérification** : `docker compose ps` montre les 3 services running. `docker network inspect proj_backend | jq '.[0].Internal'` retourne `true`. Depuis `api`, `ping db` et `ping pg` fonctionnent (alias DNS). Depuis `web`, `curl http://api-svc` fonctionne. `db` n'a pas d'accès Internet. `docker inspect proj-db-1 | jq '.[0].NetworkSettings.Networks."proj_backend".IPAddress'` montre une IP dans `172.31.0.0/24`.

> Pour IPv6 en Compose : ajouter `enable_ipv6: true` + `ipam` v6 si Docker l'autorise.

---

## 12) Do & Don't

**Do**

* Utiliser des **user-defined bridges** (isolation + DNS) plutôt que `docker0`.
* Séparer **frontend** (exposé) et **backend** (`--internal` si possible).
* Lier les ports sur une **IP spécifique** (ex. `127.0.0.1`) quand c'est local-only.
* Documenter les **plans d'adressage** (`--subnet`, IP statiques pour DB/queues).
* Consommer les services **par nom DNS** (alias), pas par IP.

**Don't**

* Éviter de tout mettre sur le **même réseau** (risque de couplage & fuites).
* Ne pas publier de ports **inutiles** ; bannir les `-P` non maîtrisés.
* Éviter `--network host` en prod sauf besoin prouvé (et maîtrisé).
* Ne pas compter sur des **liens** (`--link`) : **déprécié** ; préférez DNS user-defined.
* Ne pas désactiver iptables Docker sans plan pare-feu **équivalent**.

---

## 13) Aide-mémoire (cheat-sheet)

> **Objectif** : Récapitulatif rapide de toutes les commandes réseau Docker essentielles : création/gestion de réseaux, IPAM, attachement, DNS/alias, publication de ports, modes spéciaux, et diagnostic avec netshoot.
> **Pré-requis** : Docker Engine/CLI opérationnel. Ce bloc est une référence rapide, pas un script à exécuter séquentiellement.

```bash
# === Réseaux : opérations de base ===
docker network create app-net        # Créer un réseau bridge user-defined
docker network ls                    # Lister tous les réseaux
docker network inspect app-net | jq  # Inspecter un réseau (JSON formaté)
docker network rm app-net            # Supprimer un réseau (doit être vide)

# === IPAM & internal ===
docker network create --subnet 172.18.0.0/16 app-net  # Créer avec sous-réseau personnalisé
docker network create --internal backend               # Créer un réseau sans egress Internet

# === Attacher / détacher ===
docker network connect app-net ct     # Attacher un conteneur existant à un réseau
docker network disconnect app-net ct  # Détacher un conteneur d'un réseau

# === DNS & alias ===
# Démarrer un conteneur avec un alias DNS sur le réseau
docker run -d --network app-net --network-alias api-svc ghcr.io/acme/api:1.4.2

# === Publication de ports ===
docker run -d -p 8080:80 nginx                # Mappe port 8080 hôte -> port 80 conteneur (TCP)
docker run -d -p 127.0.0.1:8080:80 nginx      # Bind sur localhost uniquement (sécurité)
docker port nginx                              # Afficher les ports publiés d'un conteneur

# === Modes spéciaux ===
docker run --network host image   # Mode host : partage la pile réseau de l'hôte
docker run --network none image   # Mode none : aucune interface réseau

# === Netshoot (diagnostic réseau) ===
docker run --rm -it --network app-net nicolaka/netshoot  # Shell interactif avec outils réseau
```

> **Résultat attendu** :
> ```
> # docker network create app-net
> a1b2c3d4...
> # docker network ls
> NETWORK ID     NAME        DRIVER    SCOPE
> xxx            app-net     bridge    local
> ...
> # docker port nginx
> 80/tcp -> 0.0.0.0:8080
> ```
> **Vérification** : Chaque commande produit le résultat décrit dans les sections correspondantes du chapitre. Utiliser `docker network inspect`, `docker port`, et `ss -lntp` pour confirmer l'état.

---

## 14) Checklist de clôture (qualité réseau)

* Réseaux **user-defined** utilisés ; DNS interne fonctionnel par **noms**/alias.
* **Plans d'adressage** et **IPAM** documentés ; IP statiques réservées si besoin.
* Séparation **front/back** ; **backend** en `--internal` si compatible.
* Ports publiés **explicitement** (`-p`) et **au strict nécessaire** ; binds sur IP d'écoute voulues.
* **Pare-feu** de l'hôte cohérent (Docker iptables actif ou règles équivalentes).
* MTU/hairpin **testés** ; diagnostics (`netshoot`, `docker port`, `iptables -t nat -S`) connus.
* Pas d'usage de `--link` ; pas de `--network host` non justifié.
