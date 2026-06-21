# **Chapitre 5 — Sécurité et durcissement du cluster Kubernetes**

*(RBAC, Service Accounts, Secrets, Policies, TLS, Network Security)*

---

## **1. Objectifs d’apprentissage**

À la fin de ce chapitre, l’apprenant sera capable de :

* Comprendre les **mécanismes de sécurité intégrés** à Kubernetes.
* Mettre en œuvre le **contrôle d’accès basé sur les rôles (RBAC)**.
* Gérer les **identités applicatives** via les **Service Accounts**.
* Sécuriser les **informations sensibles** avec **Secrets**.
* Définir des **politiques réseau (Network Policies)**.
* Configurer la **sécurité TLS**, l’**audit API** et la **sécurisation des communications**.
* Poursuivre le **projet fil rouge** (phase 4) en durcissant le cluster et les Pods.

---

## **2. Principes fondamentaux de la sécurité Kubernetes**

### **2.1 Modèle de sécurité en profondeur**

Kubernetes applique une stratégie de **“Defense in Depth”** :

1. **Authentification (AuthN)** : identifier qui fait la requête.
2. **Autorisation (AuthZ)** : déterminer ce qu’il peut faire.
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

## **3. Contrôle d’accès RBAC**

### **3.1 Principe**

Le **Role-Based Access Control** (RBAC) définit les actions autorisées sur les ressources Kubernetes.

* **Role** : permissions dans un namespace.
* **ClusterRole** : permissions globales.
* **RoleBinding / ClusterRoleBinding** : lient ces rôles à des utilisateurs ou Service Accounts.

---

### **3.2 Hiérarchie logique**

```
Utilisateur / ServiceAccount
   │
   ▼
RoleBinding
   │
   ▼
Role
```

**Contexte :**
Le Role contient les droits, le Binding relie ces droits à une identité.

---

### **3.3 Commandes utiles**

```bash
kubectl get roles,rolebindings -A
kubectl auth can-i list pods --as=system:serviceaccount:default:sa1
```

**Contexte :**
La seconde commande teste les permissions d’une identité (utile pour vérifier qu’un ServiceAccount n’a pas de droits excessifs).

---

### **3.4 Bonnes pratiques**

* Appliquer le **principe du moindre privilège**.
* Créer des rôles spécifiques par namespace.
* Réserver les **ClusterRoles** aux administrateurs.
* Auditer régulièrement les droits (`kubectl get clusterrolebindings`).

---

## **4. Service Accounts et identités applicatives**

### **4.1 Définition**

Un **Service Account (SA)** est l’identité utilisée par un Pod pour parler à l’API Kubernetes.
Chaque namespace possède un SA `default`, mais il est recommandé de créer des SA dédiés.

---

### **4.2 Fichiers et tokens**

Le token du SA est automatiquement monté dans le Pod à :
`/var/run/secrets/kubernetes.io/serviceaccount/token`.

Il sert pour les appels authentifiés à l’API.

---

### **4.3 Commandes**

```bash
kubectl create serviceaccount webapp-sa -n projet-fil-rouge
kubectl get serviceaccounts -n projet-fil-rouge
kubectl describe sa webapp-sa -n projet-fil-rouge
```

**Contexte :**
Ces commandes créent et inspectent un SA qui sera lié par un RoleBinding à un rôle limité.

---

## **5. Secrets et données sensibles**

### **5.1 Utilité**

Les **Secrets** contiennent des mots de passe, clés API ou certificats.
Ils peuvent être montés dans un Pod ou injectés en variable d’environnement.

---

### **5.2 Création et affichage**

```bash
kubectl create secret generic db-secret \
  --from-literal=username=admin \
  --from-literal=password=1234 \
  -n projet-fil-rouge
kubectl get secrets -n projet-fil-rouge
kubectl describe secret db-secret -n projet-fil-rouge
```

**Contexte :**
Les valeurs sont encodées en Base64 mais non chiffrées ; elles doivent être protéger via l’API Server.

---

### **5.3 Bonnes pratiques**

* Activer le chiffrement “**at rest**” dans le `kube-apiserver` :

  ```
  --encryption-provider-config=/etc/kubernetes/encryption-config.yaml
  ```
* Éviter les exports en clair (`kubectl get secrets -o yaml`).
* Utiliser des solutions externes (**Vault**, **Sealed Secrets**) pour les clusters en production.

---

## **6. Network Policies**

### **6.1 Rôle**

Les **Network Policies** restreignent le trafic entrant (ingress) et sortant (egress) entre Pods.
Par défaut, tous les Pods peuvent communiquer.

---

### **6.2 Exemple de politique globale**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
  namespace: projet-fil-rouge
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
```

**Contexte :**
Cette politique bloque tout trafic pour le namespace ; d’autres règles devront ensuite autoriser certains flux.

---

### **6.3 Règle entre frontend et backend**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-backend
  namespace: projet-fil-rouge
spec:
  podSelector:
    matchLabels:
      app: backend
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
  policyTypes:
  - Ingress
```

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

```bash
sudo kubeadm certs check-expiration
```

**Contexte :**
Affiche les dates d’expiration des certificats TLS utilisés par le cluster.

---

### **7.3 Activer l’audit API**

Dans la configuration du kube-apiserver :

```
--audit-policy-file=/etc/kubernetes/audit-policy.yaml
--audit-log-path=/var/log/kubernetes/audit.log
```

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

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: web-sa
  namespace: projet-fil-rouge
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: read-pods
  namespace: projet-fil-rouge
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: bind-read
  namespace: projet-fil-rouge
subjects:
- kind: ServiceAccount
  name: web-sa
  namespace: projet-fil-rouge
roleRef:
  kind: Role
  name: read-pods
  apiGroup: rbac.authorization.k8s.io
```

Appliquer :

```bash
kubectl apply -f rbac-web.yaml
```

**Contexte :**
Ce ServiceAccount dispose seulement du droit de lister les Pods dans le namespace.

---

### **8.4 Étape 2 — Secret sécurisé**

```bash
kubectl create secret generic api-key \
  --from-literal=token=AZERTY123 \
  -n projet-fil-rouge
```

Dans le backend :

```yaml
env:
- name: API_TOKEN
  valueFrom:
    secretKeyRef:
      name: api-key
      key: token
```

**Contexte :**
Le Secret est injecté en variable d’environnement dans le Pod backend sans être stocké en clair dans le code.

---

### **8.5 Étape 3 — Politique réseau**

```bash
kubectl apply -f network-policy.yaml
```

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-backend
  namespace: projet-fil-rouge
spec:
  podSelector:
    matchLabels:
      app: backend
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
  policyTypes:
  - Ingress
```

**Contexte :**
Seuls les Pods frontend peuvent accéder au backend ; les autres communications sont bloquées.

---

### **8.6 Étape 4 — Vérifications**

```bash
kubectl get all -n projet-fil-rouge
kubectl get secrets -n projet-fil-rouge
kubectl get networkpolicy -n projet-fil-rouge
kubectl auth can-i get pods --as=system:serviceaccount:projet-fil-rouge:web-sa
```

**Résultats attendus :**

* L’application fonctionne.
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
