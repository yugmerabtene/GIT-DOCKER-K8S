# **Chapitre 4 — Administration et supervision de Kubernetes**

*(Supervision, logs, métriques, scaling, mises à jour continues)*

---

## **1. Objectifs d'apprentissage**

À la fin de ce chapitre, l'apprenant sera capable de :

* Administrer un cluster Kubernetes en production (inspection, supervision, journalisation).
* Analyser les **logs**, surveiller les **métriques** et détecter les anomalies.
* Gérer les **mises à jour continues** des applications (Rolling Update / Rollback).
* Mettre en œuvre le **scaling automatique** des Pods selon la charge.
* Poursuivre le **projet fil rouge** avec un environnement supervisé et auto-scalable.

---

## **2. Introduction à l'administration du cluster**

### **2.1 Notions fondamentales**

* Kubernetes repose sur un **contrôle continu** : chaque objet est surveillé par un contrôleur.
* L'administration consiste à :

  * Vérifier l'état du cluster et des nœuds.
  * Superviser les Pods et les Services.
  * Gérer les ressources (CPU, mémoire, stockage).
  * Surveiller la santé des applications.

---

### **2.2 Commandes de base d'administration**

> **Objectif** : Inspecter l'état général du cluster — nœuds, Pods, consommation de ressources et événements récents — pour obtenir un aperçu rapide de la santé de l'environnement.
> **Pré-requis** : Un cluster Kubernetes actif (Minikube ou autre) et kubectl configuré avec un contexte valide.

```bash
# Affiche tous les nœuds du cluster avec des détails étendus
# (adresses IP internes, version du système d'exploitation, container runtime)
kubectl get nodes -o wide

# Liste tous les Pods dans tous les namespaces (-A = --all-namespaces)
# Permet de voir les Pods système (kube-system) et applicatifs d'un coup d'œil
kubectl get pods -A

# Affiche la consommation CPU et mémoire de chaque nœud
# Nécessite que metrics-server soit installé et fonctionnel
kubectl top nodes

# Affiche la consommation CPU et mémoire de chaque Pod
# Utile pour identifier les Pods les plus gourmands en ressources
kubectl top pods

# Affiche les détails complets d'un Pod spécifique :
# état, IP, nœud assigné, événements, images utilisées, volumes montés
kubectl describe pod <nom>

# Récupère les événements du cluster triés par timestamp décroissant
# Les 10 derniers événements sont affichés pour repérer erreurs et anomalies
kubectl get events --sort-by=.lastTimestamp | tail
```

> **Résultat attendu** :
> ```
> $ kubectl get nodes -o wide
> NAME       STATUS   ROLES           AGE   VERSION   INTERNAL-IP    OS-IMAGE
> minikube   Ready    control-plane   45d   v1.29.0   192.168.49.2   Ubuntu 22.04
>
> $ kubectl get pods -A
> NAMESPACE       NAME                                READY   STATUS    RESTARTS
> kube-system     coredns-7db6d8ff4d-rk2gj            1/1     Running   0
> kube-system     etcd-minikube                        1/1     Running   0
> kube-system     metrics-server-6d684c7b5-tn4vz       1/1     Running   0
> projet-fil-rouge frontend-5b8c9f7d6-abc12            1/1     Running   0
> projet-fil-rouge backend-7a9d8e6f5-def34             1/1     Running   0
>
> $ kubectl top nodes
> NAME       CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
> minikube   250m         12%    1024Mi          53%
>
> $ kubectl top pods
> NAME                        CPU(cores)   MEMORY(bytes)
> frontend-5b8c9f7d6-abc12    5m           32Mi
> backend-7a9d8e6f5-def34     3m           48Mi
> ```
> **Vérification** : Tous les nœuds doivent être en statut `Ready`. Les Pods doivent être en statut `Running`. Les valeurs CPU/mémoire doivent s'afficher (si `<unknown>`, metrics-server n'est pas encore prêt).

**Contexte :**
Ces commandes sont les fondations de la supervision :

* `kubectl get nodes` : affiche les nœuds du cluster et leur état.
* `kubectl top nodes/pods` : nécessite **metrics-server** et montre l'utilisation CPU/mémoire.
* `kubectl describe pod` : donne les détails (état, IP, événements, images).
* `kubectl get events` : permet de repérer rapidement les erreurs (crash, scheduling…).

---

## **3. Supervision et journalisation**

### **3.1 Les métriques**

* Les métriques représentent l'utilisation **CPU**, **mémoire**, **réseau** et **stockage**.
* Outil intégré : **metrics-server**.
* Les métriques alimentent :

  * les commandes `kubectl top`,
  * les règles d'autoscaling (HPA),
  * les tableaux de bord (Prometheus, Grafana).

**Installation du metrics-server :**

> **Objectif** : Activer le composant metrics-server dans Minikube pour collecter les métriques de ressources (CPU/mémoire) de chaque nœud et Pod.
> **Pré-requis** : Minikube démarré et accessible (`minikube status` doit afficher `Running`).

```bash
# Active l'addon metrics-server fourni par Minikube
# Déploie automatiquement le pod metrics-server dans le namespace kube-system
# La première collecte de métriques prend 1 à 2 minutes
minikube addons enable metrics-server
```

> **Résultat attendu** :
> ```
> 💡  Enabling addon metrics-server
> ✅  addon 'metrics-server' successfully enabled
> ```
> **Vérification** : Le message de succès s'affiche. Vérifier avec `kubectl get pods -n kube-system | grep metrics` que le Pod metrics-server est bien en statut `Running`.

**Contexte :**
Cette commande active l'addon officiel **metrics-server** dans Minikube.
Il collecte les métriques de chaque Pod et nœud en temps réel via l'API Kubelet.

**Vérification :**

> **Objectif** : Confirmer que metrics-server fonctionne correctement en vérifiant que les métriques CPU et mémoire sont collectées et affichées.
> **Pré-requis** : metrics-server activé et en cours d'exécution depuis au moins 1 à 2 minutes.

```bash
# Affiche la consommation CPU et mémoire de chaque nœud
# Si les valeurs s'affichent, metrics-server fonctionne correctement
kubectl top nodes

# Affiche la consommation des Pods dans le namespace du projet fil rouge
# Vérifie que les métriques sont bien collectées au niveau des Pods applicatifs
kubectl top pods -n projet-fil-rouge
```

> **Résultat attendu** :
> ```
> $ kubectl top nodes
> NAME       CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
> minikube   250m         12%    1024Mi          53%
>
> $ kubectl top pods -n projet-fil-rouge
> NAME                        CPU(cores)   MEMORY(bytes)
> frontend-5b8c9f7d6-abc12    5m           32Mi
> backend-7a9d8e6f5-def34     3m           48Mi
> ```
> **Vérification** : Les colonnes CPU et MEMORY affichent des valeurs numériques (pas `<unknown>`). Si `<unknown>` apparaît, attendre 1 à 2 minutes puis relancer.

**Contexte :**
Si les valeurs CPU et mémoire s'affichent, l'addon fonctionne.
Sinon, attendez 1 à 2 minutes pour la première collecte.

---

### **3.2 Les journaux (logs)**

> **Objectif** : Consulter les journaux (logs) d'un Pod unique pour diagnostiquer les erreurs d'application ou vérifier son comportement.
> **Pré-requis** : Le Pod cible doit être en état `Running` ou `CrashLoopBackOff` dans le namespace `projet-fil-rouge`.

```bash
# Affiche les logs complets du Pod spécifié dans le namespace projet-fil-rouge
# Les logs sont récupérés depuis le conteneur principal du Pod
kubectl logs <nom_du_pod> -n projet-fil-rouge
```

> **Résultat attendu** :
> ```
> 192.168.49.1 - - [21/Jun/2026:10:15:32 +0000] "GET / HTTP/1.1" 200 615 "-" "curl/7.88.1"
> 192.168.49.1 - - [21/Jun/2026:10:15:45 +0000] "GET /index.html HTTP/1.1" 200 615 "-" "Mozilla/5.0"
> ```
> **Vérification** : Les lignes de logs s'affichent. Pour Nginx, on voit les requêtes HTTP avec leur code de réponse (200, 404, etc.).

**Contexte :**
Affiche les logs d'un Pod unique.
Les journaux sont essentiels pour diagnostiquer les erreurs d'application.

> **Objectif** : Consulter les logs d'un conteneur spécifique dans un Pod multi-conteneurs (sidecar pattern).
> **Pré-requis** : Le Pod doit contenir au moins deux conteneurs. Connaître le nom exact du conteneur cible.

```bash
# Cible un conteneur spécifique (-c) dans un Pod multi-conteneurs
# Remplacer <nom_du_conteneur> par le nom défini dans le manifest YAML
kubectl logs <nom_du_pod> -c <nom_du_conteneur> -n projet-fil-rouge
```

> **Résultat attendu** :
> ```
> [Mon Jun 21 10:20:00 2026] [core:notice] AH00094: Command line: 'httpd -D FOREGROUND'
> 192.168.49.2 - - [21/Jun/2026:10:20:15 +0000] "GET /api/health HTTP/1.1" 200 15
> ```
> **Vérification** : Seuls les logs du conteneur spécifié sont affichés, pas ceux des autres conteneurs du Pod.

**Contexte :**
Pour les Pods multi-conteneurs, cette commande permet de cibler un conteneur spécifique.

> **Objectif** : Accéder aux logs des composants système de Kubernetes (scheduler, controller-manager, etc.) pour diagnostiquer des problèmes au niveau du cluster.
> **Pré-requis** : Connaître le nom du Pod système cible dans le namespace `kube-system`.

```bash
# Affiche les logs d'un composant système du namespace kube-system
# Utile pour diagnostiquer des problèmes de scheduling, de contrôleur, etc.
kubectl -n kube-system logs <pod>
```

> **Résultat attendu** :
> ```
> I0621 10:00:00.123456  1 scheduler.go:604] "Successfully bound pod" pod="projet-fil-rouge/frontend-5b8c9f7d6-abc12"
> I0621 10:00:01.234567  1 eventhandlers.go:167] "Adding eventHandler for pod"
> ```
> **Vérification** : Les logs du composant système s'affichent. Rechercher les niveaux `E` (Error) ou `W` (Warning) pour identifier des anomalies.

**Contexte :**
Permet d'analyser les logs des composants système (scheduler, controller, etc.).

> **Objectif** : Suivre les logs d'un Pod en continu (mode "follow") pour observer le comportement en temps réel, par exemple lors d'un test ou d'un déploiement.
> **Pré-requis** : Le Pod doit être en cours d'exécution. Utiliser `Ctrl+C` pour interrompre le suivi.

```bash
# Le flag -f (follow) maintient la connexion ouverte et affiche les nouveaux logs en temps réel
# Idéal pour observer les requêtes HTTP arrivant sur un backend lors d'un test
kubectl logs -f <nom_du_pod> -n projet-fil-rouge
```

> **Résultat attendu** :
> ```
> 192.168.49.1 - - [21/Jun/2026:10:25:00 +0000] "GET / HTTP/1.1" 200 615
> 192.168.49.1 - - [21/Jun/2026:10:25:05 +0000] "GET /style.css HTTP/1.1" 200 123
> 192.168.49.1 - - [21/Jun/2026:10:25:10 +0000] "GET /api/data HTTP/1.1" 200 89
> ... (les nouvelles lignes apparaissent en temps réel)
> ```
> **Vérification** : De nouvelles lignes de logs apparaissent au fur et à mesure. Faire des requêtes depuis un autre terminal pour voir les logs défiler. `Ctrl+C` pour quitter.

**Contexte :**
`-f` ("follow") permet un suivi continu des logs en temps réel (utile pour observer un backend HTTP).

---

### **3.3 Les événements**

> **Objectif** : Lister tous les événements du cluster triés par ordre chronologique pour identifier les erreurs de scheduling, les crashs de Pods, ou tout autre incident récent.
> **Pré-requis** : Un cluster Kubernetes actif avec des Pods déployés.

```bash
# Liste tous les événements du cluster triés par date de création
# Permet de voir dans l'ordre : Scheduled, Pulled, Started, Killing, FailedScheduling, etc.
kubectl get events --sort-by=.metadata.creationTimestamp
```

> **Résultat attendu** :
> ```
> LAST SEEN   TYPE     REASON      OBJECT                          MESSAGE
> 5m          Normal   Scheduled   pod/frontend-5b8c9f7d6-abc12    Successfully assigned projet-fil-rouge/frontend-5b8c9f7d6-abc12 to minikube
> 5m          Normal   Pulling     pod/frontend-5b8c9f7d6-abc12    Pulling image "nginx:1.26"
> 4m          Normal   Pulled      pod/frontend-5b8c9f7d6-abc12    Successfully pulled image "nginx:1.26"
> 4m          Normal   Created     pod/frontend-5b8c9f7d6-abc12    Created container nginx
> 4m          Normal   Started     pod/frontend-5b8c9f7d6-abc12    Started container nginx
> ```
> **Vérification** : Les événements s'affichent dans l'ordre chronologique. Les événements de type `Warning` indiquent des problèmes potentiels (FailedScheduling, BackOff, OOMKilled, etc.).

**Contexte :**
Liste chronologiquement les événements récents du cluster (créations, suppressions, erreurs).

**Types d'événements fréquents :**

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
* En cas d'échec, un **Rollback** restaure la version précédente.

---

### **4.2 Paramètres importants**

> **Objectif** : Configurer la stratégie de déploiement d'un Deployment pour contrôler le rythme du Rolling Update — combien de Pods supplémentaires créer et combien de Pods peuvent être indisponibles simultanément.
> **Pré-requis** : Un Deployment existant dans un manifest YAML. Cette section s'insère dans le `spec` du Deployment.

```yaml
spec:
  strategy:
    # Type de stratégie : RollingUpdate remplace les Pods progressivement
    # (l'alternative est Recreate qui détruit tous les Pods avant de recréer)
    type: RollingUpdate
    rollingUpdate:
      # Nombre maximum de Pods supplémentaires pouvant être créés pendant la mise à jour
      # Peut être un nombre entier (1) ou un pourcentage (25%) du total souhaité
      maxSurge: 1
      # Nombre maximum de Pods pouvant être indisponibles pendant la mise à jour
      # Assure qu'au moins (replicas - maxUnavailable) Pods restent disponibles
      maxUnavailable: 1
```

> **Résultat attendu** :
> ```
> # Avec 3 réplicas, maxSurge=1 et maxUnavailable=1 :
> # Pendant la mise à jour, Kubernetes peut avoir jusqu'à 4 Pods (3+1)
> # et au minimum 2 Pods disponibles (3-1) à tout moment
> ```
> **Vérification** : Appliquer le manifest avec `kubectl apply -f deployment.yaml` puis observer `kubectl get pods -w` : pendant le rollout, le nombre total de Pods ne dépasse jamais `replicas + maxSurge`.

**Contexte :**
Ces paramètres indiquent que Kubernetes peut créer **1 Pod supplémentaire** au maximum pendant la mise à jour et qu'au plus **1 Pod peut être indisponible** à un instant donné.

---

### **4.3 Commandes associées**

> **Objectif** : Exécuter un Rolling Update sur un Deployment, suivre sa progression, consulter l'historique des révisions et effectuer un rollback en cas de problème.
> **Pré-requis** : Un Deployment `frontend` existant dans le namespace `projet-fil-rouge` avec un conteneur nommé `nginx`.

```bash
# Met à jour l'image du conteneur 'nginx' dans le Deployment 'frontend'
# Remplace nginx par la version 1.27 — déclenche automatiquement un Rolling Update
kubectl set image deployment/frontend nginx=nginx:1.27 -n projet-fil-rouge

# Affiche la progression du déploiement en temps réel
# Bloque jusqu'à ce que le rollout soit terminé ou échoue
kubectl rollout status deployment/frontend -n projet-fil-rouge

# Liste l'historique des révisions du Deployment
# Chaque modification d'image ou de configuration crée une nouvelle révision
kubectl rollout history deployment/frontend -n projet-fil-rouge

# Restaure la version précédente du Deployment (rollback)
# Utiliser en cas de problème après une mise à jour (image défectueuse, config erronée)
kubectl rollout undo deployment/frontend -n projet-fil-rouge
```

> **Résultat attendu** :
> ```
> $ kubectl set image deployment/frontend nginx=nginx:1.27 -n projet-fil-rouge
> deployment.apps/frontend image updated
>
> $ kubectl rollout status deployment/frontend -n projet-fil-rouge
> deployment "frontend" successfully rolled out
>
> $ kubectl rollout history deployment/frontend -n projet-fil-rouge
> REVISION  CHANGE-CAUSE
> 1         <none>
> 2         <none>
> 3         <none>
>
> $ kubectl rollout undo deployment/frontend -n projet-fil-rouge
> deployment.apps/frontend rolled back
> ```
> **Vérification** : Après `set image`, les nouveaux Pods apparaissent avec la nouvelle image (`kubectl describe pod`). Après `undo`, les Pods reviennent à l'image précédente. Chaque `rollout history` montre une nouvelle révision.

**Contexte :**
Ces commandes gèrent les déploiements en continu :

* `set image` : met à jour l'image d'un conteneur.
* `rollout status` : affiche la progression en direct.
* `rollout history` : liste les versions.
* `rollout undo` : restaure la version précédente en cas de problème.

---

## **5. Autoscaling (mise à l'échelle automatique)**

### **5.1 Types de scalabilité**

* **HPA (Horizontal Pod Autoscaler)** : augmente le nombre de Pods selon la charge.
* **VPA (Vertical Pod Autoscaler)** : ajuste les ressources d'un Pod (CPU/RAM).
* **Cluster Autoscaler** : ajoute ou retire des nœuds (non applicable dans Minikube).

---

### **5.2 Création d'un HPA**

> **Objectif** : Créer un Horizontal Pod Autoscaler (HPA) qui ajuste automatiquement le nombre de réplicas du Deployment `frontend` en fonction de l'utilisation CPU.
> **Pré-requis** : Le Deployment `frontend` doit exister dans `projet-fil-rouge`. Metrics-server doit être actif (`kubectl top pods` doit fonctionner). Le Deployment doit avoir des `resources.requests` définis pour le CPU.

```bash
# Crée un HPA sur le Deployment 'frontend' dans le namespace projet-fil-rouge
# --cpu-percent=50 : seuil CPU cible — le scaling se déclenche quand la moyenne CPU dépasse 50%
# --min=1 : nombre minimum de réplicas (ne descend jamais en dessous de 1)
# --max=5 : nombre maximum de réplicas (plafond de scaling)
kubectl autoscale deployment frontend -n projet-fil-rouge --cpu-percent=50 --min=1 --max=5
```

> **Résultat attendu** :
> ```
> horizontalpodautoscaler.autoscaling/frontend autoscaled
> ```
> **Vérification** : `kubectl get hpa -n projet-fil-rouge` doit afficher l'HPA avec les valeurs TARGETS (50%), MIN (1) et MAX (5).

**Contexte :**
Crée un **autoscaler horizontal** sur le déploiement `frontend`.
Si la charge CPU moyenne dépasse **50 %**, Kubernetes crée automatiquement de nouveaux Pods (jusqu'à 5).

---

### **5.3 Vérification**

> **Objectif** : Vérifier la configuration de l'HPA et observer les métriques en temps réel (CPU cible vs CPU actuel) pour s'assurer que l'autoscaler fonctionne correctement.
> **Pré-requis** : Un HPA créé sur le Deployment `frontend` dans le namespace `projet-fil-rouge`.

```bash
# Affiche un résumé de tous les HPA du namespace
# Colonnes clés : TARGETS (utilisation actuelle / cible), MINPODS, MAXPODS, REPLICAS
kubectl get hpa -n projet-fil-rouge

# Affiche les détails complets de l'HPA 'frontend'
# Inclut les événements de scaling, les conditions et les métriques configurées
kubectl describe hpa frontend -n projet-fil-rouge
```

> **Résultat attendu** :
> ```
> $ kubectl get hpa -n projet-fil-rouge
> NAME       REFERENCE             TARGETS   MINPODS   MAXPODS   REPLICAS
> frontend   Deployment/frontend   5%/50%    1         5         1
>
> $ kubectl describe hpa frontend -n projet-fil-rouge
> Name:                                                  frontend
> Namespace:                                             projet-fil-rouge
> Reference:                                             Deployment/frontend
> Metrics:                                               ( current / target )
>   resource cpu on pods  (as a percentage of request):  2% (1m) / 50%
> Min replicas:                                          1
> Max replicas:                                          5
> Deployment pods:                                       1 current, 1 desired
> ```
> **Vérification** : La colonne TARGETS affiche le ratio CPU actuel/cible (ex: `5%/50%`). Si la valeur actuelle est proche de 0%, c'est normal au repos. REPLICAS indique le nombre de Pods actifs.

**Contexte :**
Permet de vérifier les seuils configurés et l'évolution en temps réel (CPU target / current).

---

### **5.4 Simulation de charge**

> **Objectif** : Générer une charge CPU artificielle sur le service `frontend` en envoyant des requêtes HTTP en boucle infinie, afin de déclencher le scaling automatique de l'HPA.
> **Pré-requis** : Le Deployment `frontend` et son Service doivent être actifs. Un HPA doit être configuré sur le frontend. Le namespace `projet-fil-rouge` doit exister.

```bash
# Crée un Pod temporaire 'loadtest' basé sur l'image busybox (légère)
# --restart=Never : le Pod ne redémarre pas automatiquement (comportement de Job)
# La commande exécute une boucle infinie de requêtes wget vers le service frontend
# Cela génère une charge CPU significative pour tester l'autoscaling
kubectl run loadtest --image=busybox --restart=Never -n projet-fil-rouge -- /bin/sh -c \
"while true; do wget -q -O- http://frontend; done"
```

> **Résultat attendu** :
> ```
> pod/loadtest created
> ```
> **Vérification** : `kubectl get pod loadtest -n projet-fil-rouge` doit afficher le Pod en statut `Running`. Attendre 1 à 2 minutes pour que l'HPA détecte la hausse de CPU.

**Contexte :**
Ce Pod exécute une boucle infinie envoyant des requêtes HTTP vers `frontend`.
Cela génère de la charge CPU simulée pour déclencher le scaling.

---

### **5.5 Observation**

> **Objectif** : Observer en temps réel le comportement de l'HPA (augmentation du nombre de réplicas) et l'apparition de nouveaux Pods frontend en réponse à la charge générée.
> **Pré-requis** : Le Pod `loadtest` doit être en cours d'exécution. L'HPA doit être configuré. Attendre 1 à 2 minutes après le lancement du loadtest.

```bash
# Surveille l'HPA en continu (-w = watch)
# Observez la colonne REPLICAS augmenter et TARGETS se rapprocher de 50%
kubectl get hpa -w -n projet-fil-rouge

# Liste les Pods frontend pour voir les nouveaux réplicas apparaître
# Le label app=frontend filtre uniquement les Pods du Deployment frontend
kubectl get pods -l app=frontend -n projet-fil-rouge
```

> **Résultat attendu** :
> ```
> $ kubectl get hpa -w -n projet-fil-rouge
> NAME       REFERENCE             TARGETS    MINPODS   MAXPODS   REPLICAS
> frontend   Deployment/frontend   78%/50%    1         5         2
> frontend   Deployment/frontend   85%/50%    1         5         3
> frontend   Deployment/frontend   62%/50%    1         5         4
>
> $ kubectl get pods -l app=frontend -n projet-fil-rouge
> NAME                        READY   STATUS    RESTARTS   AGE
> frontend-5b8c9f7d6-abc12    1/1     Running   0          10m
> frontend-5b8c9f7d6-xyz99    1/1     Running   0          1m
> frontend-5b8c9f7d6-qrs45    1/1     Running   0          30s
> ```
> **Vérification** : Le nombre de REPLICAS dans l'HPA augmente progressivement. De nouveaux Pods frontend apparaissent avec un AGE récent. Une fois la charge stabilisée, le nombre de Pods se stabilise.

**Contexte :**
Le flag `-w` ("watch") actualise en continu.
Vous verrez le nombre de Pods augmenter lorsque la charge CPU dépassera le seuil défini.

---

## **6. LAB – Projet Fil Rouge (Phase 3)**

### **Supervision, mise à jour et autoscaling de l'application web**

---

### **6.1 Objectif**

Poursuivre l'application du **Chapitre 3** en ajoutant :

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

> **Objectif** : S'assurer que metrics-server est activé dans Minikube avant de commencer le LAB, afin que les commandes `kubectl top` et l'HPA fonctionnent.
> **Pré-requis** : Minikube démarré (`minikube status` affiche `Running`).

```bash
# Active l'addon metrics-server (idempotent — sans effet si déjà activé)
# Nécessaire pour les métriques CPU/mémoire et le fonctionnement de l'HPA
minikube addons enable metrics-server
```

> **Résultat attendu** :
> ```
> 💡  Enabling addon metrics-server
> ✅  addon 'metrics-server' successfully enabled
> ```
> **Vérification** : Si l'addon était déjà actif, le message confirme son état. Attendre 1 à 2 minutes avant d'utiliser `kubectl top`.

---

### **6.3 Étape 1 — Vérification initiale**

> **Objectif** : Faire un état des lieux complet du namespace `projet-fil-rouge` avant d'appliquer les modifications du LAB — vérifier que tous les Pods sont opérationnels et que les métriques sont collectées.
> **Pré-requis** : Les Deployments `frontend` et `backend` doivent être déployés depuis le Chapitre 3. Metrics-server doit être actif.

```bash
# Affiche toutes les ressources du namespace (Pods, Services, Deployments, ReplicaSets)
# Permet de vérifier en un coup d'œil que tout est en place et en état Running
kubectl get all -n projet-fil-rouge

# Affiche la consommation CPU et mémoire de chaque Pod du namespace
# Confirme que metrics-server collecte bien les données
kubectl top pods -n projet-fil-rouge
```

> **Résultat attendu** :
> ```
> $ kubectl get all -n projet-fil-rouge
> NAME                            READY   STATUS    RESTARTS   AGE
> pod/frontend-5b8c9f7d6-abc12    1/1     Running   0          2d
> pod/backend-7a9d8e6f5-def34     1/1     Running   0          2d
>
> NAME               TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
> service/frontend   ClusterIP   10.96.100.50    <none>        80/TCP    2d
> service/backend    ClusterIP   10.96.100.51    <none>        80/TCP    2d
>
> NAME                       READY   UP-TO-DATE   AVAILABLE   AGE
> deployment.apps/frontend   1/1     1            1           2d
> deployment.apps/backend    1/1     1            1           2d
>
> $ kubectl top pods -n projet-fil-rouge
> NAME                        CPU(cores)   MEMORY(bytes)
> frontend-5b8c9f7d6-abc12    5m           32Mi
> backend-7a9d8e6f5-def34     3m           48Mi
> ```
> **Vérification** : Tous les Pods sont en `Running` (1/1 READY). Les Services ont des ClusterIP assignés. Les métriques CPU/mémoire s'affichent (pas `<unknown>`).

**Contexte :**
Vérifie l'état du cluster avant modifications et la collecte de métriques CPU/mémoire.

---

### **6.4 Étape 2 — Rolling Update (mise à jour continue)**

> **Objectif** : Mettre à jour l'image Nginx du Deployment `frontend` vers la version 1.27 sans interruption de service, puis vérifier la progression et l'historique des révisions.
> **Pré-requis** : Le Deployment `frontend` existe dans `projet-fil-rouge` avec un conteneur nommé `nginx` utilisant une version antérieure (ex: nginx:1.26).

```bash
# Met à jour l'image du conteneur 'nginx' vers nginx:1.27
# Déclenche un Rolling Update : les anciens Pods sont remplacés progressivement
kubectl set image deployment/frontend nginx=nginx:1.27 -n projet-fil-rouge

# Bloque et affiche la progression du rollout jusqu'à son terme
# Se termine quand tous les nouveaux Pods sont Ready et les anciens terminés
kubectl rollout status deployment/frontend -n projet-fil-rouge

# Affiche l'historique des révisions pour tracer les changements effectués
# Chaque révision correspond à une modification du Deployment
kubectl rollout history deployment/frontend -n projet-fil-rouge
```

> **Résultat attendu** :
> ```
> $ kubectl set image deployment/frontend nginx=nginx:1.27 -n projet-fil-rouge
> deployment.apps/frontend image updated
>
> $ kubectl rollout status deployment/frontend -n projet-fil-rouge
> Waiting for deployment "frontend" rollout to finish: 1 out of 2 new replicas have been updated...
> deployment "frontend" successfully rolled out
>
> $ kubectl rollout history deployment/frontend -n projet-fil-rouge
> REVISION  CHANGE-CAUSE
> 1         <none>
> 2         <none>
> ```
> **Vérification** : Le message "successfully rolled out" confirme la mise à jour. `kubectl describe pod <nouveau-pod>` montre l'image `nginx:1.27`.

**Contexte :**
Met à jour le conteneur Nginx vers la version 1.27 sans interruption de service.
`rollout status` montre la progression du remplacement des Pods.

Observation en direct :

> **Objectif** : Observer en temps réel le cycle de vie des Pods frontend pendant le Rolling Update — voir les anciens Pods se terminer et les nouveaux démarrer.
> **Pré-requis** : Cette commande doit être lancée avant ou pendant le `kubectl set image` pour voir le changement en direct.

```bash
# Surveille les Pods frontend en continu (-w = watch)
# Observez les anciens Pods passer en Terminating et les nouveaux en ContainerCreating/Running
kubectl get pods -l app=frontend -w -n projet-fil-rouge
```

> **Résultat attendu** :
> ```
> NAME                        READY   STATUS              RESTARTS   AGE
> frontend-5b8c9f7d6-abc12    1/1     Running             0          2d
> frontend-8d4e7f2a1-ghi67    0/1     ContainerCreating   0          0s
> frontend-8d4e7f2a1-ghi67    1/1     Running             0          5s
> frontend-5b8c9f7d6-abc12    1/1     Terminating         0          2d
> ```
> **Vérification** : Un nouveau Pod apparaît (ContainerCreating → Running) avant que l'ancien ne soit terminé (Terminating). C'est le principe du Rolling Update : zéro interruption.

---

### **6.5 Étape 3 — Autoscaling**

> **Objectif** : Créer un Horizontal Pod Autoscaler sur le Deployment `frontend` pour que le nombre de Pods s'adapte automatiquement à la charge CPU.
> **Pré-requis** : Le Deployment `frontend` doit avoir des `resources.requests.cpu` définis. Metrics-server doit être actif.

```bash
# Crée un HPA avec les paramètres suivants :
# - cpu-percent=50 : seuil de déclenchement du scaling
# - min=1 : au moins 1 Pod toujours actif
# - max=5 : plafond de 5 Pods maximum
kubectl autoscale deployment frontend -n projet-fil-rouge --cpu-percent=50 --min=1 --max=5
```

> **Résultat attendu** :
> ```
> horizontalpodautoscaler.autoscaling/frontend autoscaled
> ```
> **Vérification** : `kubectl get hpa -n projet-fil-rouge` affiche l'HPA avec MINPODS=1, MAXPODS=5 et TARGETS=`<unknown>/50%` (les métriques apparaîtront après ~30s).

**Contexte :**
Crée un HPA sur le frontend.
Le cluster augmentera automatiquement le nombre de Pods si la charge CPU > 50 %.

---

### **6.6 Étape 4 — Simulation de charge**

> **Objectif** : Générer une charge HTTP artificielle sur le frontend pour provoquer le scaling automatique et observer le comportement de l'HPA en conditions réelles.
> **Pré-requis** : L'HPA doit être créé. Le Service `frontend` doit être accessible. Le Pod `loadtest` ne doit pas déjà exister (le supprimer d'abord si nécessaire).

```bash
# Crée un Pod 'loadtest' qui envoie des requêtes HTTP en boucle infinie
# vers le service frontend pour simuler une forte charge utilisateur
# --restart=Never évite le redémarrage automatique du Pod
kubectl run loadtest --image=busybox --restart=Never -n projet-fil-rouge -- /bin/sh -c \
"while true; do wget -q -O- http://frontend; done"
```

> **Résultat attendu** :
> ```
> pod/loadtest created
> ```
> **Vérification** : `kubectl get pod loadtest -n projet-fil-rouge` affiche le Pod en `Running`. Attendre 1 à 2 minutes pour que l'HPA réagisse.

**Contexte :**
Ce conteneur "génère du trafic" pour déclencher le scaling du frontend.
Surveillez l'évolution en temps réel :

> **Objectif** : Surveiller en continu l'HPA pour observer l'augmentation automatique du nombre de réplicas en réponse à la charge générée par le Pod `loadtest`.
> **Pré-requis** : Le Pod `loadtest` doit être en cours d'exécution depuis au moins 1 minute.

```bash
# Surveille l'HPA en continu — observez REPLICAS augmenter
# et TARGETS se rapprocher puis dépasser le seuil de 50%
kubectl get hpa -w -n projet-fil-rouge
```

> **Résultat attendu** :
> ```
> NAME       REFERENCE             TARGETS    MINPODS   MAXPODS   REPLICAS
> frontend   Deployment/frontend   12%/50%    1         5         1
> frontend   Deployment/frontend   65%/50%    1         5         2
> frontend   Deployment/frontend   72%/50%    1         5         3
> frontend   Deployment/frontend   55%/50%    1         5         3
> ```
> **Vérification** : Le nombre de REPLICAS augmente quand TARGETS dépasse 50%. Il se stabilise quand la charge est répartie sur suffisamment de Pods.

---

### **6.7 Étape 5 — Observation et supervision**

> **Objectif** : Visualiser l'utilisation des ressources de chaque Pod et les événements récents du cluster pour analyser le comportement du scaling et détecter d'éventuelles anomalies.
> **Pré-requis** : Le scaling doit être en cours ou terminé. Metrics-server doit être actif.

```bash
# Affiche la consommation CPU et mémoire de chaque Pod
# Permet de comparer la charge entre les différents réplicas du frontend
kubectl top pods -n projet-fil-rouge

# Affiche les 10 derniers événements triés par timestamp
# Utile pour voir les événements de scaling (SuccessfulRescale)
kubectl get events --sort-by=.metadata.creationTimestamp | tail
```

> **Résultat attendu** :
> ```
> $ kubectl top pods -n projet-fil-rouge
> NAME                        CPU(cores)   MEMORY(bytes)
> frontend-8d4e7f2a1-ghi67    45m          35Mi
> frontend-8d4e7f2a1-jkl89    42m          33Mi
> frontend-8d4e7f2a1-mno12    38m          31Mi
> backend-7a9d8e6f5-def34     3m           48Mi
> loadtest                    1m           2Mi
>
> $ kubectl get events --sort-by=.metadata.creationTimestamp | tail
> 2m    Normal   SuccessfulRescale   deployment/frontend   New size: 2; reason: cpu resource utilization (percentage of request) above target
> 1m    Normal   SuccessfulRescale   deployment/frontend   New size: 3; reason: cpu resource utilization (percentage of request) above target
> ```
> **Vérification** : Les métriques montrent une charge répartie entre les réplicas. Les événements `SuccessfulRescale` confirment que l'HPA a bien déclenché le scaling.

**Contexte :**
Permet de visualiser l'utilisation des ressources et les événements récents du cluster.

Affichage graphique :

> **Objectif** : Ouvrir le tableau de bord graphique de Kubernetes (Dashboard) pour visualiser les métriques, logs et état du cluster via une interface web intuitive.
> **Pré-requis** : Minikube en cours d'exécution. L'addon dashboard est généralement activé par défaut.

```bash
# Ouvre le Dashboard Kubernetes dans le navigateur par défaut
# Fournit une vue graphique des Pods, Deployments, Services, métriques et logs
minikube dashboard
```

> **Résultat attendu** :
> ```
> 💡  Enabling dashboard ...
> 🌟  Opening Kubernetes dashboard in the default browser...
>     http://127.0.0.1:XXXXX/api/v1/namespaces/kubernetes-dashboard/services/http:kubernetes-dashboard:/proxy/
> ```
> **Vérification** : Le navigateur s'ouvre automatiquement sur le Dashboard. Les namespaces, Pods et métriques sont visibles. Utiliser `Ctrl+C` dans le terminal pour fermer le tunnel.

**Contexte :**
Ouvre l'interface graphique de Minikube avec graphiques, métriques et logs en temps réel.

---

### **6.8 Étape 6 — Nettoyage**

> **Objectif** : Nettoyer les ressources temporaires créées pendant le LAB — supprimer le Pod de test de charge et la règle d'autoscaling pour revenir à l'état initial.
> **Pré-requis** : Le LAB doit être terminé. Le Pod `loadtest` et l'HPA `frontend` doivent exister dans `projet-fil-rouge`.

```bash
# Supprime le Pod de test de charge (arrête la génération de trafic)
kubectl delete pod loadtest -n projet-fil-rouge

# Supprime la règle HPA (le Deployment frontend revient à 1 réplica)
# Les Pods excédentaires seront progressivement terminés
kubectl delete hpa frontend -n projet-fil-rouge
```

> **Résultat attendu** :
> ```
> $ kubectl delete pod loadtest -n projet-fil-rouge
> pod "loadtest" deleted
>
> $ kubectl delete hpa frontend -n projet-fil-rouge
> horizontalpodautoscaler.autoscaling "frontend" deleted
> ```
> **Vérification** : `kubectl get pods -n projet-fil-rouge` ne montre plus le Pod `loadtest`. `kubectl get hpa -n projet-fil-rouge` n'affiche plus d'HPA. Le frontend revient à 1 seul réplica après quelques secondes.

**Contexte :**
Arrête le générateur de charge et supprime la règle d'autoscaling.
Le déploiement frontend revient à 1 Pod.

---

### **6.9 Résultats attendus**

* L'application supporte la montée en charge sans interruption.
* Le scaling se déclenche automatiquement.
* Les Rolling Updates se font sans perte de service.
* Les métriques et événements sont visibles via `kubectl top` et le dashboard.

---

## **7. Bonnes pratiques d'administration**

* Mettre à jour régulièrement Kubernetes et les images.
* Surveiller les **quotas et limites de ressources**.
* Utiliser les **namespaces** pour isoler les environnements.
* Sauvegarder les manifests YAML dans Git.
* Mettre en place un **monitoring centralisé** (Prometheus, Grafana, Alertmanager).
* Configurer des alertes pour anticiper les pannes.