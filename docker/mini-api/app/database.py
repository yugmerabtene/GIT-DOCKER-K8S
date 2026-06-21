# -*- coding: utf-8 -*-
"""
database.py — Configuration de la connexion PostgreSQL et utilitaires de session.

Ce module initialise :
- L'URL de connexion a la base de donnees (via variables d'environnement).
- Le moteur SQLAlchemy (`engine`) avec `pool_pre_ping` pour detecter les connexions mortes.
- La session factory (`SessionLocal`) pour les operations ORM.
- Le `Base` declaratif pour definir les modeles.
- Un context manager `session_scope()` pour gerer proprement les transactions.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from contextlib import contextmanager

# --- Configuration de la connexion ---
# Priorite a DATABASE_URL si defini, sinon reconstruction depuis les variables unitaires
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    # Fallback : variables d'environnement unitaires (utile pour K8s/Compose)
    DB_USER = os.getenv("DB_USER", "app")
    DB_PWD = os.getenv("DB_PASSWORD", "app")
    DB_HOST = os.getenv("DB_HOST", "db")
    DB_NAME = os.getenv("DB_NAME", "app_db")
    DB_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PWD}@{DB_HOST}:5432/{DB_NAME}"

# --- Moteur SQLAlchemy ---
# pool_pre_ping=True : verifie que la connexion est vivante avant chaque utilisation
engine = create_engine(DB_URL, pool_pre_ping=True)

# --- Session Factory ---
# autoflush=False : pas de flush automatique avant chaque requete
# autocommit=False : transactions explicites (commit/rollback)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# --- Base declarative pour les modeles ORM ---
Base = declarative_base()


# --- Context manager pour les sessions ---
@contextmanager
def session_scope():
    """
    Fournit une transaction scope pour les operations base de donnees.
    
    Usage:
        with session_scope() as s:
            s.execute(text("SELECT 1"))
    
    Garanties:
    - commit() si tout se passe bien
    - rollback() si exception
    - close() dans tous les cas (finally)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()
