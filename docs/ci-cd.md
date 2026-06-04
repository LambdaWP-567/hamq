# CI/CD Pipeline

## Overview

HAMq uses GitHub Actions for all CI/CD automation. The pipeline covers unit testing, Docker image building, container smoke tests, Helm chart linting, automated security scanning, and GitHub Pages documentation deployment.

---

## Workflow Files

| Workflow | File | Trigger |
|---|---|---|
| Build Producer | `.github/workflows/build-producer.yml` | Push/PR to `components/producer/**` |
| Build Consumer | `.github/workflows/build-consumer.yml` | Push/PR to `components/consumer/**` |
| Build Arbiter | `.github/workflows/build-arbiter.yml` | Push/PR to `components/arbiter/**` |
| Build Controller | `.github/workflows/build-controller.yml` | Push/PR to `components/controller/**` |
| Build All | `.github/workflows/build-all.yml` | Push to `main`, manual dispatch |
| Deploy Docs | `.github/workflows/docs.yml` | Push to `docs/**` or `mkdocs.yml` |
| Security Scan | `.github/workflows/security-scan.yml` | Weekly schedule (Monday 6am UTC) |

---

## Per-Component Build Workflows

Each component (producer, consumer, arbiter, controller) has its own workflow that follows an identical three-stage pipeline:

```
test  →  build  →  container-smoke-test
```

### Stage 1: Test

Runs pytest against the backend's `tests/` directory. Provides the required environment variables so the application can initialize without real Kafka or database infrastructure.

Key environment variables set during tests:

| Variable | Value |
|---|---|
| `AUTH_USERNAME` | `testuser` |
| `AUTH_PASSWORD_HASH` | bcrypt hash of `admin` |
| `AUTH_SECRET_KEY` | `test-secret-key` |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` |
| `KAFKA_TLS_ENABLED` | `false` |

### Stage 2: Build

Builds a Docker image and pushes it to GHCR. The push is skipped on pull requests.

**Image tagging strategy:**

| Condition | Tags produced |
|---|---|
| Push to `main` | `latest`, `main`, `main-<sha>` |
| Push to feature branch | `<branch>`, `<branch>-<sha>` |
| Pull request | `pr-<number>` (built but not pushed) |

**GHA cache** (`type=gha`) is used for BuildKit layer caching, significantly reducing build times for unchanged layers.

### Stage 3: Container Smoke Test

Runs after a successful build on non-PR events. Executes `components/<name>/tests/test_container.sh`, which pulls the freshly built image and verifies the container starts and responds to health checks.

The `IMAGE` environment variable is set to the registry path so the script does not need to hardcode image references.

### workflow_call Support

Each per-component workflow includes `workflow_call` in its `on:` triggers, enabling `build-all.yml` to call them as reusable workflows.

---

## Build All Workflow

`build-all.yml` fans out to all four component workflows in parallel and additionally runs Helm lint across all charts:

```yaml
jobs:
  build-producer:
    uses: ./.github/workflows/build-producer.yml
  build-consumer:
    uses: ./.github/workflows/build-consumer.yml
  build-arbiter:
    uses: ./.github/workflows/build-arbiter.yml
  build-controller:
    uses: ./.github/workflows/build-controller.yml
  helm-lint:
    ...
```

All four build jobs run concurrently. The Helm lint job iterates over every `components/*/helm` directory.

### Manual Trigger

To trigger a full build manually without a code push:

1. Go to **Actions** tab in the GitHub repository.
2. Select **Build All Components**.
3. Click **Run workflow** and choose the target branch.

---

## GHCR Authentication

The workflows authenticate to GitHub Container Registry using the built-in `GITHUB_TOKEN`. No additional secrets are required for pushing to GHCR within the same repository.

### Required Repository Permissions

The `build` job sets:

```yaml
permissions:
  contents: read
  packages: write
```

If you fork this repository, ensure the fork has the **Packages: write** permission enabled for Actions. Go to **Settings → Actions → General → Workflow permissions** and select **Read and write permissions**.

### Pulling Images from GHCR

Images are public if the repository is public. For private repositories, authenticate with:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
docker pull ghcr.io/lambdawp-567/hamq-producer:latest
```

For Kubernetes deployments, create an image pull secret:

```bash
kubectl create secret docker-registry ghcr-secret \
  --docker-server=ghcr.io \
  --docker-username=lambdawp-567 \
  --docker-password=<PAT_TOKEN> \
  --namespace=hamq
```

Then reference it in your Helm values:

```yaml
imagePullSecrets:
  - name: ghcr-secret
```

---

## Customizing Docker Tags

The tagging strategy is defined in the `docker/metadata-action` step of each build workflow. To add or change tags, edit the `tags:` block:

```yaml
- uses: docker/metadata-action@v5
  id: meta
  with:
    images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
    tags: |
      type=ref,event=branch
      type=ref,event=pr
      type=sha,prefix={{branch}}-
      type=raw,value=latest,enable=${{ github.ref == 'refs/heads/main' }}
      # Add a semver tag when a Git tag is pushed:
      type=semver,pattern={{version}}
      type=semver,pattern={{major}}.{{minor}}
```

Common customizations:

- **Semver tags**: Add `type=semver,pattern={{version}}` and push a tag like `v1.2.3`.
- **Environment suffix**: Use `type=raw,value=staging-{{sha}}` for staging-specific images.
- **Disable latest**: Remove the `type=raw,value=latest,...` line to stop tagging the `latest` tag.

---

## Helm Linting

The `helm-lint` job in `build-all.yml` automatically discovers all Helm charts:

```bash
for chart in components/*/helm; do
  helm lint "$chart"
done
```

This catches common chart errors (missing required values, malformed templates, invalid YAML) before deployment. Add a `--strict` flag to fail on warnings:

```bash
helm lint --strict "$chart"
```

---

## Enabling GitHub Pages

The documentation is deployed to `https://lambdawp-567.github.io/hamq/` by the `docs.yml` workflow.

### First-Time Setup

1. Go to **Settings → Pages** in the GitHub repository.
2. Under **Source**, select **GitHub Actions**.
3. Save the settings.
4. Push a change to `docs/**`, `mkdocs.yml`, or `.github/workflows/docs.yml` on the `main` branch, or trigger the workflow manually.

The `docs.yml` workflow uses the newer `actions/upload-pages-artifact` + `actions/deploy-pages` approach (not the legacy `gh-pages` branch method). No `gh-pages` branch is created or required.

### Deployment Concurrency

The workflow uses a `concurrency` group to prevent parallel deployments:

```yaml
concurrency:
  group: "pages"
  cancel-in-progress: false
```

`cancel-in-progress: false` ensures that if a deployment is already running, the new run queues rather than cancelling the in-progress one.

---

## Security Scanning

`security-scan.yml` runs Trivy container vulnerability scans every Monday at 06:00 UTC. It scans all four component images in parallel using a matrix strategy and uploads results as SARIF reports to GitHub Code Scanning.

### Viewing Scan Results

1. Go to **Security → Code scanning** in the repository.
2. Filter by tool: **Trivy**.
3. Results show `CRITICAL` and `HIGH` severity vulnerabilities only.

### Manual Scan Trigger

```bash
gh workflow run security-scan.yml
```

### Adding New Components

Add the new component name to the matrix in `security-scan.yml`:

```yaml
matrix:
  component: [producer, consumer, arbiter, controller, my-new-component]
```

---

## Branch Protection

Recommended branch protection rules for `main`:

- Require status checks to pass before merging
- Required checks: `test` (from each component's workflow that was modified)
- Require branches to be up to date before merging
- Restrict who can push to `main`

To configure: **Settings → Branches → Add rule → Branch name pattern: `main`**.
