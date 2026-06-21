# -*- coding: utf-8 -*-
"""
models.py — Definition des modeles SQLAlchemy (tables de la base de donnees).

Ce module definit le modele `User` qui represente la table des utilisateurs.
Chaque utilisateur a :
- id : cle primaire auto-incremente
- email : adresse email (unique, indexee)
- password_hash : mot de passe hashe (bcrypt)
- full_name : nom complet (optionnel)
- created_at : date de creation (genere automatiquement par le serveur)
"""

from sqlalchemy import Column, Integer, String, DateTime, func, UniqueConstraint
from .database import Base


class User(Base):
    """
    Modele SQLAlchemy pour la table 'users'.
    
    Attributs:
    - id (int) : Cle primaire, indexee pour les recherches rapides
    - email (str) : Email unique, indexe pour l'authentification
    - password_hash (str) : Hash bcrypt du mot de passe (jamais en clair)
    - full_name (str, optionnel) : Nom complet de l'utilisateur
    - created_at (datetime) : Horodatage de creation (timezone-aware)
    
    Contraintes:
    - UniqueConstraint sur 'email' pour garantir l'unicite au niveau DB
    """
    __tablename__ = "users"
    
    # --- Colonnes ---
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # --- Contraintes supplementaires ---
    __table_args__ = (
        UniqueConstraint('email', name='uq_users_email'),
    )
    
    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}')>"
