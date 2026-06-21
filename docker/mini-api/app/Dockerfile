# =============================================================================
# Dockerfile multi-stage pour Mini API (FastAPI + PostgreSQL)
# =============================================================================
# 
# OBJECTIF : Construire une image Docker minimale et securisee pour l'API FastAPI.
#
# STRATEGIE : Multi-stage build
# - Stage 1 (base) : Installation des dependances (y compris natives comme psycopg2)
# - Stage 2 (runtime) : Copie des dependances + code source, execution en non-root
#
# RESULTAT ATTENDU :
# - Image finale basee sur python:3.12-slim (~150-200 MB)
# - Pas d'outils de compilation dans l'image finale
# - Execution en tant qu'utilisateur non-root (appuser)
# - Exposition du port 8000
#
# USAGE :
#   docker build -t mini-api:1.0 ./app
#   docker run -p 8000:8000 mini-api:1.0
#
# VERIFICATION :
#   docker images mini-api:1.0  # Doit afficher ~150-200 MB
#   docker run mini-api:1.0 whoami  # Doit afficher "appuser"
# =============================================================================

# -----------------------------------------------------------------------------
# STAGE 1 : Base avec dependances compilees
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS base

# Variables d'environnement pour optimiser Python et pip
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Repertoire de travail
WORKDIR /app

# Copie du fichier des dependances
COPY requirements.txt ./

# Installation des dependances systeme necessaires pour la compilation
# - build-essential : compilateur C pour psycopg2
# Installation des dependances Python
# Nettoyage : suppression de build-essential et des caches apt
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && pip install -r requirements.txt \
    && apt-get purge -y build-essential \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------------
# STAGE 2 : Runtime minimal (non-root)
# -----------------------------------------------------------------------------
FROM python:3.12-slim

# Variables d'environnement Python
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Creation d'un utilisateur non-root pour la securite
# --disabled-password : pas de mot de passe (connexion SSH desactivee)
# --gecos "" : pas d'information utilisateur (evite les prompts interactifs)
RUN adduser --disabled-password --gecos "" appuser

# Repertoire de travail
WORKDIR /app

# Copie des dependances Python depuis le stage 1
# - /usr/local/lib/python3.12 : site-packages (dependances installees)
# - /usr/local/bin : executables (uvicorn, pip, etc.)
COPY --from=base /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=base /usr/local/bin /usr/local/bin

# Copie du code source de l'application
COPY . .

# Changement vers l'utilisateur non-root
USER appuser

# Exposition du port (documentaire, ne publie pas le port)
EXPOSE 8000

# Commande de demarrage : lancement de l'API avec Uvicorn
# --host 0.0.0.0 : ecoute sur toutes les interfaces (necessaire dans Docker)
# --port 8000 : port d'ecoute
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
