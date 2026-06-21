# -*- coding: utf-8 -*-
"""
schemas.py — Schemas Pydantic pour la validation des donnees (entrees/sorties API).

Ce module definit les schemas de validation pour :
- UserCreate : donnees pour l'inscription (email, password, full_name)
- UserLogin : donnees pour la connexion (email, password)
- UserOut : reponse API pour les donnees utilisateur (sans le mot de passe)
- Token : reponse API pour le token JWT apres login reussi
"""

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """
    Schema pour l'inscription d'un nouvel utilisateur.
    
    Champs:
    - email (EmailStr) : Email valide (valide automatiquement par Pydantic)
    - password (str) : Mot de passe, minimum 8 caracteres
    - full_name (str, optionnel) : Nom complet de l'utilisateur
    """
    email: EmailStr
    password: str = Field(min_length=8, description="Mot de passe, min 8 caracteres")
    full_name: str | None = None


class UserLogin(BaseModel):
    """
    Schema pour la connexion d'un utilisateur existant.
    
    Champs:
    - email (EmailStr) : Email de l'utilisateur
    - password (str) : Mot de passe en clair (sera verifie contre le hash)
    """
    email: EmailStr
    password: str


class UserOut(BaseModel):
    """
    Schema de reponse pour les donnees utilisateur (sans mot de passe).
    
    Champs:
    - id (int) : ID de l'utilisateur
    - email (EmailStr) : Email de l'utilisateur
    - full_name (str, optionnel) : Nom complet
    
    Config:
    - from_attributes=True : permet de convertir un modele SQLAlchemy en schema Pydantic
    """
    id: int
    email: EmailStr
    full_name: str | None = None
    
    class Config:
        from_attributes = True  # Compatible avec les modeles SQLAlchemy


class Token(BaseModel):
    """
    Schema de reponse pour le token JWT apres login reussi.
    
    Champs:
    - access_token (str) : Token JWT a utiliser dans le header Authorization
    - token_type (str) : Type de token, toujours "bearer"
    """
    access_token: str
    token_type: str = "bearer"
