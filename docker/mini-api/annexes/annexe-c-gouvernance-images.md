# Annexe C — Politique de nommage, immutabilite & retention d'images

## Objectifs
- Standardiser la **nomenclature** des images
- Empecher les erreurs (tags mouvants)
- Maitriser les couts de stockage via la **retention**

## 1) Nommage & labels
- Chemin : `registry.intra/ORG/PROJET/SERVICE` (minuscule, `-` separateur)
- Exemples :
  - `registry.intra/clairfact/pdp/api`
  - `ghcr.io/acme/shop/web`

### Labels OCI obligatoires
```dockerfile
LABEL org.opencontainers.image.source="https://git.example.com/acme/web" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="2025-11-01T00:00:00Z"
```

## 2) Versionning & tags
- **SemVer** : `v1.4.2` + canaux : `-rc`, `-beta`, `-dev`
- **Interdit en prod** : `latest`
- **Deploiement** : toujours **`@sha256:digest`**

## 3) Immutabilite & promotion
```bash
DIGEST=$(crane digest registry.intra/acme/web:v1.4.2)
crane copy registry.intra/acme/web@${DIGEST} registry.intra/acme/web-prod:v1.4.2
```

## 4) Retention & GC
- **Dev** : 20 versions / 30 jours
- **RC/QA** : 10 versions / 90 jours
- **Prod** : 10 versions **immuables** / 2 ans

## 5) Politique
- Images en production DOIVENT etre referencees par digest
- Tags de release (`vX.Y.Z`) sont immuables
- `latest` interdit sur QA/Prod
- Images DOIVENT etre signees (cosign) + SBOM
