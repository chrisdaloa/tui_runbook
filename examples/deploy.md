# Deploy — Web Application

Deploy version `${VERSION}` to the `${ENV}` environment.

## Check prerequisites

Verify that required tools are available and environment variables are set.

```bash
echo "=== Prerequisites ==="
echo "Environment : ${ENV}"
echo "Version     : ${VERSION}"
command -v docker >/dev/null 2>&1 && echo "docker  : ok" || echo "docker  : MISSING"
command -v git    >/dev/null 2>&1 && echo "git     : ok" || echo "git     : MISSING"
```

## Build Docker image

<!-- runbook:rollback: echo "Rollback: removing image app:${VERSION}" -->

Build and tag the application image.

```bash
echo "Building app:${VERSION} ..."
sleep 1
echo "Successfully tagged app:${VERSION}"
```

## Run database migrations

<!-- runbook:manual -->
<!-- runbook:rollback: echo "Rollback: reverting migrations for ${ENV}" -->

Review the migration plan in your staging environment before confirming.

```bash
echo "=== Applying migrations to ${ENV} ==="
sleep 1
echo "Migrations applied successfully."
```

## Deploy to ${ENV}

<!-- runbook:rollback: echo "Rollback: re-deploying previous version to ${ENV}" -->

```bash
echo "Deploying app:${VERSION} → ${ENV} ..."
sleep 1
echo "Deploy complete."
```

## Smoke test

Verify the service is responding after the deploy.

```bash
echo "Smoke test: checking /health endpoint ..."
sleep 1
echo "HTTP 200 — service is healthy in ${ENV}"
```
