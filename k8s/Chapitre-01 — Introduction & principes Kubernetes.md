# Chapitre 1 – Introduction à Kubernetes

---

## 1. Présentation de Kubernetes et origine du projet

### 1.1 Définition générale

* **Kubernetes (abrégé K8s)** est une **plateforme open-source** d’orchestration de conteneurs destinée à **automatiser le déploiement, la mise à l’échelle, la maintenance et la supervision** d’applications distribuées.
* Le terme **orchestration** désigne la **coordination automatisée** de conteneurs répartis sur plusieurs serveurs physiques ou virtuels, afin d’assurer la cohérence et la continuité des services.
* Kubernetes agit comme un **système d’exploitation pour le cloud** : il planifie, exécute, surveille et répare automatiquement les applications au sein d’un cluster (ensemble de machines).
* Il repose sur une architecture **déclarative** : l’administrateur décrit l’état souhaité du système dans des fichiers de configuration (YAML), et le plan de contrôle ajuste en permanence l’état réel du cluster pour correspondre à cette description.
* L’outil fournit un niveau d’abstraction supérieur aux infrastructures traditionnelles : on gère des *workloads* (charges de travail) et non plus des machines individuelles.

---

### 1.2 Origine et historique

* Développé par **Google** en **2014**, Kubernetes est issu d’un système interne appelé **Borg**, qui permettait à l’entreprise de gérer ses propres services (Gmail, Maps, YouTube, Search) sur des milliers de serveurs.
* **Borg** a introduit les concepts fondamentaux repris dans Kubernetes : planification automatique, isolation des ressources, déploiement déclaratif et tolérance aux pannes.
* En **2015**, Google a confié le projet à la **Cloud Native Computing Foundation (CNCF)**, organisme à but non lucratif dépendant de la **Linux Foundation**, afin d’en garantir :

  * la **gouvernance ouverte** ;
  * la **neutralité technologique** ;
  * la **pérennité** grâce à une communauté mondiale de contributeurs.
* La CNCF héberge également d’autres projets complémentaires : **Prometheus** (supervision), **Envoy** (proxy et service mesh), **Helm** (gestion de packages), **containerd** (moteur de conteneurs), **etcd** (base de données distribuée).
* Aujourd’hui, Kubernetes constitue le **standard de référence** de l’orchestration : toutes les grandes plateformes cloud proposent un service managé basé sur lui (EKS, AKS, GKE, etc.).

---

### 1.3 Objectifs fondamentaux

Kubernetes a pour finalité de fournir une plateforme universelle capable de :

* **Simplifier** le déploiement d’applications conteneurisées, quelle que soit la plateforme d’exécution.
* **Automatiser** les opérations récurrentes (démarrage, mise à jour, redémarrage, arrêt, supervision).
* **Optimiser** l’usage des ressources matérielles disponibles (CPU, mémoire, stockage).
* **Assurer la résilience** : redémarrage automatique en cas d’incident, équilibrage de charge, reprogrammation sur d’autres nœuds.
* **Garantir la portabilité** entre les environnements : développement local, datacenter privé (*on-premise*), cloud public ou hybride.
* **Renforcer la sécurité** via des mécanismes intégrés : isolation, gestion d’identité, contrôle d’accès (RBAC : Role-Based Access Control).
* **Standardiser l’écosystème cloud-native** en offrant des API stables et une interopérabilité avec d’autres outils de l’écosystème DevOps.

---

### 1.4 Signification du nom et philosophie du projet

* Le mot **Kubernetes** provient du grec *κυβερνήτης* (*kubernêtês*), signifiant **pilote de navire** ou **gouvernail**.
  Ce nom symbolise la fonction première du système : **diriger** et **maintenir le cap** d’un ensemble de conteneurs en mouvement.
* Le **logo** représente une **barre de gouvernail à sept branches**, chacune évoquant un pilier technique du projet : planification, configuration, réseau, stockage, sécurité, monitoring et scalabilité.
* La philosophie du projet repose sur trois principes :

  * **Automatisation** : réduire les tâches manuelles grâce à des mécanismes de contrôle continus.
  * **Déclarativité** : exprimer un état désiré plutôt qu’une suite d’instructions.
  * **Résilience** : garantir la continuité de service même en cas de panne ou de surcharge.

---

## 2. Fonctionnalités : automatisation du cycle de vie des applications conteneurisées

Kubernetes offre un ensemble de mécanismes intégrés pour automatiser chaque phase du cycle de vie applicatif : déploiement, mise à jour, montée en charge, tolérance aux pannes et supervision.

---

### 2.1 Automatisation du déploiement

* Les applications sont décrites sous forme de **manifestes YAML (YAML Ain’t Markup Language)** définissant les objets du cluster : Pods, Services, Deployments, etc.
* Kubernetes compare en continu **l’état réel** du cluster à **l’état souhaité** ; s’il existe un écart, il applique les correctifs nécessaires.
* Ce mécanisme garantit des **déploiements reproductibles**, cohérents et traçables.
* Les déploiements peuvent être intégrés dans des pipelines **CI/CD (Continuous Integration / Continuous Deployment)** pour automatiser entièrement la mise en production.

---

### 2.2 Gestion des mises à jour (Rolling Updates et Rollback)

* Les **Rolling Updates** permettent d’introduire une nouvelle version d’application sans interruption :

  * les nouveaux Pods sont créés progressivement ;
  * le trafic est transféré vers eux ;
  * les anciens Pods sont ensuite supprimés.
* En cas d’anomalie, un **Rollback** (retour arrière) restaure la version précédente en quelques secondes.
* Ces mécanismes assurent la **continuité de service** et s’intègrent aux pratiques de **déploiement continu**.

---

### 2.3 Mise à l’échelle automatique (Autoscaling)

* Kubernetes ajuste dynamiquement les ressources en fonction de la charge observée.
* Trois niveaux de scalabilité :

  * **HPA (Horizontal Pod Autoscaler)** : augmente ou réduit le nombre de Pods.
  * **VPA (Vertical Pod Autoscaler)** : redimensionne la puissance allouée à chaque Pod.
  * **Cluster Autoscaler** : ajoute ou supprime des nœuds dans le cluster.
* Les métriques utilisées (CPU, RAM, latence, requêtes HTTP) sont collectées par le Metrics Server ou des outils comme Prometheus.
* Objectif : adapter automatiquement les ressources aux besoins réels pour garantir performance et efficacité énergétique.

---

### 2.4 Auto-réparation (Self-Healing)

* Le **Controller Manager** surveille l’état des objets et exécute les actions nécessaires pour maintenir l’état défini.
* Si un Pod échoue, il est automatiquement **redémarré** ; si un nœud devient indisponible, les Pods qu’il héberge sont **replanifiés** sur d’autres nœuds.
* Trois types de **probes** contrôlent la santé des conteneurs :

  * **Liveness Probe** : vérifie qu’un conteneur reste opérationnel.
  * **Readiness Probe** : signale qu’un Pod est prêt à recevoir du trafic.
  * **Startup Probe** : s’assure que l’application a bien démarré avant toute autre vérification.
* L’ensemble constitue une infrastructure **résiliente** et **auto-corrigeante**.

---

### 2.5 Répartition de charge et découverte de services

* Kubernetes inclut un système de **Service Discovery** et de **Load Balancing** intégré.
* Chaque Service possède une **adresse IP stable** et un **nom DNS interne** enregistré dans le cluster.
* Le trafic est automatiquement distribué entre les Pods disponibles selon leur santé et leur charge.
* Ces mécanismes assurent une **continuité de service** et permettent aux applications de communiquer entre elles sans connaissance préalable des adresses physiques.

---

### 2.6 Gestion de la configuration et des secrets

* **ConfigMaps** : stockent des configurations non sensibles (fichiers, variables d’environnement).
* **Secrets** : conservent des données confidentielles (mots de passe, clés API, certificats) encodées en Base64.
* Ces objets sont injectés dynamiquement dans les conteneurs, sans reconstruire les images.
* Ce modèle sépare la **configuration** du **code**, améliorant la sécurité et la portabilité des applications.

---

### 2.7 Gestion du stockage persistant

* Les **Persistent Volumes (PV)** représentent des ressources de stockage physiques ou virtuelles mises à disposition du cluster.
* Les **Persistent Volume Claims (PVC)** sont des requêtes de stockage émises par les Pods ; elles lient automatiquement un PV disponible.
* Les données persistent même après suppression ou redéploiement d’un Pod.
* Kubernetes supporte différents back-ends : NFS (Network File System), iSCSI, Ceph, GlusterFS, EBS (AWS Elastic Block Store), GCE Persistent Disk, Azure Disk, etc.

---

### 2.8 Observabilité et supervision

* Kubernetes intègre une pile complète d’**observabilité** : monitoring, journalisation, traçabilité et alerting.
* **Metrics Server** : collecte les données de performance (CPU, RAM).
* **Prometheus / Grafana** : monitoring et tableaux de bord personnalisables.
* **Fluentd / Elasticsearch / Kibana (ELK)** : collecte et analyse des logs.
* **OpenTelemetry** : standard d’observation des traces et métriques distribuées.
* Ces outils assurent une **visibilité complète** du fonctionnement du cluster et facilitent la détection d’incidents.

---

## 3. Conteneurs supportés et plateformes utilisant Kubernetes

### 3.1 Runtimes compatibles

* Kubernetes utilise la **Container Runtime Interface (CRI)**, spécification normalisée reliant le noyau Kubernetes aux moteurs d’exécution.
* Runtimes majeurs :

  * **containerd** : runtime par défaut, léger, rapide et conforme à l’**OCI (Open Container Initiative)**.
  * **CRI-O** : runtime minimaliste développé pour Kubernetes.
  * **Docker Engine** : runtime historique, progressivement remplacé par containerd.
  * **gVisor** et **Kata Containers** : runtimes sécurisés utilisant la virtualisation légère pour isoler les charges sensibles.

### 3.2 Plateformes d’exécution

* **Local (développement)** :

  * **Minikube** : cluster à nœud unique pour apprentissage et tests.
  * **kind (Kubernetes IN Docker)** : cluster exécuté dans des conteneurs.
  * **MicroK8s** : distribution allégée pour environnement Ubuntu.
* **On-Premise (infrastructure interne)** :

  * Installation via **kubeadm** ou distributions comme **Rancher**, **OpenShift**, **VMware Tanzu**.
* **Cloud Public (services managés)** :

  * **EKS (AWS)**, **AKS (Azure)**, **GKE (Google Cloud)**, **OKE (Oracle)**, **ACK (Alibaba)**.
* Les services managés prennent en charge la **maintenance**, les **mises à jour** et la **haute disponibilité** du plan de contrôle.

---

## 4. Composants de Kubernetes

### 4.1 Plan de contrôle (Control Plane)

* **API Server** : point d’entrée du cluster ; expose une API REST et sert d’interface à kubectl et aux autres composants.
* **etcd** : base de données clé/valeur distribuée contenant toutes les informations d’état du cluster.
* **Controller Manager** : orchestration des contrôleurs garantissant la conformité à l’état souhaité.
* **Scheduler** : planifie l’exécution des Pods sur les nœuds en fonction des ressources disponibles.
* **Cloud Controller Manager** : interface entre Kubernetes et les services cloud externes.

### 4.2 Composants de nœud (Node Components)

* **Kubelet** : agent exécuté sur chaque nœud ; veille au bon fonctionnement des Pods et rapporte leur état.
* **Kube-Proxy** : gère le trafic réseau entrant et sortant entre les Services et les Pods.
* **Container Runtime** : moteur responsable de l’exécution réelle des conteneurs.

---

## 5. Définitions essentielles

### 5.1 Pod

* Plus petite unité de déploiement dans Kubernetes.
* Contient un ou plusieurs conteneurs partageant le même espace réseau, le même stockage et le même cycle de vie.
* Les Pods sont éphémères : ils peuvent être supprimés et recréés automatiquement selon les besoins.

### 5.2 Label

* Paire clé/valeur attribuée à un objet (Pod, Service, Deployment, etc.).
* Sert à identifier, filtrer et regrouper les ressources pour les sélections ou les politiques de réseau.

### 5.3 Controller

* Processus de surveillance et de correction permanente de l’état du cluster.
* Types principaux : **Deployment**, **ReplicaSet**, **DaemonSet**, **StatefulSet**.
* Assurent la disponibilité et la cohérence des Pods selon les règles déclarées.

### 5.4 Service

* Objet abstrait exposant un ensemble de Pods via une adresse IP fixe et un nom DNS.
* Fournit un équilibrage de charge interne et garantit l’accès aux applications malgré le caractère éphémère des Pods.
* Types : **ClusterIP**, **NodePort**, **LoadBalancer**.

---

## 6. Conclusion du Chapitre 1

À l’issue de ce chapitre, les apprenants doivent être capables de :

* Expliquer le rôle et l’origine de Kubernetes.
* Identifier les objectifs principaux du projet et sa gouvernance (CNCF, Linux Foundation).
* Décrire les fonctionnalités majeures d’automatisation et de maintenance.
* Distinguer les runtimes compatibles et les plateformes d’exécution.
* Comprendre les composants essentiels du système et leurs interactions (Pod, Label, Controller, Service).
* Relier les principes de Kubernetes à l’écosystème DevOps et au modèle cloud-native.

développe maintenant le **Chapitre 2 – Architecture** sur la même base structurée ?
