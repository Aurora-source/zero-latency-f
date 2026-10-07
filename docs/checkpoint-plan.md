# Phase 0/1/1.5 local checkpoint proposal

Prepared **2026-09-05** on `codex/project-completion`, with `HEAD` at `ebac283`.
This is a review and staging proposal only: **nothing has been staged or committed**.

## Validation closure and attribution

The scoped validation report is closed using the existing passing results in
[`frontend-quality.md`](frontend-quality.md): reproducible npm installation,
TypeScript no-emit, ESLint, 22 frontend tests, production frontend build, zero
production and full-tree npm advisories, and 47 Python tests in both the focused
feature-integrity and complete suite runs. The existing warning totals and timings
remain recorded there; no unchanged tests or installations were repeated.

Compose validation was **executed by the user**, not the agent. The user confirmed
their Ubuntu-26.04 terminal was at `/home/rikon/code/zero-latency-f` and checked the
current working tree with Docker Compose **v5.5.0**:

```sh
docker compose --env-file /dev/null config \
  --no-interpolate \
  --no-env-resolution \
  --quiet
```

Reported exit code: **0**. The prior agent-environment attempt could not access the
Docker Desktop WSL CLI. It remains recorded as an earlier environment limitation;
no fresh agent-side Compose result is claimed. Neither result demonstrates an image
build, running containers, live readiness, real-data routing quality, or deployment.

## Exact proposed file allowlist

**45 files: 26 tracked files with effective changes, plus 19 new source/config/test/
documentation files.** Paths are repository-relative. Include only these paths if
staging is separately authorized; do not use broad directory staging or `git add .`.
`package-lock.json` is the intentional reproducibility lockfile, not a runtime output.

```text
.gitignore
AGENTS.md
README.md
docker-compose.yml
docs/api-contract.md
docs/checkpoint-plan.md
docs/frontend-quality.md
docs/tracked-runtime-artifacts.md
gateway/nginx.conf
requirements-test.txt
run-local.ps1
services/data-service/.dockerignore
services/data-service/Dockerfile
services/data-service/api_key_manager.py
services/data-service/main.py
services/data-service/requirements.txt
services/data-service/scripts/fetch_trai.py
services/data-service/scripts/process_coverage.py
services/data-service/tile_loader.py
services/data-service/tower_ingestion_worker.py
services/prediction-service/.dockerignore
services/prediction-service/Dockerfile
services/prediction-service/main.py
services/routing-engine/.dockerignore
services/routing-engine/Dockerfile
services/routing-engine/main.py
services/visualization/.dockerignore
services/visualization/.nvmrc
services/visualization/Dockerfile
services/visualization/app/App.tsx
services/visualization/app/components/MapView.tsx
services/visualization/app/components/RouteCard.tsx
services/visualization/app/lib/api.ts
services/visualization/eslint.config.mjs
services/visualization/package-lock.json
services/visualization/package.json
services/visualization/tests/App.test.tsx
services/visualization/tests/MapView.test.tsx
services/visualization/tests/RouteCard.test.tsx
services/visualization/tests/api.test.ts
services/visualization/tests/setup.ts
services/visualization/tsconfig.json
services/visualization/vite.config.ts
services/visualization/vitest.config.ts
tests/test_feature_integrity.py
```

### Explicit exclusions and preservation

- **All 59 paths** listed in [`tracked-runtime-artifacts.md`](tracked-runtime-artifacts.md)
  are excluded. That inventory comprises 58 runtime/data artifacts and one `.gitkeep`.
  Filename/metadata checks confirmed all 59 are tracked and locally present, with no
  modified artifact paths reported and no overlap with the allowlist. Their contents
  were not inspected, copied, hashed, removed, or regenerated.
- Excluding already tracked artifacts from staging **does not remove them from the
  resulting commit tree or history**. They remain inherited from `HEAD`. Untracking,
  history cleanup, and any preservation/rotation decisions require separate approval.
- All dotenv files, credentials, `node_modules`, virtual environments, package/test
  caches, retained dependency backups, `dist`, logs, model/data outputs, and the
  temporary ignored review/DNS helpers are excluded. No directory-wide staging is
  proposed.
- The following six dirty paths have **identical content after CRLF-to-LF
  normalization** against `HEAD`. They add no effective Git change and are not
  proposed for staging. Their local bytes are preserved without normalization:

```text
services/data-service/scripts/clip_bangalore.py
services/data-service/scripts/convert_southern.py
services/data-service/scripts/nah.py
services/visualization/app/components/CitySelector.tsx
services/visualization/app/components/Header.tsx
services/visualization/styles/index.css
```

## Checkpoint review

- Reviewed the proposed current files and effective changes, keeping the existing
  laptop overlay rather than replacing complete files from `origin/main`. This is a
  recovery checkpoint of that overlay plus approved reconciliation, not a claim that
  every laptop change is a new improvement.
- A targeted, value-redacted check covered known credential-token formats, private
  key headers, credential-bearing URLs, and quoted credential assignments in the
  proposed current files. No candidates were found. No standalone secret-scanning
  tool was installed or downloaded; this is not an exhaustive secrets guarantee.
- No dotenv files, credential stores, runtime artifact contents, or full Git history
  were scanned. Removed baseline credential literals remain a history/rotation risk;
  no credential values belong in this report. Current-file cleanup does not revoke
  previously exposed keys.
- Review-output caveat: removed historical credential material appeared in raw diff
  output during this review. It is not repeated in these documents. Treat affected
  credentials as exposed and rotate them before sharing the repository; this review
  did not rotate credentials or rewrite history.
- All proposed files are regular text files; none is a binary/runtime output or over
  1 MiB. Lockfile changes are intentional dependency resolution, with no browser
  downloads, force/legacy peer flags, overrides, or GPU/model dependencies added.
- Data-only credential injection, scoped Docker contexts, included data-service
  modules, no-key startup, canonical provenance/percentages, restored local towers,
  stop-aware ingestion, readiness gates, and routing/frontend contract changes are
  intentional Phase 0/1 work. Time-based costs and separate bicycle/scooter values
  remain protected by the existing regression results.
- Frontend source fixes, dependency updates, deterministic tests, Node declaration,
  and no-dotenv Vite/Vitest configuration are intentional Phase 1.5 work. Nested
  unused UI templates are not an independently typechecked component library.
- No source changes were made during report closure. Only this proposal and the
  validation report were added/updated; the ignored read-only review helper is not
  part of the proposed commit.

## Remaining Phase 2 work — not implemented

1. **Runtime and toolchain alignment.** The visualization Dockerfile still selects
   `node:20.19-alpine`, while its manifest and validated local toolchain require Node
   22. Align this before image validation. Review the README's older Node/GPU/local
   startup guidance and validate the Windows/WSL helper separately. Replace Vite
   dev-server production serving with a reviewed static-serving configuration.
2. **Routing correctness under concurrency.** Validate request-local corridor scores,
   cached weighted-graph ownership, day/night bucket transitions, invalidation, and
   multi-request behavior; test route geometry/ETA/coverage tradeoffs on controlled
   fixtures before approving real-data evaluation.
3. **Provenance and coverage quality.** Validate provider attribution, stale/empty
   coverage tiles, real-data versus estimate boundaries, and route-quality metrics
   against representative approved data. Do not regenerate existing datasets by
   default. Bound full-city ingestion and adaptive score recomputation costs; review
   how persisted key-index exhaustion state behaves when credentials are reordered.
4. **Reliability and frontend behavior.** Define bounded warm-up/retry deadlines and
   pathological Retry-After handling; test cancellation after input changes. Review
   the laptop overlay's removed heatmap error isolation and route-card presentation
   changes. Validate live map/vector tiles, browser/network loading, and UI flows
   after separate browser-tool authorization; address bundle size and deprecated
   map/lint dependencies through compatible, reviewed changes.
5. **CPU deployment validation and isolation.** After explicit authorization, build
   and exercise an isolated CPU-only Compose project within 4 cores/12 GB RAM.
   Confirm model/graph readiness, startup without keys, graceful shutdown, actual
   resource limits, unique project/container naming, bind/port isolation, persistent
   paths, log limits, backups, and rollback without affecting other server services.
   Add corridor bbox/padding/payload limits and review wildcard CORS, diagnostic path
   exposure, trusted pickle loading, and deprecated FastAPI lifecycle hooks before
   exposing the services beyond the controlled development environment.
6. **Repository and credential hygiene.** Obtain separate approval before untracking
   the 59 inventoried paths or taking any history-remediation action. Preserve local
   data and rotate previously exposed credentials through their owner/provider.

## Proposed commit message

```text
chore: checkpoint Phase 0/1 recovery and Phase 1.5 frontend quality

- isolate credentials and add scoped build-context exclusions
- restore tower coverage, provenance, API loading and readiness contracts
- preserve time-based routing and distinct bicycle/scooter profiles
- add reproducible frontend quality gates and compatible security updates
- record passing validation and preserve the laptop overlay
- document excluded runtime artifacts and remaining Phase 2 risks
```

Ready for a **local checkpoint review/commit after explicit staging and commit
authorization**, with the documented deployment limitations retained. This is not
approval to stage now, deploy, start containers, untrack data, or begin Phase 2.
