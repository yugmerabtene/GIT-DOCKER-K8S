# Chapitre 9 — Observabilité & Journalisation

*(métriques, logs, traces — métriques serveur/HPA, Prometheus Operator (ServiceMonitor/PodMonitor/PrometheusRule), Grafana & Alertmanager, pipelines de logs (Fluent Bit/Vector → Loki/ELK), OpenTelemetry (OTel Collector → Jaeger/Tempo), corrélation E-M-T, sécurité & conformité, **runbooks** et **commandes détaillées**)*

---

## 1) Objectifs

* Comprendre l’architecture **E-M-T** (*Events/Logs, Metrics, Traces*) et les **Golden Signals** (latence, trafic, erreurs, saturation).
* Mettre en place **metrics-server** (HPA) vs **Prometheus** (observabilité complète).
* Déployer **Prometheus Operator** (Prometheus, Alertmanager, Grafana) et configurer **ServiceMonitor/PodMonitor**.
* Construire un pipeline de **logs** (stdout/stderr → Fluent Bit/Vector → Loki/ELK), formats JSON, parsers, rétention.
* Déployer **OpenTelemetry Collector** et **Jaeger/Tempo** pour les **traces distribuées**.
* Écrire des **règles d’alerting** (Alertmanager), des **dashboards** Grafana, et corréler métriques/logs/traces.
* Appliquer sécurité (RBAC, NetPol, secrets), conformité (PII, rétention), et exécuter des **runbooks** de diagnostic.

---

## 2) Carte d’ensemble (qui fait quoi)

```
[Nodes/Pods] → (stdout/stderr) → Fluent Bit / Vector → [Loki/Elastic]
            → (/metrics HTTP) → Prometheus (scrape) → [Alertmanager] + [Grafana]
            → (OTLP gRPC/HTTP) → OTel Collector → [Jaeger/Tempo] (+ exemplars vers Prom/Grafana)
[API/Control Plane] → /metrics (apiserver, scheduler, controller, etcd) → Prometheus
[HPA] ← metrics-server (Resource Metrics API)
```

**À retenir :**

* **metrics-server** = métriques “utilisation CPU/RAM” pour `kubectl top`/HPA — **ne remplace pas** Prometheus.
* **Prometheus** = scrappe **tout** (kubelets, cAdvisor, kube-state-metrics, exporters, apps).
* **Logs** : privilégier **JSON structurés** et **stdout/stderr**.
* **Traces** : **OTLP** partout (OpenTelemetry), sampling, propagation de contexte.

---

## 3) Métriques “système” (metrics-server, kubelet/cAdvisor, kube-state-metrics)

### 3.1 metrics-server (HPA uniquement)

**Vérifier l’APIService et les commandes :**

```bash
kubectl get apiservices | grep metrics.k8s.io
# doit afficher v1beta1.metrics.k8s.io 'Available'

kubectl top nodes             # CPU/RAM des nœuds
kubectl top pods -A           # CPU/RAM des pods
```

**Pièges courants :** erreurs SSL/hostname sur kubelet, cluster privé sans SAN → voir flags `--kubelet-insecure-tls` du metrics-server (à éviter en prod).

### 3.2 kubelet & cAdvisor (Prometheus scrappe)

* **Endpoints** (auth nécessaires) : `/metrics`, `/metrics/cadvisor`.
* Avec **Prometheus Operator**, le **kubelet** est scrappé via **Endpoints**/**ServiceMonitor** fournis par le chart/stack.

### 3.3 kube-state-metrics

* Expose l’état des objets K8s (Deployments disponibles, réplicas, conditions).
* **Indispensable** pour dashboards & alertes “santé K8s”.

---

## 4) Prometheus Operator — *stack* standard en production

### 4.1 CRDs principales

* **Prometheus** (instance, retention, storage),
* **Alertmanager** (routes/receivers),
* **ServiceMonitor** / **PodMonitor** (découverte & scrapes),
* **PrometheusRule** (alertes & enregistrements),
* **Grafana** (souvent déployé à côté),
* **kube-state-metrics** & **exporters** (node-exporter, etc.).

### 4.2 Exemple **ServiceMonitor** (scraper un service applicatif)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: api
  namespace: monitoring
  labels: { release: kube-prom }
spec:
  namespaceSelector: { matchNames: ["app"] }
  selector:
    matchLabels: { app.kubernetes.io/name: api }  # labels du Service cible
  endpoints:
    - port: metrics            # port nommé sur le Service
      path: /metrics
      interval: 30s
      scrapeTimeout: 10s
      scheme: http
      honorLabels: true
      relabelings:
        - action: labelmap
          regex: __meta_kubernetes_pod_label_(.+)
```

**Explications clés :**

* `selector` : cible le **Service** (pas le Pod).
* `endpoints.port` : **nom** du port exposé par le Service (ex: `metrics`).
* `relabelings` : copie les labels des Pods comme labels Prom.

### 4.3 Exemple **PodMonitor** (scraper directement des Pods)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: api-pods
  namespace: monitoring
spec:
  namespaceSelector: { matchNames: ["app"] }
  selector:
    matchLabels: { app.kubernetes.io/name: api }
  podMetricsEndpoints:
    - port: http
      path: /metrics
      interval: 30s
```

### 4.4 Règles Prometheus (**PrometheusRule**) — Alerting & Recording

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: api-rules
  namespace: monitoring
spec:
  groups:
  - name: api.availability
    rules:
    - alert: APIHighErrorRate
      expr: |
        sum(rate(http_requests_total{job="api",status=~"5.."}[5m]))
        /
        sum(rate(http_requests_total{job="api"}[5m])) > 0.05
      for: 10m
      labels: { severity: page }
      annotations:
        summary: "Taux d’erreurs 5xx > 5% (10m)"
        runbook_url: "https://runbooks.local/api-high-error-rate"
    - record: job:http_request_duration_seconds:95p
      expr: |
        histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="api"}[5m])) by (le))
```

**Commandes de validation :**

```bash
promtool check rules api-rules.yaml
# Valide la syntaxe des règles avant apply
```

### 4.5 Alertmanager — routes & receivers

```yaml
route:
  receiver: default
  routes:
    - match: { severity: page }
      receiver: oncall
      repeat_interval: 30m
receivers:
  - name: default
    email_configs: [ { to: "ops@exemple.com" } ]
  - name: oncall
    pagerduty_configs: [ { routing_key: "<pd-key>" } ]
```

### 4.6 Grafana — datasource & provisioning

**Datasource Prometheus (ConfigMap monté) :**

```yaml
apiVersion: v1
kind: ConfigMap
metadata: { name: grafana-datasources, namespace: monitoring }
data:
  prometheus.yaml: |
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        access: proxy
        url: http://prometheus-operated.monitoring.svc:9090
        isDefault: true
```

**Commandes utiles (scrape & targets) :**

```bash
# Lister les Prometheus/Alertmanager/Rules
kubectl get prometheus,alertmanager,servicemonitor,podmonitor,prometheusrule -n monitoring

# Ouvrir l’UI Prometheus en local
kubectl -n monitoring port-forward svc/prometheus-operated 9090:9090
# Dans l'UI: Status → Targets (voir "down" / "up")
```

---

## 5) Logs : pipeline, formats, rétention

### 5.1 Bonnes pratiques d’application

* **Écrire sur stdout/stderr**, format **JSON** (clé/val), inclure `timestamp`, `level`, `logger`, `message`, **`trace_id`**/**`span_id`** si tracing activé.
* **Pas** de secrets/PII ; masquer (hash, tokenization).
* **Niveaux** cohérents (info/warn/error) ; **clés stables**.

### 5.2 Collecte **DaemonSet** (Fluent Bit / Vector)

* Lit `/var/log/containers/*.log` (liens vers CRI), parse JSON, enrichit labels, **rate limiting** et **drop** des bruits.

**Exemple Fluent Bit (extrait config) :**

```ini
[INPUT]
  Name              tail
  Path              /var/log/containers/*.log
  Parser            docker
  Tag               kube.*
  Mem_Buf_Limit     50MB
  Skip_Long_Lines   On
  Refresh_Interval  5

[FILTER]
  Name              kubernetes
  Match             kube.*
  Merge_Log         On
  Keep_Log          Off
  K8S-Logging.Parser On

[FILTER]
  Name              grep
  Match             kube.*
  Exclude           log ^.*healthz.*$

[OUTPUT]
  Name              loki
  Match             kube.*
  Url               http://loki.monitoring.svc:3100/loki/api/v1/push
  Labels            job=fluentbit, namespace=$kubernetes['namespace_name'], pod=$kubernetes['pod_name'], container=$kubernetes['container_name']
```

### 5.3 Stockage & recherche

* **Loki** (logs indexés par labels ; requêtes **LogQL**), **ELK** (Elasticsearch + Kibana) si besoin de requêtes full-text avancées.
* **Rétention** par **tenant/namespace** (ex. 7–30 jours), **WORM** si exigé, chiffrage côté stockage.
* **Dashboards & alertes** en s’appuyant sur **métriques dérivées** (logs → metrics/promtail/loki-canary).

**Commandes de santé Loki :**

```bash
kubectl -n monitoring get pods -l app=loki
kubectl -n monitoring logs deploy/loki -f --tail=100
```

---

## 6) Traces distribuées : OpenTelemetry (OTLP) → Jaeger/Tempo

### 6.1 Principes

* **Instrumenter** les apps (SDK OTel) ou auto-instrumentation (Java/Python/Node).
* **OTel Collector** en **DaemonSet** (sidecar) ou **Deployment** (gateway) : reçoit **OTLP**, **process** (batch, attributes), **export** vers **Jaeger/Tempo** + **exemplars** vers Prometheus.

### 6.2 OTel Collector (extrait config)

```yaml
receivers:
  otlp:
    protocols:
      http:
      grpc:
processors:
  batch:
  attributes:
    actions:
      - key: k8s.namespace.name
        action: upsert
exporters:
  otlp:
    endpoint: tempo.monitoring.svc:4317
    tls:
      insecure: true
  prometheus:
    endpoint: 0.0.0.0:9464
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch, attributes]
      exporters: [otlp]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheus]
```

### 6.3 Jaeger/Tempo

* **Jaeger** : UI mature pour requêter/visualiser les traces.
* **Tempo** : backend traces (faible coût), intégré Grafana (liens **exemplars** depuis métriques).

**Vérif Collector :**

```bash
kubectl -n monitoring get pods -l app=otel-collector -o wide
kubectl -n monitoring logs deploy/otel-collector -f | grep -i "exporter"
```

### 6.4 Corrélation E-M-T

* **Exemplars** : pointeurs depuis une série Prometheus vers un **trace_id** (Grafana montre “View trace”).
* **Logs ↔ Traces** : inclure **trace_id/span_id** dans les logs → liens croisés Grafana/Tempo/Loki.

---

## 7) Sécurité, conformité & multi-tenance

* **RBAC** : limiter l’accès aux UIs (Grafana, Prom, Alertmanager, Jaeger) via **Ingress** + **authN/OIDC**.
* **NetworkPolicies** : restreindre scrapes et sorties (Prom → cibles, Fluent Bit → Loki).
* **Secrets** : mots de passe datasources/receivers en **Secret** K8s (chiffré **etcd**).
* **PII** : **ne pas** logguer de données personnelles ; **masquage** et **règles de rétention** par **namespace/projet** (GDPR/ISO 27001).
* **SLO/SLA** : publier des **SLI** (taux 2xx/latence) et alerter via **burn rate** (alerte rapide + lente).

---

## 8) Runbooks (diagnostic rapide)

### 8.1 `kubectl top` ne marche pas

```bash
kubectl get apiservices | grep metrics.k8s.io          # doit être Available
kubectl -n kube-system logs deploy/metrics-server -f
# Si erreurs certs kubelet -> vérifier SAN/CA ; éviter --kubelet-insecure-tls en prod
```

### 8.2 Cibles Prometheus “DOWN”

```bash
kubectl -n monitoring port-forward svc/prometheus-operated 9090:9090
# UI → Status → Targets → voir error (timeout, 403…)
kubectl -n monitoring get servicemonitor,podmonitor | grep api
kubectl -n app get svc,pods -l app.kubernetes.io/name=api -o wide
# Corriger: label selector, port name, path, NetPol
```

### 8.3 Alerte non envoyée

```bash
kubectl -n monitoring port-forward svc/alertmanager-operated 9093:9093
# UI → Status → Silences/Alerts
kubectl -n monitoring logs statefulset/alertmanager-main -f
# Vérifier route/receiver, inhibitions, labels 'severity'
```

### 8.4 Loki/Fluent Bit “ingestion 429/500”

```bash
kubectl -n monitoring logs ds/fluent-bit -f --tail=200 | grep -i error
kubectl -n monitoring logs deploy/loki -f --tail=200 | egrep -i "error|rate|ingest"
# Actions: réduire volume via 'Exclude', augmenter limites, sharding/partitionnement, rétention
```

### 8.5 Traces absentes

```bash
kubectl -n monitoring logs deploy/otel-collector -f | grep -i "export"
# Vérifier endpoint OTLP, sampling (taux trop bas), propagation (traceparent/b3)
```

---

## 9) Bonnes pratiques (check-list)

* **Metrics** : Prometheus Operator, `ServiceMonitor/PodMonitor`, `kube-state-metrics`, `node-exporter`.
* **Alertes** : règles **simples** + **burn rate** SLO (rapide 5m/1h et lente 1h/6h).
* **Dashboards** : **Grafana provisioning** versionné (GitOps).
* **Logs** : **JSON** sur stdout, **pas de secrets/PII**, sampling ou **rate limit**, rétention par **tenant**.
* **Traces** : **OTLP**, sampling adapté (probabiliste, tail-based pour erreurs), **exemplars** activés.
* **Sécurité** : RBAC/UI protégées, NetPol, Secrets chiffrés, accès **least-privilege**.
* **Coûts** : rétention courte par défaut (7–14 j logs ; 15–30 j métriques), downsampling (Prom/Thanos).
* **Docs** : lier chaque alerte à un **runbook_url** actionnable.

---

## 10) Aide-mémoire (commandes utiles)

```bash
# Metrics / HPA
kubectl get apiservices | grep metrics.k8s.io
kubectl top nodes ; kubectl top pods -A

# Prometheus Operator
kubectl -n monitoring get prometheus,alertmanager,servicemonitor,podmonitor,prometheusrule
kubectl -n monitoring port-forward svc/prometheus-operated 9090:9090
kubectl -n monitoring logs deploy/kube-state-metrics -f

# promtool (vérifier les règles)
promtool check rules ./rules.yaml

# Grafana
kubectl -n monitoring get cm grafana-datasources -o yaml
kubectl -n monitoring port-forward svc/grafana 3000:3000

# Logs (Loki/Fluent Bit)
kubectl -n monitoring get pods -l app=loki
kubectl -n monitoring logs ds/fluent-bit -f --tail=200

# Traces (OTel/Jaeger/Tempo)
kubectl -n monitoring get pods -l app=otel-collector -o wide
kubectl -n monitoring port-forward svc/jaeger-query 16686:16686
kubectl -n monitoring port-forward svc/tempo 3200:3200

# NetworkPolicies rapides (si scrapes bloqués)
kubectl -n monitoring get netpol
```

