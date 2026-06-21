# **Chapitre 5 — Sécurité et durcissement du cluster Kubernetes**

*(RBAC, Service Accounts, Secrets, Policies, TLS, Network Security)*

---

## **1. Objectifs d'apprentissage**

À la fin de ce chapitre, l'apprenant sera capable de :

* Comprendre les **mécanismes de sécurité intégrés** à Kubernetes.
* Mettre en œuvre le **contrôle d'accès basé sur les rôles (RBAC)**.
* Gérer les **identités applicatives** via les **Service Accounts**.
* Sécuriser les **informations sensibles** avec **Secrets**.
* Définir des **politiques réseau (Network Policies)**.
* Configurer la **sécurité TLS**, l'**audit API** et la **sécurisation des communications**.
* Poursuivre le **projet fil rouge** (phase 4) en durcissant le cluster et les Pods.

---

## **2. Principes fondamentaux de la sécurité Kubernetes**

### **2.1 Modèle de sécurité en profondeur**

Kubernetes applique une stratégie de **"Defense in Depth"** :

1. **Authentification (AuthN)** : identifier qui fait la requête.
2. **Autorisation (AuthZ)** : déterminer ce qu'il peut faire.
3. **Admission Control** : valider ou rejeter les actions.
4. **Sécurité réseau** : contrôler les communications entre Pods.
5. **Protection des Secrets** : sécuriser les données sensibles.
6. **Audit et traçabilité** : enregistrer toutes les actions API.

**Contexte :**
Chaque couche complète la précédente ; un cluster bien durci limite les risques même si un Pod ou un compte est compromis.

---

### **2.2 Enjeux du durcissement**

Un cluster mal configuré expose :

* des **escalades de privilèges** (Pods root) ;
* des **expositions de Secrets** dans les logs ou images ;
* un **réseau non segmenté** permettant les mouvements latéraux ;
* un **accès API non authentifié**.

**Objectif :** mettre en place une sécurité multi-niveaux sur le plan de contrôle, le réseau et les applications.

---

## **3. Contrôle d'accès RBAC**

### **3.1 Principe**

Le **Role-Based Access Control** (RBAC) définit les actions autorisées sur les ressources Kubernetes.

* **Role** : permissions dans un namespace.
* **ClusterRole** : permissions globales.
* **RoleBinding / ClusterRoleBinding** : lient ces rôles à des utilisateurs ou Service Accounts.

---

### **3.2 Hiérarchie logique**

> **Objectif** : Illustrer la chaîne d'autorisation RBAC — un utilisateur ou ServiceAccount reçoit ses permissions via un RoleBinding qui référence un Role contenant les droits.
> **Pre-requis** : Aucun, ce schéma est informatif.

```
Utilisateur / ServiceAccount          # Identité (humaine ou applicative) qui effectue une requête API
   │
   ▼
RoleBinding                           # Lien entre l'identité et le rôle (définit "qui a quels droits")
   │
   ▼
Role                                  # Ensemble de permissions (verbes + ressources dans un namespace)
```

> **Resultat attendu** :
> ```
> Aucun résultat d'exécution — ce bloc est un schéma conceptuel.
> ```
> **Verification** : Comprendre que sans RoleBinding, même un Role avec des droits étendus ne s'applique à personne.

**Contexte :**
Le Role contient les droits, le Binding relie ces droits à une identité.

---

### **3.3 Commandes utiles**

> **Objectif** : Lister les rôles et bindings existants dans le cluster, puis vérifier les permissions effectives d'un ServiceAccount donné.
> **Pre-requis** : Cluster Kubernetes accessible avec kubectl configuré.

```bash
# Liste tous les Roles et RoleBindings dans tous les namespaces (-A = --all-namespaces)
kubectl get roles,rolebindings -A

# Vérifie si le ServiceAccount 'sa1' du namespace 'default' a le droit de lister les pods
# Retourne "yes" ou "no" — utile pour auditer les permissions effectives
kubectl auth can-i list pods --as=system:serviceaccount:default:sa1
```

> **Resultat attendu** :
> ```
> NAMESPACE     NAME                        ROLE                              AGE
> default       role/reader                 2d
> default       rolebinding/bind-reader     Role/reader                       2d
>
> yes
> ```
> **Verification** : La première commande affiche l'ensemble des rôles et bindings. La seconde confirme ou infirme la permission du SA testé.

**Contexte :**
La seconde commande teste les permissions d'une identité (utile pour vérifier qu'un ServiceAccount n'a pas de droits excessifs).

---

### **3.4 Bonnes pratiques**

* Appliquer le **principe du moindre privilège**.
* Créer des rôles spécifiques par namespace.
* Réserver les **ClusterRoles** aux administrateurs.
* Auditer régulièrement les droits (`kubectl get clusterrolebindings`).

---

## **4. Service Accounts et identités applicatives**

### **4.1 Définition**

Un **Service Account (SA)** est l'identité utilisée par un Pod pour parler à l'API Kubernetes.
Chaque namespace possède un SA `default`, mais il est recommandé de créer des SA dédiés.

---

### **4.2 Fichiers et tokens**

Le token du SA est automatiquement monté dans le Pod à :
`/var/run/secrets/kubernetes.io/serviceaccount/token`.

Il sert pour les appels authentifiés à l'API.

---

### **4.3 Commandes**

> **Objectif** : Créer un ServiceAccount dédié nommé `webapp-sa` dans le namespace du projet, puis vérifier son existence et ses détails.
> **Pre-requis** : Namespace `projet-fil-rouge` existant, accès cluster avec droits de création de SA.

```bash
# Crée un ServiceAccount nommé 'webapp-sa' dans le namespace 'projet-fil-rouge'
kubectl create serviceaccount webapp-sa -n projet-fil-rouge

# Liste tous les ServiceAccounts du namespace pour confirmer la création
kubectl get serviceaccounts -n projet-fil-rouge

# Affiche les détails du SA (token associé, secrets liés, image pull secrets)
kubectl describe sa webapp-sa -n projet-fil-rouge
```

> **Resultat attendu** :
> ```
> serviceaccount/webapp-sa created
>
> NAME         SECRETS   AGE
> default      1         10d
> webapp-sa    1         5s
>
> Name:                webapp-sa
> Namespace:           projet-fil-rouge
> Labels:              <none>
> Annotations:         <none>
> Image pull secrets:  <none>
> Mountable secrets:   <none>
> Tokens:              webapp-sa-token-xxxxx
> Events:              <none>
> ```
> **Verification** : Le SA `webapp-sa` apparaît dans la liste et un token automatique lui est associé.

**Contexte :**
Ces commandes créent et inspectent un SA qui sera lié par un RoleBinding à un rôle limité.

---

## **5. Secrets et données sensibles**

### **5.1 Utilité**

Les **Secrets** contiennent des mots de passe, clés API ou certificats.
Ils peuvent être montés dans un Pod ou injectés en variable d'environnement.

---

### **5.2 Création et affichage**

> **Objectif** : Créer un Secret de type `generic` contenant un nom d'utilisateur et un mot de passe pour la base de données, puis inspecter son contenu.
> **Pre-requis** : Namespace `projet-fil-rouge` existant, droits de création de Secrets.

```bash
# Crée un Secret nommé 'db-secret' avec deux paires clé/valeur en littéral
# Les valeurs sont automatiquement encodées en Base64 (pas du chiffrement !)
kubectl create secret generic db-secret \
  --from-literal=username=admin \
  --from-literal=password=1234 \
  -n projet-fil-rouge

# Liste les Secrets du namespace (les valeurs ne sont PAS affichées ici)
kubectl get secrets -n projet-fil-rouge

# Affiche les métadonnées du Secret (type, clés, taille) sans révéler les valeurs
kubectl describe secret db-secret -n projet-fil-rouge
```

> **Resultat attendu** :
> ```
> secret/db-secret created
>
> NAME         TYPE     DATA   AGE
> db-secret    Opaque   2      3s
>
> Name:         db-secret
> Namespace:    projet-fil-rouge
> Labels:       <none>
> Annotations:  <none>
> Type:         Opaque
> Data
> ====
> password:  4 bytes
> username:  5 bytes
> ```
> **Verification** : Le Secret contient bien 2 clés (`username` et `password`). Les valeurs réelles ne sont pas visibles via `describe`.

**Contexte :**
Les valeurs sont encodées en Base64 mais non chiffrées ; elles doivent être protéger via l'API Server.

---

### **5.3 Bonnes pratiques**

* Activer le chiffrement "**at rest**" dans le `kube-apiserver` :

  > **Objectif** : Indiquer au kube-apiserver d'utiliser un fichier de configuration de chiffrement pour protéger les Secrets stockés dans etcd.
  > **Pre-requis** : Fichier `/etc/kubernetes/encryption-config.yaml` créé avec les clés de chiffrement appropriées.

  ```
  # Flag à ajouter dans le manifeste statique du kube-apiserver
  # Active le chiffrement des données stockées dans etcd (Secrets, ConfigMaps, etc.)
  --encryption-provider-config=/etc/kubernetes/encryption-config.yaml
  ```

  > **Resultat attendu** :
  > ```
  # Aucun retour direct — le flag est lu au démarrage du kube-apiserver.
  # Vérifier avec : journalctl -u kubelet | grep encryption
  ```
  > **Verification** : Le kube-apiserver redémarre sans erreur et les Secrets sont chiffrés dans etcd.

* Éviter les exports en clair (`kubectl get secrets -o yaml`).
* Utiliser des solutions externes (**Vault**, **Sealed Secrets**) pour les clusters en production.

---

## **6. Network Policies**

### **6.1 Rôle**

Les **Network Policies** restreignent le trafic entrant (ingress) et sortant (egress) entre Pods.
Par défaut, tous les Pods peuvent communiquer.

---

### **6.2 Exemple de politique globale**

> **Objectif** : Créer une NetworkPolicy "deny-all" qui bloque tout le trafic entrant et sortant pour tous les Pods du namespace `projet-fil-rouge`. C'est la base d'une approche "zero trust".
> **Pre-requis** : Namespace `projet-fil-rouge` existant, CNI compatible avec les NetworkPolicy (Calico, Cilium, etc.).

```yaml
apiVersion: networking.k8s.io/v1         # API stable pour les NetworkPolicy
kind: NetworkPolicy                       # Type de ressource : politique réseau
metadata:
  name: deny-all                          # Nom de la politique
  namespace: projet-fil-rouge             # Namespace ciblé
spec:
  podSelector: {}                         # Sélectionne TOUS les Pods du namespace (sélecteur vide)
  policyTypes:
  - Ingress                               # Active la restriction sur le trafic entrant
  - Egress                                # Active la restriction sur le trafic sortant
  # Aucun bloc "ingress" ni "egress" = tout est bloqué par défaut
```

> **Resultat attendu** :
> ```
> networkpolicy.networking.k8s.io/deny-all created
> ```
> **Verification** : `kubectl get networkpolicy -n projet-fil-rouge` affiche `deny-all`. Tous les Pods du namespace sont isolés — aucun flux entrant ou sortant n'est autorisé.

**Contexte :**
Cette politique bloque tout trafic pour le namespace ; d'autres règles devront ensuite autoriser certains flux.

---

### **6.3 Règle entre frontend et backend**

> **Objectif** : Autoriser uniquement les Pods labellisés `app=frontend` à communiquer avec les Pods labellisés `app=backend` en trafic entrant (ingress).
> **Pre-requis** : Pods `frontend` et `backend` déployés avec les labels `app: frontend` et `app: backend` dans le namespace `projet-fil-rouge`.

```yaml
apiVersion: networking.k8s.io/v1         # API stable pour les NetworkPolicy
kind: NetworkPolicy                       # Type de ressource : politique réseau
metadata:
  name: allow-frontend-backend            # Nom descriptif de la règle
  namespace: projet-fil-rouge             # Namespace ciblé
spec:
  podSelector:                            # Sélectionne les Pods CIBLE (destinataires du trafic)
    matchLabels:
      app: backend                        # Seuls les Pods avec label app=backend sont ciblés
  ingress:                                # Règles de trafic entrant autorisées
  - from:
    - podSelector:                        # Source autorisée : Pods du même namespace
        matchLabels:
          app: frontend                   # Uniquement les Pods avec label app=frontend
  policyTypes:
  - Ingress                               # Cette politique ne filtre que le trafic entrant
```

> **Resultat attendu** :
> ```
> networkpolicy.networking.k8s.io/allow-frontend-backend created
> ```
> **Verification** : `kubectl get networkpolicy -n projet-fil-rouge` affiche `allow-frontend-backend`. Un `curl` depuis un Pod frontend vers le backend fonctionne, mais depuis un autre Pod il échoue (timeout).

**Contexte :**
Seuls les Pods avec le label `app=frontend` peuvent accéder aux Pods `backend`.
Les autres Pods du namespace sont bloqués.

---

## **7. TLS et audit du plan de contrôle**

### **7.1 Sécurité TLS**

Les communications interne et externe sont chiffrées :

* API Server ↔ etcd
* API Server ↔ kubelet
* Client ↔ API Server

Les certificats sont dans `/etc/kubernetes/pki/`.

---

### **7.2 Vérifier les certificats**

> **Objectif** : Vérifier la date d'expiration de tous les certificats TLS du cluster (CA, API Server, etcd, kubelet, etc.) pour anticiper les renouvellements.
> **Pre-requis** : Accès au nœud master avec les droits sudo, cluster initialisé avec kubeadm.

```bash
# Affiche la date d'expiration de chaque certificat utilisé par le cluster
# Utile pour planifier les renouvellements avant expiration
sudo kubeadm certs check-expiration
```

> **Resultat attendu** :
> ```
> CERTIFICATE                EXPIRES                  RESIDUAL TIME   CERTIFICATE AUTHORITY   EXTERNALLY MANAGED
> admin.conf                 Jun 20, 2027 10:00 UTC   364d            ca                      no
> apiserver                  Jun 20, 2027 10:00 UTC   364d            ca                      no
> apiserver-etcd-client      Jun 20, 2027 10:00 UTC   364d            etcd-ca                 no
> apiserver-kubelet-client   Jun 20, 2027 10:00 UTC   364d            ca                      no
> controller-manager.conf    Jun 20, 2027 10:00 UTC   364d            ca                      no
> etcd-healthcheck-client    Jun 20, 2027 10:00 UTC   364d            etcd-ca                 no
> etcd-peer                  Jun 20, 2027 10:00 UTC   364d            etcd-ca                 no
> etcd-server                Jun 20, 2027 10:00 UTC   364d            etcd-ca                 no
> front-proxy-client         Jun 20, 2027 10:00 UTC   364d            front-proxy-ca          no
> scheduler.conf             Jun 20, 2027 10:00 UTC   364d            ca                      no
> ```
> **Verification** : Tous les certificats doivent avoir une durée résiduelle supérieure à 30 jours. Planifier un renouvellement si un certificat expire bientôt.

**Contexte :**
Affiche les dates d'expiration des certificats TLS utilisés par le cluster.

---

### **7.3 Activer l'audit API**

Dans la configuration du kube-apiserver :

> **Objectif** : Activer la journalisation d'audit de l'API Kubernetes pour tracer toutes les requêtes (qui, quand, quoi).
> **Pre-requis** : Fichier de politique d'audit `/etc/kubernetes/audit-policy.yaml` créé, répertoire `/var/log/kubernetes/` existant avec les bons droits.

```
# Fichier de politique d'audit : définit QUOI journaliser (Metadata, Request, RequestResponse, None)
--audit-policy-file=/etc/kubernetes/audit-policy.yaml
# Chemin du fichier de log d'audit : toutes les requêtes API y sont enregistrées
--audit-log-path=/var/log/kubernetes/audit.log
```

> **Resultat attendu** :
> ```
# Aucun retour direct — les flags sont lus au démarrage du kube-apiserver.
# Vérifier avec : tail -f /var/log/kubernetes/audit.log
# Les entrées apparaissent au format JSON avec les champs : user, verb, resource, timestamp, etc.
> ```
> **Verification** : Le fichier `/var/log/kubernetes/audit.log` se remplit avec les requêtes API au format JSON. Chaque entrée contient l'utilisateur, l'action, la ressource et l'horodatage.

**Contexte :**
Permet de journaliser toutes les requêtes API (utilisateur, heure, action).
Indispensable pour la conformité ISO et RGPD.

---

## **8. LAB – Projet Fil Rouge (Phase 4)**

### **8.1 Objectif**

Durcir le projet du chapitre 4 :

* Créer un ServiceAccount spécifique.
* Isoler les flux réseau frontend ↔ backend.
* Protéger les Secrets et restreindre les droits RBAC.

---

### **8.2 Prérequis**

* Cluster Minikube fonctionnel.
* Application du fil rouge déployée (`frontend`, `backend`).
* Namespace `projet-fil-rouge`.
* CNI compatible (Calico ou Flannel).

---

### **8.3 Étape 1 — ServiceAccount et rôle**

Créer `rbac-web.yaml` :

> **Objectif** : Définir dans un seul fichier YAML trois ressources RBAC : un ServiceAccount (`web-sa`), un Role (`read-pods` avec droits de lecture sur les Pods), et un RoleBinding (`bind-read`) qui lie le SA au Role.
> **Pre-requis** : Namespace `projet-fil-rouge` existant.

```yaml
# --- Ressource 1 : ServiceAccount ---
apiVersion: v1                            # API core pour les ServiceAccounts
kind: ServiceAccount                      # Identité applicative pour les Pods
metadata:
  name: web-sa                            # Nom du ServiceAccount
  namespace: projet-fil-rouge             # Namespace cible
---
# --- Ressource 2 : Role (permissions) ---
apiVersion: rbac.authorization.k8s.io/v1  # API RBAC stable
kind: Role                                # Permissions limitées à un namespace
metadata:
  name: read-pods                         # Nom du rôle
  namespace: projet-fil-rouge             # Namespace cible
rules:
- apiGroups: [""]                         # Groupe API core (pods, services, etc.)
  resources: ["pods"]                     # Ressource ciblée : les Pods uniquement
  verbs: ["get", "list"]                  # Actions autorisées : lecture et listage (pas de create/delete)
---
# --- Ressource 3 : RoleBinding (association SA ↔ Role) ---
apiVersion: rbac.authorization.k8s.io/v1  # API RBAC stable
kind: RoleBinding                         # Lie un sujet (SA/user) à un Role
metadata:
  name: bind-read                         # Nom du binding
  namespace: projet-fil-rouge             # Namespace cible
subjects:
- kind: ServiceAccount                    # Type de sujet : un ServiceAccount
  name: web-sa                            # Nom du SA à qui on donne les droits
  namespace: projet-fil-rouge             # Namespace du SA
roleRef:                                  # Référence au rôle à appliquer
  kind: Role                              # Type : Role (pas ClusterRole)
  name: read-pods                         # Nom du rôle référencé
  apiGroup: rbac.authorization.k8s.io     # Groupe API RBAC
```

> **Resultat attendu** :
> ```
> (fichier rbac-web.yaml créé avec succès)
> ```
> **Verification** : Le fichier contient bien 3 documents YAML séparés par `---` : ServiceAccount, Role et RoleBinding.

Appliquer :

> **Objectif** : Appliquer le manifeste RBAC pour créer le ServiceAccount, le Role et le RoleBinding dans le cluster.
> **Pre-requis** : Fichier `rbac-web.yaml` créé, cluster accessible avec droits d'administration.

```bash
# Applique les 3 ressources définies dans le fichier YAML
kubectl apply -f rbac-web.yaml
```

> **Resultat attendu** :
> ```
> serviceaccount/web-sa created
> role.rbac.authorization.k8s.io/read-pods created
> rolebinding.rbac.authorization.k8s.io/bind-read created
> ```
> **Verification** : `kubectl get roles,rolebindings,sa -n projet-fil-rouge` affiche les 3 ressources créées.

**Contexte :**
Ce ServiceAccount dispose seulement du droit de lister les Pods dans le namespace.

---

### **8.4 Étape 2 — Secret sécurisé**

> **Objectif** : Créer un Secret contenant un token de clé API qui sera injecté dans le Pod backend via une variable d'environnement.
> **Pre-requis** : Namespace `projet-fil-rouge` existant, droits de création de Secrets.

```bash
# Crée un Secret nommé 'api-key' avec une clé 'token' contenant la valeur 'AZERTY123'
# La valeur est encodée en Base64 automatiquement (NON chiffrée sans encryption at rest)
kubectl create secret generic api-key \
  --from-literal=token=AZERTY123 \
  -n projet-fil-rouge
```

> **Resultat attendu** :
> ```
> secret/api-key created
> ```
> **Verification** : `kubectl get secret api-key -n projet-fil-rouge` affiche le Secret avec 1 donnée (DATA = 1).

Dans le backend :

> **Objectif** : Injecter la valeur du Secret `api-key` (clé `token`) dans la variable d'environnement `API_TOKEN` du conteneur backend.
> **Pre-requis** : Secret `api-key` créé dans le namespace `projet-fil-rouge`.

```yaml
env:                                    # Bloc de variables d'environnement du conteneur
- name: API_TOKEN                       # Nom de la variable exposée dans le conteneur
  valueFrom:                            # La valeur provient d'une source Kubernetes
    secretKeyRef:                       # Référence à une clé d'un Secret
      name: api-key                     # Nom du Secret source
      key: token                        # Clé spécifique dans le Secret à injecter
```

> **Resultat attendu** :
> ```
> (Extrait du manifeste de déploiement backend — pas de sortie directe)
> ```
> **Verification** : Une fois le Pod redéployé, `kubectl exec -it <pod-backend> -- env | grep API_TOKEN` affiche `API_TOKEN=AZERTY123`.

**Contexte :**
Le Secret est injecté en variable d'environnement dans le Pod backend sans être stocké en clair dans le code.

---

### **8.5 Étape 3 — Politique réseau**

> **Objectif** : Appliquer le fichier YAML de NetworkPolicy qui restreint l'accès au backend aux seuls Pods frontend.
> **Pre-requis** : Fichier `network-policy.yaml` créé (contenu ci-dessous), CNI compatible avec les NetworkPolicy.

```bash
# Applique la NetworkPolicy définie dans le fichier network-policy.yaml
kubectl apply -f network-policy.yaml
```

> **Resultat attendu** :
> ```
> networkpolicy.networking.k8s.io/allow-frontend-backend created
> ```
> **Verification** : `kubectl get networkpolicy -n projet-fil-rouge` affiche la politique `allow-frontend-backend`.

```yaml
apiVersion: networking.k8s.io/v1         # API stable pour les NetworkPolicy
kind: NetworkPolicy                       # Type de ressource : politique réseau
metadata:
  name: allow-frontend-backend            # Nom de la politique
  namespace: projet-fil-rouge             # Namespace ciblé
spec:
  podSelector:                            # Sélectionne les Pods CIBLE
    matchLabels:
      app: backend                        # Cible : Pods avec label app=backend
  ingress:                                # Règles de trafic entrant
  - from:
    - podSelector:                        # Source autorisée (même namespace)
        matchLabels:
          app: frontend                   # Source : Pods avec label app=frontend
  policyTypes:
  - Ingress                               # Filtrage uniquement sur le trafic entrant
```

> **Resultat attendu** :
> ```
> (Contenu du fichier network-policy.yaml — pas de sortie directe)
> ```
> **Verification** : Le fichier est bien structuré avec podSelector ciblant backend et ingress autorisant uniquement frontend.

**Contexte :**
Seuls les Pods frontend peuvent accéder au backend ; les autres communications sont bloquées.

---

### **8.6 Étape 4 — Vérifications**

> **Objectif** : Effectuer un audit complet du namespace pour vérifier que toutes les ressources de sécurité (Secrets, NetworkPolicies, RBAC) sont correctement en place.
> **Pre-requis** : Toutes les étapes précédentes (8.3 à 8.5) exécutées avec succès.

```bash
# Liste toutes les ressources du namespace (Pods, Services, Deployments, ReplicaSets)
kubectl get all -n projet-fil-rouge

# Liste tous les Secrets du namespace (vérifier que db-secret et api-key sont présents)
kubectl get secrets -n projet-fil-rouge

# Liste les NetworkPolicies actives dans le namespace
kubectl get networkpolicy -n projet-fil-rouge

# Vérifie que le SA 'web-sa' a bien le droit de lire les pods (doit retourner "yes")
kubectl auth can-i get pods --as=system:serviceaccount:projet-fil-rouge:web-sa
```

> **Resultat attendu** :
> ```
> NAME                            READY   STATUS    RESTARTS   AGE
> pod/backend-xxx                 1/1     Running   0          5m
> pod/frontend-xxx                1/1     Running   0          5m
>
> NAME                 TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)    AGE
> service/backend-svc  ClusterIP   10.96.xxx.xxx   <none>        8080/TCP   5m
> service/frontend-svc ClusterIP   10.96.xxx.xxx   <none>        80/TCP     5m
>
> NAME                       READY   UP-TO-DATE   AVAILABLE   AGE
> deployment.apps/backend    1/1     1            1           5m
> deployment.apps/frontend   1/1     1            1           5m
>
> NAME         TYPE     DATA   AGE
> api-key      Opaque   1      3m
> db-secret    Opaque   2      3m
>
> NAME                     POD-SELECTOR    AGE
> allow-frontend-backend   app=backend     2m
>
> yes
> ```
> **Verification** :
> - Les Pods frontend et backend sont Running.
> - Les Secrets `api-key` et `db-secret` sont présents.
> - La NetworkPolicy `allow-frontend-backend` est active.
> - Le SA `web-sa` peut lire les pods (`yes`).
> - Tester que `kubectl auth can-i delete pods --as=system:serviceaccount:projet-fil-rouge:web-sa` retourne `no` (principe du moindre privilège).

**Résultats attendus :**

* L'application fonctionne.
* Le flux est limité au couple frontend ↔ backend.
* Les Secrets sont protégés.
* Les droits SA sont restreints.

---

## **9. Bonnes pratiques de sécurité**

* Respect du **moindre privilège** (RBAC et SA).
* **Rotation régulière** des tokens et certificats.
* **Chiffrement at-rest** des Secrets.
* **Audit logging activé** et analysé.
* **Cloisonnement réseau** entre Namespaces.
* **Images signées et scannées** avant déploiement.
