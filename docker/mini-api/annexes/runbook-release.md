# Runbook Release (Compose)

## Procedure de deploiement

### 1. Pre-flight checks
- [ ] Digest signe et verifie
- [ ] Base de donnees operationnelle
- [ ] NTP synchronise
- [ ] Espace disque suffisant

### 2. Deploiement green
```bash
docker compose -p app-green -f compose.yaml up -d
```

### 3. Migrations
```bash
docker compose run --rm migrate
```

### 4. Canary 10%
- Configurer le load balancer pour 10% vers green
- Observer metriques et logs pendant 15-30 minutes

### 5. Promotion progressive
- 50% → observer 15 min
- 100% → garder blue 24h en standby

### 6. Nettoyage
- Arreter l'environnement blue
- Post-mortem si incidents

## Rollback
```bash
# Remettre 100% du trafic sur blue
# Arreter green
docker compose -p app-green down
```
