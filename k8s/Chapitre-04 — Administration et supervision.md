# **Chapitre 4 — Administration et supervision de Kubernetes**

*(Supervision, logs, métriques, scaling, mises à jour continues)*

---

## **1. Objectifs d’apprentissage**

À la fin de ce chapitre, l’apprenant sera capable de :

* Administrer un cluster Kubernetes en production (inspection, supervision, journalisation).
* Analyser les **logs**, surveiller les **métriques** et détecter les anomalies.
* Gérer les **mises à jour continues** des applications (Rolling Update / Rollback).
* Mettre en œuvre le **scaling automatique** des Pods selon la charge.
* Poursuivre le **projet fil rouge** avec un environnement supervisé et auto-scalable.

---

## **2. Introduction à l’administration du cluster**

### **2.1 Notions fondamentales**

* Kubernetes repose sur un **contrôle continu** : chaque objet est surveillé par un contrôleur.
* L’administration consiste à :

  * Vérifier l’état du cluster et des nœuds.
  * Superviser les Pods et les Services.
  * Gérer les ressources (CPU, mémoire, stockage).
  * Surveiller la santé des applications.

---

### **2.2 Commandes de base d’administration**

```bash
kubectl get nodes -o wide
kubectl get pods -A
kubectl top nodes
kubectl top pods
kubectl describe pod <nom>
kubectl get events --sort-by=.lastTimestamp | tail
```

**Contexte :**
Ces commandes sont les fondations de la supervision :

* `kubectl get nodes` : affiche les nœuds du cluster et leur état.
* `kubectl top nodes/pods` : nécessite **metrics-server** et montre l’utilisation CPU/mémoire.
* `kubectl describe pod` : donne les détails (état, IP, événements, images).
* `kubectl get events` : permet de repérer rapidement les erreurs (crash, scheduling…).

---

## **3. Supervision et journalisation**

### **3.1 Les métriques**

* Les métriques représentent l’utilisation **CPU**, **mémoire**, **réseau** et **stockage**.
* Outil intégré : **metrics-server**.
* Les métriques alimentent :

  * les commandes `kubectl top`,
  * les règles d’autoscaling (HPA),
  * les tableaux de bord (Prometheus, Grafana).

**Installation du metrics-server :**

```bash
minikube addons enable metrics-server
```

**Contexte :**
Cette commande active l’addon officiel **metrics-server** dans Minikube.
Il collecte les métriques de chaque Pod et nœud en temps réel via l’API Kubelet.

**Vérification :**

```bash
kubectl top nodes
kubectl top pods -n projet-fil-rouge
```

**Contexte :**
Si les valeurs CPU et mémoire s’affichent, l’addon fonctionne.
Sinon, attendez 1 à 2 minutes pour la première collecte.

---

### **3.2 Les journaux (logs)**

```bash
kubectl logs <nom_du_pod> -n projet-fil-rouge
```

**Contexte :**
Affiche les logs d’un Pod unique.
Les journaux sont essentiels pour diagnostiquer les erreurs d’application.

```bash
kubectl logs <nom_du_pod> -c <nom_du_conteneur> -n projet-fil-rouge
```

**Contexte :**
Pour les Pods multi-conteneurs, cette commande permet de cibler un conteneur spécifique.

```bash
kubectl -n kube-system logs <pod>
```

**Contexte :**
Permet d’analyser les logs des composants système (scheduler, controller, etc.).

```bash
kubectl logs -f <nom_du_pod> -n projet-fil-rouge
```

**Contexte :**
`-f` ("follow") permet un suivi continu des logs en temps réel (utile pour observer un backend HTTP).

---

### **3.3 Les événements**

```bash
kubectl get events --sort-by=.metadata.creationTimestamp
```

**Contexte :**
Liste chronologiquement les événements récents du cluster (créations, suppressions, erreurs).

**Types d’événements fréquents :**

* `Scheduled` : Pod assigné à un nœud.
* `Pulled` : image téléchargée.
* `Started` / `Killing` : cycle de vie.
* `FailedScheduling` : ressource indisponible ou contrainte non respectée.

---

## **4. Rolling Update et Rollback**

### **4.1 Principe**

* Les **Rolling Updates** permettent de **mettre à jour une application sans interruption** :

  * les nouveaux Pods démarrent progressivement,
  * les anciens sont arrêtés une fois les nouveaux disponibles.
* En cas d’échec, un **Rollback** restaure la version précédente.

---

### **4.2 Paramètres importants**

```yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 1
```

**Contexte :**
Ces paramètres indiquent que Kubernetes peut créer **1 Pod supplémentaire** au maximum pendant la mise à jour et qu’au plus **1 Pod peut être indisponible** à un instant donné.

---

### **4.3 Commandes associées**

```bash
kubectl set image deployment/frontend nginx=nginx:1.27 -n projet-fil-rouge
kubectl rollout status deployment/frontend -n projet-fil-rouge
kubectl rollout history deployment/frontend -n projet-fil-rouge
kubectl rollout undo deployment/frontend -n projet-fil-rouge
```

**Contexte :**
Ces commandes gèrent les déploiements en continu :

* `set image` : met à jour l’image d’un conteneur.
* `rollout status` : affiche la progression en direct.
* `rollout history` : liste les versions.
* `rollout undo` : restaure la version précédente en cas de problème.

---

## **5. Autoscaling (mise à l’échelle automatique)**

### **5.1 Types de scalabilité**

* **HPA (Horizontal Pod Autoscaler)** : augmente le nombre de Pods selon la charge.
* **VPA (Vertical Pod Autoscaler)** : ajuste les ressources d’un Pod (CPU/RAM).
* **Cluster Autoscaler** : ajoute ou retire des nœuds (non applicable dans Minikube).

---

### **5.2 Création d’un HPA**

```bash
kubectl autoscale deployment frontend -n projet-fil-rouge --cpu-percent=50 --min=1 --max=5
```

**Contexte :**
Crée un **autoscaler horizontal** sur le déploiement `frontend`.
Si la charge CPU moyenne dépasse **50 %**, Kubernetes crée automatiquement de nouveaux Pods (jusqu’à 5).

---

### **5.3 Vérification**

```bash
kubectl get hpa -n projet-fil-rouge
kubectl describe hpa frontend -n projet-fil-rouge
```

**Contexte :**
Permet de vérifier les seuils configurés et l’évolution en temps réel (CPU target / current).

---

### **5.4 Simulation de charge**

```bash
kubectl run loadtest --image=busybox --restart=Never -n projet-fil-rouge -- /bin/sh -c \
"while true; do wget -q -O- http://frontend; done"
```

**Contexte :**
Ce Pod exécute une boucle infinie envoyant des requêtes HTTP vers `frontend`.
Cela génère de la charge CPU simulée pour déclencher le scaling.

---

### **5.5 Observation**

```bash
kubectl get hpa -w -n projet-fil-rouge
kubectl get pods -l app=frontend -n projet-fil-rouge
```

**Contexte :**
Le flag `-w` ("watch") actualise en continu.
Vous verrez le nombre de Pods augmenter lorsque la charge CPU dépassera le seuil défini.

---

## **6. LAB – Projet Fil Rouge (Phase 3)**

### **Supervision, mise à jour et autoscaling de l’application web**

---

### **6.1 Objectif**

Poursuivre l’application du **Chapitre 3** en ajoutant :

* la **supervision (metrics-server)**,
* une **mise à jour continue du frontend**,
* un **autoscaling dynamique**.

---

### **6.2 Prérequis**

* Cluster Minikube actif avec :

  * `frontend (Nginx)`,
  * `backend (HTTPD)`,
  * `Ingress activé`.
* Domaine local `local.dev` configuré dans `/etc/hosts`.
* Docker, kubectl et metrics-server opérationnels :

```bash
minikube addons enable metrics-server
```

---

### **6.3 Étape 1 — Vérification initiale**

```bash
kubectl get all -n projet-fil-rouge
kubectl top pods -n projet-fil-rouge
```

**Contexte :**
Vérifie l’état du cluster avant modifications et la collecte de métriques CPU/mémoire.

---

### **6.4 Étape 2 — Rolling Update (mise à jour continue)**

```bash
kubectl set image deployment/frontend nginx=nginx:1.27 -n projet-fil-rouge
kubectl rollout status deployment/frontend -n projet-fil-rouge
kubectl rollout history deployment/frontend -n projet-fil-rouge
```

**Contexte :**
Met à jour le conteneur Nginx vers la version 1.27 sans interruption de service.
`rollout status` montre la progression du remplacement des Pods.

Observation en direct :

```bash
kubectl get pods -l app=frontend -w -n projet-fil-rouge
```

---

### **6.5 Étape 3 — Autoscaling**

```bash
kubectl autoscale deployment frontend -n projet-fil-rouge --cpu-percent=50 --min=1 --max=5
```

**Contexte :**
Crée un HPA sur le frontend.
Le cluster augmentera automatiquement le nombre de Pods si la charge CPU > 50 %.

---

### **6.6 Étape 4 — Simulation de charge**

```bash
kubectl run loadtest --image=busybox --restart=Never -n projet-fil-rouge -- /bin/sh -c \
"while true; do wget -q -O- http://frontend; done"
```

**Contexte :**
Ce conteneur “génère du trafic” pour déclencher le scaling du frontend.
Surveillez l’évolution en temps réel :

```bash
kubectl get hpa -w -n projet-fil-rouge
```

---

### **6.7 Étape 5 — Observation et supervision**

```bash
kubectl top pods -n projet-fil-rouge
kubectl get events --sort-by=.metadata.creationTimestamp | tail
```

**Contexte :**
Permet de visualiser l’utilisation des ressources et les événements récents du cluster.

Affichage graphique :

```bash
minikube dashboard
```

**Contexte :**
Ouvre l’interface graphique de Minikube avec graphiques, métriques et logs en temps réel.

---

### **6.8 Étape 6 — Nettoyage**

```bash
kubectl delete pod loadtest -n projet-fil-rouge
kubectl delete hpa frontend -n projet-fil-rouge
```

**Contexte :**
Arrête le générateur de charge et supprime la règle d’autoscaling.
Le déploiement frontend revient à 1 Pod.

---

### **6.9 Résultats attendus**

* L’application supporte la montée en charge sans interruption.
* Le scaling se déclenche automatiquement.
* Les Rolling Updates se font sans perte de service.
* Les métriques et événements sont visibles via `kubectl top` et le dashboard.

---

## **7. Bonnes pratiques d’administration**

* Mettre à jour régulièrement Kubernetes et les images.
* Surveiller les **quotas et limites de ressources**.
* Utiliser les **namespaces** pour isoler les environnements.
* Sauvegarder les manifests YAML dans Git.
* Mettre en place un **monitoring centralisé** (Prometheus, Grafana, Alertmanager).
* Configurer des alertes pour anticiper les pannes.
