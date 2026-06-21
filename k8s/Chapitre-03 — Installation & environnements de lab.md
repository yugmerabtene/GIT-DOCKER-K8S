# **Chapitre 3 — Installation et configuration de Kubernetes**

*(Outils, manifests YAML, déploiement d'applications, gestion des ressources)*

---

## **1. Objectifs d'apprentissage**

À la fin de ce chapitre, l'apprenant sera capable de :

* Installer, configurer et administrer Kubernetes dans un environnement local.
* Créer, appliquer et comprendre les **manifests YAML** (Pods, Deployments, Services).
* Gérer les ressources des conteneurs (CPU, mémoire, stockage).
* Utiliser `kubectl` pour déployer, inspecter et mettre à jour les applications.
* Étendre le projet fil rouge en déployant une **application web complète** (frontend + backend).

---

## **2. Présentation des différentes solutions d'installation**

### **2.1 Environnement local (développement)**

* **Minikube** : cluster à nœud unique, léger, parfait pour l'apprentissage.
* **Kind (Kubernetes in Docker)** : exécute un cluster Kubernetes dans des conteneurs Docker.
* **MicroK8s** : distribution légère développée par Canonical (Ubuntu).

Ces environnements sont utilisés pour les tests et la formation sans nécessiter d'infrastructure réelle.

---

### **2.2 Environnement sur site (on-premise)**

* **kubeadm** : outil officiel pour construire un cluster complet à partir de zéro.
* **Rancher** : interface graphique de gestion multi-clusters.
* **OpenShift** : distribution d'entreprise basée sur Kubernetes (Red Hat).

Ces solutions sont destinées aux serveurs physiques ou virtuels internes à une organisation.

---

### **2.3 Environnements Cloud (managés)**

* **EKS (AWS)**, **AKS (Azure)**, **GKE (Google Cloud)** : les fournisseurs gèrent le Control Plane et l'infrastructure.
* Ces solutions sont prêtes à l'emploi mais facturées à l'usage.

---

## **3. Installation des outils de base**

(Si vous avez déjà terminé le TP du Chapitre 2, votre environnement est prêt. Sinon, reprenez ces étapes.)

---

### **3.1 Docker**

Docker est le moteur de conteneurs utilisé par Kubernetes pour exécuter les Pods localement.

(Se référer au Chapitre 2 pour l'installation détaillée.)

---

### **3.2 kubectl**

> **Objectif** : Vérifier que le client kubectl est correctement configuré et connecté à un cluster Kubernetes.
> **Pre-requis** : kubectl installé, un cluster Kubernetes accessible, fichier `~/.kube/config` présent.

```bash
# Affiche le contenu complet du fichier de configuration kubectl (~/.kube/config)
# Ce fichier contient les clusters, contextes et identifiants connus du client
kubectl config view

# Affiche les adresses des services principaux du cluster (API Server, KubeDNS, etc.)
# Permet de confirmer que le client peut joindre le Control Plane
kubectl cluster-info
```

**Contexte :**
Ces deux commandes permettent de vérifier la configuration de votre client :

* `kubectl config view` affiche le contenu du fichier `~/.kube/config`, qui contient les informations d'accès au cluster.
* `kubectl cluster-info` affiche les adresses de l'API Server et des services système.

> **Résultat attendu** :
> ```
> $ kubectl config view
> apiVersion: v1
> clusters:
> - cluster:
>     certificate-authority: /home/user/.minikube/ca.crt
>     server: https://192.168.49.2:8443
>   name: minikube
> contexts:
> - context:
>     cluster: minikube
>     user: minikube
>   name: minikube
> current-context: minikube
> kind: Config
> preferences: {}
> users:
> - name: minikube
>   user:
>     client-certificate: /home/user/.minikube/profiles/minikube/client.crt
>     client-key: /home/user/.minikube/profiles/minikube/client.key
>
> $ kubectl cluster-info
> Kubernetes control plane is running at https://192.168.49.2:8443
> CoreDNS is running at https://192.168.49.2:8443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
> ```
> **Vérification** : Le `current-context` doit pointer vers votre cluster (ex: `minikube`). L'URL de l'API Server doit être affichée sans erreur de connexion.

---

### **3.3 Minikube**

> **Objectif** : Supprimer tout ancien cluster Minikube puis créer un nouveau cluster local avec des ressources adaptées au développement.
> **Pre-requis** : Minikube installé, Docker installé et running, au moins 4 vCPU et 8 Go de RAM disponibles.

```bash
# Supprime le cluster Minikube existant (pods, images, volumes) pour repartir proprement
minikube delete

# Démarre un nouveau cluster Minikube en utilisant Docker comme driver (hyperviseur)
# --cpus=4 alloue 4 processeurs virtuels au nœud unique du cluster
# --memory=8192 alloue 8 Go de mémoire RAM au nœud
minikube start --driver=docker --cpus=4 --memory=8192
```

**Contexte :**

* `minikube delete` supprime tout ancien cluster local.
* `minikube start` crée un nouveau cluster dans Docker, avec 4 vCPU et 8 Go de RAM.
  Cette configuration est adaptée à la plupart des postes de développement.

> **Résultat attendu** :
> ```
> $ minikube delete
> 🔥  Deleting "minikube" in docker ...
> 🔥  Deleting container "minikube" ...
> 🔥  Removing /home/user/.minikube/machines/minikube ...
> 💀  Removed all traces of the "minikube" cluster.
>
> $ minikube start --driver=docker --cpus=4 --memory=8192
> 😄  minikube v1.32.0 on Ubuntu 22.04
> ✨  Using the docker driver based on user configuration
> 📌  Using Docker driver with root privileges
> 👍  Starting control plane node minikube in cluster minikube
> 🚜  Pulling base image ...
> 🔥  Creating docker container (CPUs=4, Memory=8192MB) ...
> 🐳  Preparing Kubernetes v1.28.3 on Docker 24.0.7 ...
>     ▪ Generating certificates and keys ...
>     ▪ Booting up control plane ...
>     ▪ Configuring RBAC rules ...
> 🔗  Configuring bridge CNI (Container Networking Interface) ...
> ✅  Enabled addons: default-storageclass, storage-provisioner
> 🏄  Done! kubectl is now configured to use "minikube" cluster
> ```
> **Vérification** : Le message `Done!` doit s'afficher. Exécuter `kubectl get nodes` pour confirmer que le nœud est `Ready`.

---

## **4. Configuration et manipulation de base**

### **4.1 Syntaxe YAML**

> **Objectif** : Définir un Pod Kubernetes minimal exécutant un conteneur Nginx exposé sur le port 80.
> **Pre-requis** : Un cluster Kubernetes opérationnel, kubectl configuré.

```yaml
# Version de l'API Kubernetes utilisée pour cet objet
# "v1" est le groupe d'API principal (core) pour les objets de base comme les Pods
apiVersion: v1

# Type d'objet Kubernetes à créer
# "Pod" représente la plus petite unité déployable dans Kubernetes
kind: Pod

# Métadonnées : informations d'identification et d'organisation de l'objet
metadata:
  # Nom unique du Pod dans son namespace
  name: monpod

# Spécification : description du comportement attendu du Pod
spec:
  # Liste des conteneurs exécutés dans ce Pod
  containers:
  - name: nginx           # Nom du conteneur (identifiant interne)
    image: nginx:latest   # Image Docker à utiliser (dernière version de Nginx)
    ports:
    - containerPort: 80   # Port exposé par le conteneur (Nginx écoute sur 80 par défaut)
```

**Contexte :**
Ce fichier YAML décrit un Pod exécutant un conteneur `nginx`.
Chaque ressource Kubernetes suit cette même structure :

1. `apiVersion` indique la version de l'API utilisée.
2. `kind` définit le type d'objet (Pod, Service, Deployment…).
3. `metadata` contient les informations d'identification (nom, labels, namespace).
4. `spec` décrit le comportement attendu (conteneurs, ports, volumes…).

> **Résultat attendu** :
> ```
> $ kubectl apply -f pod.yaml
> pod/monpod created
>
> $ kubectl get pod monpod
> NAME     READY   STATUS    RESTARTS   AGE
> monpod   1/1     Running   0          5s
> ```
> **Vérification** : Le Pod doit être dans l'état `Running` avec `1/1` Ready. Vérifier avec `kubectl describe pod monpod`.

---

### **4.2 Les principaux objets Kubernetes**

| Objet                           | Description                                                      |
| ------------------------------- | ---------------------------------------------------------------- |
| **Pod**                         | Exécute un ou plusieurs conteneurs.                              |
| **Deployment**                  | Supervise la création, la mise à jour et la redondance des Pods. |
| **Service**                     | Expose les Pods via une IP stable.                               |
| **ConfigMap / Secret**          | Contiennent des paramètres ou des données sensibles.             |
| **PVC (PersistentVolumeClaim)** | Réserve du stockage persistant.                                  |

**Contexte :**
Ces objets interagissent ensemble : un Deployment crée des Pods, un Service les expose et un Ingress permet d'y accéder depuis un navigateur ou une API externe.

---

### **4.3 Commandes `kubectl` essentielles**

> **Objectif** : Présenter les commandes kubectl les plus utilisées pour gérer le cycle de vie des ressources Kubernetes.
> **Pre-requis** : kubectl configuré et connecté à un cluster, au moins un fichier YAML de ressource à disposition.

```bash
# Applique un manifeste YAML : crée la ressource si elle n'existe pas, la met à jour sinon (idempotent)
kubectl apply -f fichier.yaml      # Crée ou met à jour un objet

# Supprime la ressource décrite dans le fichier YAML (Pod, Service, Deployment, etc.)
kubectl delete -f fichier.yaml     # Supprime l'objet décrit dans le YAML

# Liste tous les Pods, Services et Deployments dans TOUS les namespaces du cluster
# -A est un raccourci pour --all-namespaces
kubectl get pods,svc,deploy -A     # Liste Pods, Services et Deployments dans tous les namespaces

# Affiche les détails complets d'un objet spécifique (événements, spec, status, conditions)
# Remplacer <nom> par le nom réel du Pod (ex: monpod)
kubectl describe pod <nom>         # Détaille un objet spécifique

# Affiche les logs (stdout/stderr) d'un conteneur, utile pour le débogage
# Remplacer <nom> par le nom réel du Pod
kubectl logs <nom>                 # Affiche les journaux d'un conteneur

# Ouvre un terminal interactif (bash) à l'intérieur du conteneur en cours d'exécution
# -it = interactif + tty, -- sépare les arguments kubectl de la commande à exécuter
kubectl exec -it <nom> -- bash     # Ouvre un shell interactif dans un conteneur
```

**Contexte :**
Ces commandes constituent la base de l'administration quotidienne de Kubernetes.
Elles permettent de créer, inspecter, mettre à jour et dépanner des ressources à partir de fichiers YAML.

> **Résultat attendu** :
> ```
> $ kubectl apply -f fichier.yaml
> pod/monpod created
>
> $ kubectl get pods,svc,deploy -A
> NAMESPACE     NAME                           READY   STATUS    RESTARTS   AGE
> kube-system   pod/coredns-5dd5756b68-abcde   1/1     Running   0          10m
> default       pod/monpod                     1/1     Running   0          30s
>
> NAMESPACE   NAME                 TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
> default     service/kubernetes   ClusterIP   10.96.0.1    <none>        443/TCP   10m
>
> $ kubectl describe pod monpod
> Name:         monpod
> Namespace:    default
> Status:       Running
> IP:           10.244.0.5
> Containers:
>   nginx:
>     Image:          nginx:latest
>     Port:           80/TCP
>     State:          Running
>
> $ kubectl exec -it monpod -- bash
> root@monpod:/#
> ```
> **Vérification** : `apply` doit retourner `created` ou `configured`. `get -A` liste toutes les ressources. `describe` affiche les détails complets. `exec` ouvre un shell dans le conteneur.

---

## **5. Gestion des ressources**

### **5.1 Allocation CPU et mémoire**

> **Objectif** : Définir les limites et requêtes de ressources (CPU et mémoire) pour un conteneur, afin que le scheduler Kubernetes puisse planifier correctement les Pods.
> **Pre-requis** : Un manifeste de Pod ou Deployment existant dans lequel insérer cette section `resources`.

```yaml
# Section "resources" à placer dans la spec d'un conteneur
resources:
  # Requêtes minimales : ressources garanties au conteneur
  # Le scheduler utilise ces valeurs pour décider sur quel nœud placer le Pod
  requests:
    cpu: "500m"       # 500 milliCPU = 0.5 cœur de processeur garanti
    memory: "256Mi"   # 256 Mebibytes de RAM garantis au démarrage
  # Limites maximales : plafond de ressources que le conteneur ne peut pas dépasser
  # Si le conteneur dépasse la limite CPU, il sera throttled (ralenti)
  # Si le conteneur dépasse la limite mémoire, il sera tué (OOMKilled)
  limits:
    cpu: "1"          # 1 cœur de processeur maximum
    memory: "512Mi"   # 512 Mebibytes de RAM maximum
```

**Contexte :**
Chaque conteneur déclare :

* des *requests* (ressources garanties, nécessaires au démarrage)
* des *limits* (maximum autorisé)

Kubernetes planifie les Pods en fonction de ces valeurs pour éviter la surcharge.

> **Résultat attendu** :
> ```
> $ kubectl describe pod monpod
> ...
> Containers:
>   nginx:
>     Limits:
>       cpu:     1
>       memory:  512Mi
>     Requests:
>       cpu:     500m
>       memory:  256Mi
> ```
> **Vérification** : `kubectl describe pod` doit afficher les sections `Limits` et `Requests` avec les valeurs définies. Le Pod doit démarrer sans être évincé (evicted).

---

### **5.2 Gestion du stockage**

* **Éphémère** : supprimé avec le Pod (utile pour le cache).
* **Persistant** : stocké via PV/PVC (bases de données, logs, fichiers permanents).

**Contexte :**
La persistance des données est cruciale pour les applications d'entreprise.
Les volumes éphémères servent surtout pour le cache ou les fichiers temporaires.

---

## **6. TP – Projet Fil Rouge (Phase 2)**

### **Déploiement d'une application web (frontend + backend simulé)**

---

### **6.1 Vérification du cluster**

> **Objectif** : S'assurer que le cluster Minikube est opérationnel avant de déployer l'application.
> **Pre-requis** : Minikube installé, Docker running.

```bash
# Démarre (ou redémarre) le cluster Minikube avec le driver Docker
# Si le cluster existe déjà, cette commande le reconnecte simplement
minikube start --driver=docker

# Affiche la liste des nœuds du cluster avec leurs adresses IP et versions
# -o wide fournit des colonnes supplémentaires (IP interne, version OS, runtime)
kubectl get nodes -o wide

# Liste tous les Pods système dans tous les namespaces
# Les pods système (CoreDNS, kube-proxy, etc.) doivent être en état Running
kubectl get pods -A
```

**Contexte :**
Ces commandes assurent que le cluster est bien opérationnel :
le nœud `minikube` doit être dans l'état **Ready**, et les pods système doivent s'afficher en cours d'exécution.

> **Résultat attendu** :
> ```
> $ minikube start --driver=docker
> 😄  minikube v1.32.0 on Ubuntu 22.04
> 🏄  kubectl is now configured to use "minikube" cluster
>
> $ kubectl get nodes -o wide
> NAME       STATUS   ROLES           AGE   VERSION   INTERNAL-IP    EXTERNAL-IP   OS-IMAGE             KERNEL-VERSION     CONTAINER-RUNTIME
> minikube   Ready    control-plane   45s   v1.28.3   192.168.49.2   <none>        Ubuntu 22.04.3 LTS   5.15.0-91-generic   docker://24.0.7
>
> $ kubectl get pods -A
> NAMESPACE     NAME                               READY   STATUS    RESTARTS   AGE
> kube-system   coredns-5dd5756b68-abcde           1/1     Running   0          45s
> kube-system   etcd-minikube                      1/1     Running   0          50s
> kube-system   kube-apiserver-minikube            1/1     Running   0          50s
> kube-system   kube-controller-manager-minikube   1/1     Running   0          50s
> kube-system   kube-proxy-xyz12                   1/1     Running   0          45s
> kube-system   kube-scheduler-minikube            1/1     Running   0          50s
> kube-system   storage-provisioner                1/1     Running   0          50s
> ```
> **Vérification** : Le nœud `minikube` doit afficher `Ready` dans la colonne STATUS. Tous les pods système doivent être `Running` avec `1/1` Ready.

---

### **6.2 Créer un namespace dédié**

> **Objectif** : Créer un namespace isolé pour le projet fil rouge et configurer kubectl pour l'utiliser par défaut.
> **Pre-requis** : Cluster Minikube opérationnel, kubectl configuré.

```bash
# Crée un nouveau namespace "projet-fil-rouge" pour isoler les ressources du projet
# Les namespaces permettent d'éviter les conflits de noms entre différents projets
kubectl create namespace projet-fil-rouge

# Met à jour le contexte courant pour utiliser ce namespace par défaut
# Toutes les commandes kubectl suivantes s'exécuteront dans ce namespace
# sans avoir à spécifier -n projet-fil-rouge à chaque fois
kubectl config set-context --current --namespace=projet-fil-rouge
```

**Contexte :**
Les namespaces permettent d'isoler les projets et d'éviter les conflits de noms.
Le contexte est mis à jour pour que `kubectl` exécute toutes les commandes dans ce namespace par défaut.

> **Résultat attendu** :
> ```
> $ kubectl create namespace projet-fil-rouge
> namespace/projet-fil-rouge created
>
> $ kubectl config set-context --current --namespace=projet-fil-rouge
> Context "minikube" modified.
> ```
> **Vérification** : Exécuter `kubectl config view --minify | grep namespace` pour confirmer que le namespace courant est `projet-fil-rouge`.

---

### **6.3 Créer le backend (API simulée)**

> **Objectif** : Déployer un backend simulé (serveur Apache HTTPD) avec un Service pour le rendre accessible aux autres Pods du cluster via le nom DNS `backend`.
> **Pre-requis** : Namespace `projet-fil-rouge` créé et sélectionné comme contexte courant.

```yaml
# --- PREMIER OBJET : Deployment pour le backend ---
# Version de l'API pour les Deployments (groupe apps)
apiVersion: apps/v1

# Type : Deployment — gère la création et la redondance des Pods
kind: Deployment

# Métadonnées du Deployment
metadata:
  name: backend  # Nom du Deployment (utilisé pour kubectl get deployment backend)

# Spécification du Deployment
spec:
  # Nombre de répliques (Pods) à maintenir en permanence
  replicas: 1  # Un seul Pod backend pour ce TP

  # Sélecteur : définit comment le Deployment identifie les Pods qu'il gère
  selector:
    matchLabels:
      app: backend  # Le Deployment gère tous les Pods portant le label "app: backend"

  # Template : modèle de Pod à créer pour chaque réplica
  template:
    metadata:
      labels:
        app: backend  # Label appliqué à chaque Pod créé (doit correspondre au selector)
    spec:
      containers:
      - name: backend          # Nom du conteneur
        image: httpd:latest    # Image Apache HTTPD (sert de backend simulé)
        ports:
        - containerPort: 80    # Port d'écoute du conteneur (HTTP par défaut)

---
# --- DEUXIÈME OBJET : Service pour exposer le backend ---
# Version de l'API core (v1) pour les Services
apiVersion: v1

# Type : Service — expose les Pods via une IP stable et un nom DNS
kind: Service

# Métadonnées du Service
metadata:
  name: backend  # Nom du Service — sera accessible via "backend" en DNS interne

# Spécification du Service
spec:
  # Sélecteur : le Service route le trafic vers les Pods portant ce label
  selector:
    app: backend  # Cible tous les Pods avec label "app: backend"

  # Définition des ports exposés par le Service
  ports:
  - port: 80         # Port exposé par le Service (accessible aux autres Pods)
    targetPort: 80   # Port cible sur le Pod (doit correspondre au containerPort)
```

```bash
# Applique le fichier backend.yaml : crée le Deployment et le Service en une seule commande
kubectl apply -f backend.yaml

# Affiche les Pods et Services du namespace courant pour vérifier le déploiement
kubectl get pods,svc
```

**Contexte :**
Ce backend simule une API à l'aide d'un serveur Apache HTTPD.
Le Service associé permet aux autres Pods (comme le frontend) d'y accéder via son nom DNS interne `backend`.

> **Résultat attendu** :
> ```
> $ kubectl apply -f backend.yaml
> deployment.apps/backend created
> service/backend created
>
> $ kubectl get pods,svc
> NAME                           READY   STATUS    RESTARTS   AGE
> pod/backend-7f8b9c6d5-abc12   1/1     Running   0          10s
>
> NAME              TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
> service/backend   ClusterIP   10.105.42.100   <none>        80/TCP    10s
> ```
> **Vérification** : Le Pod backend doit être `Running` avec `1/1` Ready. Le Service backend doit avoir une ClusterIP assignée. Tester avec `kubectl exec -it <pod-frontend> -- curl http://backend`.

---

### **6.4 Créer le frontend (Nginx)**

> **Objectif** : Déployer le frontend Nginx avec un Service de type NodePort pour le rendre accessible depuis la machine hôte, et configurer la variable d'environnement pointant vers le backend.
> **Pre-requis** : Backend déployé et accessible (Service `backend` opérationnel), namespace `projet-fil-rouge` actif.

```yaml
# --- PREMIER OBJET : Deployment pour le frontend ---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend  # Nom du Deployment frontend
spec:
  replicas: 1  # Un seul Pod frontend
  selector:
    matchLabels:
      app: frontend  # Le Deployment gère les Pods avec label "app: frontend"
  template:
    metadata:
      labels:
        app: frontend  # Label appliqué à chaque Pod frontend
    spec:
      containers:
      - name: frontend          # Nom du conteneur
        image: nginx:latest     # Image Nginx comme serveur frontend
        ports:
        - containerPort: 80     # Port d'écoute Nginx
        env:
        # Variable d'environnement injectée dans le conteneur
        # Permet au frontend de connaître l'URL du backend
        - name: BACKEND_URL
          value: "http://backend"  # URL interne du Service backend (résolution DNS Kubernetes)

---
# --- DEUXIÈME OBJET : Service pour exposer le frontend ---
apiVersion: v1
kind: Service
metadata:
  name: frontend  # Nom du Service frontend
spec:
  selector:
    app: frontend  # Route le trafic vers les Pods "app: frontend"
  ports:
  - port: 80         # Port du Service
    targetPort: 80   # Port du conteneur cible
  # Type NodePort : expose le Service sur un port statique de chaque nœud du cluster
  # Accessible depuis la machine hôte via <IP-nœud>:<NodePort>
  type: NodePort
```

```bash
# Applique le fichier frontend.yaml : crée le Deployment et le Service frontend
kubectl apply -f frontend.yaml
```

**Contexte :**
Le frontend affiche l'interface utilisateur.
Le Service de type `NodePort` rend l'application accessible depuis la machine hôte via un port réseau spécifique.
La variable `BACKEND_URL` permettra de pointer vers le backend HTTPD.

> **Résultat attendu** :
> ```
> $ kubectl apply -f frontend.yaml
> deployment.apps/frontend created
> service/frontend created
>
> $ kubectl get pods,svc
> NAME                            READY   STATUS    RESTARTS   AGE
> pod/backend-7f8b9c6d5-abc12    1/1     Running   0          5m
> pod/frontend-5d4c8b7e9-xyz34   1/1     Running   0          8s
>
> NAME                TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
> service/backend     ClusterIP   10.105.42.100   <none>        80/TCP         5m
> service/frontend    NodePort    10.105.88.200   <none>        80:31234/TCP   8s
> ```
> **Vérifier** : Le Pod frontend doit être `Running`. Le Service frontend doit afficher un port `NodePort` (ex: `80:31234/TCP`). Accéder via `minikube service frontend` pour tester.

---

### **6.5 Exposer le frontend via Ingress**

#### **1. Activer le module Ingress**

> **Objectif** : Activer le contrôleur Ingress NGINX intégré à Minikube pour permettre le routage HTTP basé sur le nom de domaine.
> **Pre-requis** : Cluster Minikube en cours d'exécution.

```bash
# Active l'addon Ingress dans Minikube (déploie le contrôleur NGINX Ingress)
# Ce contrôleur écoute sur les ports 80/443 du nœud et route selon les règles Ingress
minikube addons enable ingress
```

**Contexte :**
Le module Ingress intégré à Minikube active le contrôleur NGINX, qui joue le rôle de proxy HTTP pour router les requêtes.

> **Résultat attendu** :
> ```
> $ minikube addons enable ingress
> 💡  ingress is an addon maintained by Kubernetes.
>     ▪ Generating certificates and keys ...
> 💡  Kubelet needs the "kubelet" addon to be enabled.
> 🌟  The 'ingress' addon is enabled
> ```
> **Vérification** : Exécuter `kubectl get pods -n ingress-nginx` — le pod `ingress-nginx-controller` doit être `Running`.

---

#### **2. Créer le fichier `ingress.yaml`**

> **Objectif** : Créer une règle Ingress qui route toutes les requêtes HTTP vers le domaine `local.dev` vers le Service frontend sur le port 80.
> **Pre-requis** : Addon Ingress activé, Service `frontend` déployé et opérationnel.

```yaml
# Version de l'API pour les ressources Ingress (groupe networking.k8s.io)
apiVersion: networking.k8s.io/v1

# Type : Ingress — définit des règles de routage HTTP(S) vers les Services
kind: Ingress

# Métadonnées de la ressource Ingress
metadata:
  name: web-ingress  # Nom de la règle Ingress

# Spécification des règles de routage
spec:
  rules:
  # Règle appliquée aux requêtes arrivant sur ce domaine
  - host: local.dev
    http:
      paths:
      # Route pour tous les chemins commençant par "/"
      - path: /
        # PathType: Prefix — correspond à tous les chemins commençant par "/"
        pathType: Prefix
        backend:
          service:
            name: frontend  # Nom du Service cible (le frontend Nginx)
            port:
              number: 80    # Port du Service cible
```

**Contexte :**
Cet Ingress redirige toutes les requêtes HTTP arrivant sur le domaine `local.dev` vers le Service `frontend`.
C'est le point d'entrée unique de l'application côté client.

> **Résultat attendu** :
> ```
> $ kubectl apply -f ingress.yaml
> ingress.networking.k8s.io/web-ingress created
>
> $ kubectl get ingress
> NAME          CLASS    HOSTS        ADDRESS          PORTS   AGE
> web-ingress   nginx    local.dev    192.168.49.2     80      5s
> ```
> **Vérification** : L'Ingress doit afficher une adresse IP dans la colonne ADDRESS (celle du contrôleur Ingress). Le HOST doit être `local.dev`.

---

#### **⚠ Prévention des conflits Ingress**

Avant d'appliquer votre Ingress, vérifiez qu'aucun autre Ingress n'utilise déjà le domaine `local.dev` :

> **Objectif** : Vérifier qu'aucun Ingress existant n'utilise déjà le domaine `local.dev` pour éviter un conflit de routage.
> **Pre-requis** : kubectl configuré, cluster en cours d'exécution.

```bash
# Liste tous les Ingress dans tous les namespaces pour détecter d'éventuels conflits
kubectl get ingress -A
```

> **Résultat attendu** :
> ```
> $ kubectl get ingress -A
> NAMESPACE            NAME          CLASS    HOSTS        ADDRESS          PORTS   AGE
> projet-fil-rouge     web-ingress   nginx    local.dev    192.168.49.2     80      10s
> ```
> **Vérification** : Si une entrée existe dans le namespace `default` avec le même host `local.dev`, il faut la supprimer.

Si un Ingress existe déjà dans le namespace `default`, supprimez-le :

> **Objectif** : Supprimer un Ingress conflictuel dans le namespace `default` qui utilise le même domaine `local.dev`.
> **Pre-requis** : Un Ingress `web-ingress` existant dans le namespace `default` avec le host `local.dev`.

```bash
# Supprime l'Ingress conflictuel dans le namespace default
# Nécessaire car deux Ingress ne peuvent pas partager le même host+path
kubectl delete ingress web-ingress -n default
```

> **Résultat attendu** :
> ```
> $ kubectl delete ingress web-ingress -n default
> ingress.networking.k8s.io "web-ingress" deleted
> ```
> **Vérification** : Relancer `kubectl get ingress -A` pour confirmer que seul votre Ingress dans `projet-fil-rouge` subsiste.

Cela évite l'erreur :

```
admission webhook "validate.nginx.ingress.kubernetes.io" denied the request:
host "local.dev" and path "/" is already defined in ingress default/web-ingress
```

Optionnellement, utilisez un domaine unique :

```yaml
# Utiliser un sous-domaine unique pour éviter tout conflit avec d'autres projets
- host: projet-fil-rouge.local.dev
```

et ajoutez-le à `/etc/hosts` :

> **Objectif** : Ajouter la résolution DNS du sous-domaine personnalisé vers l'IP de Minikube dans le fichier hosts local.
> **Pre-requis** : Minikube en cours d'exécution, droits sudo pour modifier `/etc/hosts`.

```bash
# Récupère l'IP de Minikube et l'ajoute au fichier /etc/hosts avec le nom de domaine
# "tee -a" ajoute la ligne sans écraser le fichier existant
# sudo est nécessaire car /etc/hosts est protégé en écriture root
echo "$(minikube ip) projet-fil-rouge.local.dev" | sudo tee -a /etc/hosts
```

> **Résultat attendu** :
> ```
> $ echo "$(minikube ip) projet-fil-rouge.local.dev" | sudo tee -a /etc/hosts
> 192.168.49.2 projet-fil-rouge.local.dev
> ```
> **Vérification** : Exécuter `ping -c 1 projet-fil-rouge.local.dev` pour confirmer que le domaine résout vers l'IP de Minikube.

---

#### **3. Configurer le nom de domaine local**

> **Objectif** : Ajouter une entrée dans `/etc/hosts` pour que le domaine `local.dev` pointe vers l'IP du cluster Minikube, permettant l'accès via le navigateur.
> **Pre-requis** : Minikube en cours d'exécution, droits sudo pour modifier `/etc/hosts`.

```bash
# Récupère dynamiquement l'IP de Minikube et l'associe au domaine "local.dev"
# dans le fichier /etc/hosts du système hôte
echo "$(minikube ip) local.dev" | sudo tee -a /etc/hosts

# Vérifie que l'entrée a bien été ajoutée au fichier hosts
cat /etc/hosts | grep local.dev
```

**Contexte :**
Cette commande ajoute le nom `local.dev` au fichier `/etc/hosts` en le liant à l'adresse IP de Minikube.
Cela permet d'accéder à l'application via `http://local.dev` dans le navigateur.

> **Résultat attendu** :
> ```
> $ echo "$(minikube ip) local.dev" | sudo tee -a /etc/hosts
> 192.168.49.2 local.dev
>
> $ cat /etc/hosts | grep local.dev
> 192.168.49.2 local.dev
> ```
> **Vérification** : La ligne `192.168.49.2 local.dev` doit apparaître. Tester avec `ping -c 1 local.dev` qui doit résoudre vers `192.168.49.2`.

---

#### **4. Tester l'accès via Ingress**

> **Objectif** : Créer un tunnel réseau vers Minikube et vérifier que l'application est accessible via le domaine `local.dev` et le contrôleur Ingress.
> **Pre-requis** : Ingress configuré, `/etc/hosts` configuré, addon Ingress activé.

```bash
# Crée un tunnel réseau entre la machine hôte et le cluster Minikube
# Expose les Services LoadBalancer et Ingress sur les ports de la machine hôte
# Cette commande reste active (bloquante) — ouvrir dans un terminal dédié
minikube tunnel

# Envoie une requête HTTP HEAD au domaine local.dev pour vérifier la réponse
# -I récupère uniquement les en-têtes HTTP (sans le corps de la réponse)
# Un code 200 OK confirme que l'Ingress route correctement vers le frontend
curl -I http://local.dev
```

**Contexte :**

* `minikube tunnel` crée un pont réseau pour exposer les Services et Ingress en dehors du cluster.
* `curl -I` vérifie la réponse HTTP.
  Si le déploiement est correct, la réponse doit contenir `HTTP/1.1 200 OK`.

> **Résultat attendu** :
> ```
> $ minikube tunnel
> ✅  Tunnel successfully started
> 📌  NOTE : Please do not close this terminal.
>
> $ curl -I http://local.dev
> HTTP/1.1 200 OK
> Date: Thu, 06 Nov 2025 23:10:00 GMT
> Server: nginx/1.29.3
> Content-Type: text/html
> Last-Modified: Thu, 06 Nov 2025 22:00:00 GMT
> ETag: "672b8a00-267"
> Accept-Ranges: bytes
> ```
> **Vérification** : Le code de réponse doit être `200 OK`. Le header `Server` doit indiquer `nginx`. Si le tunnel n'est pas actif, la connexion sera refusée.

---

### **6.6 Vérifier le déploiement complet**

> **Objectif** : Effectuer une vérification complète de tous les composants déployés (Pods, Services, Ingress, logs) pour s'assurer que l'application fonctionne correctement.
> **Pre-requis** : Tous les composants (backend, frontend, Ingress) déployés, tunnel Minikube actif.

```bash
# Affiche toutes les ressources (Pods, Services, Deployments, ReplicaSets) du namespace
# Permet une vue d'ensemble rapide de l'état du déploiement
kubectl get all -n projet-fil-rouge

# Affiche les détails de la ressource Ingress (règles, backend, état, adresse)
# Utile pour vérifier que le contrôleur Ingress a bien pris en compte la règle
kubectl describe ingress web-ingress

# Affiche les logs de tous les Pods portant le label "app: frontend"
# -l (label selector) cible tous les Pods correspondants
kubectl logs -l app=frontend

# Affiche les logs de tous les Pods portant le label "app: backend"
kubectl logs -l app=backend
```

**Contexte :**
Ces commandes permettent de s'assurer que tout fonctionne :

* Les Pods et Services sont actifs.
* L'Ingress est bien configuré.
* Les logs montrent la communication entre frontend et backend.

> **Résultat attendu** :
> ```
> $ kubectl get all -n projet-fil-rouge
> NAME                            READY   STATUS    RESTARTS   AGE
> pod/backend-7f8b9c6d5-abc12    1/1     Running   0          15m
> pod/frontend-5d4c8b7e9-xyz34   1/1     Running   0          10m
>
> NAME                TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
> service/backend     ClusterIP   10.105.42.100   <none>        80/TCP         15m
> service/frontend    NodePort    10.105.88.200   <none>        80:31234/TCP   10m
>
> NAME                       READY   UP-TO-DATE   AVAILABLE   AGE
> deployment.apps/backend    1/1     1            1           15m
> deployment.apps/frontend   1/1     1            1           10m
>
> $ kubectl describe ingress web-ingress
> Name:             web-ingress
> Namespace:        projet-fil-rouge
> Address:          192.168.49.2
> Rules:
>   Host        Path  Backends
>   ----        ----  --------
>   local.dev
>               /   frontend:80 (10.244.0.5:80)
>
> $ kubectl logs -l app=frontend
> 2025/11/06 23:06:10 [notice] 1#1: nginx/1.29.3
> ...
>
> $ kubectl logs -l app=backend
> AH00489: Apache/2.4.65 (Unix) configured -- resuming normal operations
> ...
> ```
> **Vérification** : Tous les Pods doivent être `Running` avec `1/1` Ready. L'Ingress doit afficher le backend `frontend:80` avec une IP de Pod. Les logs ne doivent pas contenir d'erreurs critiques.

---

#### **Analyse des logs**

**Logs frontend (NGINX)**

```
2025/11/06 23:06:10 [notice] 1#1: using the "epoll" event method
2025/11/06 23:06:10 [notice] 1#1: nginx/1.29.3
2025/11/06 23:06:10 [notice] 1#1: start worker processes
2025/11/06 23:06:10 [notice] 1#1: start worker process 28
2025/11/06 23:06:10 [notice] 1#1: start worker process 29
```

Le serveur NGINX démarre ses processus "workers" sans erreur : le frontend fonctionne normalement.

**Logs backend (Apache HTTPD)**

```
AH00558: httpd: Could not reliably determine the server's fully qualified domain name, using 10.244.0.10.
Set the 'ServerName' directive globally to suppress this message
[Thu Nov 06 23:03:59.643852 2025] [mpm_event:notice] [pid 1:tid 1] AH00489: Apache/2.4.65 (Unix) configured -- resuming normal operations
[Thu Nov 06 23:03:59.671509 2025] [core:notice] [pid 1:tid 1] AH00094: Command line: 'httpd -D FOREGROUND'
```

L'avertissement `ServerName` indique simplement qu'Apache ne connaît pas son nom d'hôte complet (FQDN).
Il peut être ignoré ou supprimé en ajoutant cette ligne dans la configuration du conteneur :

> **Objectif** : Supprimer l'avertissement Apache `ServerName` en ajoutant un paramètre de configuration directement dans la spec du conteneur.
> **Pre-requis** : Manifeste YAML du backend existant, prêt à être modifié.

```yaml
# Remplace la commande par défaut du conteneur httpd
# Ajoute l'option "-c ServerName localhost" pour définir le nom de serveur
# et supprimer l'avertissement AH00558 au démarrage
command: ["httpd", "-D", "FOREGROUND", "-c", "ServerName localhost"]
```

> **Résultat attendu** :
> ```
> $ kubectl logs -l app=backend
> [Thu Nov 06 23:15:00.000000 2025] [mpm_event:notice] [pid 1:tid 1] AH00489: Apache/2.4.65 (Unix) configured -- resuming normal operations
> [Thu Nov 06 23:15:00.000000 2025] [core:notice] [pid 1:tid 1] AH00094: Command line: 'httpd -D FOREGROUND -c ServerName localhost'
> ```
> **Vérification** : L'avertissement `AH00558: Could not reliably determine the server's fully qualified domain name` ne doit plus apparaître dans les logs.

Cela supprime le message sans affecter le fonctionnement.

---

### **6.7 Nettoyage (facultatif)**

> **Objectif** : Supprimer toutes les ressources du projet fil rouge en une seule commande en supprimant le namespace entier.
> **Pre-requis** : Avoir terminé les tests et validations du TP.

```bash
# Supprime le namespace "projet-fil-rouge" et TOUTES les ressources qu'il contient
# (Pods, Deployments, Services, Ingress, ConfigMaps, etc.)
# C'est la méthode la plus propre pour un nettoyage complet
kubectl delete namespace projet-fil-rouge
```

**Contexte :**
Supprime toutes les ressources du projet et libère la mémoire du cluster Minikube.

> **Résultat attendu** :
> ```
> $ kubectl delete namespace projet-fil-rouge
> namespace "projet-fil-rouge" deleted
> ```
> **Vérification** : Exécuter `kubectl get namespaces` pour confirmer que `projet-fil-rouge` n'apparaît plus. Exécuter `kubectl get all -A` pour vérifier qu'aucune ressource orpheline ne subsiste.
