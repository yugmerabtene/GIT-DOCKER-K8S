# git-docker-k8s

Supports de cours complets couvrant **Git**, **Docker** et **Kubernetes** : des fondamentaux jusqu'a la production, en passant par la securite, l'observabilite et la CI/CD.

---

## Pre-requis generaux

- Bases Linux (shell, permissions, processus)
- Notions reseau (IP/CIDR, ports, DNS)
- Git + editeur de code (VS Code recommande)
- Docker Desktop / Engine installe (pour la partie Docker)

---

## Sommaire

### [Git](git/)

| Chapitre | Sujet |
|----------|-------|
| *(a completer)* | Contenu Git a rediger |

---

### [Docker](docker/)

| Chapitre | Sujet |
|----------|-------|
| 00 | Installation & Environnement |
| 01 | Images Docker (OCI, layers, digests) |
| 02 | Conteneurs (cycle de vie & execution) |
| 03 | Storage (volumes, bind mounts, tmpfs) |
| 04 | Reseau Docker |
| 05 | Dockerfile & Build (BuildKit avance) |
| 06 | Docker Compose v2 (multi-services) |
| 07 | Registry & Distribution |
| 08 | Securite & Durcissement |
| 09 | Observabilite & Diagnostic |
| 10 | Performance & Optimisation |
| 11 | CI/CD avec Docker |
| 12 | Exploitation en Production (sans orchestrateur) |
| 13 | Swarm & Passerelle vers Kubernetes |
| 14 | Mini-projet Python API + Docker + Swarm + K8s + Helm |

---

### [Kubernetes](k8s/)

| Chapitre | Sujet |
|----------|-------|
| 1 | Introduction & principes Kubernetes |
| 2 | Architecture detaillee |
| 3 | Installation & environnements de lab |
| 4 | Administration et supervision |
| 5 | Securite et durcissement du cluster |
| 6 | Stockage & Donnees |
| 7 | Configuration & Secrets |
| 8 | Securite & Politiques (RBAC, PSA, NetworkPolicies) |
| 9 | Observabilite & Journalisation |
| 10 | Packaging & Deploiement applicatif |
| 11 | CI/CD & GitOps |
| 12 | Troubleshooting & Performance |
| 13 | Orchestration avancee & ecosysteme |
| 14 | Gouvernance & Conformite des images |

**Ressources complementaires :**
- [Lexique Kubernetes](k8s/lexiques.md)
- [Annexes K8s (cheat-sheet kubectl, YAML patterns...)](k8s/Annexes%20(supports%20fournis).md)

---

## Progression recommandee

```
Git (bases) → Docker (00 a 14) → Kubernetes (1 a 14)
```

1. **Git** : maitriser le versioning avant tout
2. **Docker** : construire des images propres, operer des conteneurs, securiser
3. **Kubernetes** : orchestrer a l'echelle, deployer en production

---

## Licence

Ce contenu est distribue sous licence [Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)](LICENSE).
