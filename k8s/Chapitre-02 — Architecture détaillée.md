# **Chapitre 2 — Architecture de Kubernetes**

*(Control Plane, Nœuds, Réseau, Stockage, Sécurité, Diagnostic)*

---

## **1. Objectifs d'apprentissage**

À la fin de ce chapitre, vous serez capable de :

* Expliquer l'**architecture interne** de Kubernetes (Control Plane et Nœuds).
* Identifier les **composants clés** du cluster et leur rôle.
* Diagnostiquer le **fonctionnement global** du système à l'aide de `kubectl`.
* Comprendre les **flux internes de communication et de sécurité**.
* Mettre en place un **cluster local complet** pour le projet fil rouge.

---

## **2. Vue d'ensemble de l'architecture Kubernetes**

Kubernetes est une plateforme **distribuée** composée de deux ensembles logiques :

1. **Le Control Plane**
   Regroupe les composants responsables de l'**API**, du **stockage d'état**, de la **réconciliation** et de l'**ordonnancement** :

   * **kube-apiserver** : point d'entrée unique. Valide les requêtes, applique AuthN/AuthZ/Admission, et persiste/lit l'état.
   * **etcd** : base **clé/valeur** distribuée (consensus **Raft**) stockant l'état source de vérité.
   * **kube-controller-manager** : exécute des **boucles de contrôle** assurant la convergence vers l'état souhaité (Deployments, Nodes, Jobs, GC…).
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
* **Observabilité** : tout passe par l'API → **events**, **logs**, **metrics**.

---

## **3. Control Plane : les composants principaux**

### **3.1 etcd — base clé/valeur (consensus Raft)**

* **Rôle** : stocke l'état complet du cluster (objets API sérialisés).
* **Ports** : 2379 (client API server), 2380 (peer cluster).
* **Quorum** : nombre impair (3/5). Perte de quorum → **écritures impossibles**.
* **Maintenance** : compaction, **defrag**, **sauvegardes régulières**.

Fichiers :

* `/etc/kubernetes/manifests/etcd.yaml`
* `/var/lib/etcd`

Commandes :

> **Objectif** : Vérifier l'état de santé d'un membre etcd via son endpoint client, en utilisant l'API v3 avec authentification TLS mutuelle.
> **Pre-requis** : Un cluster Kubernetes opérationnel (kubeadm ou autre) avec etcd accessible localement sur le port 2379. Les certificats PKI doivent être présents dans `/etc/kubernetes/pki/etcd/`.

```bash
# Force l'utilisation de l'API etcd v3 (au lieu de v2 par défaut)
export ETCDCTL_API=3
# Interroge le membre etcd local via HTTPS avec authentification TLS mutuelle :
#   --endpoints  : adresse du client etcd (localhost:2379)
#   --cacert     : CA qui a signé le certificat serveur etcd
#   --cert       : certificat client présenté au serveur etcd
#   --key        : clé privée associée au certificat client
#   endpoint health : vérifie que le membre répond et peut servir les requêtes
etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint health
```

> **Résultat attendu** :
> ```
> https://127.0.0.1:2379 is healthy: successfully committed proposal: took = 2.345ms
> ```
> **Vérification** : Le message doit indiquer "is healthy". Si etcd est down ou si les certificats sont incorrects, une erreur de connexion ou d'authentification apparaîtra.

---

### **3.2 kube-apiserver — cœur de Kubernetes**

* **Rôle** : reçoit/valide chaque requête, applique **AuthN → AuthZ → Admission**, lit/écrit dans etcd.
* **Extensibilité** : CRDs, API Aggregation.
* **Audit** : via `--audit-policy-file` et `--audit-log-path`.

Exemples :

> **Objectif** : Obtenir les informations générales du cluster Kubernetes et vérifier que le Pod kube-apiserver est bien actif dans le namespace système.
> **Pre-requis** : `kubectl` configuré avec un kubeconfig valide pointant vers le cluster cible.

```bash
# Affiche les adresses du control plane et de KubeDNS (vérifie la connectivité API)
kubectl cluster-info
# Liste les Pods du namespace kube-system portant le label component=kube-apiserver
# -l         : filtre par label (sélecteur)
# -o wide    : affichage élargi avec le nœud et l'IP
kubectl -n kube-system get pods -l component=kube-apiserver -o wide
```

> **Résultat attendu** :
> ```
> Kubernetes control plane is running at https://192.168.49.2:8443
> CoreDNS is running at https://192.168.49.2:8443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
>
> NAME                               READY   STATUS    RESTARTS   AGE   IP              NODE
> kube-apiserver-minikube            1/1     Running   0          5m    192.168.49.2    minikube
> ```
> **Vérification** : Le Pod kube-apiserver doit être en statut `Running` et `READY 1/1`. L'adresse IP doit correspondre au nœud du control plane.

---

### **3.3 kube-controller-manager — boucles de réconciliation**

* Orchestre les contrôleurs (Deployment → ReplicaSet → Pods, Node, Job…).
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

> **Objectif** : Vérifier l'état du service kubelet sur le nœud courant, lister les nœuds du cluster avec leurs détails, et obtenir une description détaillée d'un nœud spécifique (conditions, capacité, événements).
> **Pre-requis** : Accès SSH ou terminal sur un nœud worker/master. `kubectl` configuré avec les droits de lecture sur les nœuds. Remplacer `<node_name>` par le nom réel du nœud.

```bash
# Affiche l'état du service systemd kubelet (actif/inactif, derniers logs)
systemctl status kubelet
# Liste tous les nœuds avec leurs adresses IP internes, version OS et container runtime
kubectl get nodes -o wide
# Description complète d'un nœud : capacité, conditions, addresses, événements récents
kubectl describe node <node_name>
```

> **Résultat attendu** :
> ```
> ● kubelet.service - kubelet: The Kubernetes Node Agent
>      Loaded: loaded (/lib/systemd/system/kubelet.service; enabled)
>      Active: active (running) since ...
>
> NAME       STATUS   ROLES           AGE   VERSION   INTERNAL-IP    OS-IMAGE
> minikube   Ready    control-plane   10m   v1.30.0   192.168.49.2   Ubuntu 22.04
>
> Name:               minikube
> Roles:              control-plane
> Conditions:
>   Type                 Status
>   ----                 ------
>   MemoryPressure       False
>   DiskPressure         False
>   PIDPressure          False
>   Ready                True
> ```
> **Vérification** : Le service kubelet doit être `active (running)`. Le nœud doit afficher `STATUS = Ready` et la condition `Ready = True`.

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

> **Objectif** : Tester si le ServiceAccount `viewer` dans le namespace `default` a la permission de lire les Pods dans le namespace `demo`. Utile pour valider une configuration RBAC sans créer de token.
> **Pre-requis** : Un cluster Kubernetes avec RBAC activé. Le namespace `demo` doit exister. Le ServiceAccount `system:serviceaccount:default:viewer` doit avoir été créé au préalable (ou non, pour tester un refus).

```bash
# Vérifie les permissions RBAC pour une identité simulée (--as)
# --as   : impersonne l'identité donnée (ici un ServiceAccount)
# -n     : namespace cible pour la vérification
kubectl auth can-i get pods --as=system:serviceaccount:default:viewer -n demo
```

> **Résultat attendu** :
> ```
> yes
> ```
> ou
> ```
> no
> ```
> **Vérification** : `yes` signifie qu'une ClusterRole/Role binding autorise ce ServiceAccount à lire les Pods dans `demo`. `no` signifie qu'aucune règle RBAC ne l'autorise.

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

> **Objectif** : Installer Docker Engine depuis le dépôt officiel Docker sur Ubuntu/Debian, en ajoutant la clé GPG et le dépôt APT, puis activer et démarrer le service.
> **Pre-requis** : Ubuntu/Debian à jour. Accès `sudo`. Connexion Internet. Aucun Docker pré-installé (sinon désinstaller les anciennes versions).

```bash
# Met à jour les index de paquets et upgrade les paquets existants
sudo apt update && sudo apt upgrade -y
# Installe les dépendances nécessaires pour ajouter un dépôt HTTPS
sudo apt install apt-transport-https ca-certificates curl software-properties-common -y
# Télécharge la clé GPG officielle Docker et l'installe dans le keyring système
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg
# Ajoute le dépôt officiel Docker aux sources APT (architecture dynamique + clé signée)
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
sudo tee /etc/apt/sources.list.d/docker.list
# Met à jour les index APT pour inclure le nouveau dépôt Docker
sudo apt update
# Installe Docker Engine, CLI et containerd (runtime de conteneurs)
sudo apt install docker-ce docker-ce-cli containerd.io -y
# Active Docker au démarrage et le démarre immédiatement
sudo systemctl enable docker && sudo systemctl start docker
# Affiche la version installée de Docker (vérification)
docker --version
```

> **Résultat attendu** :
> ```
> Docker version 27.x.x, build xxxxxxx
> ```
> **Vérification** : La commande `docker --version` retourne un numéro de version ≥ 20.x. Le service Docker est actif (`systemctl is-active docker` → `active`).

#### **Sous Windows**

Télécharger **Docker Desktop**, installer, activer **WSL2**, vérifier :

> **Objectif** : Vérifier que Docker Desktop est correctement installé et que le client et le daemon communiquent.
> **Pre-requis** : Docker Desktop installé et démarré. WSL2 activé sur Windows 10/11.

```powershell
# Affiche les versions du client et du daemon Docker (connexion via named pipe)
docker version
```

> **Résultat attendu** :
> ```
> Client: Docker Desktop
>  Version:           27.x.x
>  OS/Arch:           windows/amd64
>
> Server: Docker Desktop
>  Engine:
>   Version:          27.x.x
>   OS/Arch:          linux/amd64
> ```
> **Vérification** : Les sections Client ET Server doivent toutes deux apparaître. Si le Server est absent, Docker Desktop n'est pas démarré.

---

### ⚠️ **Dépannage Docker/Minikube – Permissions et erreurs courantes**

Les utilisateurs Linux peuvent rencontrer ces erreurs :

#### **1️⃣ Erreur :**

```
DRV_AS_ROOT : Le pilote "docker" ne doit pas être utilisé avec les privilèges root.
```

**Cause** : tu as lancé Minikube avec `sudo`.
**Solution** : exécute `minikube start` en tant qu'utilisateur normal (non root).

---

#### **2️⃣ Erreur :**

```
permission denied while trying to connect to the Docker daemon socket
```

**Cause** : ton utilisateur n'a pas accès au daemon Docker.
**Solution :**

> **Objectif** : Ajouter l'utilisateur courant au groupe `docker` pour lui donner accès au socket Docker sans `sudo`, puis recharger les groupes dans la session courante.
> **Pre-requis** : Docker installé. L'utilisateur courant existe. Accès `sudo` pour modifier les groupes.

```bash
# Ajoute l'utilisateur courant ($USER) au groupe docker (-a = append, -G = groupes supplémentaires)
sudo usermod -aG docker $USER
# Recharge les groupes dans la session shell courante sans se déconnecter
newgrp docker
```

> **Résultat attendu** :
> ```
> (aucune sortie si succès)
> ```
> **Vérification** : La commande `groups` doit maintenant afficher `docker` dans la liste des groupes de l'utilisateur.

Puis :

> **Objectif** : Valider que l'accès Docker fonctionne et démarrer un cluster Minikube avec le pilote Docker.
> **Pre-requis** : L'utilisateur ajouté au groupe `docker` et `newgrp docker` exécuté. Docker daemon actif.

```bash
# Liste les conteneurs en cours d'exécution (teste l'accès au daemon Docker)
docker ps
# Démarre Minikube en utilisant Docker comme pilote (crée un conteneur comme "nœud")
minikube start --driver=docker
```

> **Résultat attendu** :
> ```
> CONTAINER ID   IMAGE   COMMAND   CREATED   STATUS    PORTS     NAMES
>
> 😄  minikube v1.34.0 on Ubuntu 22.04
> ✨  Using the docker driver based on user configuration
> ...
> 🏄  Done! kubectl is now configured to use "minikube" cluster
> ```
> **Vérification** : `docker ps` ne retourne pas d'erreur de permission. Minikube se termine par `Done!`.

---

#### **3️⃣ Erreur :**

```
PROVIDER_DOCKER_NEWGRP : permission denied while trying to connect to the Docker daemon socket
```

**Cause** : la modification de groupe n'est pas prise en compte.
**Solution** : déconnecte-toi ou exécute `newgrp docker` avant de relancer Minikube.

---

#### **4️⃣ Erreur :**

```
DRV_NOT_HEALTHY : aucun pilote en fonctionnement
```

**Cause** : Docker n'est pas actif.
**Solution :**

> **Objectif** : Redémarrer le service Docker, supprimer tout état Minikube corrompu, puis redémarrer Minikube de zéro avec le pilote Docker.
> **Pre-requis** : Docker installé mais potentiellement dans un état instable. `minikube` installé.

```bash
# Redémarre le service Docker (arrête puis relance le daemon)
sudo systemctl restart docker
# Supprime tous les clusters et profils Minikube existants (nettoyage complet)
minikube delete --all
# Démarre un nouveau cluster Minikube avec le pilote Docker
minikube start --driver=docker
```

> **Résultat attendu** :
> ```
> 🔥  Deleting "minikube" in docker ...
> 🔥  Deleting container "minikube" ...
> 💀  Removed all traces of the "minikube" profile(s).
>
> 😄  minikube v1.34.0 on Ubuntu 22.04
> ...
> 🏄  Done! kubectl is now configured to use "minikube" cluster
> ```
> **Vérification** : Minikube se termine par `Done!`. Le cluster est fraîchement créé sans état corrompu.

---

Une fois ces correctifs appliqués, vérifie :

> **Objectif** : Confirmer que le cluster Minikube est opérationnel et que kubectl communique correctement avec le nœud.
> **Pre-requis** : Minikube démarré avec succès (étapes de dépannage ci-dessus appliquées si nécessaire).

```bash
# Affiche l'état de chaque composant Minikube (host, kubelet, apiserver)
minikube status
# Liste les nœuds du cluster et leur statut (doit afficher "Ready")
kubectl get nodes
```

> **Résultat attendu** :
> ```
> minikube
> type: Control Plane
> host: Running
> kubelet: Running
> apiserver: Running
> kubeconfig: Configured
>
> NAME       STATUS   ROLES           AGE   VERSION
> minikube   Ready    control-plane   2m    v1.30.0
> ```
> **Vérification** : Tous les composants Minikube sont `Running`. Le nœud affiche `STATUS = Ready`.

---

### **6.3 Étape 2 — Installer kubectl**

#### **Sous Linux**

> **Objectif** : Télécharger la dernière version stable de kubectl pour Linux amd64, la rendre exécutable et l'installer dans le PATH système.
> **Pre-requis** : `curl` installé. Accès `sudo`. Connexion Internet.

```bash
# Télécharge le binaire kubectl de la dernière version stable (détection dynamique via l'URL stable.txt)
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
# Rend le binaire exécutable et le déplace dans /usr/local/bin (accessible globalement)
chmod +x kubectl && sudo mv kubectl /usr/local/bin/
# Affiche la version client de kubectl (vérification, sans connexion cluster)
kubectl version --client
```

> **Résultat attendu** :
> ```
> Client Version: v1.30.x
> Kustomize Version: v5.x.x
> ```
> **Vérification** : kubectl retourne un numéro de version. La version client doit être compatible (±1 mineur) avec la version du cluster.

#### **Sous Windows**

> **Objectif** : Installer kubectl via le gestionnaire de paquets Chocolatey et vérifier la version.
> **Pre-requis** : Chocolatey (`choco`) installé sur Windows. Accès administrateur.

```powershell
# Installe le package kubernetes-cli via Chocolatey (télécharge et configure le PATH)
choco install kubernetes-cli -y
# Affiche la version client de kubectl
kubectl version --client
```

> **Résultat attendu** :
> ```
> Client Version: v1.30.x
> Kustomize Version: v5.x.x
> ```
> **Vérification** : kubectl est accessible dans le PATH et affiche une version valide.

---

### **6.4 Étape 3 — Installer Minikube**

**Linux :**

> **Objectif** : Télécharger la dernière version de Minikube pour Linux amd64 et l'installer dans `/usr/local/bin/`.
> **Pre-requis** : `curl` installé. Accès `sudo`. Docker déjà installé et fonctionnel.

```bash
# Télécharge le binaire Minikube depuis Google Cloud Storage (dernière release)
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
# Installe le binaire dans /usr/local/bin avec les permissions d'exécution (755)
sudo install minikube-linux-amd64 /usr/local/bin/minikube
```

> **Résultat attendu** :
> ```
> (aucune sortie si succès)
> ```
> **Vérification** : La commande `minikube version` retourne un numéro de version valide.

**Windows :**

> **Objectif** : Installer Minikube via Chocolatey.
> **Pre-requis** : Chocolatey installé. Accès administrateur. Docker Desktop actif.

```powershell
# Installe Minikube via Chocolatey (gère le téléchargement et le PATH)
choco install minikube -y
```

> **Résultat attendu** :
> ```
> The install of minikube was SUCCESSFUL
> ```
> **Vérification** : `minikube version` fonctionne dans un nouveau terminal.

---

### **6.5 Étape 4 — Démarrer le cluster**

> **Objectif** : Démarrer un cluster Minikube local en utilisant Docker comme pilote, avec 4 CPU et 8 Go de RAM alloués au nœud unique.
> **Pre-requis** : Docker installé et actif. Minikube et kubectl installés. L'utilisateur a accès au daemon Docker (groupe `docker`). Au moins 8 Go de RAM disponible.

```bash
# Démarre Minikube :
#   --driver=docker  : utilise un conteneur Docker comme "nœud" Kubernetes
#   --cpus=4         : alloue 4 cœurs CPU au conteneur/nœud
#   --memory=8192    : alloue 8192 Mo (8 Go) de RAM au conteneur/nœud
minikube start --driver=docker --cpus=4 --memory=8192
```

> **Résultat attendu** :
> ```
> 😄  minikube v1.34.0 on Ubuntu 22.04
> ✨  Using the docker driver based on user configuration
> 👍  Starting control plane node minikube in cluster minikube
> 🚜  Pulling base image ...
> 🔥  Creating docker container (CPUs=4, Memory=8192MB) ...
> 🐳  Preparing Kubernetes v1.30.0 on Docker 27.x.x ...
> 🔎  Verifying Kubernetes components...
> 🏄  Done! kubectl is now configured to use "minikube" cluster
> ```
> **Vérification** : Le message final indique `Done!`. kubectl est automatiquement configuré pour pointer vers ce cluster.

Vérifications :

> **Objectif** : Vérifier que tous les composants du cluster Minikube sont opérationnels, que l'API répond, et que le nœud est en état Ready.
> **Pre-requis** : Minikube démarré avec succès (commande précédente terminée sans erreur).

```bash
# Affiche l'état détaillé de chaque composant Minikube (host, kubelet, apiserver)
minikube status
# Affiche les adresses du control plane et des services internes (CoreDNS)
kubectl cluster-info
# Liste les nœuds avec leurs détails : statut, rôle, âge, version, IP, OS
kubectl get nodes -o wide
```

> **Résultat attendu** :
> ```
> minikube
> type: Control Plane
> host: Running
> kubelet: Running
> apiserver: Running
> kubeconfig: Configured
>
> Kubernetes control plane is running at https://192.168.49.2:8443
> CoreDNS is running at https://192.168.49.2:8443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
>
> NAME       STATUS   ROLES           AGE   VERSION   INTERNAL-IP    OS-IMAGE
> minikube   Ready    control-plane   1m    v1.30.0   192.168.49.2   Ubuntu 22.04
> ```
> **Vérification** : Tous les composants sont `Running`. Le nœud est `Ready`. L'URL du control plane est accessible.

---

### **6.6 Étape 5 — Premier Pod de test**

> **Objectif** : Créer un Pod nginx simple via `kubectl run`, vérifier son état et consulter ses logs pour confirmer que le serveur web est démarré.
> **Pre-requis** : Cluster Minikube démarré et nœud `Ready`. kubectl configuré.

```bash
# Crée un Pod nommé nginx-demo à partir de l'image nginx, exposant le port 80
# (crée un Pod nu, sans Deployment — adapté uniquement pour un test rapide)
kubectl run nginx-demo --image=nginx --port=80
# Liste les Pods du namespace par défaut et affiche leur statut
kubectl get pods
# Affiche les logs du Pod nginx-demo (sortie stdout du conteneur nginx)
kubectl logs nginx-demo
```

> **Résultat attendu** :
> ```
> pod/nginx-demo created
>
> NAME         READY   STATUS    RESTARTS   AGE
> nginx-demo   1/1     Running   0          5s
>
> /docker-entrypoint.sh: Configuration complete; ready for start up
> 10.244.0.1 - - [21/Jun/2026:10:00:00 +0000] "GET / HTTP/1.1" 200 ...
> ```
> **Vérification** : Le Pod passe à `Running` et `READY 1/1`. Les logs affichent le message de démarrage nginx et potentiellement des lignes d'accès HTTP.

---

### **6.7 Étape 6 — Nettoyage**

> **Objectif** : Supprimer le Pod de test nginx-demo et arrêter le cluster Minikube pour libérer les ressources.
> **Pre-requis** : Le Pod `nginx-demo` existe dans le namespace par défaut. Le cluster Minikube est actif.

```bash
# Supprime le Pod nginx-demo (libère le conteneur et l'IP associée)
kubectl delete pod nginx-demo
# Arrête le cluster Minikube (les conteneurs Docker sont stoppés mais conservés)
minikube stop
```

> **Résultat attendu** :
> ```
> pod "nginx-demo" deleted
>
> ✋  Stopping node "minikube"  ...
> 🛑  1 node stopped.
> ```
> **Vérification** : Le Pod n'apparaît plus dans `kubectl get pods`. `minikube status` affiche `Stopped`.

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

* Comprendre l'**architecture interne de Kubernetes**.
* Installer un **cluster local fonctionnel**.
* Corriger les **erreurs courantes de permissions Docker/Minikube**.
* Préparer la suite du projet fil rouge :

  * **Chapitre 3 :** déploiement et configuration d'applications.
  * **Chapitre 4 :** supervision et administration du cluster.

---

## **8. Du projet fil rouge**

Objectif : poser les bases du dépôt et de l'environnement qui serviront dans tous les chapitres suivants

### 8.1 Initialiser l'espace de travail

> **Objectif** : Créer la structure de dossiers du projet fil rouge, initialiser un dépôt Git local, configurer l'identité Git, créer l'arborescence Kustomize (base + overlays par environnement) et les dossiers applicatifs, puis démarrer Minikube si ce n'est pas déjà fait.
> **Pre-requis** : Git installé. Minikube et kubectl installés. Docker actif.

```bash
# Créer un dossier de travail et s'y positionner
mkdir -p ~/k8s-fil-rouge && cd ~/k8s-fil-rouge

# Initialiser un nouveau dépôt Git local
git init
# Configurer l'identité Git (nom et email utilisés dans les commits)
git config user.name "Votre Nom"
git config user.email "vous@example.com"

# Arborescence standard Kustomize :
#   k8s/base           : manifests communs à tous les environnements
#   k8s/overlays/dev   : surcouches spécifiques à l'environnement dev
#   k8s/overlays/staging : surcouches spécifiques à staging
#   k8s/overlays/prod  : surcouches spécifiques à prod
mkdir -p k8s/base k8s/overlays/dev k8s/overlays/staging k8s/overlays/prod
# Dossiers pour les applications frontend et backend
mkdir -p apps/frontend apps/backend
# Dossiers pour la documentation et les scripts utilitaires
mkdir -p docs scripts
# Démarre Minikube avec le pilote Docker (skip si déjà démarré)
minikube start --driver=docker

```

> **Résultat attendu** :
> ```
> Initialized empty Git repository in /home/user/k8s-fil-rouge/.git/
>
> 😄  minikube v1.34.0 on Ubuntu 22.04
> ...
> 🏄  Done! kubectl is now configured to use "minikube" cluster
> ```
> **Vérification** : `ls -R` affiche l'arborescence complète. `git status` montre un dépôt vide. `minikube status` affiche `Running`.

### 8.2 Créer le namespace du fil rouge

> **Objectif** : Générer un manifeste YAML définissant le namespace `projet-fil-rouge` avec des labels identifiant le projet et l'environnement, puis l'appliquer au cluster.
> **Pre-requis** : Être dans le dossier `~/k8s-fil-rouge`. Cluster Minikube actif.

```bash
# Crée le fichier namespace.yaml via une heredoc (cat > fichier <<'YAML' ... YAML)
# Le manifeste définit :
#   apiVersion: v1        : API core (les namespaces sont des ressources core)
#   kind: Namespace       : type de ressource
#   metadata.name         : nom du namespace
#   metadata.labels       : labels pour l'organisation et le filtrage
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

> **Résultat attendu** :
> ```
> (aucune sortie si succès — le fichier est créé)
> ```
> **Vérification** : `cat k8s/base/namespace.yaml` affiche le contenu YAML correct.

> **Objectif** : Appliquer le manifeste namespace au cluster pour créer le namespace, puis vérifier sa création et ses labels.
> **Pre-requis** : Le fichier `k8s/base/namespace.yaml` existe et contient le manifeste valide. Cluster Minikube actif.

```bash
# Applique le manifeste : crée le namespace dans le cluster (idempotent)
kubectl apply -f k8s/base/namespace.yaml
# Affiche le namespace avec toutes ses colonnes de labels (--show-labels)
kubectl get ns projet-fil-rouge --show-labels
```

> **Résultat attendu** :
> ```
> namespace/projet-fil-rouge created
>
> NAME               STATUS   AGE   LABELS
> projet-fil-rouge   Active   2s    env=dev,project=fil-rouge
> ```
> **Vérification** : Le namespace est en statut `Active`. Les labels `project=fil-rouge` et `env=dev` sont bien présents.

### 8.3 Capturer l'état du cluster pour traçabilité

> **Objectif** : Sauvegarder un instantané de l'état du cluster dans des fichiers texte (cluster-info, version kubectl, liste des nœuds, Pods du namespace kube-system) pour documentation et traçabilité.
> **Pre-requis** : Cluster Minikube actif. Le dossier `~/k8s-fil-rouge` existe. kubectl configuré.

```bash
# Crée un dossier docs à la racine du home pour stocker les captures
mkdir -p ~/docs
# Capture les adresses du control plane et des services internes
kubectl cluster-info > docs/cluster-info.txt
# Capture la version complète du client et du serveur au format YAML
kubectl version --output=yaml > docs/kubectl-version.yaml
# Capture la liste détaillée des nœuds (IP, OS, version, rôles)
kubectl get nodes -o wide > docs/nodes.txt
# Capture la liste des Pods système avec leur nœud et IP (diagnostic)
kubectl -n kube-system get pods -o wide > docs/kube-system-pods.txt
```

> **Résultat attendu** :
> ```
> (aucune sortie si succès — tout est redirigé vers les fichiers)
> ```
> **Vérification** : `ls ~/docs/` affiche les 4 fichiers. `cat docs/nodes.txt` montre au moins le nœud `minikube` en statut `Ready`. `cat docs/kube-system-pods.txt` liste les Pods système (coredns, etcd, kube-apiserver, etc.).



### 8.7 Prochaine étape :

* Au **Chapitre 3**, on ajoutera les premiers manifests d'application (Deployment, Service), puis l'Ingress et la configuration.
* Le namespace `projet-fil-rouge` restera notre cible par défaut.