# Annexe A — Air-gapped & mirroring (environnements contraints)

## Objectifs
- Utiliser Docker et distribuer des images **sans acces direct a Internet**
- Mettre en place un **miroir/proxy cache** et une **chaine de synchronisation** d'artefacts OCI
- Garantir la **securite** (signatures, verification offline)

## 1) Registry proxy/cache avec registry:2

### Exemple Compose
```yaml
services:
  regcache:
    image: registry:2
    ports: ["5000:5000"]
    environment:
      REGISTRY_PROXY_REMOTEURL: https://registry-1.docker.io
    volumes:
      - regdata:/var/lib/registry
volumes:
  regdata: {}
```

### Client (daemon.json)
```json
{
  "registry-mirrors": ["http://<ip>:5000"]
}
```

## 2) Synchronisation offline

### skopeo
```bash
skopeo copy docker://docker.io/library/nginx:1.27 \
            docker://reg.local:5000/cache/nginx:1.27
```

### crane
```bash
crane copy docker.io/library/nginx:1.27 reg.local:5000/cache/nginx:1.27
```

### Signatures avec cosign
```bash
cosign sign --key cosign.key reg.local:5000/acme/web:1.4.2
cosign verify --key cosign.pub reg.local:5000/acme/web@sha256:...
```
