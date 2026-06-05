# Session Log — 2026-06-06 (Cockpit deployment)

## Done this session

| Commit | What |
|--------|------|
| `11e58e9` | feat(cockpit): Cockpit reverse-proxy via Traefik TCP passthrough |

### Cockpit deployment details

- **Installed on all 3 nodes:** cubecluster (+ cockpit-machines for KVM), k3s-w1, k3s-w2
- **cockpit.conf** on cubecluster: `Origins = https://cockpit.hamq.test ...`, `AllowUnencrypted = true`
- **Helm chart:** `components/cockpit/helm/` — headless Service + Endpoints (3 IPs:9090) + IngressRouteTCP
- **Routing:** `IngressRouteTCP` with `HostSNI(cockpit.hamq.test)` + `tls.passthrough: true` on `websecure` entrypoint
- **Verified:** HTTP 200, Cockpit CSP scoped to cockpit.hamq.test, TLS handshake with Cockpit's own cert
- **Access:** `https://cockpit.hamq.test` (accept self-signed cert once; add k3s-w1/w2 as additional hosts inside Cockpit)

### Why TCP passthrough (not HTTP proxy)
- Cockpit HTTPS uses self-signed cert
- Global `insecureSkipVerify` on Traefik was blocked (affects all services)
- ServersTransport CRD approach gave 502 (debug inconclusive)
- TCP passthrough avoids TLS termination entirely — Cockpit's cert used end-to-end

## Still open

1. **Consumer auto-start on pod restart** — `CONSUMER_AUTOSTART` env var exists in configmap but not wired into `config.py` / `main.py`. Lifespan hook needs `await svc.start()` when env is true. Then flip helm values to `true`.

2. **Arbiter lag-aware reconciliation** — reconciler compares producer's newest 50 seqs vs consumer, showing 100% loss when consumer is behind. Fix: fetch consumer status first to find its `last_sequence_by_producer`, then only compare seqs ≤ that watermark.

## Files changed
- `components/cockpit/helm/Chart.yaml` (new)
- `components/cockpit/helm/values.yaml` (new)
- `components/cockpit/helm/templates/ingressroute.yaml` (new — IngressRouteTCP)
- `components/cockpit/helm/templates/service.yaml` (new — headless Service + Endpoints)
- `infra/values/cockpit-test.yaml` (new)
- `infra/deploy.sh` (added cockpit deploy step + access URL)
- `/etc/cockpit/cockpit.conf` (on host — not in git, manual step)
