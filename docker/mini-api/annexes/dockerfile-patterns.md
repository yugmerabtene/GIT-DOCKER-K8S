# Patterns Dockerfile (Python)

## Bonnes pratiques pour le mini-projet

- **Multi-stage** pour reduire la taille de l'image finale
- `pip install --no-cache-dir` pour eviter le cache (reduit la taille)
- `.dockerignore` strict pour exclure les fichiers inutiles
- `USER` non-root pour la securite
- Systeme de fichiers `read-only` + `tmpfs` pour /tmp et /run
- Healthcheck au niveau Compose/K8s plutot que dans l'image
- Deployer par **digest** en production (pas par tag)

## Exemple de .dockerignore

```
.git
.gitignore
__pycache__
*.pyc
.env
.venv
venv
*.md
```

## Commandes utiles

```bash
# Analyser la taille des couches
docker history mini-api:1.0

# Inspecter l'image
docker inspect mini-api:1.0

# Scanner les vulnerabilites
docker scout cves mini-api:1.0
```
