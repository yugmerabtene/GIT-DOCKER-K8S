# Chapitre 7 — Configuration & Secrets

*(ConfigMaps, Secrets, Downward API, volumes projetés, imagePullSecrets, chiffrement)*

---

## 1. Objectifs d’apprentissage

À la fin de ce chapitre, vous serez capable de :

1. Distinguer **configuration** et **code** selon les principes Twelve-Factor.
2. Créer et consommer des **ConfigMaps** (fichiers, variables d’environnement, volumes).
3. Créer et consommer des **Secrets** (Opaque, TLS, dockerconfigjson, etc.).
4. Utiliser la **Downward API** pour injecter des métadonnées Pod/ressources.
5. Combiner ConfigMaps/Secrets/Downward API en **volume projeté**.
6. Gérer les **imagePullSecrets** et l’authentification aux registres.
7. Déployer des configurations de manière **sûre** (RBAC, chiffrement at-rest, rotation).
8. Mettre en place un **cycle de vie** de configuration (versioning Git, rechargement, checksum rollout).

---

## 2. Principes fondamentaux

1. **Séparation config/code** : la configuration doit vivre hors des images.
2. **Portabilité** : même image, configs différentes par environnement (dev, staging, prod).
3. **Sources de vérité** : configurations versionnées (Git), déployées par manifestes.
4. **Sécurité** : Secrets jamais en clair dans Git; chiffrement côté API Server et contrôles d’accès (RBAC).
5. **Observabilité** : toute modification de config doit être traçable (audit, events).

---

## 3. ConfigMaps

### 3.1 Rôle et cas d’usage

* Stocker des **données non sensibles** : variables, fichiers de configuration, templates.
* Injecter dans les Pods via :

  * **variables d’environnement** (`env`, `envFrom`),
  * **volumes** (fichiers montés),
  * références directes dans les champs supportés.

### 3.2 Structure et limites

* Clés/valeurs dans `data:` (texte) ou `binaryData:` (base64 brut).
* Taille maximale d’un objet: environ 1 MiB (lié à etcd).
* Option **immutable** pour figer un ConfigMap en production :

  ```yaml
  immutable: true
  ```

### 3.3 Consommation

* **env** (clé à clé) ou **envFrom** (tout le map).
* **volume + subPath** pour monter un fichier précis (ex. `default.conf` NGINX).
* Les fichiers montés se mettent à jour au fil de l’eau, mais la plupart des applications nécessitent un **reload** ou un **rollout**.

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

* Les valeurs sont **encodées en base64**, ce n’est pas du chiffrement.
* Activer le **chiffrement at-rest** côté API Server en production (section 9.3).

### 4.3 Consommation

* Comme les ConfigMaps : **env**, **envFrom**, **volume**.
* Les **variables d’environnement** sont évaluées au **démarrage** du Pod (pas mises à jour dynamiquement).
* En volume, l’OS voit des fichiers; votre application doit recharger si nécessaire.

### 4.4 imagePullSecrets

* Authentifier les pulls d’images private registry :

  ```bash
  kubectl create secret docker-registry regcred \
    --docker-server=REGISTRY_URL \
    --docker-username=USER \
    --docker-password=PASS \
    --docker-email=you@example.com \
    -n projet-fil-rouge
  ```
* Référence dans `spec.imagePullSecrets` ou lier au **ServiceAccount**.

---

## 5. Downward API

Injecter des **métadonnées** du Pod sans les coder en dur :

* En variables d’environnement :

  ```yaml
  env:
  - name: POD_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
  - name: CPU_LIMITS
    valueFrom:
      resourceFieldRef:
        resource: limits.cpu
  ```
* En volume `downwardAPI` (fichiers contenant labels, annotations, ressources).

---

## 6. Volumes projetés (Projected Volumes)

Combiner plusieurs sources en un **seul montage** :

```yaml
volumes:
- name: app-config
  projected:
    sources:
    - configMap:
        name: frontend-conf
    - secret:
        name: api-key
    - downwardAPI:
        items:
        - path: "labels"
          fieldRef: { fieldPath: metadata.labels }
```

---

## 7. Cycle de vie et déploiements

1. **Versionner** vos ConfigMaps/Secrets (manifestes YAML) dans Git; pas de secrets en clair.
2. **Déclencher un rollout** quand la config change :

   * Ajoutez une annotation de **checksum** dans le template Pod (hash du ConfigMap/Secret) pour forcer le redeploy.
3. **Reload automatique** :

   * Soit `kubectl rollout restart deployment X`,
   * Soit opérateurs de reload (ex. sidecar reloader),
   * Soit l’app sait recharger ses fichiers.
4. **immutable: true** sur les objets stables pour éviter les modifications inopinées.

---

## 8. RBAC et gouvernance

* Limiter qui peut lire/écrire `configmaps` et surtout `secrets`.
* Logs d’audit activés sur l’API Server.
* Quotas : contrôler le nombre de ConfigMaps/Secrets par namespace.

---

## 9. Sécurité avancée

### 9.1 Bonnes pratiques

* Jamais de secret en clair dans Git; utilisez des solutions de **chiffrement Git** (SOPS) ou des opérateurs de secrets (External Secrets).
* Rotation régulière des secrets et des tokens de ServiceAccount.
* Restreindre l’accès `get/list` sur `secrets` au minimum.

### 9.2 Externalisation des secrets

* **External Secrets Operator** pour synchroniser depuis un secret store (AWS Secrets Manager, HashiCorp Vault, GCP Secret Manager, Azure Key Vault).
* **SealedSecrets** pour stocker des secrets chiffrés côté Git.

### 9.3 Chiffrement at-rest (API Server)

* Activer un **EncryptionConfiguration** côté API Server pour chiffrer les `secrets` dans etcd (kubeadm/cluster managé).
* En pratique sur kubeadm : fichier `encryption-config.yaml` référencé par `--encryption-provider-config=...` puis redémarrage contrôlé du plan de contrôle.

---

## 10. LAB — Fil rouge (Phase 5)

Externaliser la configuration et sécuriser les secrets de l’application

### 10.1 Objectif

* Déplacer la configuration du **frontend** (NGINX) dans un **ConfigMap**.
* Injecter une **clé API** dans le **backend** via **Secret**.
* Démontrer `env`, `envFrom`, **volumes** et **imagePullSecrets**.
* Mettre en place un **rollout** à changement de config.

### 10.2 Prérequis

* Avoir un cluster Minikube (Chap. 2) et l’application fil rouge (Chap. 3–5) :

  * Namespace `projet-fil-rouge`, Deployments `frontend` (nginx) et `backend` (httpd), Ingress `web-ingress`.
* Si vous partez de zéro, installez rapidement :

  * Windows : Docker Desktop, `choco install kubernetes-cli minikube`, `minikube start --driver=docker`.
  * Linux : installez Docker, kubectl et Minikube, puis `minikube start --driver=docker`.
* Vérifiez :

  ```bash
  kubectl get nodes -o wide
  kubectl get all -n projet-fil-rouge
  ```

### 10.3 Étape 1 — ConfigMap du frontend (fichier HTML + conf NGINX)

Créez `configmap-frontend.yaml` :

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: frontend-conf
  namespace: projet-fil-rouge
data:
  index.html: |
    <!doctype html>
    <html>
      <head><title>Fil Rouge</title></head>
      <body>
        <h1>Bienvenue sur le Frontend</h1>
        <p>BACKEND_URL={{ .Values.backendUrl | default "http://backend" }}</p>
      </body>
    </html>
  default.conf: |
    server {
      listen 80;
      location / {
        root   /usr/share/nginx/html;
        index  index.html;
      }
      location /api/ {
        proxy_pass http://backend/;
      }
    }
```

Appliquez :

```bash
kubectl apply -f configmap-frontend.yaml
```

### 10.4 Étape 2 — Monter la config dans le frontend

Éditez votre `frontend.yaml` (ou créez `frontend-deploy.yaml`) pour consommer le ConfigMap en **volume** et **subPath** :

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
  namespace: projet-fil-rouge
spec:
  replicas: 1
  selector: { matchLabels: { app: frontend } }
  template:
    metadata:
      labels: { app: frontend }
      annotations:
        # Astuce : checksum pour forcer rollout si ConfigMap change
        configmap-checksum: "PLACEHOLDER_REPLACED_BY_PIPELINE"
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
        volumeMounts:
        - name: html
          mountPath: /usr/share/nginx/html/index.html
          subPath: index.html
        - name: conf
          mountPath: /etc/nginx/conf.d/default.conf
          subPath: default.conf
      volumes:
      - name: html
        configMap:
          name: frontend-conf
          items:
          - key: index.html
            path: index.html
      - name: conf
        configMap:
          name: frontend-conf
          items:
          - key: default.conf
            path: default.conf
```

Appliquez :

```bash
kubectl apply -f frontend-deploy.yaml
kubectl rollout status deployment/frontend -n projet-fil-rouge
```

Vérifiez :

```bash
kubectl exec -n projet-fil-rouge deploy/frontend -- cat /etc/nginx/conf.d/default.conf
kubectl exec -n projet-fil-rouge deploy/frontend -- ls /usr/share/nginx/html
```

### 10.5 Étape 3 — Secret du backend (clé API)

Créez un Secret `api-key` :

```bash
kubectl create secret generic api-key \
  --from-literal=token=AZERTY123 \
  -n projet-fil-rouge
kubectl get secrets -n projet-fil-rouge
```

Modifiez votre `backend.yaml` pour consommer la clé en **env** :

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
  namespace: projet-fil-rouge
spec:
  replicas: 1
  selector: { matchLabels: { app: backend } }
  template:
    metadata:
      labels: { app: backend }
    spec:
      containers:
      - name: httpd
        image: httpd:latest
        ports:
        - containerPort: 80
        env:
        - name: API_TOKEN
          valueFrom:
            secretKeyRef:
              name: api-key
              key: token
```

Appliquez :

```bash
kubectl apply -f backend.yaml
kubectl get pods -l app=backend -n projet-fil-rouge
kubectl exec -n projet-fil-rouge deploy/backend -- printenv | grep API_TOKEN
```

### 10.6 Étape 4 — imagePullSecrets (démonstration)

Créez un secret de registre (si vous avez un registre privé) :

```bash
kubectl create secret docker-registry regcred \
  --docker-server=REGISTRY_URL \
  --docker-username=USER \
  --docker-password=PASS \
  --docker-email=you@example.com \
  -n projet-fil-rouge
```

Référencez-le dans un Deployment (ex. frontend) :

```yaml
spec:
  template:
    spec:
      imagePullSecrets:
      - name: regcred
```

### 10.7 Étape 5 — Downward API

Ajoutez des métadonnées utiles au frontend :

```yaml
env:
- name: POD_NAME
  valueFrom: { fieldRef: { fieldPath: metadata.name } }
- name: POD_NAMESPACE
  valueFrom: { fieldRef: { fieldPath: metadata.namespace } }
```

Vérifiez :

```bash
kubectl exec -n projet-fil-rouge deploy/frontend -- sh -c 'echo $POD_NAME $POD_NAMESPACE'
```

### 10.8 Étape 6 — Test et rollouts

* Testez l’application :

  ```bash
  curl -I http://local.dev
  ```
* Modifiez `index.html` dans le ConfigMap (message différent) puis :

  * soit `kubectl rollout restart deployment/frontend -n projet-fil-rouge`,
  * soit mettez à jour l’**annotation checksum** via votre pipeline CI pour forcer un redeploy.
* Confirmez :

  ```bash
  kubectl rollout status deployment/frontend -n projet-fil-rouge
  ```

### 10.9 Étape 7 — Validation

```bash
kubectl get configmap frontend-conf -n projet-fil-rouge -o yaml | head -n 20
kubectl get secret api-key -n projet-fil-rouge
kubectl logs -n projet-fil-rouge deploy/frontend
kubectl logs -n projet-fil-rouge deploy/backend
```

### 10.10 Nettoyage (facultatif)

```bash
kubectl delete secret api-key -n projet-fil-rouge
kubectl delete configmap frontend-conf -n projet-fil-rouge
```

---

## 11. Bonnes pratiques et pièges

1. **Ne stockez jamais** de secrets en clair dans Git; utilisez SOPS, SealedSecrets ou un secret store externe.
2. **RBAC strict** : restreindre l’accès lecture/écriture sur `secrets`.
3. **Chiffrement at-rest** des secrets sur l’API Server en production.
4. **Checksum/annotation** pour forcer un rollout lors d’un changement de ConfigMap/Secret.
5. **Reload applicatif** : la plupart des apps ne rechargent pas les fichiers automatiquement.
6. **immutable: true** pour figer un ConfigMap/Secret stable.
7. **Quotas** sur le nombre de ConfigMaps/Secrets par namespace.
8. **Logs** : éviter d’imprimer des secrets; attention aux `kubectl describe` et logs applicatifs.
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
