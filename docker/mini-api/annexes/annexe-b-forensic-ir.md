# Annexe B — Forensic & reponse a incident (IR)

## Objectifs
- **Preserver les preuves** (integrite, horodatage) en environnement Docker
- Capturer images, couches, logs, volumes, evenements, traces reseau
- Alignement **ISO 27001** (registre de preuves, chaine de possession)

## 1) Principes cles
- **Ne pas alterer** la scene : eviter redemarrages, `docker commit`
- **Horodatage fiable** (NTP), **hash** (SHA-256) apres chaque capture
- **Chaine de possession** : qui, quoi, quand, comment

## 2) Collecte rapide
```bash
# Liste & etats
docker ps -a > evidence/ps_a.txt
docker events --since=24h > evidence/events_24h.txt

# Pour chaque conteneur
for c in $(docker ps -a --format '{{.ID}}'); do
  mkdir -p evidence/$c
  docker inspect $c > evidence/$c/inspect.json
  docker logs --since=24h $c > evidence/$c/logs_24h.txt
  docker export $c | gzip -c > evidence/$c/export.tar.gz
  sha256sum evidence/$c/export.tar.gz >> evidence/hashes.txt
done
```

## 3) Volumes
```bash
VOL=data_pg
CID=$(docker create -v $VOL:/v alpine:3.20 sh)
docker cp $CID:/v - > evidence/vol_${VOL}.tar
sha256sum evidence/vol_${VOL}.tar >> evidence/hashes.txt
docker rm $CID
```

## 4) Emballage
```bash
find evidence -type f -exec sha256sum {} + > evidence/sha256_manifest.txt
tar -czf evidence_bundle.tgz evidence/
sha256sum evidence_bundle.tgz > evidence_bundle.tgz.sha256
```
