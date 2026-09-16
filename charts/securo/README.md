# Securo Helm Chart

[Securo](https://github.com/securo-finance/securo) is an advanced, self-hosted personal finance manager with built-in AI agents. This Helm chart provides a complete, production-ready deployment of Securo to any Kubernetes cluster.

## Features

- **Complete Application Stack**: Deploys the Vite/React SPA (nginx) and FastAPI backend, fully supporting all features including Open Banking integrations, OIDC authentication, and AI financial agents. This is not a Next.js rewrite.
- **Asynchronous Task Scheduler**: Runs Celery workers and a Celery beat singleton for automated background processing (such as bank syncs, recurring transactions, document extraction, and exchange rate updates).
- **Databases**: Easily configure connections to your external PostgreSQL (including Neon pooled + direct URLs) and Redis instances. Object storage is S3-compatible (`storageProvider: s3`); Vercel Blob is not used.
- **Gateway API & Ingress**: Native support for standard Kubernetes Ingress or the modern Kubernetes Gateway API (`HTTPRoute`).

## Prerequisites

- Kubernetes 1.25+
- Helm 3.2.0+
- PostgreSQL 15+ (with the `pgvector` extension installed)
- Redis 7+
- Persistent Volume (PV) provisioner support in the underlying infrastructure

### Persistent Storage Requirements
Since the Backend, Celery Worker, and MCP Server all share the same files (like uploaded attachments and AI knowledge bases), they all mount the same Persistent Volume Claims concurrently.
**If your cluster spans multiple nodes, you MUST use a StorageClass that supports `ReadWriteMany` (RWX) access mode (e.g., NFS, CephFS, or Longhorn RWX).**
If your storage only supports `ReadWriteOnce` (RWO), you must restrict all Securo pods to run on a single node (using `nodeSelector` or `podAffinity`) but that is an antipattern in Kubernetes.

## Quickstart

This chart ships the **this-repository** images (`ghcr.io/gscunha-22/securo-*`), not `ghcr.io/securo-finance`. Build them first, or `helm install` will pull a missing tag.

```bash
docker build -t ghcr.io/gscunha-22/securo-backend:local backend
docker build -t ghcr.io/gscunha-22/securo-frontend:local frontend
helm install securo ./charts/securo \
  --set backend.image.tag=local \
  --set frontend.image.tag=local \
  --set backend.image.pullPolicy=Never
```

On a VPS without Kubernetes, build and run this tree instead of pulling upstream:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.neon.yml up -d --build
```

## Configuration

All application-level features (such as AI Services, OIDC authentication, and Open Banking integrations) can be configured directly through Helm.
The keys in the `config:` and `secret:` blocks of the `values.yaml` map directly to the `UPPER_SNAKE_CASE` environment variables used in the standard Docker setup (converted to `camelCase`).

For a full list of available environment variables and API keys, please refer to the **[Securo Application Configuration Guide](https://github.com/securo-finance/securo-docs)**.

### Secrets Management (Production)

For production deployments, we highly recommend managing your secrets securely by passing an existing Kubernetes `Secret` rather than putting plain text keys in your `values.yaml`:

```yaml
global:
  existingSecret: "my-securo-secrets"
```

The secret must contain the corresponding keys (e.g., `SECRET_KEY`, `DATABASE_URL`, `DATABASE_URL_DIRECT`, `STORAGE_S3_ACCESS_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `AGENTS_OPENAI_API_KEY` — Helm maps `camelCase` values.yaml keys to `UPPER_SNAKE_CASE`).
For Neon, `databaseUrl` is the pooled (`-pooler`) URL and `databaseUrlDirect` is the compute endpoint used by the migration Job.
For an S3 vault, set `config.storageProvider` to `s3` and put access keys in the Secret (or `existingSecret`). Then disable `persistence.attachments` so originals are not expected on a local volume.

## Uninstalling the Chart

To uninstall/delete the `securo` deployment:

```bash
helm uninstall securo
```

This command removes all the Kubernetes components associated with the chart and deletes the release. Note that Persistent Volume Claims (PVCs) created by the chart might not be deleted automatically to prevent accidental data loss.
