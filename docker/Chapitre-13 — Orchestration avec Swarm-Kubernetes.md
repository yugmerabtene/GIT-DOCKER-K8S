# Chapitre-13 — Orchestration avec Swarm/Kubernetes

*(passerelles depuis Compose, HA, déploiements, réseau, stockage, sécurité, observabilité)*

## Objectifs d'apprentissage

* Comprendre **quand** et **pourquoi** passer de Docker Compose à un orchestrateur (**Swarm** ou **Kubernetes**).
* Savoir modéliser une application en **services répliqués**, gérer **mises à jour progressives**, **rollbacks**, **placement** des workloads et **haute disponibilité**.
* Maîtriser les bases **réseau**, **stockage**, **sécurité**, **observabilité** et **CI/CD** propres à Swarm et Kubernetes.
* Disposer d'une **cartographie Compose → Swarm/K8s** et de **patrons de déploiement** (rolling, blue/green, canary) réutilisables.

## Pré-requis

* Chap. 01–12 (images, conteneurs, réseau, stockage, Dockerfile/BuildKit, Compose, registry, sécurité, perf, CI/CD, releases).
* Connaissances Linux réseau/FS. Pour Kubernetes : notions YAML, RBAC.

---

## 1) Quand quitter Compose ?

* **Scale & HA** : besoin de **réplicas** auto-gérés, redémarrage sur panne, **auto-healing**.
* **Rolling updates** et **rollbacks** atomiques.
* **Planification** (anti-affinité, contraintes par nœud), **autoscaling**, **quotas**.
* **Sécurité** (RBAC, isolement réseau), **multi-tenant**.
* **Add-ons** : ingress contrôleurs, service mesh, secrets KMS/cloud, opérateurs DB.

> **Swarm** : chemin le plus court depuis Compose, simple, natif Docker.
> **Kubernetes** : écosystème riche, standard de facto, plus verbeux mais plus puissant.

---

## 2) Compose → Swarm : concepts & commandes

### 2.1 Concepts clés

* **Cluster** Swarm = **managers** (Raft) + **workers**.
* **Service** = définition d'un conteneur répliqué (**tasks**).
* **Stack** = groupe de services issu d'un fichier Compose v3+ (`deploy.*` **pris en charge**).
* **Réseau overlay** chiffré multi-hôtes ; **routing mesh** (LB L4 intégré).
* **Secrets/Configs** gérés par Swarm (montés en fichiers).
* **Update/Rollback** paramétrables (parallélisme, délais, action on-failure).

### 2.2 Initialiser un cluster & joindre des nœuds

> **Objectif** : Initialiser un cluster Swarm sur le premier nœud manager, puis faire rejoindre des nœuds workers au cluster.
> **Pré-requis** : Docker Engine installé et démarré sur tous les nœuds ; le port TCP 2377 doit être ouvert entre les nœuds.

```bash
# Initialise le cluster Swarm sur ce nœud (devient manager leader)
# Génère les tokens manager et worker nécessaires pour rejoindre le cluster
docker swarm init                         # sur le premier manager

# Fait rejoindre un nœud worker au cluster en utilisant le token fourni par 'swarm init'
# Remplacer <worker-token> par le token réel et <manager-ip> par l'IP du manager
docker swarm join --token <worker-token> <manager-ip>:2377

# Liste tous les nœuds du cluster Swarm avec leur statut (Ready/Down) et leur rôle (Manager/Worker)
docker node ls
```

> **Résultat attendu** :
> ```
> $ docker swarm init
> Swarm initialized: current node (abc123) is now a manager.
>
> $ docker swarm join --token SWMTKN-1-xxxxx 192.168.1.10:2377
> This node joined a swarm as a worker.
>
> $ docker node ls
> ID                            HOSTNAME   STATUS    AVAILABILITY   MANAGER STATUS
> abc123 *                      manager1   Ready     Active         Leader
> def456                        worker1    Ready     Active
> ```
> **Vérification** : `docker node ls` affiche tous les nœuds avec le statut `Ready` et le rôle correct (Manager/Worker).

### 2.3 Créer un service répliqué

> **Objectif** : Créer un service Swarm répliqué (3 instances de nginx) exposé sur le port 80, puis vérifier son état.
> **Pré-requis** : Cluster Swarm initialisé (section 2.2) ; au moins un nœud worker disponible.

```bash
# Crée un service nommé 'web' avec 3 réplicas, mappant le port 80 de l'hôte vers le port 80 du conteneur
# L'image nginx:1.27 est utilisée ; le routing mesh distribue le trafic sur tous les nœuds
docker service create --name web --replicas 3 -p 80:80 nginx:1.27

# Liste tous les services Swarm avec le nombre de réplicas désirés/actifs
docker service ls

# Affiche les tâches (tasks) du service 'web' : chaque réplica, son nœud, son état (running/preparing)
docker service ps web
```

> **Résultat attendu** :
> ```
> $ docker service ls
> ID          NAME  MODE        REPLICAS   IMAGE        PORTS
> xyz789      web   replicated  3/3        nginx:1.27   *:80->80/tcp
>
> $ docker service ps web
> ID          NAME    IMAGE        NODE      DESIRED STATE   CURRENT STATE
> a1b2c3      web.1   nginx:1.27   worker1   Running         Running 5s ago
> d4e5f6      web.2   nginx:1.27   worker2   Running         Running 5s ago
> g7h8i9      web.3   nginx:1.27   manager1  Running         Running 5s ago
> ```
> **Vérification** : `docker service ls` montre `3/3` dans la colonne REPLICAS ; `docker service ps web` montre 3 tâches en état `Running`.

### 2.4 Déployer une **stack** depuis Compose (v3+)

> **Objectif** : Déployer un groupe de services (stack) à partir d'un fichier `compose.yaml` utilisant la syntaxe `deploy.*` de Swarm, puis inspecter et supprimer la stack.
> **Pré-requis** : Cluster Swarm actif ; un fichier `compose.yaml` valide avec des directives `deploy.*` (replicas, resources, etc.).

```bash
# Déploie la stack 'myapp' à partir du fichier compose.yaml
# Crée les services, réseaux et volumes définis dans le fichier Compose
docker stack deploy -c compose.yaml myapp

# Liste tous les services de la stack 'myapp' avec leur nombre de réplicas
docker stack services myapp

# Affiche les tâches de tous les services de la stack 'myapp' (répartition par nœud)
docker stack ps myapp

# Supprime la stack 'myapp' : arrête tous les services, supprime réseaux et volumes anonymes
docker stack rm myapp
```

> **Résultat attendu** :
> ```
> $ docker stack deploy -c compose.yaml myapp
> Creating network myapp_front
> Creating service myapp_web
> Creating service myapp_api
>
> $ docker stack services myapp
> ID          NAME         MODE        REPLICAS   IMAGE
> a1b2c3      myapp_web    replicated  3/3        nginx:1.27
> d4e5f6      myapp_api    replicated  4/4        ghcr.io/acme/api:1.4.2
>
> $ docker stack rm myapp
> Removing service myapp_web
> Removing service myapp_api
> Removing network myapp_front
> ```
> **Vérification** : `docker stack services myapp` montre tous les services avec les réplicas attendus ; après `stack rm`, `docker stack ls` ne liste plus la stack.

> Contrairement à `docker compose`, les champs **`deploy.*`** (réplicas, ressources, update) **sont actifs** en Swarm.

### 2.5 Mises à jour & rollback

> **Objectif** : Mettre à jour l'image d'un service Swarm avec une stratégie de rolling update contrôlée (parallélisme, délai, monitor), et pouvoir annuler via un rollback.
> **Pré-requis** : Service `web` existant dans le cluster Swarm (section 2.3).

```bash
# Met à jour le service 'web' vers nginx:1.27.2 avec une stratégie de rolling update :
#   --update-parallelism 1  : met à jour 1 conteneur à la fois
#   --update-delay 10s      : attend 10s entre chaque conteneur
#   --update-monitor 30s    : surveille 30s après chaque mise à jour pour détecter les échecs
#   --update-failure-action rollback : annule automatiquement en cas d'échec
docker service update --image nginx:1.27.2 --update-parallelism 1 \
  --update-delay 10s --update-monitor 30s --update-failure-action rollback web

# Annule la dernière mise à jour du service 'web' et restaure la version précédente
docker service rollback web
```

> **Résultat attendu** :
> ```
> $ docker service update --image nginx:1.27.2 --update-parallelism 1 \
>   --update-delay 10s --update-monitor 30s --update-failure-action rollback web
> web
> overall progress: 3 out of 3 tasks
> 1/3: running   [==================================================>]
> 2/3: running   [==================================================>]
> 3/3: running   [==================================================>]
> verify: Service converged
>
> $ docker service rollback web
> web
> rollback: manually requested rollback
> overall progress: rolling back update: 3 out of 3 tasks
> ```
> **Vérification** : `docker service ps web` montre la nouvelle image après update, puis l'ancienne image après rollback.

### 2.6 Placement & ressources

> **Objectif** : Appliquer des contraintes de placement (étiquettes de nœuds) et des limites de ressources (CPU/mémoire) sur les services Swarm.
> **Pré-requis** : Cluster Swarm avec au moins 2 nœuds ; accès `docker node update` (rôle manager).

```bash
# Ajoute l'étiquette 'role=frontend' au nœud spécifié pour le utiliser comme contrainte de placement
# Contraintes (exécuter sur les nœuds tagués)
docker node update --label-add role=frontend <node>

# Crée un service qui ne sera planifié QUE sur les nœuds possédant l'étiquette 'role=frontend'
docker service create --constraint 'node.labels.role == frontend' ...

# Crée un service avec des limites de ressources : 1 CPU max et 512 Mo de mémoire max par conteneur
# Limites
docker service create --limit-cpu 1 --limit-memory 512M ...
```

> **Résultat attendu** :
> ```
> $ docker node update --label-add role=frontend worker1
> worker1
>
> $ docker service create --constraint 'node.labels.role == frontend' --name web nginx:1.27
> x7y8z9
>
> $ docker service ps web
> ID          NAME    IMAGE        NODE     DESIRED STATE   CURRENT STATE
> a1b2c3      web.1   nginx:1.27   worker1  Running         Running 2s ago
> ```
> **Vérification** : `docker service ps <service>` montre que les tâches sont planifiées uniquement sur les nœuds étiquetés ; `docker service inspect <service>` affiche les limites de ressources.

### 2.7 Réseau overlay & modes de résolution

* **Routing mesh** : publication L4 sur tous les nœuds (`-p 80:80`).
* **DNS VIP** (par défaut) vs **DNSRR** (round-robin sans VIP) :

> **Objectif** : Créer un service utilisant le mode DNSRR (DNS Round Robin) au lieu du VIP par défaut, pour une résolution DNS directe vers les IPs des conteneurs.
> **Pré-requis** : Cluster Swarm actif ; réseau overlay disponible.

```bash
# Crée un service 'api' avec 3 réplicas en mode DNSRR (DNS Round Robin)
# Au lieu d'un VIP unique, le DNS retourne directement les IPs de chaque tâche
# Utile pour du load-balancing côté client ou pour contourner le routing mesh
docker service create --name api --replicas 3 --endpoint-mode dnsrr ...
```

> **Résultat attendu** :
> ```
> $ docker service create --name api --replicas 3 --endpoint-mode dnsrr --network back ghcr.io/acme/api:1.4.2
> b2c3d4
>
> $ docker service inspect --format '{{.Endpoint.Spec.Mode}}' api
> dnsrr
> ```
> **Vérification** : `docker service inspect api` confirme `Endpoint.Spec.Mode: dnsrr` ; une requête DNS depuis un conteneur du même réseau retourne plusieurs IPs.

### 2.8 Secrets & configs

> **Objectif** : Créer un secret Swarm (donnée sensible chiffrée) et une config Swarm (fichier de configuration), puis les monter dans un service.
> **Pré-requis** : Cluster Swarm actif (les secrets/configs ne sont disponibles que sur les managers) ; le fichier `./nginx.conf` existe localement.

```bash
# Crée un secret nommé 'jwt' à partir de l'entrée standard (stdin)
# Le secret est chiffré et stocké dans le Raft store du cluster
echo 'supersecret' | docker secret create jwt -

# Crée un service 'api' qui monte le secret 'jwt' en fichier (/run/secrets/jwt dans le conteneur)
docker service create --name api --secret jwt ghcr.io/acme/api:1.4.2

# Crée une config nommée 'webconf' à partir du fichier local nginx.conf
# Les configs sont montées en fichiers dans le conteneur (non chiffrées, pour données non sensibles)
docker config create webconf ./nginx.conf
```

> **Résultat attendu** :
> ```
> $ echo 'supersecret' | docker secret create jwt -
> m9n0o1p2q3
>
> $ docker service create --name api --secret jwt ghcr.io/acme/api:1.4.2
> r4s5t6u7v8
>
> $ docker config create webconf ./nginx.conf
> w9x0y1z2a3
>
> $ docker secret ls
> ID          NAME   CREATED             UPDATED
> m9n0o1p2q3  jwt    10 seconds ago      10 seconds ago
> ```
> **Vérification** : `docker secret ls` et `docker config ls` listent les ressources créées ; dans le conteneur, le secret est accessible en `/run/secrets/jwt`.

### 2.9 Patron Compose→Swarm (extrait `compose.yaml`)

> **Objectif** : Fournir un modèle complet de fichier `compose.yaml` v3.9 utilisant les directives `deploy.*` spécifiques à Swarm (réplicas, update_config, rollback_config, placement, ressources, endpoint_mode, secrets, réseaux overlay).
> **Pré-requis** : Cluster Swarm avec des nœuds étiquetés `role=frontend` ; secret `jwt` créé (section 2.8).

```yaml
# Version 3.9 du format Compose — requise pour les directives deploy.* complètes
version: "3.9"
services:
  # Service web : reverse proxy nginx exposé publiquement sur le port 80
  web:
    image: nginx:1.27
    ports: [ "80:80" ]                          # Publication via routing mesh Swarm
    deploy:
      replicas: 3                               # 3 instances du conteneur web
      update_config: { parallelism: 1, delay: 10s, order: start-first }  # Rolling update : 1 à la fois, 10s de délai, démarre le nouveau avant d'arrêter l'ancien (zero-downtime)
      rollback_config: { parallelism: 1, delay: 5s }                     # Rollback : 1 conteneur à la fois, 5s de délai
      placement:
        constraints: [ "node.labels.role == frontend" ]  # Planifié uniquement sur les nœuds étiquetés 'frontend'
    networks: [ front ]                         # Connecté uniquement au réseau frontal

  # Service api : backend applicatif avec limites de ressources et mode DNSRR
  api:
    image: ghcr.io/acme/api@sha256:...          # Image épinglée par digest (immutabilité)
    deploy:
      replicas: 4                               # 4 instances du conteneur api
      resources:
        limits: { cpus: "1.0", memory: 512M }   # Limites : 1 CPU et 512 Mo par conteneur
      endpoint_mode: dnsrr                      # Mode DNSRR : pas de VIP, résolution directe
    networks: [ front, back ]                   # Connecté aux réseaux frontal ET backend
    secrets: [ jwt ]                            # Monte le secret 'jwt' en /run/secrets/jwt

# Définition des réseaux overlay (multi-hôtes, chiffrés)
networks:
  front: { driver: overlay }                    # Réseau frontal (overlay, accessible depuis l'extérieur)
  back:  { driver: overlay, attachable: true }  # Réseau backend (overlay, 'attachable' permet aux conteneurs standalone de s'y connecter)

# Secrets référencés (externes = créés manuellement via 'docker secret create', pas gérés par la stack)
secrets:
  jwt: { external: true }
```

> **Résultat attendu** :
> ```
> $ docker stack deploy -c compose.yaml myapp
> Creating network myapp_front
> Creating network myapp_back
> Creating service myapp_web
> Creating service myapp_api
>
> $ docker stack services myapp
> ID          NAME         MODE        REPLICAS   IMAGE
> a1b2c3      myapp_web    replicated  3/3        nginx:1.27
> d4e5f6      myapp_api    replicated  4/4        ghcr.io/acme/api@sha256:...
> ```
> **Vérification** : `docker stack services myapp` montre 3/3 pour web et 4/4 pour api ; `docker service inspect myapp_web` confirme les contraintes de placement et la stratégie d'update.

**Limites Swarm (à connaître)** : écosystème plus restreint (ingress avancés, opérateurs), autoscaling natif limité, communauté moindre vs K8s.

---

## 3) Compose → Kubernetes : concepts & ressources

### 3.1 Objets fondamentaux

* **Pod** : plus petite unité d'exécution (1+ conteneurs).
* **Deployment** : gère les **réplicas**, **rolling updates** et **rollbacks** (ReplicaSets).
* **Service** : L4 stable (ClusterIP/NodePort/LoadBalancer) avec **DNS** interne.
* **Ingress** : L7 (HTTP) via **Ingress Controller** (Nginx, Traefik, HAProxy…).
* **ConfigMap / Secret** : configuration et secrets **montés** (fichiers/env).
* **StatefulSet** : apps **stateful** (DB, queue) avec **volumes persistants** stables.
* **Job/CronJob** : traitements batch/planifiés.
* **Namespace/RBAC** : multi-tenant et permissions.
* **HorizontalPodAutoscaler (HPA)** : autoscaling **CPU/mémoire** (et metrics custom).

### 3.2 Mapping Compose → K8s (repères)

| Compose (v2)    | Swarm           | Kubernetes                             |
| --------------- | --------------- | -------------------------------------- |
| service         | service         | Deployment (+ Service)                 |
| ports           | publish         | Service (NodePort/LB) + Ingress        |
| volumes         | volumes         | PersistentVolumeClaim (+ StorageClass) |
| configs/secrets | configs/secrets | ConfigMap / Secret                     |
| networks        | overlay         | CNI (pod network) + Service/Ingress    |
| healthcheck     | update monitor  | probes (readiness/liveness/startup)    |

### 3.3 Manifeste minimal (api + web)

> **Objectif** : Déployer un service API (3 réplicas) avec un Deployment et un Service ClusterIP, puis un frontend web (2 réplicas) avec un Ingress pour l'exposition HTTP externe.
> **Pré-requis** : Cluster Kubernetes actif (`kubectl` configuré) ; Ingress Controller Nginx installé ; image `ghcr.io/acme/api` accessible.

```yaml
# deployment-api.yaml
# API version et type de ressource Kubernetes
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api                                    # Nom du Deployment
  labels: { app: demo }                        # Étiquette globale du Deployment
spec:
  replicas: 3                                  # 3 pods répliqués
  selector:
    matchLabels: { app: demo, tier: api }      # Sélectionne les pods étiquetés 'app=demo, tier=api'
  template:                                    # Template du pod (spécification des conteneurs)
    metadata: { labels: { app: demo, tier: api } }  # Étiquettes appliquées à chaque pod
    spec:
      containers:
        - name: api
          image: ghcr.io/acme/api@sha256:...   # Image épinglée par digest (immutabilité, reproductibilité)
          ports: [ { containerPort: 8080 } ]   # Le conteneur écoute sur le port 8080
          resources:
            requests: { cpu: "250m", memory: "256Mi" }  # Ressources garanties (schedulability) : 0.25 CPU, 256 Mo
            limits:   { cpu: "1",    memory: "512Mi" }   # Ressources maximales : 1 CPU, 512 Mo (throttling au-delà)
          readinessProbe:                      # Sonde de readiness : détermine si le pod peut recevoir du trafic
            httpGet: { path: /health, port: 8080 }       # Requête HTTP GET sur /health:8080
            periodSeconds: 10                  # Vérifiée toutes les 10 secondes
          livenessProbe:                       # Sonde de liveness : détermine si le pod doit être redémarré
            httpGet: { path: /health, port: 8080 }       # Requête HTTP GET sur /health:8080
            initialDelaySeconds: 20            # Première vérification après 20s (délai de démarrage)
---
# Service Kubernetes de type ClusterIP (accessible uniquement dans le cluster)
apiVersion: v1
kind: Service
metadata: { name: api }                        # Nom du Service (devient le nom DNS : api.default.svc.cluster.local)
spec:
  selector: { app: demo, tier: api }           # Route le trafic vers les pods correspondants
  ports: [ { port: 80, targetPort: 8080 } ]    # Expose le port 80 du Service vers le port 8080 des pods
  type: ClusterIP                              # IP interne au cluster (pas d'exposition externe)
```

> **Résultat attendu** :
> ```
> $ kubectl apply -f deployment-api.yaml
> deployment.apps/api created
> service/api created
>
> $ kubectl get pods -l app=demo,tier=api
> NAME                   READY   STATUS    RESTARTS   AGE
> api-6d4f5b8c9-abc12   1/1     Running   0          30s
> api-6d4f5b8c9-def34   1/1     Running   0          30s
> api-6d4f5b8c9-ghi56   1/1     Running   0          30s
>
> $ kubectl get svc api
> NAME   TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
> api    ClusterIP   10.96.100.50    <none>        80/TCP    30s
> ```
> **Vérification** : `kubectl get pods` montre 3 pods en état `Running` et `READY 1/1` ; `kubectl describe pod <name>` affiche les probes et limites de ressources.

```yaml
# web + ingress
# Deployment pour le frontend web (nginx)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web                                    # Nom du Deployment web
  labels: { app: demo, tier: web }             # Étiquettes : app=demo, tier=web
spec:
  replicas: 2                                  # 2 pods répliqués
  selector:
    matchLabels: { app: demo, tier: web }      # Sélectionne les pods 'app=demo, tier=web'
  template:
    metadata: { labels: { app: demo, tier: web } }
    spec:
      containers:
        - name: web
          image: nginx:1.27                    # Image nginx version 1.27
          ports: [ { containerPort: 80 } ]     # Le conteneur écoute sur le port 80
---
# Service ClusterIP pour le frontend web
apiVersion: v1
kind: Service
metadata: { name: web }
spec:
  selector: { app: demo, tier: web }           # Route vers les pods web
  ports: [ { port: 80, targetPort: 80 } ]      # Port 80 → port 80 des pods
  type: ClusterIP                              # Accessible uniquement en interne
---
# Ingress : règle de routage HTTP L7 pour exposer le service web à l'extérieur
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: demo                                   # Nom de la ressource Ingress
  annotations:
    kubernetes.io/ingress.class: nginx         # Utilise l'Ingress Controller Nginx
spec:
  rules:
    - host: demo.example.com                   # Route uniquement les requêtes pour ce domaine
      http:
        paths:
          - path: /                            # Chemin racine (toutes les URLs)
            pathType: Prefix                   # Correspondance par préfixe
            backend:
              service:
                name: web                      # Route vers le Service 'web'
                port:
                  number: 80                   # Sur le port 80
```

> **Résultat attendu** :
> ```
> $ kubectl apply -f web-ingress.yaml
> deployment.apps/web created
> service/web created
> ingress.networking.k8s.io/demo created
>
> $ kubectl get ingress demo
> NAME   CLASS   HOSTS                ADDRESS         PORTS   AGE
> demo   nginx   demo.example.com     203.0.113.10    80      15s
>
> $ kubectl get pods -l app=demo,tier=web
> NAME                  READY   STATUS    RESTARTS   AGE
> web-7f8g9h0i1-jk12   1/1     Running   0          15s
> web-7f8g9h0i1-lm34   1/1     Running   0          15s
> ```
> **Vérification** : `kubectl get ingress` affiche l'adresse IP de l'Ingress Controller ; `curl -H "Host: demo.example.com" http://<ADDRESS>` retourne la page nginx.

### 3.4 Stockage & données persistantes

* **StorageClass** (provisionneur dynamique cloud/CSI), **PVC** par Pod/StatefulSet.

> **Objectif** : Créer une PersistentVolumeClaim (PVC) de 20 GiB utilisant la StorageClass `fast-ssd` pour le stockage persistant d'une base de données (ex: PostgreSQL).
> **Pré-requis** : Cluster Kubernetes avec un provisionneur de volumes (CSI/cloud) configuré ; StorageClass `fast-ssd` existante.

```yaml
# PersistentVolumeClaim : demande de stockage persistant
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: data-pg }                    # Nom du PVC (référencé par les pods/StatefulSets)
spec:
  accessModes: [ ReadWriteOnce ]               # Montage en lecture/écriture par un seul nœud (RWO)
  resources: { requests: { storage: 20Gi } }   # Demande 20 Gio d'espace de stockage
  storageClassName: fast-ssd                   # Utilise la StorageClass 'fast-ssd' (provisionnement dynamique SSD)
```

> **Résultat attendu** :
> ```
> $ kubectl apply -f pvc.yaml
> persistentvolumeclaim/data-pg created
>
> $ kubectl get pvc data-pg
> NAME      STATUS   VOLUME          CAPACITY   ACCESS MODES   STORAGECLASS   AGE
> data-pg   Bound    pv-abc123       20Gi       RWO            fast-ssd       5s
> ```
> **Vérification** : `kubectl get pvc data-pg` montre le statut `Bound` ; un PersistentVolume a été provisionné dynamiquement avec 20Gi.

### 3.5 Sécurité (bases)

* **ServiceAccount** + **RBAC** (roles/rolebindings) par namespace.
* **SecurityContext** : `runAsUser`, `runAsNonRoot`, `readOnlyRootFilesystem`, `capabilities`.
* **Pod Security Admission** (baseline/restricted).
* **NetworkPolicy** (isoler le trafic).
* **imagePullSecrets** pour registries privés.
* **OPA Gatekeeper/Kyverno** : politiques d'admission (refuser `:latest`, pods non-root, etc.).
* **cosign** + **policy-controller** (vérif. de signatures) — selon stack choisie.

### 3.6 Observabilité

* `kubectl logs -f`, `kubectl describe`, `kubectl top pods/nodes`.
* **metrics-server**, Prometheus/Grafana pour métriques, Loki/ELK pour logs.
* Traces : OTEL Collector + Jaeger/Tempo.

### 3.7 Mises à jour, rollbacks & autoscaling

> **Objectif** : Surveiller le déploiement d'une mise à jour, annuler un rollout problématique, mettre à jour l'image par digest, et configurer l'autoscaling horizontal (HPA) basé sur l'utilisation CPU.
> **Pré-requis** : Cluster Kubernetes avec `metrics-server` installé ; Deployment `api` existant.

```bash
# Affiche le statut du rollout en cours (attend que tous les pods soient à jour et disponibles)
kubectl rollout status deploy/api

# Annule le dernier rollout et restaure la révision précédente du Deployment
kubectl rollout undo deploy/api

# Met à jour l'image du conteneur 'api' dans le Deployment en utilisant un digest SHA256 (immutabilité)
kubectl set image deploy/api api=ghcr.io/acme/api@sha256:...   # update par digest

# Crée un HorizontalPodAutoscaler (HPA) pour le Deployment 'api' :
#   --min=3        : minimum 3 réplicas
#   --max=10       : maximum 10 réplicas
#   --cpu-percent=70 : scale si l'utilisation CPU moyenne dépasse 70%
kubectl autoscale deploy/api --min=3 --max=10 --cpu-percent=70
```

> **Résultat attendu** :
> ```
> $ kubectl rollout status deploy/api
> deployment "api" successfully rolled out
>
> $ kubectl set image deploy/api api=ghcr.io/acme/api@sha256:abc123...
> deployment.apps/api image updated
>
> $ kubectl autoscale deploy/api --min=3 --max=10 --cpu-percent=70
> horizontalpodautoscaler.autoscaling/api autoscaled
>
> $ kubectl get hpa api
> NAME   REFERENCE         TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
> api    Deployment/api    45%/70%   3         10        3          10s
> ```
> **Vérification** : `kubectl get hpa api` montre la cible CPU courante vs le seuil ; `kubectl get pods` affiche le nombre de réplicas qui augmente sous la charge.

* Probes **readiness** = portes de trafic ; **liveness** = redémarrage en échec.

### 3.8 Blue/Green & Canary (K8s)

* **Blue/Green** : deux Deployments (labels `version=blue|green`) + **Service** pointant vers `version=green` à la bascule.
* **Canary** :

  * Ingress Nginx (annotations canary/poids) **ou**
  * Deux Services (stable/canary) & règles L7 pondérées **ou**
  * **Service mesh** (Istio/Linkerd) pour controler le pourcentage fin, avec traces mTLS.

### 3.9 Gestion des manifests

* **Helm** (charts, valeurs) pour factoriser.
* **Kustomize** (patch/overlay) pour variantes env sans templating.
* **Kompose** pour convertir un Compose en manifests (point de départ, **à revoir** manuellement).

---

## 4) Réseau : Swarm vs Kubernetes (repères)

| Thème          | Swarm                            | Kubernetes                                       |
| -------------- | -------------------------------- | ------------------------------------------------ |
| L4 interne     | VIP/DNSRR                        | Service ClusterIP (kube-proxy/IPVS)              |
| L4 externe     | Routing mesh (`-p`)              | Service NodePort/LoadBalancer                    |
| L7             | Nginx/Traefik externes           | Ingress Controller (Nginx/Traefik/HAProxy/Envoy) |
| DNS            | Interne service name             | CoreDNS                                          |
| Network policy | Basique (isolation via networks) | **NetworkPolicy** (CNI must support)             |

---

## 5) Stockage & données

|          | Swarm                                | Kubernetes                                           |
| -------- | ------------------------------------ | ---------------------------------------------------- |
| Volumes  | `local`, NFS, drivers tiers          | **PVC/PV/StorageClass** (CSI)                        |
| Stateful | Réplicas simples, pas de StatefulSet | **StatefulSet** (volumes par Pod, identités stables) |
| Backups  | scripts/volumes                      | opérateurs/sidecars & jobs dédiés                    |

---

## 6) Sécurité (résumé opérationnel)

**Swarm**

* Secrets/Configs natifs, chiffrés en transit & au repos (Raft).
* Contrainte placement, pas de RBAC riche.
* Exposition API Docker à restreindre (TLS, pare-feu).

**Kubernetes**

* **RBAC** fin, **ServiceAccounts**, **NetworkPolicy**, PodSecurity (baseline/restricted).
* **SecurityContext** non-root, capabilities minimales, **readOnlyRootFilesystem**.
* Admission policies (Gatekeeper/Kyverno), signatures cosign, **imagePolicyWebhook** (selon stack).

---

## 7) CI/CD & déploiements

* **Swarm** : `docker stack deploy` depuis CI, paramètres `deploy.*` dans Compose ; promotion **par digest**.
* **K8s** : `kubectl apply`/`helm upgrade`/`kustomize` ; `rollout status/undo`; promotion **par digest** ; gates (OPA), scanners (Trivy/Starboard), **HPA**.

---

## 8) Exemples "prod-like" synthèse

### 8.1 Swarm — stack web/api/db

> **Objectif** : Déployer une stack Swarm complète en mode production avec 3 services (db PostgreSQL, api backend, web frontend), des réseaux overlay isolés (front/back), des contraintes de placement, des limites de ressources, et un secret externe pour le mot de passe DB.
> **Pré-requis** : Cluster Swarm avec nœuds étiquetés `role=frontend` et `role=backend` ; secret `pg_pwd` créé via `docker secret create`.

```yaml
# Stack Compose v3.9 pour déploiement Swarm en mode production
version: "3.9"
services:
  # Service base de données PostgreSQL
  db:
    image: postgres:16                         # Image PostgreSQL 16
    volumes: [ data_pg:/var/lib/postgresql/data ]  # Volume persistant pour les données DB
    networks: [ back ]                         # Uniquement sur le réseau backend (isolé)
    deploy:
      placement:
        constraints: [ "node.labels.role == backend" ]  # Planifié sur les nœuds 'backend' uniquement

  # Service API backend
  api:
    image: ghcr.io/acme/api@sha256:...         # Image épinglée par digest (immutabilité)
    secrets: [ pg_pwd ]                        # Monte le secret du mot de passe PostgreSQL
    networks: [ front, back ]                  # Connecté aux deux réseaux (front ET back)
    deploy:
      replicas: 4                              # 4 instances de l'API
      resources: { limits: { cpus: "1", memory: 512M } }  # Limites : 1 CPU, 512 Mo par conteneur
      update_config:
        parallelism: 1                         # Rolling update : 1 conteneur à la fois
        delay: 10s                             # 10s entre chaque mise à jour
        order: start-first                     # Démarre le nouveau conteneur AVANT d'arrêter l'ancien (zero-downtime)

  # Service frontend web (nginx)
  web:
    image: nginx:1.27                          # Image nginx 1.27
    ports: [ "80:80" ]                         # Exposition publique sur le port 80 (routing mesh)
    networks: [ front ]                        # Uniquement sur le réseau frontal
    deploy:
      replicas: 3                              # 3 instances du frontend
      placement:
        constraints: [ "node.labels.role == frontend" ]  # Planifié sur les nœuds 'frontend'

# Réseaux overlay isolés
networks:
  front: { driver: overlay }                   # Réseau frontal (overlay, pour web)
  back:  { driver: overlay }                   # Réseau backend (overlay, pour db et api)

# Volumes nommés
volumes:
  data_pg: {}                                  # Volume pour les données PostgreSQL (géré par Swarm)

# Secrets externes (créés manuellement, non gérés par la stack)
secrets:
  pg_pwd: { external: true }
```

> **Résultat attendu** :
> ```
> $ docker stack deploy -c compose.yaml prod
> Creating network prod_back
> Creating network prod_front
> Creating service prod_db
> Creating service prod_api
> Creating service prod_web
>
> $ docker stack services prod
> ID          NAME        MODE        REPLICAS   IMAGE
> a1b2c3      prod_db     replicated  1/1        postgres:16
> d4e5f6      prod_api    replicated  4/4        ghcr.io/acme/api@sha256:...
> g7h8i9      prod_web    replicated  3/3        nginx:1.27
>
> $ docker stack ps prod
> ID          NAME         IMAGE              NODE      DESIRED STATE   CURRENT STATE
> ...         prod_db.1    postgres:16        backend1  Running         Running 10s ago
> ...         prod_api.1   acme/api@sha256    worker1   Running         Running 10s ago
> ...         prod_web.1   nginx:1.27         front1    Running         Running 10s ago
> ```
> **Vérification** : `docker stack ps prod` montre que `db` est sur un nœud `backend`, `web` sur un nœud `frontend`, et `api` est réparti ; `curl http://<manager-ip>:80` retourne la page nginx.

### 8.2 Kubernetes — api avec HPA & NetworkPolicy

> **Objectif** : Déployer un service API Kubernetes en mode production avec : un Deployment sécurisé (non-root, filesystem read-only, capabilities minimales), un Service ClusterIP, un HorizontalPodAutoscaler (HPA) pour l'autoscaling CPU, et une NetworkPolicy pour restreindre le trafic entrant aux seuls pods frontend.
> **Pré-requis** : Cluster Kubernetes avec `metrics-server` installé ; CNI supportant les NetworkPolicy (Calico, Cilium, etc.) ; ServiceAccount `api` créé.

```yaml
# Deployment API avec durcissement de sécurité
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api                                    # Nom du Deployment
  labels: { app: demo }                        # Étiquette globale
spec:
  replicas: 3                                  # 3 pods répliqués
  selector:
    matchLabels: { app: demo }                 # Sélectionne les pods 'app=demo'
  template:
    metadata: { labels: { app: demo } }
    spec:
      serviceAccountName: api                  # ServiceAccount dédié (principe de moindre privilège RBAC)
      containers:
        - name: api
          image: ghcr.io/acme/api@sha256:...   # Image épinglée par digest
          ports: [ { containerPort: 8080 } ]
          securityContext:
            runAsNonRoot: true                 # Interdit l'exécution en tant que root (sécurité)
            readOnlyRootFilesystem: true        # Système de fichiers en lecture seule (empêche l'écriture)
            capabilities:
              drop: [ "ALL" ]                  # Supprime TOUTES les capabilities Linux (principe de moindre privilège)
---
# Service ClusterIP pour l'API
apiVersion: v1
kind: Service
metadata: { name: api }
spec:
  selector: { app: demo }                      # Route vers les pods 'app=demo'
  ports: [ { port: 80, targetPort: 8080 } ]    # Port 80 → port 8080 des pods
---
# HorizontalPodAutoscaler : autoscaling basé sur l'utilisation CPU
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: { name: api }
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api                                  # Cible le Deployment 'api'
  minReplicas: 3                               # Minimum 3 réplicas (haute disponibilité)
  maxReplicas: 10                              # Maximum 10 réplicas (limite de coût)
  metrics:
    - type: Resource
      resource:
        name: cpu                              # Métrique : utilisation CPU
        target:
          type: Utilization
          averageUtilization: 70               # Seuil : scale quand CPU moyen > 70%
---
# NetworkPolicy : isolation réseau du service API
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-allow-web                          # Nom de la politique réseau
  namespace: default
spec:
  podSelector:
    matchLabels: { app: demo }                 # S'applique aux pods 'app=demo' (l'API)
  ingress:
    - from:
        - podSelector:
            matchLabels: { tier: web }         # Autorise le trafic UNIQUEMENT depuis les pods 'tier=web'
      ports:
        - protocol: TCP
          port: 8080                           # Sur le port TCP 8080 uniquement
  policyTypes: [ Ingress ]                     # Type de politique : contrôle du trafic entrant
```

> **Résultat attendu** :
> ```
> $ kubectl apply -f api-prod.yaml
> deployment.apps/api created
> service/api created
> horizontalpodautoscaler.autoscaling/api created
> networkpolicy.networking.k8s.io/api-allow-web created
>
> $ kubectl get all -l app=demo
> NAME                       READY   STATUS    RESTARTS   AGE
> pod/api-5d6f7g8h9-abc12   1/1     Running   0          20s
> pod/api-5d6f7g8h9-def34   1/1     Running   0          20s
> pod/api-5d6f7g8h9-ghi56   1/1     Running   0          20s
>
> NAME          TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
> service/api   ClusterIP   10.96.200.100   <none>        80/TCP    20s
>
> $ kubectl get hpa api
> NAME   REFERENCE         TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
> api    Deployment/api    32%/70%   3         10        3          20s
>
> $ kubectl get networkpolicy api-allow-web
> NAME            POD-SELECTOR   AGE
> api-allow-web   app=demo       20s
> ```
> **Vérification** : `kubectl get pods` montre 3 pods Running ; `kubectl get hpa` affiche l'HPA actif ; `kubectl describe networkpolicy api-allow-web` confirme que seuls les pods `tier=web` peuvent accéder au port 8080.

---

## 9) Aide-mémoire (cheat-sheet)

**Swarm**

> **Objectif** : Récapitulatif des commandes essentielles pour gérer un cluster Swarm (initialisation, services, mises à jour, stacks).
> **Pré-requis** : Docker Engine installé ; accès au nœud manager du cluster.

```bash
# Initialise un nouveau cluster Swarm (ce nœud devient manager)
docker swarm init

# Liste tous les nœuds du cluster (ID, hostname, statut, rôle)
docker node ls

# Crée un service répliqué 'web' avec 3 instances, exposé sur le port 80
docker service create --name web --replicas 3 -p 80:80 nginx

# Met à jour l'image du service 'web' vers nginx:1.27.2 (rolling update)
docker service update --image nginx:1.27.2 web

# Annule la dernière mise à jour du service 'web' (rollback)
docker service rollback web

# Déploie une stack 'app' à partir du fichier compose.yaml
docker stack deploy -c compose.yaml app

# Affiche les tâches de tous les services de la stack 'app'
docker stack ps app
```

> **Résultat attendu** :
> ```
> $ docker swarm init
> Swarm initialized: current node (abc123) is now a manager.
>
> $ docker node ls
> ID          HOSTNAME    STATUS    AVAILABILITY   MANAGER STATUS
> abc123 *    manager1    Ready     Active         Leader
>
> $ docker service ls
> ID          NAME   MODE        REPLICAS   IMAGE
> xyz789      web    replicated  3/3        nginx:latest
> ```
> **Vérification** : Chaque commande retourne un acquittement ; `docker node ls` et `docker service ls` affichent l'état attendu du cluster.

**Kubernetes**

> **Objectif** : Récapitulatif des commandes essentielles pour inspecter, déployer et gérer des applications sur Kubernetes (kubectl, Helm, Kustomize).
> **Pré-requis** : Cluster Kubernetes actif ; `kubectl` configuré avec un contexte valide ; Helm installé (pour la dernière commande).

```bash
# Liste les nœuds, pods, services et ingress du cluster (vue d'ensemble)
kubectl get nodes,pods,svc,ingress

# Affiche les logs en continu du Deployment 'api' (streaming)
kubectl logs -f deploy/api

# Affiche les détails d'un pod (événements, statut, conteneurs, volumes, etc.)
kubectl describe pod <name>

# Affiche le statut du rollout du Deployment 'api' (en cours / terminé)
kubectl rollout status deploy/api

# Met à jour l'image du conteneur 'api' dans le Deployment (par digest)
kubectl set image deploy/api api=REG/IMG@sha256:...

# Annule le dernier rollout du Deployment 'api' (restaure la révision précédente)
kubectl rollout undo deploy/api

# Applique des manifests Kustomize depuis le répertoire overlays/prod (variantes par environnement)
kubectl apply -k overlays/prod        # Kustomize

# Installe ou met à jour une release Helm 'web' à partir du chart ./chart
helm upgrade --install web ./chart     # Helm
```

> **Résultat attendu** :
> ```
> $ kubectl get nodes,pods,svc,ingress
> NAME                     STATUS   ROLES           AGE   VERSION
> node/cluster-node-1      Ready    control-plane   30d   v1.29.0
>
> NAME                         READY   STATUS    RESTARTS   AGE
> pod/api-5d6f7g8h9-abc12     1/1     Running   0          5m
> pod/web-7f8g9h0i1-jk34      1/1     Running   0          5m
>
> NAME              TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
> service/api       ClusterIP   10.96.100.50    <none>        80/TCP    5m
> service/web       ClusterIP   10.96.100.51    <none>        80/TCP    5m
>
> NAME                               CLASS   HOSTS                ADDRESS        PORTS   AGE
> ingress.networking.k8s.io/demo     nginx   demo.example.com     203.0.113.10   80      5m
>
> $ helm upgrade --install web ./chart
> Release "web" has been upgraded. Happy Helming!
> NAME: web
> STATUS: deployed
> REVISION: 3
> ```
> **Vérification** : `kubectl get pods` montre tous les pods en état `Running` ; `kubectl rollout status` confirme `successfully rolled out` ; `helm list` affiche la release avec le statut `deployed`.

---

## 10) Checklist de clôture (prêt pour l'orchestration)

**Modélisation**

* Services stateless en **Deployments**/services ; stateful en **StatefulSets** + **PVC**.
* **Digests** partout (immutabilité), **secrets** montés en fichiers.

**Réseau**

* Entrées via **Ingress/LB** ; politiques de flux (**NetworkPolicy**).
* Probes **readiness/liveness** correctes ; rolling updates testés.

**Sécurité**

* **Non-root**, capabilities minimales, FS **read-only**.
* **RBAC** par namespace, **Pod Security** baseline/restricted.
* Admission policies (Gatekeeper/Kyverno), **signatures cosign** vérifiées.

**Observabilité**

* Logs centralisés, métriques Prometheus, traces OTEL.
* Dashboards de release (blue/green/canary) et alertes SLO.

**Opérations**

* Runbooks de **rollout/rollback**, migrations **expand→migrate→contract**.
* Sauvegardes/restores des **PVC** testés.
* Pipelines CI/CD : **scan → sbom → sign → push → promote by digest**.
