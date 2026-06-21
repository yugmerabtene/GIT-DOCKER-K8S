# Chapitre 9 — Observabilité & Journalisation

*(métriques, logs, traces — métriques serveur/HPA, Prometheus Operator (ServiceMonitor/PodMonitor/PrometheusRule), Grafana & Alertmanager, pipelines de logs (Fluent Bit/Vector → Loki/ELK), OpenTelemetry (OTel Collector → Jaeger/Tempo), corrélation E-M-T, sécurité & conformité, **runbooks** et **commandes détaillées**)*

---

## 1) Objectifs

* Comprendre l'architecture **E-M-T** (*Events/Logs, Metrics, Traces*) et les **Golden Signals** (latence, trafic, erreurs, saturation).
* Mettre en place **metrics-server** (HPA) vs **Prometheus** (observabilité complète).
* Déployer **Prometheus Operator** (Prometheus, Alertmanager, Grafana) et configurer **ServiceMonitor/PodMonitor**.
* Construire un pipeline de **logs** (stdout/stderr → Fluent Bit/Vector → Loki/ELK), formats JSON, parsers, rétention.
* Déployer **OpenTelemetry Collector** et **Jaeger/Tempo** pour les **traces distribuées**.
* Écrire des **règles d'alerting** (Alertmanager), des **dashboards** Grafana, et corréler métriques/logs/traces.
* Appliquer sécurité (RBAC, NetPol, secrets), conformité (PII, rétention), et exécuter des **runbooks** de diagnostic.

---

## 2) Carte d'ensemble (qui fait quoi)

> **Objectif** : Visualiser le flux de données d'observabilité dans le cluster — comment les logs, métriques et traces circulent des applications vers les backends de stockage et de visualisation.
> **Pre-requis** : Aucun — ce schéma est une référence architecturale à garder en tête pour la suite.

```
# Flux de données d'observabilité dans un cluster Kubernetes
# Chaque ligne représente un pipeline distinct (Logs, Métriques, Traces)

# PIPELINE LOGS : les conteneurs écrivent sur stdout/stderr,
# un agent DaemonSet (Fluent Bit/Vector) collecte et route vers un backend
[Nodes/Pods] → (stdout/stderr) → Fluent Bit / Vector → [Loki/Elastic]

# PIPELINE METRIQUES : Prometheus scrappe les endpoints /metrics exposés
# par les pods, kubelets, et composants du control plane
            → (/metrics HTTP) → Prometheus (scrape) → [Alertmanager] + [Grafana]

# PIPELINE TRACES : les apps instrumentées envoient des spans via OTLP
# vers l'OTel Collector qui les exporte vers Jaeger ou Tempo
            → (OTLP gRPC/HTTP) → OTel Collector → [Jaeger/Tempo] (+ exemplars vers Prom/Grafana)

# Le control plane K8s expose aussi des métriques internes
[API/Control Plane] → /metrics (apiserver, scheduler, controller, etcd) → Prometheus

# HPA utilise metrics-server (et non Prometheus) pour les métriques CPU/RAM
[HPA] ← metrics-server (Resource Metrics API)
```

> **Résultat attendu** :
> ```
> Schéma conceptuel — pas de sortie commande.
> Trois pipelines indépendants : Logs (→ Loki), Métriques (→ Prometheus), Traces (→ Tempo/Jaeger).
> ```
> **Vérification** : S'assurer que chaque pipeline est bien identifié et que le rôle de chaque composant est clair avant de passer à l'implémentation.

**À retenir :**

* **metrics-server** = métriques "utilisation CPU/RAM" pour `kubectl top`/HPA — **ne remplace pas** Prometheus.
* **Prometheus** = scrappe **tout** (kubelets, cAdvisor, kube-state-metrics, exporters, apps).
* **Logs** : privilégier **JSON structurés** et **stdout/stderr**.
* **Traces** : **OTLP** partout (OpenTelemetry), sampling, propagation de contexte.

---

## 3) Métriques "système" (metrics-server, kubelet/cAdvisor, kube-state-metrics)

### 3.1 metrics-server (HPA uniquement)

**Vérifier l'APIService et les commandes :**

> **Objectif** : Vérifier que le metrics-server est correctement déployé et fonctionnel, puis récupérer les métriques d'utilisation CPU/RAM des nœuds et pods.
> **Pre-requis** : metrics-server déployé dans le cluster (généralement dans kube-system).

```bash
# Vérifie que l'APIService metrics.k8s.io est bien enregistrée et disponible
# Le status doit afficher 'Available' (True)
kubectl get apiservices | grep metrics.k8s.io
# doit afficher v1beta1.metrics.k8s.io 'Available'

# Affiche la consommation CPU et mémoire de chaque nœud du cluster
# Utilise la Resource Metrics API fournie par metrics-server
kubectl top nodes             # CPU/RAM des nœuds

# Affiche la consommation CPU et mémoire de tous les pods du cluster (-A = tous namespaces)
kubectl top pods -A           # CPU/RAM des pods
```

> **Résultat attendu** :
> ```
> $ kubectl get apiservices | grep metrics.k8s.io
> v1beta1.metrics.k8s.io                 kube-system/metrics-server   True    4m
>
> $ kubectl top nodes
> NAME     CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
> node-1   250m         12%    1024Mi          53%
> node-2   180m         9%     896Mi           46%
>
> $ kubectl top pods -A
> NAMESPACE     NAME                        CPU(cores)   MEMORY(bytes)
> kube-system   metrics-server-6d4f8b...    5m           32Mi
> monitoring    prometheus-k8s-0            45m          256Mi
> app           api-deployment-7b8c9d-...   12m          64Mi
> ```
> **Vérification** : L'APIService doit être `True` (Available). `kubectl top` doit retourner des valeurs non-nulles pour CPU/RAM. Si erreur "metrics not available", vérifier les logs du metrics-server.

**Pièges courants :** erreurs SSL/hostname sur kubelet, cluster privé sans SAN → voir flags `--kubelet-insecure-tls` du metrics-server (à éviter en prod).

### 3.2 kubelet & cAdvisor (Prometheus scrappe)

* **Endpoints** (auth nécessaires) : `/metrics`, `/metrics/cadvisor`.
* Avec **Prometheus Operator**, le **kubelet** est scrappé via **Endpoints**/**ServiceMonitor** fournis par le chart/stack.

### 3.3 kube-state-metrics

* Expose l'état des objets K8s (Deployments disponibles, réplicas, conditions).
* **Indispensable** pour dashboards & alertes "santé K8s".

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

> **Objectif** : Créer un ServiceMonitor qui indique à Prometheus comment découvrir et scraper les métriques d'un service applicatif nommé "api" dans le namespace "app".
> **Pre-requis** : Prometheus Operator installé, CRDs déployées, un Service avec le label `app.kubernetes.io/name: api` et un port nommé `metrics` dans le namespace `app`.

```yaml
apiVersion: monitoring.coreos.com/v1  # API du Prometheus Operator
kind: ServiceMonitor                   # Ressource CRD qui décrit comment scraper un Service
metadata:
  name: api                            # Nom du ServiceMonitor
  namespace: monitoring                # Doit être dans le namespace où Prometheus tourne
  labels: { release: kube-prom }       # Label pour que l'instance Prometheus sélectionne ce ServiceMonitor
spec:
  namespaceSelector: { matchNames: ["app"] }  # Prometheus cherchera les Services dans le namespace "app"
  selector:
    matchLabels: { app.kubernetes.io/name: api }  # Cible le Service K8s portant ce label
  endpoints:
    - port: metrics            # Nom du port défini dans le Service K8s (pas le numéro !)
      path: /metrics           # Chemin HTTP de l'endpoint de métriques
      interval: 30s            # Fréquence de scrape (30 secondes)
      scrapeTimeout: 10s       # Timeout pour chaque requête de scrape
      scheme: http             # Protocole (http ou https)
      honorLabels: true        # Conserve les labels de l'application (ne les écrase pas)
      relabelings:
        - action: labelmap     # Copie les labels des Pods vers les labels Prometheus
          regex: __meta_kubernetes_pod_label_(.+)  # Regex pour capturer tous les labels de Pod
```

> **Résultat attendu** :
> ```
> $ kubectl apply -f servicemonitor-api.yaml
> servicemonitor.monitoring.coreos.com/api created
>
> # Dans l'UI Prometheus → Status → Targets :
> # la cible "api" doit apparaître avec l'état "UP"
> ```
> **Vérification** : `kubectl get servicemonitor -n monitoring` doit lister `api`. Dans l'UI Prometheus, le target doit être `UP` après 30s.

**Explications clés :**

* `selector` : cible le **Service** (pas le Pod).
* `endpoints.port` : **nom** du port exposé par le Service (ex: `metrics`).
* `relabelings` : copie les labels des Pods comme labels Prom.

### 4.3 Exemple **PodMonitor** (scraper directement des Pods)

> **Objectif** : Créer un PodMonitor pour scraper directement les Pods (sans passer par un Service K8s). Utile quand les pods n'ont pas de Service ou pour un scraping plus fin.
> **Pre-requis** : Prometheus Operator installé, des Pods avec le label `app.kubernetes.io/name: api` dans le namespace `app`, exposant un port nommé `http` sur `/metrics`.

```yaml
apiVersion: monitoring.coreos.com/v1  # API du Prometheus Operator
kind: PodMonitor                       # CRD qui scrape directement des Pods (pas de Service nécessaire)
metadata:
  name: api-pods                       # Nom du PodMonitor
  namespace: monitoring                # Namespace du Prometheus Operator
spec:
  namespaceSelector: { matchNames: ["app"] }  # Scrute les Pods dans le namespace "app"
  selector:
    matchLabels: { app.kubernetes.io/name: api }  # Sélectionne les Pods avec ce label
  podMetricsEndpoints:
    - port: http             # Nom du port défini dans le spec.containers[].ports du Pod
      path: /metrics         # Chemin HTTP pour les métriques
      interval: 30s          # Intervalle de scrape
```

> **Résultat attendu** :
> ```
> $ kubectl apply -f podmonitor-api.yaml
> podmonitor.monitoring.coreos.com/api-pods created
>
> # Dans l'UI Prometheus → Status → Targets :
> # chaque Pod matché apparaît comme une cible individuelle avec l'état "UP"
> ```
> **Vérification** : `kubectl get podmonitor -n monitoring` liste `api-pods`. Les targets Prometheus montrent un entry par Pod avec `UP`.

### 4.4 Règles Prometheus (**PrometheusRule**) — Alerting & Recording

> **Objectif** : Définir des règles d'alerte (alerting) et des règles de calcul pré-agrégé (recording) pour l'application API. L'alerte se déclenche si le taux d'erreurs 5xx dépasse 5% pendant 10 minutes. La règle de calcul pré-calculle le percentile 95 de la latence.
> **Pre-requis** : Prometheus Operator déployé, l'application exposant les métriques `http_requests_total` et `http_request_duration_seconds_bucket` via un ServiceMonitor/PodMonitor.

```yaml
apiVersion: monitoring.coreos.com/v1  # API du Prometheus Operator
kind: PrometheusRule                   # CRD pour définir des règles d'alerte et de calcul
metadata:
  name: api-rules                      # Nom de la ressource
  namespace: monitoring                # Namespace où Prometheus les chargera
spec:
  groups:
  - name: api.availability             # Groupe logique de règles
    rules:
    # --- RÈGLE D'ALERTE ---
    - alert: APIHighErrorRate          # Nom de l'alerte (apparaîtra dans Alertmanager)
      expr: |
        # Calcule le ratio de requêtes 5xx sur le total des requêtes sur 5 minutes
        sum(rate(http_requests_total{job="api",status=~"5.."}[5m]))
        /
        sum(rate(http_requests_total{job="api"}[5m])) > 0.05  # Seuil : > 5% d'erreurs
      for: 10m                         # L'alerte ne se déclenche qu'après 10 min continues
      labels: { severity: page }       # Label utilisé par Alertmanager pour router
      annotations:
        summary: "Taux d'erreurs 5xx > 5% (10m)"  # Description lisible
        runbook_url: "https://runbooks.local/api-high-error-rate"  # Lien vers le runbook
    # --- RÈGLE DE CALCUL (Recording Rule) ---
    - record: job:http_request_duration_seconds:95p  # Nom de la nouvelle série métrique créée
      expr: |
        # Calcule le percentile 95 (P95) de la latence des requêtes HTTP sur 5 min
        histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="api"}[5m])) by (le))
```

> **Résultat attendu** :
> ```
> $ kubectl apply -f prometheusrule-api.yaml
> prometheusrule.monitoring.coreos.com/api-rules created
>
> # Dans l'UI Prometheus → Alerts :
> # l'alerte "APIHighErrorRate" apparaît (état : PENDING ou FIRING selon les données)
> # La métrique "job:http_request_duration_seconds:95p" est disponible dans /graph
> ```
> **Vérification** : `kubectl get prometheusrule -n monitoring` liste `api-rules`. Dans Prometheus UI → Alerts, la règle est visible. La métrique recording est requêtable.

**Commandes de validation :**

> **Objectif** : Valider la syntaxe du fichier de règles Prometheus avant de l'appliquer dans le cluster, pour éviter les erreurs de déploiement.
> **Pre-requis** : L'outil `promtool` installé (fourni avec le binaire Prometheus ou via `go install`).

```bash
# Valide la syntaxe YAML et la cohérence des expressions PromQL du fichier de règles
# Retourne 0 si OK, sinon affiche l'erreur avec le numéro de ligne
promtool check rules api-rules.yaml
# Valide la syntaxe des règles avant apply
```

> **Résultat attendu** :
> ```
> $ promtool check rules api-rules.yaml
> Checking api-rules.yaml  SUCCESS: 1 rules found
> ```
> **Vérification** : La sortie doit afficher `SUCCESS`. Toute erreur de syntaxe PromQL ou YAML sera indiquée avec le numéro de ligne.

### 4.5 Alertmanager — routes & receivers

> **Objectif** : Configurer Alertmanager pour router les alertes selon leur sévérité : les alertes `severity: page` vont vers PagerDuty (oncall), les autres vers un email par défaut.
> **Pre-requis** : Alertmanager déployé (via Prometheus Operator), une clé de routing PagerDuty valide.

```yaml
# Configuration Alertmanager : définit comment les alertes sont routées et notifiées
route:
  receiver: default              # Receiver par défaut si aucune sous-route ne matche
  routes:
    - match: { severity: page }  # Si l'alerte a le label severity=page
      receiver: oncall           # → envoyée au receiver "oncall"
      repeat_interval: 30m       # Rappel toutes les 30 min tant que l'alerte est active
receivers:
  - name: default                # Receiver pour les alertes non-critiques
    email_configs: [ { to: "ops@exemple.com" } ]  # Envoi par email
  - name: oncall                 # Receiver pour les alertes critiques (page)
    pagerduty_configs: [ { routing_key: "<pd-key>" } ]  # Envoi vers PagerDuty
```

> **Résultat attendu** :
> ```
> # Après application via le CRD Alertmanager ou le Secret de config :
> # Alertmanager redémarre et charge la nouvelle configuration
> # Les alertes severity=page → PagerDuty, les autres → email ops@exemple.com
> ```
> **Vérification** : UI Alertmanager → Status pour voir la config chargée. Tester avec `amtool alert add` pour vérifier le routage.

### 4.6 Grafana — datasource & provisioning

**Datasource Prometheus (ConfigMap monté) :**

> **Objectif** : Configurer automatiquement Prometheus comme datasource par défaut dans Grafana via une ConfigMap de provisioning. Grafana la chargera au démarrage sans configuration manuelle.
> **Pre-requis** : Grafana déployé dans le namespace `monitoring`, Prometheus accessible via le service `prometheus-operated.monitoring.svc:9090`.

```yaml
apiVersion: v1
kind: ConfigMap                            # ConfigMap pour le provisioning Grafana
metadata: { name: grafana-datasources, namespace: monitoring }  # Montée par Grafana au démarrage
data:
  prometheus.yaml: |                       # Fichier de datasource au format Grafana provisioning
    apiVersion: 1                          # Version du format de provisioning
    datasources:
      - name: Prometheus                   # Nom affiché dans Grafana
        type: prometheus                   # Type de datasource
        access: proxy                      # Accès via le backend Grafana (proxy), pas direct (browser)
        url: http://prometheus-operated.monitoring.svc:9090  # URL interne du service Prometheus
        isDefault: true                    # Cette datasource est utilisée par défaut dans les dashboards
```

> **Résultat attendu** :
> ```
> $ kubectl apply -f grafana-datasources.yaml
> configmap/grafana-datasources created
>
> # Après redémarrage de Grafana :
> # Configuration → Data Sources → "Prometheus" apparaît avec un badge "Default"
> # Le bouton "Save & Test" retourne "Data source is working"
> ```
> **Vérification** : `kubectl get cm grafana-datasources -n monitoring` liste la ConfigMap. Dans Grafana UI, la datasource Prometheus est présente et fonctionnelle.

**Commandes utiles (scrape & targets) :**

> **Objectif** : Lister toutes les ressources du Prometheus Operator et ouvrir l'interface Prometheus en local pour inspecter les targets de scrape.
> **Pre-requis** : Prometheus Operator déployé dans le namespace `monitoring`.

```bash
# Liste toutes les ressources CRD du Prometheus Operator en une seule commande
# Permet de voir en un coup d'œil l'état de la stack de monitoring
kubectl get prometheus,alertmanager,servicemonitor,podmonitor,prometheusrule -n monitoring

# Crée un tunnel port-forward pour accéder à l'UI Prometheus depuis le navigateur
# http://localhost:9090 donne accès à l'interface complète de Prometheus
kubectl -n monitoring port-forward svc/prometheus-operated 9090:9090
# Dans l'UI: Status → Targets (voir "down" / "up")
```

> **Résultat attendu** :
> ```
> $ kubectl get prometheus,alertmanager,servicemonitor,podmonitor,prometheusrule -n monitoring
> NAME                                    VERSION   REPLICAS   AGE
> prometheus.monitoring.coreos.com/k8s    2.45.0    2          30d
>
> NAME                              VERSION   REPLICAS   AGE
> alertmanager.monitoring.coreos.com/main   0.26.0    2          30d
>
> NAME                                              AGE
> servicemonitor.monitoring.coreos.com/api          5d
> servicemonitor.monitoring.coreos.com/kubelet      30d
>
> $ kubectl -n monitoring port-forward svc/prometheus-operated 9090:9090
> Forwarding from 127.0.0.1:9090 → 9090
> ```
> **Vérification** : Toutes les ressources doivent exister. L'UI Prometheus sur `localhost:9090` → Status → Targets doit montrer les cibles avec l'état `UP`.

---

## 5) Logs : pipeline, formats, rétention

### 5.1 Bonnes pratiques d'application

* **Écrire sur stdout/stderr**, format **JSON** (clé/val), inclure `timestamp`, `level`, `logger`, `message`, **`trace_id`**/**`span_id`** si tracing activé.
* **Pas** de secrets/PII ; masquer (hash, tokenization).
* **Niveaux** cohérents (info/warn/error) ; **clés stables**.

### 5.2 Collecte **DaemonSet** (Fluent Bit / Vector)

* Lit `/var/log/containers/*.log` (liens vers CRI), parse JSON, enrichit labels, **rate limiting** et **drop** des bruits.

**Exemple Fluent Bit (extrait config) :**

> **Objectif** : Configurer Fluent Bit (en DaemonSet sur chaque nœud) pour collecter les logs des conteneurs, les enrichir avec les métadonnées Kubernetes, filtrer les logs de healthcheck, et les envoyer vers Loki.
> **Pre-requis** : Fluent Bit déployé en DaemonSet, Loki accessible dans le namespace `monitoring` sur le port 3100.

```ini
# --- INPUT : collecte les fichiers de logs des conteneurs ---
[INPUT]
  Name              tail                    # Plugin d'entrée : suit les fichiers en temps réel (comme tail -f)
  Path              /var/log/containers/*.log  # Chemin des logs conteneurs (symlinks vers le CRI)
  Parser            docker                  # Parse le format JSON du runtime Docker/containerd
  Tag               kube.*                  # Tag appliqué à chaque log pour le routage interne
  Mem_Buf_Limit     50MB                    # Limite mémoire tampon (backpressure si dépassé)
  Skip_Long_Lines   On                      # Ignore les lignes trop longues plutôt que de bloquer
  Refresh_Interval  5                       # Vérifie les nouveaux fichiers toutes les 5 secondes

# --- FILTER : enrichit avec les métadonnées Kubernetes ---
[FILTER]
  Name              kubernetes              # Plugin K8s : ajoute namespace, pod, container, labels
  Match             kube.*                  # Applique ce filtre aux logs tagués "kube.*"
  Merge_Log         On                      # Parse le champ "log" JSON et le fusionne dans la structure
  Keep_Log          Off                     # Supprime le champ "log" original après merge (évite la duplication)
  K8S-Logging.Parser On                    # Respecte les annotations K8s pour le parsing

# --- FILTER : exclusion des logs de healthcheck (bruit) ---
[FILTER]
  Name              grep                    # Plugin de filtrage par regex
  Match             kube.*                  # Cible tous les logs Kubernetes
  Exclude           log ^.*healthz.*$       # Exclut les lignes contenant "healthz" (healthchecks)

# --- OUTPUT : envoie les logs vers Loki ---
[OUTPUT]
  Name              loki                    # Plugin de sortie Loki
  Match             kube.*                  # Envoie tous les logs tagués "kube.*"
  Url               http://loki.monitoring.svc:3100/loki/api/v1/push  # Endpoint Loki
  Labels            job=fluentbit, namespace=$kubernetes['namespace_name'], pod=$kubernetes['pod_name'], container=$kubernetes['container_name']
  # Les labels Loki sont extraits dynamiquement des métadonnées K8s
```

> **Résultat attendu** :
> ```
> # Fluent Bit démarre et affiche dans ses logs :
> [info] [input:tail:tail.0] inotify_fs_add(): inode=... watch=... path=/var/log/containers/*.log
> [info] [filter:kubernetes:kubernetes.0] init complete
> [info] [output:loki:loki.0] connected, endpoint=http://loki.monitoring.svc:3100
>
> # Les logs apparaissent dans Loki/Grafana (Explore → Log Browser)
> ```
> **Vérification** : `kubectl logs ds/fluent-bit -n monitoring` ne doit pas montrer d'erreurs. Dans Grafana → Explore → Loki, les logs des pods sont requêtables par namespace/pod/container.

### 5.3 Stockage & recherche

* **Loki** (logs indexés par labels ; requêtes **LogQL**), **ELK** (Elasticsearch + Kibana) si besoin de requêtes full-text avancées.
* **Rétention** par **tenant/namespace** (ex. 7–30 jours), **WORM** si exigé, chiffrage côté stockage.
* **Dashboards & alertes** en s'appuyant sur **métriques dérivées** (logs → metrics/promtail/loki-canary).

**Commandes de santé Loki :**

> **Objectif** : Vérifier que Loki est opérationnel en inspectant l'état des pods et les logs récents du déploiement.
> **Pre-requis** : Loki déployé dans le namespace `monitoring`.

```bash
# Vérifie que les pods Loki sont bien Running/Ready
kubectl -n monitoring get pods -l app=loki

# Affiche les logs en temps réel des 100 dernières lignes de Loki
# Utile pour détecter des erreurs d'ingestion, de stockage, etc.
kubectl -n monitoring logs deploy/loki -f --tail=100
```

> **Résultat attendu** :
> ```
> $ kubectl -n monitoring get pods -l app=loki
> NAME                     READY   STATUS    RESTARTS   AGE
> loki-0                   1/1     Running   0          15d
>
> $ kubectl -n monitoring logs deploy/loki -f --tail=100
> level=info ts=... msg="server configuration loaded"
> level=info ts=... msg="table manager metrics synced"
> ```
> **Vérification** : Le pod Loki doit être `Running` avec `READY 1/1`. Les logs ne doivent pas contenir d'erreurs récurrentes (`level=error`).

---

## 6) Traces distribuées : OpenTelemetry (OTLP) → Jaeger/Tempo

### 6.1 Principes

* **Instrumenter** les apps (SDK OTel) ou auto-instrumentation (Java/Python/Node).
* **OTel Collector** en **DaemonSet** (sidecar) ou **Deployment** (gateway) : reçoit **OTLP**, **process** (batch, attributes), **export** vers **Jaeger/Tempo** + **exemplars** vers Prometheus.

### 6.2 OTel Collector (extrait config)

> **Objectif** : Configurer l'OTel Collector pour recevoir des traces et métriques via OTLP (gRPC et HTTP), les traiter (batch + enrichment d'attributs), puis les exporter vers Tempo (traces) et Prometheus (métriques via exemplars).
> **Pre-requis** : OTel Collector déployé dans le namespace `monitoring`, Tempo accessible sur `tempo.monitoring.svc:4317`.

```yaml
# --- RECEIVERS : points d'entrée OTLP ---
receivers:
  otlp:                          # Récepteur OTLP (OpenTelemetry Protocol)
    protocols:
      http:                      # Accepte les spans OTLP via HTTP (port 4318 par défaut)
      grpc:                      # Accepte les spans OTLP via gRPC (port 4317 par défaut)

# --- PROCESSORS : transformations appliquées aux données ---
processors:
  batch:                         # Regroupe les spans/métriques en lots (réduit les appels réseau)
  attributes:                    # Processeur d'attributs (enrichit/modifie les métadonnées)
    actions:
      - key: k8s.namespace.name  # Ajout de l'attribut "k8s.namespace.name"
        action: upsert           # Insère ou met à jour la valeur

# --- EXPORTERS : destinations des données traitées ---
exporters:
  otlp:                          # Exporte les traces via OTLP vers Tempo
    endpoint: tempo.monitoring.svc:4317  # Adresse du service Tempo (gRPC)
    tls:
      insecure: true             # Pas de TLS (environnement interne au cluster)
  prometheus:                    # Exporte les métriques pour Prometheus (exemplars)
    endpoint: 0.0.0.0:9464       # Port exposé pour que Prometheus scrappe les métriques OTel

# --- SERVICE : assemblage des pipelines ---
service:
  pipelines:
    traces:                      # Pipeline dédié aux traces
      receivers: [otlp]          # Reçoit via OTLP
      processors: [batch, attributes]  # Batch + enrichissement
      exporters: [otlp]          # Exporte vers Tempo
    metrics:                     # Pipeline dédié aux métriques
      receivers: [otlp]          # Reçoit via OTLP
      processors: [batch]        # Batch uniquement
      exporters: [prometheus]    # Exporte vers Prometheus (exemplars)
```

> **Résultat attendu** :
> ```
> # L'OTel Collector démarre et affiche :
> 2024-01-15T10:00:00Z  info  service/telemetry.go:95  Setting up own telemetry...
> 2024-01-15T10:00:00Z  info  service/telemetry.go:115  Serving Prometheus metrics  {"address": "0.0.0.0:9464"}
> 2024-01-15T10:00:00Z  info  exporters/exporter.go:xxx  Exporter built  {"kind": "exporter", "name": "otlp"}
> 2024-01-15T10:00:00Z  info  service/service.go:140  Everything is ready. Begin running and processing data.
> ```
> **Vérification** : `kubectl get pods -l app=otel-collector -n monitoring` → Running. Les logs montrent "Everything is ready". Dans Tempo/Jaeger, les traces apparaissent après instrumentation d'une app.

### 6.3 Jaeger/Tempo

* **Jaeger** : UI mature pour requêter/visualiser les traces.
* **Tempo** : backend traces (faible coût), intégré Grafana (liens **exemplars** depuis métriques).

**Vérif Collector :**

> **Objectif** : Vérifier que l'OTel Collector fonctionne correctement et que les exporters sont actifs.
> **Pre-requis** : OTel Collector déployé dans le namespace `monitoring`.

```bash
# Affiche l'état des pods OTel Collector avec les infos de nœud et IP
kubectl -n monitoring get pods -l app=otel-collector -o wide

# Suit les logs en temps réel et filtre sur les lignes contenant "exporter"
# Permet de vérifier que les exporters (otlp, prometheus) sont bien initialisés
kubectl -n monitoring logs deploy/otel-collector -f | grep -i "exporter"
```

> **Résultat attendu** :
> ```
> $ kubectl -n monitoring get pods -l app=otel-collector -o wide
> NAME                             READY   STATUS    RESTARTS   AGE   IP           NODE
> otel-collector-6b7c8d9f5-x2k4m  1/1     Running   0          5d    10.244.1.5   node-1
>
> $ kubectl -n monitoring logs deploy/otel-collector -f | grep -i "exporter"
> 2024-01-15T10:00:00Z  info  otlpexporter/exporter.go:xxx  Exporter started  {"kind": "exporter", "name": "otlp"}
> 2024-01-15T10:00:00Z  info  prometheusexporter/exporter.go:xxx  Exporter started  {"kind": "exporter", "name": "prometheus"}
> ```
> **Vérification** : Le pod est `Running 1/1`. Les logs montrent les deux exporters (`otlp` et `prometheus`) démarrés sans erreur.

### 6.4 Corrélation E-M-T

* **Exemplars** : pointeurs depuis une série Prometheus vers un **trace_id** (Grafana montre "View trace").
* **Logs ↔ Traces** : inclure **trace_id/span_id** dans les logs → liens croisés Grafana/Tempo/Loki.

---

## 7) Sécurité, conformité & multi-tenance

* **RBAC** : limiter l'accès aux UIs (Grafana, Prom, Alertmanager, Jaeger) via **Ingress** + **authN/OIDC**.
* **NetworkPolicies** : restreindre scrapes et sorties (Prom → cibles, Fluent Bit → Loki).
* **Secrets** : mots de passe datasources/receivers en **Secret** K8s (chiffré **etcd**).
* **PII** : **ne pas** logguer de données personnelles ; **masquage** et **règles de rétention** par **namespace/projet** (GDPR/ISO 27001).
* **SLO/SLA** : publier des **SLI** (taux 2xx/latence) et alerter via **burn rate** (alerte rapide + lente).

---

## 8) Runbooks (diagnostic rapide)

### 8.1 `kubectl top` ne marche pas

> **Objectif** : Diagnostiquer pourquoi `kubectl top` ne retourne pas de métriques. Le problème vient généralement du metrics-server (APIService non disponible, erreurs TLS).
> **Pre-requis** : metrics-server déployé dans `kube-system`.

```bash
# Étape 1 : Vérifie que l'APIService metrics.k8s.io est disponible
# Si le status n'est pas "Available", le metrics-server a un problème
kubectl get apiservices | grep metrics.k8s.io          # doit être Available

# Étape 2 : Consulte les logs du metrics-server en temps réel
# Chercher les erreurs TLS, les timeouts de connexion au kubelet, etc.
kubectl -n kube-system logs deploy/metrics-server -f

# Si erreurs certs kubelet -> vérifier SAN/CA ; éviter --kubelet-insecure-tls en prod
```

> **Résultat attendu** :
> ```
> $ kubectl get apiservices | grep metrics.k8s.io
> v1beta1.metrics.k8s.io   kube-system/metrics-server   True   2m
>
> $ kubectl -n kube-system logs deploy/metrics-server -f
> I0115 10:00:00  scraper.go:xxx] ScrapeMetrics: time=... nodeCount=2 podCount=50
> # Si erreur : "x509: certificate signed by unknown authority" → problème CA kubelet
> ```
> **Vérification** : L'APIService doit être `True`. Si `False`, les logs du metrics-server indiqueront la cause (TLS, SAN manquant, kubelet injoignable).

### 8.2 Cibles Prometheus "DOWN"

> **Objectif** : Diagnostiquer pourquoi des cibles de scrape Prometheus apparaissent comme "DOWN" dans l'interface Status → Targets.
> **Pre-requis** : Prometheus Operator déployé, accès port-forward vers le service Prometheus.

```bash
# Étape 1 : Ouvre l'UI Prometheus pour inspecter les targets
kubectl -n monitoring port-forward svc/prometheus-operated 9090:9090
# UI → Status → Targets → voir error (timeout, 403…)

# Étape 2 : Vérifie que les ServiceMonitor/PodMonitor concernés existent
kubectl -n monitoring get servicemonitor,podmonitor | grep api

# Étape 3 : Vérifie que le Service et les Pods cibles existent et sont accessibles
kubectl -n app get svc,pods -l app.kubernetes.io/name=api -o wide
# Corriger: label selector, port name, path, NetPol
```

> **Résultat attendu** :
> ```
> $ kubectl -n monitoring get servicemonitor,podmonitor | grep api
> api   5d
>
> $ kubectl -n app get svc,pods -l app.kubernetes.io/name=api -o wide
> NAME          TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)    AGE
> svc/api       ClusterIP   10.96.50.100   <none>        8080/TCP   10d
>
> NAME                              READY   STATUS    IP           NODE
> api-deployment-7b8c9d-x2k4m      1/1     Running   10.244.1.5   node-1
> ```
> **Vérification** : Dans l'UI Prometheus → Targets, la cible doit passer à `UP`. Causes fréquentes : mauvais nom de port dans le ServiceMonitor, NetworkPolicy bloquante, path incorrect.

### 8.3 Alerte non envoyée

> **Objectif** : Diagnostiquer pourquoi une alerte Prometheus ne déclenche pas de notification via Alertmanager (alerte silencieuse, mauvais routage, receiver défaillant).
> **Pre-requis** : Prometheus et Alertmanager déployés.

```bash
# Étape 1 : Ouvre l'UI Alertmanager pour inspecter les alertes et silences
kubectl -n monitoring port-forward svc/alertmanager-operated 9093:9093
# UI → Status → Silences/Alerts

# Étape 2 : Consulte les logs d'Alertmanager en temps réel
# Chercher les erreurs d'envoi (SMTP, PagerDuty, webhook)
kubectl -n monitoring logs statefulset/alertmanager-main -f
# Vérifier route/receiver, inhibitions, labels 'severity'
```

> **Résultat attendu** :
> ```
> $ kubectl -n monitoring port-forward svc/alertmanager-operated 9093:9093
> Forwarding from 127.0.0.1:9093 → 9093
>
> $ kubectl -n monitoring logs statefulset/alertmanager-main -f
> level=info ts=... msg="Notify success" attempts=1 receiver=oncall
> # Si erreur : level=error msg="Notify failure" err="connection refused"
> ```
> **Vérification** : L'UI Alertmanager (localhost:9093) montre les alertes actives et leur statut. Les logs confirment les notifications envoyées ou les erreurs.

### 8.4 Loki/Fluent Bit "ingestion 429/500"

> **Objectif** : Diagnostiquer des erreurs d'ingestion Loki (HTTP 429 = rate limit, 500 = erreur interne) remontées par Fluent Bit.
> **Pre-requis** : Fluent Bit en DaemonSet et Loki déployés dans le namespace `monitoring`.

```bash
# Étape 1 : Vérifie les erreurs côté Fluent Bit (source de l'envoi)
kubectl -n monitoring logs ds/fluent-bit -f --tail=200 | grep -i error

# Étape 2 : Vérifie les erreurs côté Loki (récepteur)
# Cherche les messages liés aux erreurs, rate limiting, ou ingestion
kubectl -n monitoring logs deploy/loki -f --tail=200 | egrep -i "error|rate|ingest"
# Actions: réduire volume via 'Exclude', augmenter limites, sharding/partitionnement, rétention
```

> **Résultat attendu** :
> ```
> $ kubectl -n monitoring logs ds/fluent-bit -f --tail=200 | grep -i error
> # (si erreur 429) : [error] [output:loki:loki.0] loki.monitoring.svc:3100, HTTP status=429
>
> $ kubectl -n monitoring logs deploy/loki -f --tail=200 | egrep -i "error|rate|ingest"
> level=warn msg="entry too far behind" retention=true
> # ou : level=error msg="ingestion rate limit exceeded"
> ```
> **Vérification** : Identifier si le problème est un rate limit (429 → augmenter `ingestion_rate_mb` dans Loki) ou une erreur interne (500 → vérifier stockage/disque). Ajouter des `Exclude` dans Fluent Bit pour réduire le volume.

### 8.5 Traces absentes

> **Objectif** : Diagnostiquer pourquoi aucune trace n'apparaît dans Jaeger/Tempo malgré l'instrumentation de l'application.
> **Pre-requis** : OTel Collector et Tempo/Jaeger déployés.

```bash
# Vérifie les logs de l'OTel Collector pour confirmer que l'exporter fonctionne
# Si des erreurs apparaissent, l'endpoint est peut-être incorrect ou Tempo est down
kubectl -n monitoring logs deploy/otel-collector -f | grep -i "export"
# Vérifier endpoint OTLP, sampling (taux trop bas), propagation (traceparent/b3)
```

> **Résultat attendu** :
> ```
> $ kubectl -n monitoring logs deploy/otel-collector -f | grep -i "export"
> 2024-01-15T10:00:00Z  info  otlpexporter/exporter.go:xxx  Exporter started  {"kind": "exporter", "name": "otlp"}
> # Si erreur : level=error msg="Failed to export traces" error="connection refused"
> ```
> **Vérification** : L'exporter OTLP doit être démarré sans erreur. Vérifier aussi : le taux de sampling (trop bas = traces perdues), la propagation du contexte (`traceparent`/`b3` headers), et l'endpoint Tempo.

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

> **Objectif** : Regrouper toutes les commandes essentielles pour opérer la stack d'observabilité (metrics, Prometheus, Grafana, logs, traces) en une seule référence rapide.
> **Pre-requis** : Stack complète déployée (metrics-server, Prometheus Operator, Grafana, Loki/Fluent Bit, OTel Collector/Jaeger/Tempo).

```bash
# === MÉTRIQUES / HPA ===
# Vérifie que l'API de métriques est disponible
kubectl get apiservices | grep metrics.k8s.io
# Affiche la consommation CPU/RAM des nœuds et de tous les pods
kubectl top nodes ; kubectl top pods -A

# === PROMETHEUS OPERATOR ===
# Liste toutes les ressources CRD du stack Prometheus Operator
kubectl -n monitoring get prometheus,alertmanager,servicemonitor,podmonitor,prometheusrule
# Ouvre l'UI Prometheus sur localhost:9090
kubectl -n monitoring port-forward svc/prometheus-operated 9090:9090
# Consulte les logs de kube-state-metrics (source de métriques d'état K8s)
kubectl -n monitoring logs deploy/kube-state-metrics -f

# === PROMTOOL (vérifier les règles) ===
# Valide la syntaxe des règles Prometheus avant déploiement
promtool check rules ./rules.yaml

# === GRAFANA ===
# Affiche la ConfigMap des datasources Grafana (provisioning)
kubectl -n monitoring get cm grafana-datasources -o yaml
# Ouvre l'UI Grafana sur localhost:3000
kubectl -n monitoring port-forward svc/grafana 3000:3000

# === LOGS (Loki/Fluent Bit) ===
# Vérifie l'état des pods Loki
kubectl -n monitoring get pods -l app=loki
# Consulte les logs récents de Fluent Bit (DaemonSet = un pod par nœud)
kubectl -n monitoring logs ds/fluent-bit -f --tail=200

# === TRACES (OTel/Jaeger/Tempo) ===
# Vérifie l'état des pods OTel Collector avec détails nœud/IP
kubectl -n monitoring get pods -l app=otel-collector -o wide
# Ouvre l'UI Jaeger sur localhost:16686
kubectl -n monitoring port-forward svc/jaeger-query 16686:16686
# Ouvre l'API Tempo sur localhost:3200
kubectl -n monitoring port-forward svc/tempo 3200:3200

# === NETWORKPOLICIES (si scrapes bloqués) ===
# Liste les NetworkPolicies du namespace monitoring (peuvent bloquer les scrapes)
kubectl -n monitoring get netpol
```

> **Résultat attendu** :
> ```
> Chaque commande retourne les informations de son composant respectif.
> Exemple : kubectl top nodes → tableau CPU/RAM par nœud.
> Exemple : port-forward → "Forwarding from 127.0.0.1:9090 → 9090"
> ```
> **Vérification** : Toutes les commandes doivent retourner des résultats sans erreur. Un `Error from server (NotFound)` indique un composant non déployé.
