# Chapitre 7 — Configuration & Secrets

*(ConfigMaps, Secrets, Downward API, volumes projetés, imagePullSecrets, chiffrement)*

---

## 1. Objectifs d'apprentissage

À la fin de ce chapitre, vous serez capable de :

1. Distinguer **configuration** et **code** selon les principes Twelve-Factor.
2. Créer et consommer des **ConfigMaps** (fichiers, variables d'environnement, volumes).
3. Créer et consommer des **Secrets** (Opaque, TLS, dockerconfigjson, etc.).
4. Utiliser la **Downward API** pour injecter des métadonnées Pod/ressources.
5. Combiner ConfigMaps/Secrets/Downward API en **volume projeté**.
6. Gérer les **imagePullSecrets** et l'authentification aux registres.
7. Déployer des configurations de manière **sûre** (RBAC, chiffrement at-rest, rotation).
8. Mettre en place un **cycle de vie** de configuration (versioning Git, rechargement, checksum rollout).

---

## 2. Principes fondamentaux

1. **Séparation config/code** : la configuration doit vivre hors des images.
2. **Portabilité** : même image, configs différentes par environnement (dev, staging, prod).
3. **Sources de vérité** : configurations versionnées (Git), déployées par manifestes.
4. **Sécurité** : Secrets jamais en clair dans Git; chiffrement côté API Server et contrôles d'accès (RBAC).
5. **Observabilité** : toute modification de config doit être traçable (audit, events).

---

## 3. ConfigMaps

### 3.1 Rôle et cas d'usage

* Stocker des **données non sensibles** : variables, fichiers de configuration, templates.
* Injecter dans les Pods via :

  * **variables d'environnement** (`env`, `envFrom`),
  * **volumes** (fichiers montés),
  * références directes dans les champs supportés.

### 3.2 Structure et limites

* Clés/valeurs dans `data:` (texte) ou `binaryData:` (base64 brut).
* Taille maximale d'un objet: environ 1 MiB (lié à etcd).
* Option **immutable** pour figer un ConfigMap en production :

> **Objectif** : Rendre le ConfigMap immuable après création, empêchant toute modification ultérieure de ses données.
> **Pre-requis** : Le ConfigMap doit déjà exister ou être créé avec ce champ ; une fois `immutable: true`, les champs `data` et `binaryData` ne peuvent plus être modifiés.

```yaml
  # Marque le ConfigMap comme immuable : aucune mise à jour de data/binaryData ne sera acceptée
  immutable: true
```

> **Resultat attendu** :
> ```
> # Toute tentative de modification retournera une erreur :
> # The ConfigMap "mon-config" is invalid: data: Forbidden: field is immutable when `immutable` is set
> ```
> **Verification** : Tenter `kubectl edit configmap mon-config` et modifier une valeur → l'API Server rejette la modification.

### 3.3 Consommation

* **env** (clé à clé) ou **envFrom** (tout le map).
* **volume + subPath** pour monter un fichier précis (ex. `default.conf` NGINX).
* Les fichiers montés se mettent à jour au fil de l'eau, mais la plupart des applications nécessitent un **reload** ou un **rollout**.

---

## 4. Secrets

### 4.1 Rôle et types

* Données **sensibles** : mots de passe, clés API, certificats.
* Types courants :

  * `Opaque` (par défaut, paires clé/valeur encodées base64),
  * `kubernetes.io/tls` (certificat/clé),
  * `kubernetes.io/dockerconfigjson` (auth registre),
  * `kubernetes.io/basic-auth`, `kubernetes.io/ssh-auth`, etc.

### 4.2 Important : encodage vs chiffrement

* Les valeurs sont **encodées en base64**, ce n'est pas du chiffrement.
* Activer le **chiffrement at-rest** côté API Server en production (section 9.3).

### 4.3 Consommation

* Comme les ConfigMaps : **env**, **envFrom**, **volume**.
* Les **variables d'environnement** sont évaluées au **démarrage** du Pod (pas mises à jour dynamiquement).
* En volume, l'OS voit des fichiers; votre application doit recharger si nécessaire.

### 4.4 imagePullSecrets

* Authentifier les pulls d'images private registry :

> **Objectif** : Créer un Secret de type `docker-registry` permettant au cluster de s'authentifier auprès d'un registre d'images privé pour pull les images.
> **Pre-requis** : Avoir un cluster Kubernetes fonctionnel, un namespace `projet-fil-rouge` existant, et disposer des identifiants du registre privé (URL, utilisateur, mot de passe, email).

```bash
  # Crée un Secret de type docker-registry nommé 'regcred'
  kubectl create secret docker-registry regcred \
    --docker-server=REGISTRY_URL \       # URL du registre (ex: https://index.docker.io/v1/)
    --docker-username=USER \             # Nom d'utilisateur du registre
    --docker-password=PASS \             # Mot de passe du registre
    --docker-email=you@example.com \     # Email associé au compte registre
    -n projet-fil-rouge                  # Namespace cible
```

> **Resultat attendu** :
> ```
> secret/regcred created
> ```
> **Verification** : `kubectl get secret regcred -n projet-fil-rouge -o jsonpath='{.type}'` doit retourner `kubernetes.io/dockerconfigjson`.

* Référence dans `spec.imagePullSecrets` ou lier au **ServiceAccount**.

---

## 5. Downward API

Injecter des **métadonnées** du Pod sans les coder en dur :

* En variables d'environnement :

> **Objectif** : Exposer les métadonnées du Pod (nom, limites CPU) comme variables d'environnement via la Downward API, sans les coder en dur.
> **Pre-requis** : Un Pod en cours d'exécution ; le champ `fieldRef` référence des champs du Pod spec, et `resourceFieldRef` référence les ressources (limits/requests).

```yaml
  env:
  - name: POD_NAME                      # Variable exposant le nom du Pod
    valueFrom:
      fieldRef:
        fieldPath: metadata.name        # Chemin vers le nom du Pod dans les métadonnées
  - name: CPU_LIMITS                    # Variable exposant la limite CPU du conteneur
    valueFrom:
      resourceFieldRef:
        resource: limits.cpu            # Référence la limite CPU définie dans resources
```

> **Resultat attendu** :
> ```
> # Dans le conteneur :
> # echo $POD_NAME   → frontend-6d4f8b7c5-abc12
> # echo $CPU_LIMITS → 500m
> ```
> **Verification** : `kubectl exec <pod> -- printenv | grep -E 'POD_NAME|CPU_LIMITS'` doit afficher les valeurs dynamiques.

* En volume `downwardAPI` (fichiers contenant labels, annotations, ressources).

---

## 6. Volumes projetés (Projected Volumes)

Combiner plusieurs sources en un **seul montage** :

> **Objectif** : Fusionner plusieurs sources (ConfigMap, Secret, Downward API) en un unique volume monté dans le Pod, simplifiant la gestion des fichiers de configuration.
> **Pre-requis** : Les ressources référencées doivent exister dans le même namespace : ConfigMap `frontend-conf`, Secret `api-key`.

```yaml
  volumes:
  - name: app-config                     # Nom du volume (référencé dans volumeMounts)
    projected:                           # Type projected : combine plusieurs sources
      sources:
      - configMap:                       # Source 1 : ConfigMap
          name: frontend-conf            # Nom du ConfigMap à monter
      - secret:                          # Source 2 : Secret
          name: api-key                  # Nom du Secret à monter
      - downwardAPI:                     # Source 3 : Downward API (métadonnées Pod)
          items:
          - path: "labels"              # Chemin du fichier dans le volume
            fieldRef: { fieldPath: metadata.labels }  # Injecte les labels du Pod
```

> **Resultat attendu** :
> ```
> # Le volume /app-config/ contiendra :
> #   index.html         (depuis frontend-conf)
> #   default.conf       (depuis frontend-conf)
> #   token              (depuis api-key)
> #   labels             (depuis downwardAPI)
> ```
> **Verification** : `kubectl exec <pod> -- ls /app-config/` doit lister les fichiers de toutes les sources combinées.

---

## 7. Cycle de vie et déploiements

1. **Versionner** vos ConfigMaps/Secrets (manifestes YAML) dans Git; pas de secrets en clair.
2. **Déclencher un rollout** quand la config change :

   * Ajoutez une annotation de **checksum** dans le template Pod (hash du ConfigMap/Secret) pour forcer le redeploy.
3. **Reload automatique** :

   * Soit `kubectl rollout restart deployment X`,
   * Soit opérateurs de reload (ex. sidecar reloader),
   * Soit l'app sait recharger ses fichiers.
4. **immutable: true** sur les objets stables pour éviter les modifications inopinées.

---

## 8. RBAC et gouvernance

* Limiter qui peut lire/écrire `configmaps` et surtout `secrets`.
* Logs d'audit activés sur l'API Server.
* Quotas : contrôler le nombre de ConfigMaps/Secrets par namespace.

---

## 9. Sécurité avancée

### 9.1 Bonnes pratiques

* Jamais de secret en clair dans Git; utilisez des solutions de **chiffrement Git** (SOPS) ou des opérateurs de secrets (External Secrets).
* Rotation régulière des secrets et des tokens de ServiceAccount.
* Restreindre l'accès `get/list` sur `secrets` au minimum.

### 9.2 Externalisation des secrets

* **External Secrets Operator** pour synchroniser depuis un secret store (AWS Secrets Manager, HashiCorp Vault, GCP Secret Manager, Azure Key Vault).
* **SealedSecrets** pour stocker des secrets chiffrés côté Git.

### 9.3 Chiffrement at-rest (API Server)

* Activer un **EncryptionConfiguration** côté API Server pour chiffrer les `secrets` dans etcd (kubeadm/cluster managé).
* En pratique sur kubeadm : fichier `encryption-config.yaml` référencé par `--encryption-provider-config=...` puis redémarrage contrôlé du plan de contrôle.

---

## 10. LAB — Fil rouge (Phase 5)

Externaliser la configuration et sécuriser les secrets de l'application

### 10.1 Objectif

* Déplacer la configuration du **frontend** (NGINX) dans un **ConfigMap**.
* Injecter une **clé API** dans le **backend** via **Secret**.
* Démontrer `env`, `envFrom`, **volumes** et **imagePullSecrets**.
* Mettre en place un **rollout** à changement de config.

### 10.2 Prérequis

* Avoir un cluster Minikube (Chap. 2) et l'application fil rouge (Chap. 3–5) :

  * Namespace `projet-fil-rouge`, Deployments `frontend` (nginx) et `backend` (httpd), Ingress `web-ingress`.
* Si vous partez de zéro, installez rapidement :

  * Windows : Docker Desktop, `choco install kubernetes-cli minikube`, `minikube start --driver=docker`.
  * Linux : installez Docker, kubectl et Minikube, puis `minikube start --driver=docker`.
* Vérifiez :

> **Objectif** : Vérifier que le cluster Kubernetes est opérationnel et que le namespace `projet-fil-rouge` contient les ressources du fil rouge.
> **Pre-requis** : Minikube démarré (`minikube start`) et kubectl configuré pour communiquer avec le cluster.

```bash
  # Affiche les nœuds du cluster avec leurs adresses IP et versions
  kubectl get nodes -o wide
  # Liste toutes les ressources du namespace fil rouge (Pods, Deployments, Services, etc.)
  kubectl get all -n projet-fil-rouge
```

> **Resultat attendu** :
> ```
> NAME       STATUS   ROLES           AGE   VERSION   INTERNAL-IP    EXTERNAL-IP   OS-IMAGE
> minikube   Ready    control-plane   10d   v1.29.0   192.168.49.2   <none>        Ubuntu 22.04.3 LTS
>
> NAME                            READY   STATUS    RESTARTS   AGE
> pod/frontend-6d4f8b7c5-abc12    1/1     Running   0          5m
> pod/backend-7f9a8b6c4d-xyz99    1/1     Running   0          5m
>
> NAME                       TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
> service/backend            ClusterIP   10.96.100.50    <none>        80/TCP    5m
>
> NAME                       READY   UP-TO-DATE   AVAILABLE   AGE
> deployment.apps/frontend   1/1     1            1           5m
> deployment.apps/backend    1/1     1            1           5m
> ```
> **Verification** : Le nœud doit être `Ready` et les Pods du namespace doivent être `Running` avec `1/1` READY.

### 10.3 Étape 1 — ConfigMap du frontend (fichier HTML + conf NGINX)

Créez `configmap-frontend.yaml` :

> **Objectif** : Créer un ConfigMap contenant le fichier HTML principal (`index.html`) et la configuration NGINX (`default.conf`) qui sera monté dans le Pod frontend.
> **Pre-requis** : Le namespace `projet-fil-rouge` doit exister. Le fichier `configmap-frontend.yaml` doit être créé dans le répertoire courant.

```yaml
  apiVersion: v1                          # API version pour les ressources core
  kind: ConfigMap                         # Type : ConfigMap (données non sensibles)
  metadata:
    name: frontend-conf                   # Nom du ConfigMap (référencé dans les Deployments)
    namespace: projet-fil-rouge           # Namespace cible
  data:
    index.html: |                         # Clé 'index.html' contenant le HTML (bloc littéral)
      <!doctype html>
      <html>
        <head><title>Fil Rouge</title></head>
        <body>
          <h1>Bienvenue sur le Frontend</h1>
          <p>BACKEND_URL={{ .Values.backendUrl | default "http://backend" }}</p>
        </body>
      </html>
    default.conf: |                       # Clé 'default.conf' contenant la config NGINX
      server {
        listen 80;                        # Écoute sur le port 80
        location / {
          root   /usr/share/nginx/html;   # Racine des fichiers statiques
          index  index.html;              # Page d'accueil par défaut
        }
        location /api/ {
          proxy_pass http://backend/;     # Proxy inverse vers le service backend
        }
      }
```

Appliquez :

> **Objectif** : Appliquer le manifeste du ConfigMap pour le créer dans le cluster.
> **Pre-requis** : Le fichier `configmap-frontend.yaml` doit être présent dans le répertoire courant.

```bash
  # Crée ou met à jour le ConfigMap 'frontend-conf' dans le cluster
  kubectl apply -f configmap-frontend.yaml
```

> **Resultat attendu** :
> ```
> configmap/frontend-conf created
> ```
> **Verification** : `kubectl get configmap frontend-conf -n projet-fil-rouge` doit afficher le ConfigMap avec un âge récent.

### 10.4 Étape 2 — Monter la config dans le frontend

Éditez votre `frontend.yaml` (ou créez `frontend-deploy.yaml`) pour consommer le ConfigMap en **volume** et **subPath** :

> **Objectif** : Déployer le frontend NGINX en montant les fichiers du ConfigMap (`index.html` et `default.conf`) via des volumes avec `subPath` pour des chemins de fichier précis.
> **Pre-requis** : Le ConfigMap `frontend-conf` doit exister dans le namespace `projet-fil-rouge` (étape 10.3). Le fichier `frontend-deploy.yaml` doit être créé.

```yaml
  apiVersion: apps/v1                     # API version pour les Deployments
  kind: Deployment
  metadata:
    name: frontend                        # Nom du Deployment
    namespace: projet-fil-rouge           # Namespace cible
  spec:
    replicas: 1                           # Un seul replica pour le frontend
    selector: { matchLabels: { app: frontend } }  # Sélectionne les Pods avec label app=frontend
    template:
      metadata:
        labels: { app: frontend }         # Label appliqué aux Pods créés
        annotations:
          # Astuce : checksum pour forcer rollout si ConfigMap change
          configmap-checksum: "PLACEHOLDER_REPLACED_BY_PIPELINE"  # Annotation mise à jour par la CI pour déclencher un rollout
      spec:
        containers:
        - name: nginx                     # Nom du conteneur
          image: nginx:latest             # Image NGINX depuis Docker Hub
          ports:
          - containerPort: 80             # Port exposé par le conteneur
          volumeMounts:
          - name: html                    # Référence au volume 'html' défini plus bas
            mountPath: /usr/share/nginx/html/index.html  # Chemin cible dans le conteneur
            subPath: index.html           # Monte uniquement la clé 'index.html' du ConfigMap
          - name: conf                    # Référence au volume 'conf' défini plus bas
            mountPath: /etc/nginx/conf.d/default.conf    # Chemin de la config NGINX
            subPath: default.conf         # Monte uniquement la clé 'default.conf' du ConfigMap
        volumes:
        - name: html                      # Nom du volume (référencé dans volumeMounts)
          configMap:
            name: frontend-conf           # Source : ConfigMap 'frontend-conf'
            items:
            - key: index.html             # Clé du ConfigMap à monter
              path: index.html            # Nom du fichier dans le volume
        - name: conf                      # Deuxième volume pour la config NGINX
          configMap:
            name: frontend-conf           # Même ConfigMap, clé différente
            items:
            - key: default.conf
              path: default.conf
```

Appliquez :

> **Objectif** : Déployer (ou mettre à jour) le Deployment frontend et attendre que le rollout soit terminé.
> **Pre-requis** : Le fichier `frontend-deploy.yaml` doit être présent ; le ConfigMap `frontend-conf` doit exister.

```bash
  # Applique le manifeste du Deployment frontend
  kubectl apply -f frontend-deploy.yaml
  # Attend que le rollout du Deployment soit complet (tous les Pods prêts)
  kubectl rollout status deployment/frontend -n projet-fil-rouge
```

> **Resultat attendu** :
> ```
> deployment.apps/frontend configured
> Waiting for deployment "frontend" rollout to finish: 1 of 1 updated replicas are available...
> deployment "frontend" successfully rolled out
> ```
> **Verification** : `kubectl get pods -l app=frontend -n projet-fil-rouge` doit afficher un Pod avec STATUS `Running` et READY `1/1`.

Vérifiez :

> **Objectif** : Vérifier que les fichiers du ConfigMap sont correctement montés dans le conteneur frontend.
> **Pre-requis** : Le Pod frontend doit être en état `Running`.

```bash
  # Affiche le contenu de default.conf monté depuis le ConfigMap
  kubectl exec -n projet-fil-rouge deploy/frontend -- cat /etc/nginx/conf.d/default.conf
  # Liste les fichiers dans le répertoire HTML monté depuis le ConfigMap
  kubectl exec -n projet-fil-rouge deploy/frontend -- ls /usr/share/nginx/html
```

> **Resultat attendu** :
> ```
> server {
>   listen 80;
>   location / {
>     root   /usr/share/nginx/html;
>     index  index.html;
>   }
>   location /api/ {
>     proxy_pass http://backend/;
>   }
> }
>
> index.html
> ```
> **Verification** : Le contenu de `default.conf` doit correspondre exactement à celui défini dans le ConfigMap ; `index.html` doit être présent dans `/usr/share/nginx/html`.

### 10.5 Étape 3 — Secret du backend (clé API)

Créez un Secret `api-key` :

> **Objectif** : Créer un Secret de type `generic` (Opaque) contenant une clé API sous forme de littéral, puis lister les Secrets du namespace.
> **Pre-requis** : Le namespace `projet-fil-rouge` doit exister.

```bash
  # Crée un Secret nommé 'api-key' avec une clé 'token' ayant pour valeur 'AZERTY123'
  kubectl create secret generic api-key \
    --from-literal=token=AZERTY123 \      # --from-literal : clé=valeur en ligne de commande
    -n projet-fil-rouge                   # Namespace cible
  # Liste tous les Secrets du namespace pour vérifier la création
  kubectl get secrets -n projet-fil-rouge
```

> **Resultat attendu** :
> ```
> secret/api-key created
>
> NAME       TYPE                             DATA   AGE
> api-key    Opaque                           1      5s
> ```
> **Verification** : Le Secret `api-key` de type `Opaque` avec `DATA: 1` doit apparaître dans la liste.

Modifiez votre `backend.yaml` pour consommer la clé en **env** :

> **Objectif** : Déployer le backend (httpd) en injectant la clé API du Secret comme variable d'environnement `API_TOKEN` via `secretKeyRef`.
> **Pre-requis** : Le Secret `api-key` doit exister dans le namespace `projet-fil-rouge` (créé ci-dessus).

```yaml
  apiVersion: apps/v1
  kind: Deployment
  metadata:
    name: backend                           # Nom du Deployment
    namespace: projet-fil-rouge
  spec:
    replicas: 1                             # Un seul replica
    selector: { matchLabels: { app: backend } }  # Sélectionne les Pods labelisés app=backend
    template:
      metadata:
        labels: { app: backend }            # Label appliqué aux Pods
      spec:
        containers:
        - name: httpd                       # Conteneur Apache httpd
          image: httpd:latest               # Image httpd depuis Docker Hub
          ports:
          - containerPort: 80               # Port exposé
          env:
          - name: API_TOKEN                 # Nom de la variable d'environnement dans le conteneur
            valueFrom:
              secretKeyRef:                 # Source : référence à une clé d'un Secret
                name: api-key               # Nom du Secret
                key: token                  # Clé spécifique dans le Secret
```

Appliquez :

> **Objectif** : Appliquer le Deployment backend et vérifier que la variable d'environnement `API_TOKEN` est correctement injectée depuis le Secret.
> **Pre-requis** : Le fichier `backend.yaml` doit être à jour ; le Secret `api-key` doit exister.

```bash
  # Applique le manifeste du Deployment backend
  kubectl apply -f backend.yaml
  # Liste les Pods backend pour vérifier leur état
  kubectl get pods -l app=backend -n projet-fil-rouge
  # Vérifie que la variable API_TOKEN est bien injectée dans le conteneur
  kubectl exec -n projet-fil-rouge deploy/backend -- printenv | grep API_TOKEN
```

> **Resultat attendu** :
> ```
> deployment.apps/backend configured
>
> NAME                       READY   STATUS    RESTARTS   AGE
> pod/backend-7f9a8b6c4d-xyz99   1/1     Running   0          30s
>
> API_TOKEN=AZERTY123
> ```
> **Verification** : Le Pod backend doit être `Running` et `printenv` doit afficher `API_TOKEN=AZERTY123`.

### 10.6 Étape 4 — imagePullSecrets (démonstration)

Créez un secret de registre (si vous avez un registre privé) :

> **Objectif** : Créer un Secret de type `docker-registry` pour authentifier le pull d'images depuis un registre privé.
> **Pre-requis** : Disposer des identifiants d'un registre privé (URL, utilisateur, mot de passe, email). Le namespace `projet-fil-rouge` doit exister.

```bash
  # Crée un Secret docker-registry nommé 'regcred' pour l'authentification au registre
  kubectl create secret docker-registry regcred \
    --docker-server=REGISTRY_URL \         # URL du registre privé
    --docker-username=USER \               # Identifiant du registre
    --docker-password=PASS \               # Mot de passe du registre
    --docker-email=you@example.com \       # Email du compte registre
    -n projet-fil-rouge                    # Namespace cible
```

> **Resultat attendu** :
> ```
> secret/regcred created
> ```
> **Verification** : `kubectl get secret regcred -n projet-fil-rouge` doit afficher le Secret de type `kubernetes.io/dockerconfigjson`.

Référencez-le dans un Deployment (ex. frontend) :

> **Objectif** : Configurer le Pod pour utiliser le Secret `regcred` lors du pull d'images, permettant l'accès aux images de registres privés.
> **Pre-requis** : Le Secret `regcred` doit exister dans le namespace `projet-fil-rouge`.

```yaml
  spec:
    template:
      spec:
        imagePullSecrets:                   # Liste de Secrets pour l'authentification aux registres
        - name: regcred                     # Nom du Secret docker-registry à utiliser
```

> **Resultat attendu** :
> ```
> # Pas de sortie directe ; le prochain Pod créé utilisera regcred pour pull l'image
> ```
> **Verification** : `kubectl describe pod <pod-name> -n projet-fil-rouge` doit montrer `ImagePullSecrets: regcred` dans la section Spec.

### 10.7 Étape 5 — Downward API

Ajoutez des métadonnées utiles au frontend :

> **Objectif** : Injecter le nom et le namespace du Pod comme variables d'environnement via la Downward API, permettant à l'application de connaître son propre contexte d'exécution.
> **Pre-requis** : Le Deployment `frontend` doit exister dans le namespace `projet-fil-rouge`. Cette section de `env:` doit être ajoutée dans le conteneur du Deployment.

```yaml
  env:
  - name: POD_NAME                        # Variable contenant le nom unique du Pod
    valueFrom: { fieldRef: { fieldPath: metadata.name } }      # Résolu dynamiquement par kubelet
  - name: POD_NAMESPACE                   # Variable contenant le namespace du Pod
    valueFrom: { fieldRef: { fieldPath: metadata.namespace } } # Résolu dynamiquement par kubelet
```

> **Resultat attendu** :
> ```
> # Les variables sont disponibles dans le conteneur :
> # POD_NAME=frontend-6d4f8b7c5-abc12
> # POD_NAMESPACE=projet-fil-rouge
> ```
> **Verification** : Exécuter la commande ci-dessous pour confirmer les valeurs.

Vérifiez :

> **Objectif** : Vérifier que les variables d'environnement `POD_NAME` et `POD_NAMESPACE` sont correctement injectées dans le conteneur frontend via la Downward API.
> **Pre-requis** : Le Pod frontend doit être en état `Running` avec les variables Downward API configurées.

```bash
  # Exécute une commande shell dans le conteneur frontend pour afficher les variables
  kubectl exec -n projet-fil-rouge deploy/frontend -- sh -c 'echo $POD_NAME $POD_NAMESPACE'
```

> **Resultat attendu** :
> ```
> frontend-6d4f8b7c5-abc12 projet-fil-rouge
> ```
> **Verification** : Le nom du Pod (ex. `frontend-6d4f8b7c5-abc12`) et le namespace (`projet-fil-rouge`) doivent s'afficher correctement.

### 10.8 Étape 6 — Test et rollouts

* Testez l'application :

> **Objectif** : Tester que le frontend répond correctement via l'Ingress en envoyant une requête HTTP HEAD.
> **Pre-requis** : L'Ingress `web-ingress` doit être configuré avec le hostname `local.dev` ; Minikube doit avoir l'Ingress addon activé ; l'entrée DNS ou `/etc/hosts` doit pointer vers Minikube.

```bash
  # Envoie une requête HTTP HEAD pour vérifier les headers de réponse du frontend
  curl -I http://local.dev
```

> **Resultat attendu** :
> ```
> HTTP/1.1 200 OK
> Server: nginx/1.25.3
> Date: Sun, 21 Jun 2026 10:00:00 GMT
> Content-Type: text/html
> Content-Length: 145
> Last-Modified: Sun, 21 Jun 2026 09:55:00 GMT
> Connection: keep-alive
> ETag: "66753a24-91"
> Accept-Ranges: bytes
> ```
> **Verification** : Le code de réponse doit être `200 OK` et le serveur doit être `nginx`.

* Modifiez `index.html` dans le ConfigMap (message différent) puis :

  * soit `kubectl rollout restart deployment/frontend -n projet-fil-rouge`,
  * soit mettez à jour l'**annotation checksum** via votre pipeline CI pour forcer un redeploy.
* Confirmez :

> **Objectif** : Confirmer que le rollout du frontend s'est terminé avec succès après la modification du ConfigMap.
> **Pre-requis** : Le ConfigMap `frontend-conf` doit avoir été modifié et le rollout restart déclenché.

```bash
  # Attend et affiche le statut du rollout du Deployment frontend
  kubectl rollout status deployment/frontend -n projet-fil-rouge
```

> **Resultat attendu** :
> ```
> Waiting for deployment "frontend" rollout to finish: 1 old replicas are pending termination...
> Waiting for deployment "frontend" rollout to finish: 1 of 1 updated replicas are available...
> deployment "frontend" successfully rolled out
> ```
> **Verification** : Le message `successfully rolled out` confirme que les nouveaux Pods utilisent la configuration mise à jour.

### 10.9 Étape 7 — Validation

> **Objectif** : Valider l'ensemble de la configuration en inspectant le ConfigMap, le Secret, et les logs des Deployments frontend et backend.
> **Pre-requis** : Toutes les étapes précédentes (10.3 à 10.8) doivent être complétées avec succès.

```bash
  # Affiche les 20 premières lignes du ConfigMap au format YAML pour vérifier son contenu
  kubectl get configmap frontend-conf -n projet-fil-rouge -o yaml | head -n 20
  # Vérifie que le Secret api-key existe et affiche son type/nombre de clés
  kubectl get secret api-key -n projet-fil-rouge
  # Affiche les logs du conteneur frontend (NGINX) pour vérifier l'absence d'erreurs
  kubectl logs -n projet-fil-rouge deploy/frontend
  # Affiche les logs du conteneur backend (httpd) pour vérifier l'absence d'erreurs
  kubectl logs -n projet-fil-rouge deploy/backend
```

> **Resultat attendu** :
> ```
> apiVersion: v1
> data:
>   default.conf: |
>     server {
>       listen 80;
>       ...
> kind: ConfigMap
> metadata:
>   name: frontend-conf
>   namespace: projet-fil-rouge
>
> NAME      TYPE     DATA   AGE
> api-key   Opaque   1      15m
>
> 192.168.49.1 - - [21/Jun/2026:10:00:00 +0000] "GET / HTTP/1.1" 200 ...
> 192.168.49.1 - - [21/Jun/2026:10:00:05 +0000] "HEAD / HTTP/1.1" 200 ...
>
> AH00558: httpd: Could not reliably determine the server's fully qualified domain name...
> 192.168.49.1 - - [21/Jun/2026:10:00:00 +0000] "GET / HTTP/1.1" 200 ...
> ```
> **Verification** : Le ConfigMap contient bien `default.conf` et `index.html` ; le Secret `api-key` est de type `Opaque` avec `DATA: 1` ; les logs ne montrent pas d'erreurs critiques.

### 10.10 Nettoyage (facultatif)

> **Objectif** : Supprimer les ressources créées durant le LAB (Secret et ConfigMap) pour nettoyer le namespace.
> **Pre-requis** : Avoir terminé les tests et validations. Les Deployments référenceront des ressources inexistantes après suppression — à supprimer aussi si nécessaire.

```bash
  # Supprime le Secret 'api-key' du namespace
  kubectl delete secret api-key -n projet-fil-rouge
  # Supprime le ConfigMap 'frontend-conf' du namespace
  kubectl delete configmap frontend-conf -n projet-fil-rouge
```

> **Resultat attendu** :
> ```
> secret "api-key" deleted
> configmap "frontend-conf" deleted
> ```
> **Verification** : `kubectl get secrets,configmaps -n projet-fil-rouge` ne doit plus lister `api-key` ni `frontend-conf`.

---

## 11. Bonnes pratiques et pièges

1. **Ne stockez jamais** de secrets en clair dans Git; utilisez SOPS, SealedSecrets ou un secret store externe.
2. **RBAC strict** : restreindre l'accès lecture/écriture sur `secrets`.
3. **Chiffrement at-rest** des secrets sur l'API Server en production.
4. **Checksum/annotation** pour forcer un rollout lors d'un changement de ConfigMap/Secret.
5. **Reload applicatif** : la plupart des apps ne rechargent pas les fichiers automatiquement.
6. **immutable: true** pour figer un ConfigMap/Secret stable.
7. **Quotas** sur le nombre de ConfigMaps/Secrets par namespace.
8. **Logs** : éviter d'imprimer des secrets; attention aux `kubectl describe` et logs applicatifs.
9. **Taille** : rester bien en dessous de 1 MiB par ConfigMap/Secret.
10. **imagePullSecrets** : privilégier un ServiceAccount dédié par namespace.

---

## 12. Résumé pour diapo

1. ConfigMaps = configuration non sensible; Secrets = données sensibles.
2. Modes de consommation : `env`, `envFrom`, volumes, volumes projetés.
3. Downward API : injecter métadonnées Pod/ressources.
4. imagePullSecrets : authentification registre privé.
5. Sécurité : RBAC, chiffrement at-rest, pas de secrets en clair dans Git.
6. Déploiements : checksum/annotation, rollout, éventuellement reloader.
7. Fil rouge : frontend piloté par ConfigMap, backend par Secret, tests et rollouts vérifiés.
