# -*- coding: utf-8 -*-
"""
main.py — Application FastAPI principale : endpoints et configuration.

Ce module definit :
- L'application FastAPI avec CORS
- Les endpoints :
  - GET /health : verification de sante (utilise par Docker/K8s)
  - GET /users/me : retourne l'utilisateur authentifie (protege par JWT)
- L'inclusion du router d'authentification (/auth/*)
- La creation automatique des tables au demarrage
"""

import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from .database import Base, engine, session_scope
from . import models
from .auth import router as auth_router, current_user

# --- Creation de l'application FastAPI ---
# title : nom affiche dans la documentation Swagger
# version : version de l'API (utilise pour le versionning)
app = FastAPI(title="Mini API", version="1.0.0")

# --- Configuration CORS (Cross-Origin Resource Sharing) ---
# Permet aux navigateurs web d'acceder a l'API depuis un autre domaine
# ATTENTION : configuration permissive pour le developpement uniquement !
# En production, restreindre allow_origins aux domaines autorises
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],              # Tous les domaines (dev only)
    allow_credentials=True,           # Autorise les cookies/auth
    allow_methods=["*"],              # Toutes les methodes HTTP
    allow_headers=["*"],              # Tous les headers
)

# --- Creation automatique des tables ---
# Cree les tables definies dans models.py si elles n'existent pas
# ATTENTION : pour la production, preferer les migrations Alembic
Base.metadata.create_all(bind=engine)

# --- Inclusion du router d'authentification ---
# Ajoute les endpoints /auth/register et /auth/login
app.include_router(auth_router)


@app.get("/health")
def health():
    """
    Endpoint de verification de sante (healthcheck).
    
    Utilise par Docker Compose et Kubernetes pour verifier que :
    - L'application demarre correctement
    - La connexion a la base de donnees fonctionne
    
    Returns:
        dict : {"status": "ok"} si tout va bien
    
    Raises:
        Exception : Si la connexion DB echoue (Docker/K8s redemarrera le conteneur)
    
    Example:
        GET /health
        
        Reponse 200:
        {
            "status": "ok"
        }
    """
    with session_scope() as s:
        # Execute une requete simple pour verifier la connexion DB
        s.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/users/me")
def me(user=Depends(current_user)):
    """
    Endpoint protege : retourne les donnees de l'utilisateur authentifie.
    
    Necessite un token JWT valide dans le header Authorization: Bearer <token>
    
    Args:
        user (User) : Utilisateur extrait du token (injecte par current_user)
    
    Returns:
        dict : Donnees de l'utilisateur (id, email, full_name)
    
    Raises:
        HTTPException 401 : Si le token est invalide ou expire
    
    Example:
        GET /users/me
        Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
        
        Reponse 200:
        {
            "id": 1,
            "email": "user@example.com",
            "full_name": "John Doe"
        }
    """
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name
    }
