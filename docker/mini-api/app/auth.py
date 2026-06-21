# -*- coding: utf-8 -*-
"""
auth.py — Routes d'authentification : inscription, connexion, et dependency injection.

Ce module definit les endpoints :
- POST /auth/register : inscription d'un nouvel utilisateur
- POST /auth/login : connexion et obtention d'un token JWT
- current_user() : dependency pour extraire l'utilisateur courant depuis le token

Flux d'authentification :
1. L'utilisateur s'inscrit via /auth/register (email + password)
2. L'utilisateur se connecte via /auth/login et recoit un token JWT
3. Pour les routes protegees, le token est envoye dans le header Authorization: Bearer <token>
4. La dependency current_user() decode le token et retourne l'utilisateur correspondant
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .database import SessionLocal
from . import models, schemas
from .security import hash_password, verify_password, create_access_token, decode_token

# --- Router pour les endpoints d'authentification ---
# prefix="/auth" : tous les endpoints commencent par /auth
# tags=["auth"] : regroupement dans la documentation Swagger
router = APIRouter(prefix="/auth", tags=["auth"])

# --- Schema OAuth2 pour extraire le token du header Authorization ---
# tokenUrl="/auth/login" : indique ou obtenir un token (pour la doc Swagger)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db():
    """
    Dependency pour obtenir une session base de donnees.
    
    Usage:
        def my_endpoint(db: Session = Depends(get_db)):
            ...
    
    Garanties:
    - La session est fermee apres usage (finally)
    - Pas de commit automatique (a gerer explicitement)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/register", response_model=schemas.UserOut, status_code=201)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    """
    Inscrit un nouvel utilisateur.
    
    Args:
        payload (UserCreate) : Donnees d'inscription (email, password, full_name)
        db (Session) : Session base de donnees (injectee)
    
    Returns:
        UserOut : Donnees de l'utilisateur cree (sans mot de passe)
    
    Raises:
        HTTPException 409 : Si l'email est deja utilise
    
    Example:
        POST /auth/register
        {
            "email": "user@example.com",
            "password": "securepassword123",
            "full_name": "John Doe"
        }
        
        Reponse 201:
        {
            "id": 1,
            "email": "user@example.com",
            "full_name": "John Doe"
        }
    """
    # Verifie si l'email est deja utilise
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    
    # Cree le nouvel utilisateur avec mot de passe hashe
    user = models.User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=schemas.Token)
def login(payload: schemas.UserLogin, db: Session = Depends(get_db)):
    """
    Connecte un utilisateur et retourne un token JWT.
    
    Args:
        payload (UserLogin) : Donnees de connexion (email, password)
        db (Session) : Session base de donnees (injectee)
    
    Returns:
        Token : Token JWT avec access_token et token_type
    
    Raises:
        HTTPException 401 : Si les identifiants sont invalides
    
    Example:
        POST /auth/login
        {
            "email": "user@example.com",
            "password": "securepassword123"
        }
        
        Reponse 200:
        {
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "token_type": "bearer"
        }
    """
    # Recherche l'utilisateur par email
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    
    # Verifie que l'utilisateur existe et que le mot de passe correspond
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    # Genere le token JWT avec l'ID de l'utilisateur comme sujet
    token = create_access_token(str(user.id))
    return {"access_token": token, "token_type": "bearer"}


def current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> models.User:
    """
    Dependency pour extraire l'utilisateur courant depuis le token JWT.
    
    Usage:
        @app.get("/protected")
        def protected_route(user: models.User = Depends(current_user)):
            return {"user_id": user.id}
    
    Args:
        token (str) : Token JWT extrait du header Authorization (injecte)
        db (Session) : Session base de donnees (injectee)
    
    Returns:
        User : Modele SQLAlchemy de l'utilisateur authentifie
    
    Raises:
        HTTPException 401 : Si le token est invalide, expire, ou l'utilisateur n'existe pas
    
    Example:
        GET /protected
        Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
        
        -> user = <User(id=1, email='user@example.com')>
    """
    try:
        # Decode le token et extrait le sujet (ID utilisateur)
        payload = decode_token(token)
        uid = int(payload.get("sub"))
    except Exception:
        # Token invalide, expire, ou mal forme
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Recherche l'utilisateur dans la base
    user = db.query(models.User).get(uid)
    if not user:
        # L'utilisateur n'existe plus (supprime entre-temps)
        raise HTTPException(status_code=401, detail="User not found")
    
    return user
