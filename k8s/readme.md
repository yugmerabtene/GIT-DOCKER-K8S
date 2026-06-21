# Kubernetes — Sommaire du cours

**Description generale.** Etude structuree et exhaustive de Kubernetes : de l'architecture et des objets fondamentaux jusqu'a la production (securite, observabilite, CI/CD, GitOps, troubleshooting, gouvernance).
**Pre-requis.** Bases Linux (shell, permissions, processus, systemd), notions reseau (IP/CIDR, ports, DNS, HTTP/TLS), Docker (images, conteneurs, Compose — voir le cours Docker de ce depot), Git + VS Code.
**Competences visees.** Deployer et operer des applications conteneurisees a l'echelle, securiser un cluster (RBAC, PSA, NetworkPolicies, admission), mettre en place une supply-chain d'images (SBOM, signatures, politiques), observer et deboguer en production, appliquer les principes GitOps.

---

## Progression recommandee

```
Bloc 1 : Fondations          → Chapitres 1 a 4
Bloc 2 : Production          → Chapitres 5 a 9
Bloc 3 : Packaging & CI/CD   → Chapitres 10 a 11
Bloc 4 : Operations          → Chapitres 12 a 14
```

---

## Sommaire detaille

### Bloc 1 — Fondations

| Chapitre | Sujet | Objectifs cles |
|----------|-------|----------------|
| [1](Chapitre-01%20—%20Introduction%20&%20principes%20Kubernetes.md) | Introduction & principes | Comprendre K8s, son origine, son modele declaratif |
| [2](Chapitre-02%20—%20Architecture%20détaillée.md) | Architecture detaillee | Control Plane, Nodes, boucle de reconciliation |
| [3](Chapitre-03%20—%20Installation%20&%20environnements%20de%20lab.md) | Installation & labs | kubeadm, minikube, kind, k3s, managed (EKS/GKE/AKS) |
| [4](Chapitre-04%20—%20Administration%20et%20supervision.md) | Administration et supervision | Logs, metriques, rolling updates, scaling, supervision |

### Bloc 2 — Production

| Chapitre | Sujet | Objectifs cles |
|----------|-------|----------------|
| [5](Chapitre-05%20—%20Sécurité%20et%20durcissement%20du%20cluster%20Kubernetes.md) | Securite & durcissement cluster | RBAC, ServiceAccounts, Secrets, TLS, NetworkPolicies |
| [6](Chapitre-06%20—%20Stockage%20&%20Données.md) | Stockage & Donnees | PV/PVC, StorageClass, CSI, StatefulSet, snapshots |
| [7](Chapitre-07%20—%20Configuration%20&%20Secrets.md) | Configuration & Secrets | ConfigMap, Secret, injection, chiffrement at-rest |
| [8](Chapitre-08%20—%20Sécurité%20&%20Politiques.md) | Securite & Politiques | PSA, Kyverno/Gatekeeper, admission, seccomp/AppArmor, Audit |
| [9](Chapitre-09%20—%20Observabilité%20&%20Journalisation.md) | Observabilite & Journalisation | Prometheus, Grafana, logs centralises, tracing |

### Bloc 3 — Packaging & CI/CD

| Chapitre | Sujet | Objectifs cles |
|----------|-------|----------------|
| [10](Chapitre-10%20—%20Packaging%20&%20Déploiement%20applicatif.md) | Packaging & Deploiement | Dockerfile reproductible, Helm, Kustomize, strategies (rolling/blue-green/canary) |
| [11](Chapitre-11%20—%20CI-CD%20&%20GitOp.md) | CI/CD & GitOps | Pipeline complet (build/scan/sign/push), Argo CD, Flux |

### Bloc 4 — Operations

| Chapitre | Sujet | Objectifs cles |
|----------|-------|----------------|
| [12](Chapitre-12%20—%20Troubleshooting%20&%20Performance.md) | Troubleshooting & Performance | Triage, runbooks, classes de pannes, optimisation |
| [13](Chapitre-13%20—%20Orchestration%20avancée%20&%20écosystème%20(aperçu).md) | Orchestration avancee & ecosysteme | CRDs/Operators, Gateway API, Service Mesh, autoscaling avance, multi-cluster |
| [14](Chapitre-14%20—%20Gouvernance%20&%20Conformité%20des%20images%20(rappel).md) | Gouvernance & Conformite images | Nommage, immutabilite, SBOM, signatures, politiques d'admission |

---

## Ressources complementaires

| Ressource | Description |
|-----------|-------------|
| [Lexique Kubernetes](lexiques.md) | Glossaire complet (A-Z) + mini-lexiques Securite, Reseau, Stockage, Operations |
| [Annexes](Annexes%20(supports%20fournis).md) | Cheat-sheet kubectl, patterns YAML, exemples de manifests |

---

## Liens avec le cours Docker

| Docker | Kubernetes |
|--------|------------|
| Ch-05 Dockerfile & Build | Ch-10 Packaging & Deploiement |
| Ch-07 Registry & Distribution | Ch-14 Gouvernance & Conformite |
| Ch-08 Securite & Durcissement | Ch-5 & Ch-8 Securite K8s |
| Ch-11 CI/CD Docker | Ch-11 CI/CD & GitOps |
| Ch-13 Swarm & Passerelle K8s | Ch-1 Introduction |

---

## Conventions utilisees dans ce cours

- **Variables d'environnement** : `ORG`, `APP`, `IMG`, `VER`, `GIT_SHA` (definies en debut de chapitre).
- **Namespace** : `app` par defaut pour les exemples.
- **Registry** : `ghcr.io` par defaut (transposable a Harbor, GitLab, etc.).
- **Deployer par digest** : `image@sha256:...` en production, jamais `:latest`.
