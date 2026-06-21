# **Chapitre 3 — Installation et configuration de Kubernetes**

*(Outils, manifests YAML, déploiement d’applications, gestion des ressources)*

---

## **1. Objectifs d’apprentissage**

À la fin de ce chapitre, l’apprenant sera capable de :

* Installer, configurer et administrer Kubernetes dans un environnement local.
* Créer, appliquer et comprendre les **manifests YAML** (Pods, Deployments, Services).
* Gérer les ressources des conteneurs (CPU, mémoire, stockage).
* Utiliser `kubectl` pour déployer, inspecter et mettre à jour les applications.
* Étendre le projet fil rouge en déployant une **application web complète** (frontend + backend).

---

## **2. Présentation des différentes solutions d’installation**

### **2.1 Environnement local (développement)**

* **Minikube** : cluster à nœud unique, léger, parfait pour l’apprentissage.
* **Kind (Kubernetes in Docker)** : exécute un cluster Kubernetes dans des conteneurs Docker.
* **MicroK8s** : distribution légère développée par Canonical (Ubuntu).

Ces environnements sont utilisés pour les tests et la formation sans nécessiter d’infrastructure réelle.

---

### **2.2 Environnement sur site (on-premise)**

* **kubeadm** : outil officiel pour construire un cluster complet à partir de zéro.
* **Rancher** : interface graphique de gestion multi-clusters.
* **OpenShift** : distribution d’entreprise basée sur Kubernetes (Red Hat).

Ces solutions sont destinées aux serveurs physiques ou virtuels internes à une organisation.

---

### **2.3 Environnements Cloud (managés)**

* **EKS (AWS)**, **AKS (Azure)**, **GKE (Google Cloud)** : les fournisseurs gèrent le Control Plane et l’infrastructure.
* Ces solutions sont prêtes à l’emploi mais facturées à l’usage.

---

## **3. Installation des outils de base**

(Si vous avez déjà terminé le TP du Chapitre 2, votre environnement est prêt. Sinon, reprenez ces étapes.)

---

### **3.1 Docker**

Docker est le moteur de conteneurs utilisé par Kubernetes pour exécuter les Pods localement.

(Se référer au Chapitre 2 pour l’installation détaillée.)

---

### **3.2 kubectl**

```bash
kubectl config view
kubectl cluster-info
```

**Contexte :**
Ces deux commandes permettent de vérifier la configuration de votre client :

* `kubectl config view` affiche le contenu du fichier `~/.kube/config`, qui contient les informations d’accès au cluster.
* `kubectl cluster-info` affiche les adresses de l’API Server et des services système.

---

### **3.3 Minikube**

```bash
minikube delete
minikube start --driver=docker --cpus=4 --memory=8192
```

**Contexte :**

* `minikube delete` supprime tout ancien cluster local.
* `minikube start` crée un nouveau cluster dans Docker, avec 4 vCPU et 8 Go de RAM.
  Cette configuration est adaptée à la plupart des postes de développement.

---

## **4. Configuration et manipulation de base**

### **4.1 Syntaxe YAML**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: monpod
spec:
  containers:
  - name: nginx
    image: nginx:latest
    ports:
    - containerPort: 80
```

**Contexte :**
Ce fichier YAML décrit un Pod exécutant un conteneur `nginx`.
Chaque ressource Kubernetes suit cette même structure :

1. `apiVersion` indique la version de l’API utilisée.
2. `kind` définit le type d’objet (Pod, Service, Deployment…).
3. `metadata` contient les informations d’identification (nom, labels, namespace).
4. `spec` décrit le comportement attendu (conteneurs, ports, volumes…).

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
Ces objets interagissent ensemble : un Deployment crée des Pods, un Service les expose et un Ingress permet d’y accéder depuis un navigateur ou une API externe.

---

### **4.3 Commandes `kubectl` essentielles**

```bash
kubectl apply -f fichier.yaml      # Crée ou met à jour un objet
kubectl delete -f fichier.yaml     # Supprime l’objet décrit dans le YAML
kubectl get pods,svc,deploy -A     # Liste Pods, Services et Deployments dans tous les namespaces
kubectl describe pod <nom>         # Détaille un objet spécifique
kubectl logs <nom>                 # Affiche les journaux d’un conteneur
kubectl exec -it <nom> -- bash     # Ouvre un shell interactif dans un conteneur
```

**Contexte :**
Ces commandes constituent la base de l’administration quotidienne de Kubernetes.
Elles permettent de créer, inspecter, mettre à jour et dépanner des ressources à partir de fichiers YAML.

---

## **5. Gestion des ressources**

### **5.1 Allocation CPU et mémoire**

```yaml
resources:
  requests:
    cpu: "500m"
    memory: "256Mi"
  limits:
    cpu: "1"
    memory: "512Mi"
```

**Contexte :**
Chaque conteneur déclare :

* des *requests* (ressources garanties, nécessaires au démarrage)
* des *limits* (maximum autorisé)

Kubernetes planifie les Pods en fonction de ces valeurs pour éviter la surcharge.

---

### **5.2 Gestion du stockage**

* **Éphémère** : supprimé avec le Pod (utile pour le cache).
* **Persistant** : stocké via PV/PVC (bases de données, logs, fichiers permanents).

**Contexte :**
La persistance des données est cruciale pour les applications d’entreprise.
Les volumes éphémères servent surtout pour le cache ou les fichiers temporaires.

---

## **6. TP – Projet Fil Rouge (Phase 2)**

### **Déploiement d’une application web (frontend + backend simulé)**

---

### **6.1 Vérification du cluster**

```bash
minikube start --driver=docker
kubectl get nodes -o wide
kubectl get pods -A
```

**Contexte :**
Ces commandes assurent que le cluster est bien opérationnel :
le nœud `minikube` doit être dans l’état **Ready**, et les pods système doivent s’afficher en cours d’exécution.

---

### **6.2 Créer un namespace dédié**

```bash
kubectl create namespace projet-fil-rouge
kubectl config set-context --current --namespace=projet-fil-rouge
```

**Contexte :**
Les namespaces permettent d’isoler les projets et d’éviter les conflits de noms.
Le contexte est mis à jour pour que `kubectl` exécute toutes les commandes dans ce namespace par défaut.

---

### **6.3 Créer le backend (API simulée)**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
spec:
  replicas: 1
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      containers:
      - name: backend
        image: httpd:latest
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: backend
spec:
  selector:
    app: backend
  ports:
  - port: 80
    targetPort: 80
```

```bash
kubectl apply -f backend.yaml
kubectl get pods,svc
```

**Contexte :**
Ce backend simule une API à l’aide d’un serveur Apache HTTPD.
Le Service associé permet aux autres Pods (comme le frontend) d’y accéder via son nom DNS interne `backend`.

---

### **6.4 Créer le frontend (Nginx)**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
spec:
  replicas: 1
  selector:
    matchLabels:
      app: frontend
  template:
    metadata:
      labels:
        app: frontend
    spec:
      containers:
      - name: frontend
        image: nginx:latest
        ports:
        - containerPort: 80
        env:
        - name: BACKEND_URL
          value: "http://backend"
---
apiVersion: v1
kind: Service
metadata:
  name: frontend
spec:
  selector:
    app: frontend
  ports:
  - port: 80
    targetPort: 80
  type: NodePort
```

```bash
kubectl apply -f frontend.yaml
```

**Contexte :**
Le frontend affiche l’interface utilisateur.
Le Service de type `NodePort` rend l’application accessible depuis la machine hôte via un port réseau spécifique.
La variable `BACKEND_URL` permettra de pointer vers le backend HTTPD.

---

### **6.5 Exposer le frontend via Ingress**

#### **1. Activer le module Ingress**

```bash
minikube addons enable ingress
```

**Contexte :**
Le module Ingress intégré à Minikube active le contrôleur NGINX, qui joue le rôle de proxy HTTP pour router les requêtes.

---

#### **2. Créer le fichier `ingress.yaml`**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web-ingress
spec:
  rules:
  - host: local.dev
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: frontend
            port:
              number: 80
```

**Contexte :**
Cet Ingress redirige toutes les requêtes HTTP arrivant sur le domaine `local.dev` vers le Service `frontend`.
C’est le point d’entrée unique de l’application côté client.

---

#### **⚠ Prévention des conflits Ingress**

Avant d’appliquer votre Ingress, vérifiez qu’aucun autre Ingress n’utilise déjà le domaine `local.dev` :

```bash
kubectl get ingress -A
```

Si un Ingress existe déjà dans le namespace `default`, supprimez-le :

```bash
kubectl delete ingress web-ingress -n default
```

Cela évite l’erreur :

```
admission webhook "validate.nginx.ingress.kubernetes.io" denied the request:
host "local.dev" and path "/" is already defined in ingress default/web-ingress
```

Optionnellement, utilisez un domaine unique :

```yaml
- host: projet-fil-rouge.local.dev
```

et ajoutez-le à `/etc/hosts` :

```bash
echo "$(minikube ip) projet-fil-rouge.local.dev" | sudo tee -a /etc/hosts
```

---

#### **3. Configurer le nom de domaine local**

```bash
echo "$(minikube ip) local.dev" | sudo tee -a /etc/hosts
cat /etc/hosts | grep local.dev
```

**Contexte :**
Cette commande ajoute le nom `local.dev` au fichier `/etc/hosts` en le liant à l’adresse IP de Minikube.
Cela permet d’accéder à l’application via `http://local.dev` dans le navigateur.

---

#### **4. Tester l’accès via Ingress**

```bash
minikube tunnel
curl -I http://local.dev
```

**Contexte :**

* `minikube tunnel` crée un pont réseau pour exposer les Services et Ingress en dehors du cluster.
* `curl -I` vérifie la réponse HTTP.
  Si le déploiement est correct, la réponse doit contenir `HTTP/1.1 200 OK`.

---

### **6.6 Vérifier le déploiement complet**

```bash
kubectl get all -n projet-fil-rouge
kubectl describe ingress web-ingress
kubectl logs -l app=frontend
kubectl logs -l app=backend
```

**Contexte :**
Ces commandes permettent de s’assurer que tout fonctionne :

* Les Pods et Services sont actifs.
* L’Ingress est bien configuré.
* Les logs montrent la communication entre frontend et backend.

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

Le serveur NGINX démarre ses processus “workers” sans erreur : le frontend fonctionne normalement.

**Logs backend (Apache HTTPD)**

```
AH00558: httpd: Could not reliably determine the server's fully qualified domain name, using 10.244.0.10.
Set the 'ServerName' directive globally to suppress this message
[Thu Nov 06 23:03:59.643852 2025] [mpm_event:notice] [pid 1:tid 1] AH00489: Apache/2.4.65 (Unix) configured -- resuming normal operations
[Thu Nov 06 23:03:59.671509 2025] [core:notice] [pid 1:tid 1] AH00094: Command line: 'httpd -D FOREGROUND'
```

L’avertissement `ServerName` indique simplement qu’Apache ne connaît pas son nom d’hôte complet (FQDN).
Il peut être ignoré ou supprimé en ajoutant cette ligne dans la configuration du conteneur :

```yaml
command: ["httpd", "-D", "FOREGROUND", "-c", "ServerName localhost"]
```

Cela supprime le message sans affecter le fonctionnement.

---

### **6.7 Nettoyage (facultatif)**

```bash
kubectl delete namespace projet-fil-rouge
```

**Contexte :**
Supprime toutes les ressources du projet et libère la mémoire du cluster Minikube.

