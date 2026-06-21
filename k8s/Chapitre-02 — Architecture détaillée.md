# **Chapitre 2 — Architecture de Kubernetes**

*(Control Plane, Nœuds, Réseau, Stockage, Sécurité, Diagnostic)*

---

## **1. Objectifs d’apprentissage**

À la fin de ce chapitre, vous serez capable de :

* Expliquer l’**architecture interne** de Kubernetes (Control Plane et Nœuds).
* Identifier les **composants clés** du cluster et leur rôle.
* Diagnostiquer le **fonctionnement global** du système à l’aide de `kubectl`.
* Comprendre les **flux internes de communication et de sécurité**.
* Mettre en place un **cluster local complet** pour le projet fil rouge.

---

## **2. Vue d’ensemble de l’architecture Kubernetes**

Kubernetes est une plateforme **distribuée** composée de deux ensembles logiques :

1. **Le Control Plane**
   Regroupe les composants responsables de l’**API**, du **stockage d’état**, de la **réconciliation** et de l’**ordonnancement** :

   * **kube-apiserver** : point d’entrée unique. Valide les requêtes, applique AuthN/AuthZ/Admission, et persiste/lit l’état.
   * **etcd** : base **clé/valeur** distribuée (consensus **Raft**) stockant l’état source de vérité.
   * **kube-controller-manager** : exécute des **boucles de contrôle** assurant la convergence vers l’état souhaité (Deployments, Nodes, Jobs, GC…).
   * **kube-scheduler** : **assigne** chaque Pod en attente à un nœud selon ressources et contraintes.

2. **Les Nœuds (Workers)**
   Exécutent les **Pods** et hébergent :

   * **kubelet** : agent local qui reçoit les ordres du Control Plane et orchestre les conteneurs.
   * **Container Runtime** (via **CRI**, ex. containerd/CRI-O) : crée et détruit les conteneurs.
   * **kube-proxy** : programme les règles **L4** (iptables/IPVS) pour la translation des Services.
   * **CNI** : plugin réseau (Calico, Cilium, Flannel, Weave) qui attache des interfaces et attribue des IP aux Pods.

### **Flux internes (schéma mental)**

```
[kubectl/clients] → (TLS, AuthN/AuthZ/Admission) → [kube-apiserver] ↔ [etcd]
                                        │                  ▲   watch
                              controllers/scheduler  ──────┘
                                        │
                                    [kubelet] → (CRI) → [runtime] → containers
                                        │
                                       (CNI) réseau Pod↔Pod, (kube-proxy) Services
```

Points clés :

* **Modèle déclaratif** : on publie un état souhaité (YAML). Les contrôleurs assurent la convergence.
* **Découplage fort** : API centrale, nœuds remplaçables, Pods éphémères.
* **Observabilité** : tout passe par l’API → **events**, **logs**, **metrics**.

---

## **3. Control Plane : les composants principaux**

### **3.1 etcd — base clé/valeur (consensus Raft)**

* **Rôle** : stocke l’état complet du cluster (objets API sérialisés).
* **Ports** : 2379 (client API server), 2380 (peer cluster).
* **Quorum** : nombre impair (3/5). Perte de quorum → **écritures impossibles**.
* **Maintenance** : compaction, **defrag**, **sauvegardes régulières**.

Fichiers :

* `/etc/kubernetes/manifests/etcd.yaml`
* `/var/lib/etcd`

Commandes :

```bash
export ETCDCTL_API=3
etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint health
```

---

### **3.2 kube-apiserver — cœur de Kubernetes**

* **Rôle** : reçoit/valide chaque requête, applique **AuthN → AuthZ → Admission**, lit/écrit dans etcd.
* **Extensibilité** : CRDs, API Aggregation.
* **Audit** : via `--audit-policy-file` et `--audit-log-path`.

Exemples :

```bash
kubectl cluster-info
kubectl -n kube-system get pods -l component=kube-apiserver -o wide
```

---

### **3.3 kube-controller-manager — boucles de réconciliation**

* Orchestre les contrôleurs (Deployment → ReplicaSet → Pods, Node, Service, Job…).
* **Leader Election** : un actif, les autres en attente.

---

### **3.4 kube-scheduler — placement des Pods**

* **Rôle** : choisit un nœud pour chaque Pod en `Pending`.
* **Étapes** : filtrage → notation → binding.

---

## **4. Nœuds et exécution des conteneurs**

### **4.1 kubelet — agent du nœud**

* Enregistre le nœud, applique les PodSpecs, gère les probes.
* Diagnostic :

```bash
systemctl status kubelet
kubectl get nodes -o wide
kubectl describe node <node_name>
```

---

### **4.2 Container Runtime — containerd / CRI-O**

* Gère images, conteneurs, journaux.
* Outils : `crictl`, `ctr`.

---

### **4.3 CNI — réseau des Pods**

* Attribue IP, routes, isolation.
* Plugins : Flannel, Calico, Cilium, Weave.

---

### **4.4 kube-proxy — routage des Services**

* Configure la translation L4 (VIP → Endpoints).
* Modes : `iptables` ou `ipvs`.

---

## **5. Sécurité et flux AAA**

Toute requête au `kube-apiserver` passe par :

1. **Authentification (AuthN)** : certificats X.509, tokens JWT, OIDC.
2. **Autorisation (AuthZ)** : RBAC, Node, Webhook.
3. **Admission** : plugins (Mutating/Validating).

Exemple :

```bash
kubectl auth can-i get pods --as=system:serviceaccount:default:viewer -n demo
```

---

## **6. TP – Projet Fil Rouge (Phase 1)**

### **Objectif**

Installer un environnement Kubernetes local complet : Docker + Minikube + kubectl.

---

### **6.1 Prérequis**

| Élément  | Description                           | Détails           |
| -------- | ------------------------------------- | ----------------- |
| OS       | Windows 10/11 (WSL2) ou Ubuntu/Debian | Mode admin requis |
| CPU      | 4 cœurs min.                          | 8 recommandés     |
| RAM      | 8 Go min.                             | 16 Go recommandés |
| Stockage | 25 Go libres                          | SSD recommandé    |
| Internet | Connexion stable                      | —                 |

---

### **6.2 Étape 1 — Installer Docker**

#### **Sous Linux**

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install apt-transport-https ca-certificates curl software-properties-common -y
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io -y
sudo systemctl enable docker && sudo systemctl start docker
docker --version
```

#### **Sous Windows**

Télécharger **Docker Desktop**, installer, activer **WSL2**, vérifier :

```powershell
docker version
```

---

### ⚠️ **Dépannage Docker/Minikube – Permissions et erreurs courantes**

Les utilisateurs Linux peuvent rencontrer ces erreurs :

#### **1️⃣ Erreur :**

```
DRV_AS_ROOT : Le pilote "docker" ne doit pas être utilisé avec les privilèges root.
```

**Cause** : tu as lancé Minikube avec `sudo`.
**Solution** : exécute `minikube start` en tant qu’utilisateur normal (non root).

---

#### **2️⃣ Erreur :**

```
permission denied while trying to connect to the Docker daemon socket
```

**Cause** : ton utilisateur n’a pas accès au daemon Docker.
**Solution :**

```bash
sudo usermod -aG docker $USER
newgrp docker
```

Puis :

```bash
docker ps
minikube start --driver=docker
```

---

#### **3️⃣ Erreur :**

```
PROVIDER_DOCKER_NEWGRP : permission denied while trying to connect to the Docker daemon socket
```

**Cause** : la modification de groupe n’est pas prise en compte.
**Solution** : déconnecte-toi ou exécute `newgrp docker` avant de relancer Minikube.

---

#### **4️⃣ Erreur :**

```
DRV_NOT_HEALTHY : aucun pilote en fonctionnement
```

**Cause** : Docker n’est pas actif.
**Solution :**

```bash
sudo systemctl restart docker
minikube delete --all
minikube start --driver=docker
```

---

Une fois ces correctifs appliqués, vérifie :

```bash
minikube status
kubectl get nodes
```

---

### **6.3 Étape 2 — Installer kubectl**

#### **Sous Linux**

```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/
kubectl version --client
```

#### **Sous Windows**

```powershell
choco install kubernetes-cli -y
kubectl version --client
```

---

### **6.4 Étape 3 — Installer Minikube**

**Linux :**

```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
```

**Windows :**

```powershell
choco install minikube -y
```

---

### **6.5 Étape 4 — Démarrer le cluster**

```bash
minikube start --driver=docker --cpus=4 --memory=8192
```

Vérifications :

```bash
minikube status
kubectl cluster-info
kubectl get nodes -o wide
```

---

### **6.6 Étape 5 — Premier Pod de test**

```bash
kubectl run nginx-demo --image=nginx --port=80
kubectl get pods
kubectl logs nginx-demo
```

---

### **6.7 Étape 6 — Nettoyage**

```bash
kubectl delete pod nginx-demo
minikube stop
```

---

### **6.8 Validation du TP**

| Vérification  | Commande                          | Résultat attendu |
| ------------- | --------------------------------- | ---------------- |
| Cluster actif | `kubectl get nodes`               | Ready            |
| kube-system   | `kubectl -n kube-system get pods` | Running          |
| Pod nginx     | `kubectl get pods`                | Running          |
| Logs nginx    | `kubectl logs nginx-demo`         | Logs HTTP        |

---

## **7. Conclusion**

Ce chapitre a permis de :

* Comprendre l’**architecture interne de Kubernetes**.
* Installer un **cluster local fonctionnel**.
* Corriger les **erreurs courantes de permissions Docker/Minikube**.
* Préparer la suite du projet fil rouge :

  * **Chapitre 3 :** déploiement et configuration d’applications.
  * **Chapitre 4 :** supervision et administration du cluster.

---

## **8. Du projet fil rouge**

Objectif : poser les bases du dépôt et de l’environnement qui serviront dans tous les chapitres suivants

### 8.1 Initialiser l’espace de travail

```bash
# Créer un dossier de travail
mkdir -p ~/k8s-fil-rouge && cd ~/k8s-fil-rouge

# Initialiser git
git init
git config user.name "Votre Nom"
git config user.email "vous@example.com"

# Arborescence standard
mkdir -p k8s/base k8s/overlays/dev k8s/overlays/staging k8s/overlays/prod
mkdir -p apps/frontend apps/backend
mkdir -p docs scripts
minikube start --driver=docker

```

### 8.2 Créer le namespace du fil rouge

```bash
cat > k8s/base/namespace.yaml <<'YAML'
apiVersion: v1
kind: Namespace
metadata:
  name: projet-fil-rouge
  labels:
    project: fil-rouge
    env: dev
YAML
```
```bash
kubectl apply -f k8s/base/namespace.yaml
kubectl get ns projet-fil-rouge --show-labels
```

### 8.3 Capturer l’état du cluster pour traçabilité

```bash
mkdir -p ~/docs
kubectl cluster-info > docs/cluster-info.txt
kubectl version --output=yaml > docs/kubectl-version.yaml
kubectl get nodes -o wide > docs/nodes.txt
kubectl -n kube-system get pods -o wide > docs/kube-system-pods.txt
```



### 8.7 Prochaine étape :

* Au **Chapitre 3**, on ajoutera les premiers manifests d’application (Deployment, Service), puis l’Ingress et la configuration.
* Le namespace `projet-fil-rouge` restera notre cible par défaut.
