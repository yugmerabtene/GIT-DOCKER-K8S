# =============================================================================
# Makefile — Commandes utilitaires pour le mini-projet
# =============================================================================
#
# OBJECTIF : Automatiser les operations courantes avec des commandes simples.
#
# USAGE :
#   make dev     # Lance en mode developpement (avec reload)
#   make up      # Lance en mode production
#   make down    # Arrete tous les conteneurs
#   make logs    # Affiche les logs de l'API
#   make build   # Construit l'image Docker
#   make test    # Teste l'endpoint /health
#
# PERSONNALISATION :
#   make ENV=.env.prod up  # Utilise un fichier .env different
# =============================================================================

SHELL := /bin/bash
ENV ?= .env

.PHONY: dev up down logs build test

# --- Developpement ---
# Lance avec compose.dev.yaml (bind mount + reload)
dev:
	docker compose -f compose.yaml -f compose.dev.yaml --env-file $(ENV) up -d

# --- Production ---
# Lance avec la configuration de production
up:
	docker compose --env-file $(ENV) up -d

# --- Arret ---
# Arrete tous les conteneurs et supprime les orphelins
down:
	docker compose down --remove-orphans

# --- Logs ---
# Affiche les logs de l'API en temps reel (derniers 200 lignes)
logs:
	docker compose logs -f --tail=200 api

# --- Build ---
# Construit l'image Docker de l'API
build:
	docker build -t mini-api:1.0 ./app

# --- Test ---
# Teste l'endpoint /health avec curl et jq
test:
	curl -s localhost:8000/health | jq .
