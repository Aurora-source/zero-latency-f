# Deployment bundle — zero-latency-f 0.1.0

This is the public source deployment guide for tag `v0.1.0`. The exact tag
commit SHA, public asset hashes, image identifiers, and private artifact bundle
hash are in the adjacent `release-manifest.json` and GitHub Release assets.
`deployment-artifacts-manifest.json` defines the mandatory runtime inputs.

## Release inputs

Download and verify the public `zero-latency-f-0.1.0-deploy.tar.gz` with the
published `SHA256SUMS`. The public source archive intentionally excludes all
runtime graph, tower, and model data.

**The separate private file for manual transfer to the Ubuntu server is
`zero-latency-f-0.1.0-private-runtime.tar.gz`, SHA-256
`1d476e87c08af8786857f53598b24b5dd7be19ac894bc58d518309a8ff96348b`. It is
not attached to the public GitHub Release.** Keep it private. Check the archive
hash against the release manifest, extract it outside any public/web directory,
then run `sha256sum -c SHA256SUMS` inside the extracted bundle.

The bundle contains `artifacts/bangalore.graphml`,
`artifacts/bangalore_towers.csv`, `artifacts/connectivity_model.pkl`, and the
runtime schema-1 checksum manifest. Do not modify these files. Provenance and
redistribution limitations are explicit in the manifests; hashes establish
integrity only, not authenticity, legality, data quality, or model quality.

## Server prerequisites and layout

Use an Ubuntu 26.04 host with Docker Engine and Compose v2, `tar`, and
`sha256sum`. Production inference is CPU-only. The measured local Compose peak
was about 4.61 GiB, with data and routing each near 2.2 GiB; the Compose hard
ceilings total 9 GiB. This is not proof that a particular 12 GB host has enough
free memory alongside other workloads. Verify actual free RAM and disk before
starting.

Suggested private layout (adjust directory ownership for the service operator):

```text
/srv/zero-latency-f/releases/0.1.0/     public source bundle
/srv/zero-latency-f/artifacts/          extracted private artifacts/artifacts/*
/srv/zero-latency-f/production.env      non-secret Compose configuration
```

Copy the public archive into the release directory, extract it, and extract the
private bundle into a temporary directory. Copy only its three files and inner
`manifest.json` into `/srv/zero-latency-f/artifacts/`. Verify the artifact
checksums before use. The model is a pickle: only use this trusted, hash-matched
private transfer. Keep source artifacts read-only; Compose creates separate
named volumes for mutable graph publication, generated data/score state, route
cache, and prediction runtime.

## Configure and start

From `/srv/zero-latency-f/releases/0.1.0`, copy
`config/production.example` to `/srv/zero-latency-f/production.env`. Set
`ARTIFACT_DIR=/srv/zero-latency-f/artifacts`, `RELEASE_TAG=0.1.0`, and
`GATEWAY_PORT=8080`. Keep `CORS_ORIGINS` empty for same-origin requests. This
configuration has no credentials. Do not add secrets to the frontend or build
arguments. The gateway binds to `127.0.0.1:8080`; public ingress/TLS is a
separate deployment decision and is not configured by this bundle.

```bash
docker compose --env-file /srv/zero-latency-f/production.env \
  --project-name zlf-0.1.0 config --quiet
docker compose --env-file /srv/zero-latency-f/production.env \
  --project-name zlf-0.1.0 build
docker compose --env-file /srv/zero-latency-f/production.env \
  --project-name zlf-0.1.0 up -d --wait --wait-timeout 600
```

If the release provides the optional image archive, verify it using the
published checksums, load it with `docker load`, then use the same Compose
commands without `build`. The images contain no graph/tower/model inputs.

The entrypoints verify all artifact hashes before application startup. The
prediction service loads the seven-feature XGBoost model on CPU. Compose starts
prediction before data and data before routing, using actual readiness health
checks; the gateway is healthy only when all backend readiness routes respond.
Only gateway port 8080 is host-published, on loopback.

## Smoke, logs, and lifecycle

```bash
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/api/ready/prediction
curl --fail http://127.0.0.1:8080/api/ready/data
curl --fail http://127.0.0.1:8080/api/ready/routing
curl --fail http://127.0.0.1:8080/inspect-route
python3 scripts/production-smoke.py --url http://127.0.0.1:8080
docker compose --env-file /srv/zero-latency-f/production.env \
  --project-name zlf-0.1.0 logs --tail 100
```

The smoke script exercises CPU inference, a real route, SPA fallback, and
invalid input. Browser basemap tiles still need internet; the local GraphML
supports route calculations and does not contain raster tiles.

```bash
docker compose --env-file /srv/zero-latency-f/production.env \
  --project-name zlf-0.1.0 restart prediction-service
docker compose --env-file /srv/zero-latency-f/production.env \
  --project-name zlf-0.1.0 up -d --wait --wait-timeout 600
docker compose --env-file /srv/zero-latency-f/production.env \
  --project-name zlf-0.1.0 stop
```

Use only the stated Compose project. `stop` preserves volumes. Do not remove a
graph-publication volume to troubleshoot a mismatch; use a new release-scoped
project/volume with matching immutable inputs. Generated databases and caches
can be rebuilt, while the graph publication carries revision metadata and
should be backed up together with its source receipt.

## Rollback and known limits

Keep the previous immutable source/image tag, artifact bundle, and named volume
backup before upgrading. Roll back with the prior source/image tag and its
matching artifact hashes and volumes; do not reuse state from a different graph
revision. This release does not automate backup, restore, public networking,
TLS, firewall rules, or server deployment.

Tower provider/date, model training/evaluation and calibration, and complete
road restrictions metadata remain unknown. RF and traffic values are estimates;
connected routes may detour. Geocoding and the visual basemap require internet.
The local production browser check used Chromium only. See
`docs/phase-2e-production-release.md` and
`docs/phase-2f-a-release.md` for validation evidence and unresolved risks.
