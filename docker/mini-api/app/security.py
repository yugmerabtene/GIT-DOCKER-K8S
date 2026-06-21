# -*- coding: utf-8 -*-
"""
security.py — Fonctions de securite : hachage de mots de passe et gestion JWT.

Ce module fournit :
- hash_password() : hashe un mot de passe avec bcrypt
- verify_password() : verifie un mot de passe contre un hash
- create_access_token() : cree un token JWT avec expiration
- decode_token() : decode et verifie un token JWT

Configuration (via variables d'environnement) :
- JWT_SECRET : cle secrete pour signer les tokens (ou JWT_SECRET_FILE pour lire depuis un fichier)
- JWT_ALG : algorithme de signature (defaut: HS256)
- JWT_EXPIRE_MIN : duree de validite en minutes (defaut: 60)
"""

import os
import datetime
from jose import jwt
from passlib.context import CryptContext

# --- Contexte de hachage bcrypt ---
# schemes=["bcrypt"] : utilise bcrypt pour le hachage (secure et adapte)
# deprecated="auto" : marque automatiquement les anciens algorithmes comme deprecies
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Configuration JWT ---
# Priorite au fichier si present (meilleure securite en production)
JWT_SECRET = None
_secret_file = os.getenv("JWT_SECRET_FILE")
if _secret_file and os.path.exists(_secret_file):
    # Lit la cle secrete depuis un fichier (ex: Docker secret, K8s secret mount)
    JWT_SECRET = open(_secret_file, 'rb').read().decode('utf-8').strip()

if not JWT_SECRET:
    # Fallback sur variable d'environnement (dev/test)
    JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-prod")

# Algorithme de signature JWT
JWT_ALG = os.getenv("JWT_ALG", "HS256")

# Duree de validite du token en minutes
JWT_EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MIN", "60"))


def hash_password(p: str) -> str:
    """
    Hashe un mot de passe avec bcrypt.
    
    Args:
        p (str) : Mot de passe en clair
    
    Returns:
        str : Hash bcrypt du mot de passe
    
    Example:
        >>> hashed = hash_password("mysecretpassword")
        >>> print(hashed)
        '$2b$12$Lqo3...'
    """
    return pwd_ctx.hash(p)


def verify_password(p: str, hashed: str) -> bool:
    """
    Verifie un mot de passe contre un hash bcrypt.
    
    Args:
        p (str) : Mot de passe en clair a verifier
        hashed (str) : Hash bcrypt stocke en base
    
    Returns:
        bool : True si le mot de passe correspond au hash, False sinon
    
    Example:
        >>> verify_password("mysecretpassword", "$2b$12$Lqo3...")
        True
    """
    return pwd_ctx.verify(p, hashed)


def create_access_token(sub: str) -> str:
    """
    Cree un token JWT avec expiration.
    
    Args:
        sub (str) : Sujet du token (generalement l'ID de l'utilisateur)
    
    Returns:
        str : Token JWT signe
    
    Payload du token:
    - sub : sujet (ID utilisateur)
    - iat : "issued at" (date de creation)
    - exp : expiration (iat + JWT_EXPIRE_MIN)
    
    Example:
        >>> token = create_access_token("42")
        >>> print(token)
        'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
    """
    now = datetime.datetime.utcnow()
    payload = {
        "sub": sub,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=JWT_EXPIRE_MIN),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    """
    Decode et verifie un token JWT.
    
    Args:
        token (str) : Token JWT a decoder
    
    Returns:
        dict : Payload du token (contient 'sub', 'iat', 'exp')
    
    Raises:
        jose.ExpiredSignatureError : Si le token a expire
        jose.JWTError : Si le token est invalide
    
    Example:
        >>> payload = decode_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
        >>> print(payload['sub'])
        '42'
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
