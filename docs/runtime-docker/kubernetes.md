# Lancement Via Kubernetes

Objectif: déployer l'image Arclith en workloads Kubernetes séparés, chacun avec un transport clair,
des probes, des ressources et un contexte de sécurité.

## Principe

Ne pas lancer tous les transports dans un seul Pod de production. Utiliser la même image immutable,
mais créer un workload par responsabilité:

- `Deployment/api`: FastAPI;
- `Deployment/mcp`: FastMCP HTTP;
- `Deployment/agent`: LangGraph/Agent Server;
- `Deployment/worker`: command-bus RabbitMQ;
- `Job` ou `CronJob`: tâches ponctuelles si nécessaire.

## Image

Publier une image versionnée:

```bash
IMAGE=ghcr.io/karned-rekipe/my-service:0.1.0
docker build -t "$IMAGE" .
docker push "$IMAGE"
```

En production, pin un digest si la plateforme le permet:

```text
ghcr.io/karned-rekipe/my-service@sha256:<digest>
```

## Config Et Secrets

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-service-config
data:
  APP_ENV: production
  ARCLITH_PROBE_PORT: "9000"
---
apiVersion: v1
kind: Secret
metadata:
  name: my-service-secrets
type: Opaque
stringData:
  MONGODB_URI: mongodb://mongo:27017/my-service
  LANGSMITH_API_KEY: change-me
```

En vrai déploiement, générer les `Secret` depuis le gestionnaire de secrets de la plateforme, pas
depuis un manifeste commité en clair.

## Deployment API

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-service-api
spec:
  replicas: 2
  selector:
    matchLabels:
      app: my-service
      transport: api
  template:
    metadata:
      labels:
        app: my-service
        transport: api
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        runAsGroup: 1001
        fsGroup: 1001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: api
          image: ghcr.io/karned-rekipe/my-service:0.1.0
          args: ["api"]
          ports:
            - name: http
              containerPort: 8000
            - name: probes
              containerPort: 9000
          envFrom:
            - configMapRef:
                name: my-service-config
            - secretRef:
                name: my-service-secrets
          readinessProbe:
            httpGet:
              path: /ready
              port: probes
            periodSeconds: 10
            timeoutSeconds: 2
            failureThreshold: 3
          livenessProbe:
            httpGet:
              path: /health
              port: probes
            periodSeconds: 20
            timeoutSeconds: 2
            failureThreshold: 3
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 512Mi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
```

Service:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service-api
spec:
  selector:
    app: my-service
    transport: api
  ports:
    - name: http
      port: 80
      targetPort: http
```

## MCP, Agent Et Worker

MCP réutilise l'image avec un autre argument:

```yaml
containers:
  - name: mcp
    image: ghcr.io/karned-rekipe/my-service:0.1.0
    args: ["mcp_http"]
    ports:
      - name: mcp
        containerPort: 8001
      - name: probes
        containerPort: 9000
```

Agent:

```yaml
containers:
  - name: agent
    image: ghcr.io/karned-rekipe/my-service:0.1.0
    args: ["agent"]
    env:
      - name: LANGGRAPH_HOST
        value: "0.0.0.0"
      - name: LANGGRAPH_PORT
        value: "2024"
    ports:
      - name: agent
        containerPort: 2024
    readinessProbe:
      tcpSocket:
        port: agent
```

Worker RabbitMQ:

```yaml
containers:
  - name: worker
    image: ghcr.io/karned-rekipe/my-service:0.1.0
    args: ["bus"]
    envFrom:
      - secretRef:
          name: my-service-secrets
```

## Déploiement

```bash
kubectl apply -f k8s/
kubectl rollout status deployment/my-service-api
kubectl get pods -l app=my-service
kubectl logs deployment/my-service-api
```

## Checklist SOTA

- Image immutable, idéalement pin par digest.
- Un workload par transport.
- `readinessProbe` et `livenessProbe` sur les probes Arclith quand disponibles.
- `resources.requests` et `resources.limits` définis.
- `runAsNonRoot`, `allowPrivilegeEscalation: false`, capabilities droppées.
- `seccompProfile: RuntimeDefault` pour rester aligné avec le profil de sécurité restreint.
- Secrets injectés par la plateforme, jamais committés.
- Logs collectés depuis stdout/stderr et traces exportées via OpenTelemetry si activé.
- Rollout vérifié avec `kubectl rollout status` et smoke applicatif après déploiement.

Retour: [vue d'ensemble Docker](../runtime-docker.md).
