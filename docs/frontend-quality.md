# Frontend quality and dependency security (Phase 1.5)

The authoritative frontend is `services/visualization`, using its `app/main.tsx`
entry point. This work does not activate the historical nested `visualization/`
copy or change the backend/routing architecture.

## Reproducible checks

Use Linux-native Node **22.23.2**, declared in `services/visualization/.nvmrc`.
The manifest accepts Node `>=22.12 <23` and npm `>=10 <12`; the normal package
manager declaration is npm **10.9.8**. Run from `services/visualization`:

```sh
rtk proxy env npm_config_cache=/home/rikon/code/zero-latency-f/.cache/npm npm ci
rtk npm run typecheck
rtk npm run lint
rtk npm test -- --run
rtk npm run build
rtk proxy env npm_config_cache=/home/rikon/code/zero-latency-f/.cache/npm npm audit --omit=dev
rtk proxy env npm_config_cache=/home/rikon/code/zero-latency-f/.cache/npm npm audit
rtk npm explain nanoid postcss vite ws browserslist
```

Then, from the repository root:

```sh
rtk proxy env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_feature_integrity.py
rtk proxy env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
rtk docker compose --env-file /dev/null config --no-interpolate --no-env-resolution --quiet
rtk git diff --check
rtk git status --short --branch
```

Vite and Vitest explicitly disable automatic dotenv-file loading (`envDir: false`).
No browser credential injection is introduced. The Compose command disables dotenv
loading and leaves variable references uninterpolated. These checks do not start
containers or download datasets, models, GPUs, or browsers.

### Quality-check scope

- TypeScript uses strict checking with `noEmit`. Its roots include the application
  entry point, top-level components, API/library code, declarations, tests, and Vite
  configuration. TypeScript follows the complete import graph from those roots.
- The unreferenced `app/components/ui/` and `app/components/figma/` template catalog
  is not an independent TypeScript root. Some templates name undeclared packages;
  activating one requires reviewing and declaring its dependencies. It is not a
  supported, typechecked component library. No dormant files are removed.
- ESLint checks all `app/**/*.{ts,tsx}`, including the dormant catalog, tests, and
  configuration files. It checks React hook order/dependencies and treats warnings
  as failures. It is not an import-resolution or accessibility audit.
- Vitest uses jsdom and React Testing Library. App tests mock the map and API
  boundaries; MapView tests exercise its real prop wiring with Leaflet/network
  boundaries mocked. No live map tiles or backend services are needed.
- Browser layout, actual canvas/vector-tile rendering, and end-to-end networking
  remain unvalidated. A successful build is not a deployment-readiness claim.

### Initial regression coverage

| Test file | Coverage |
| --- | --- |
| `tests/api.test.ts` | HTTP 202 and legacy loading 503; delta/date Retry-After, expired/invalid/missing values; unrelated 503 failure; all three mode payloads; all four distinct vehicles; GeoJSON coordinate conversion; hybrid per-edge and unknown provenance; separate real-data and good-signal percentages. |
| `tests/App.test.tsx` | Initial route workflow; all three mode requests; unknown/hybrid/ML rendering; real and good percentages; no retry before the advertised delay; retry completion; unmount cancellation. |
| `tests/RouteCard.test.tsx` | Route metrics, selection, and explanation controls. |
| `tests/MapView.test.tsx` | Hotspot latitude/longitude reaches CircleMarker via `center`; selected route preserves geometry and direct `noClip`/`smoothFactor` properties. |

Checks exposed and fixed incorrect CircleMarker props, misplaced Polyline options,
untyped VectorGrid use, unsafe TypeScript union narrowing, and unused App code.
The Python source-level map regression was updated to require those direct Polyline
props in both the base route and signal segment, instead of requiring the old
incorrect PathOptions syntax; no regression test was removed.
Retry handling now respects an already elapsed HTTP-date header (one-second minimum)
instead of reverting to the body's longer delay; negative numeric headers use the
body fallback instead of being parsed as dates.

## Dependency review

Review date: **2026-09-05**. Baseline versions below are from the laptop lockfile and
the pre-update installed tree; final versions are locked, not inferred from ranges.

| Package | Dependency paths and action |
| --- | --- |
| `vite` | Root dev dependency, also consumed through the React/Tailwind plugins and Vitest. **8.0.8 → 8.2.2**, within the existing major. Existing plugin-react 6.0.1 accepts Vite 8; Tailwind's Vite plugin 4.2.2 and Vitest 4.1.11 also accept it. |
| `postcss` | Root dev dependency; `vite → postcss`; Autoprefixer's peer resolves to the same package. **8.5.10 → 8.5.28**, within the existing major. |
| `nanoid` | `postcss → nanoid`, and consequently `vite → postcss → nanoid`. **3.3.11 → 3.3.18**, using PostCSS's declared `^3.3.18` range, with no override. |
| `ws` | Removed production path: `@supabase/supabase-js@2.103.3 → @supabase/realtime-js@2.103.3 → ws@8.20.0`. The unused Supabase dependency was removed; no active source imports it, and the local type/stub module remains. The new test-only path is `jsdom@27.4.0 → ws@8.21.3`, within jsdom's declared `^8.18.3` range. Vitest also resolves jsdom as an optional peer. |
| `browserslist` | `autoprefixer@10.5.0 → browserslist` and `eslint-plugin-react-hooks@7.1.1 → @babel/core@7.29.7 → @babel/helper-compilation-targets@7.29.7 → browserslist`. **4.28.2 → 4.28.9**; compatible patch update within both parents' ranges. |

The original Vite Windows-path advisories affect Vite 8.0.0–8.0.15, although this
checkout runs on Linux. They were fixed instead of relying on platform assumptions:
[filesystem deny bypass](https://github.com/advisories/GHSA-fx2h-pf6j-xcff),
[launch-editor UNC handling](https://github.com/advisories/GHSA-v6wh-96g9-6wx3).

PostCSS 8.5.28 is beyond the affected ranges for the reviewed
[file read](https://github.com/advisories/GHSA-6g55-p6wh-862q),
[map traversal](https://github.com/advisories/GHSA-r28c-9q8g-f849), and
[incomplete-fix](https://github.com/postcss/postcss/security/advisories/GHSA-fxqj-rqcc-2cmp)
advisories. NanoID 3.3.18 addresses the reviewed
[negative size](https://github.com/advisories/GHSA-28wg-ghj8-5hjv),
[zero size](https://github.com/advisories/GHSA-2v37-7h3g-55p8), and
[integer overflow](https://github.com/advisories/GHSA-xwg4-73v4-xw9w) issues.

The old ws 8.20.0 was affected by
[memory disclosure](https://github.com/advisories/GHSA-58qx-3vcg-4xpx) and
[memory exhaustion](https://github.com/advisories/GHSA-96hv-2xvq-fx4p).
The test-only ws 8.21.3 is outside both affected ranges. Browserslist's
[unbounded memory](https://github.com/advisories/GHSA-c83g-rgw3-j3cx) and
[custom-stats crash](https://github.com/advisories/GHSA-73wf-gq98-2v4g)
advisories affect versions through 4.28.6; the lockfile now uses 4.28.9.

Build plugins were moved from runtime dependencies to `devDependencies`. This is
correct classification, not the sole security fix: Vite, PostCSS, and NanoID were
actually updated, and both production-only and full-tree audits are required.
The current Compose frontend still runs Vite, so dev-tool security continues to
matter until a separately approved static-production-serving change.

### Added development tooling (locked versions)

- TypeScript **5.9.3**; `@types/node` **22.20.1**, `@types/leaflet` **1.9.22**,
  `@types/leaflet.vectorgrid` **1.3.10**. Existing React types stay at **19.2.14**
  and React DOM types at **19.2.3**.
- ESLint and `@eslint/js` **9.39.5**, `typescript-eslint` **8.69.0**,
  `eslint-plugin-react-hooks` **7.1.1**, `globals` **16.5.0**.
- Vitest **4.1.11**, jsdom **27.4.0**, React Testing Library **16.3.3**,
  and `@testing-library/jest-dom` **6.9.1**.

No `overrides`, `--force`, or `--legacy-peer-deps` are used. No breaking dependency
migration was needed. ESLint 9 currently emits an upstream end-of-support/deprecation
warning; it is not an npm advisory. A future linter-major upgrade requires reviewing
the config and plugin compatibility, not suppressing that warning.
The existing production chain `leaflet.vectorgrid@1.3.0 → vector-tile@1.3.0 →
point-geometry@0.0.0` also emits package-rename deprecations. Both audits report no
advisories for that chain; replacing the map plugin is not part of this closure.

### Installation environment notes

npm 10.9.8 and 10.9.9 hit an internal `edgesOut` exception while resolving the newly
added optional Vitest peers. Lockfile resolution succeeded with a cache-local npm
11.19.1 helper using ordinary peer resolution; npm 10.9.8 can reproduce the resulting
lockfile with `npm ci`. If another manifest edit encounters that installer bug, use
the reviewed helper rather than force/legacy peer flags:

```sh
rtk proxy env npm_config_cache=/home/rikon/code/zero-latency-f/.cache/npm npm exec --yes --package=npm@11.19.1 -- npm install
rtk proxy env npm_config_cache=/home/rikon/code/zero-latency-f/.cache/npm npm ci
```

This session also encountered a WSL DNS resolver failure. Validation downloads used
a temporary, ignored, process-local DNS shim for the public npm registry, retaining
normal hostname/TLS verification. No system DNS or production configuration was
changed. Ordinary fresh installs still require a working registry resolver.

Dependencies and npm helper/cache files remain under this D:-backed WSL checkout.
The previous node_modules tree is retained recoverably in
`.cache/visualization-node-modules-before-phase15`; it is ignored and must not be
staged. Neither that backup nor any tracked runtime artifacts were deleted.

## Remaining boundaries

- Retry cancellation is tested for unmount, not every city/endpoint/vehicle change.
  The existing warm-up retry loop has no attempt/deadline policy or maximum supported
  Retry-After duration; define those semantics before hardening pathological waits.
- A clean npm audit is a registry snapshot, not proof of absence of vulnerabilities.
- Tracked runtime artifacts remain listed by filename in
  `docs/tracked-runtime-artifacts.md`, pending separate untracking approval.
- CPU-only container/runtime validation, routing concurrency/time-bucket quality,
  live service readiness, static frontend serving, and browser end-to-end validation
  belong to separately authorized follow-up work. No Phase 2 work is implemented here.

## Final validation record

Validated on 2026-09-05 using Node 22.23.2, npm 10.9.8, Python 3.11.16, and the
existing virtual environment. Networked npm commands used the process-local DNS
workaround described above. All commands used RTK.

| Check | Result |
| --- | --- |
| `npm ci` | Exit 0; added 299 packages, audited 300 in 9 seconds; zero vulnerabilities. The three package deprecation warnings are documented above. |
| `npm run typecheck` | Exit 0; strict no-emit check passed. |
| `npm run lint` | Exit 0; no warnings or errors. |
| `npm test -- --run` | Exit 0; 4 files, 22 tests passed in 2.79 seconds. |
| `npm run build` | Exit 0; 2,171 modules transformed. JS: 575.19 kB (175.74 kB gzip); CSS: 112.49 kB (22.16 kB gzip). Existing >500 kB chunk warning remains. |
| `npm audit --omit=dev` | Exit 0; zero vulnerabilities. |
| `npm audit` | Exit 0; zero vulnerabilities, including development dependencies. |
| Manifest/lockfile consistency | Dependency and engine fields match; no Playwright/Puppeteer/Vitest browser packages in lockfile. |
| Focused Python frontend regressions | 7 passed in 0.41 seconds after updating the obsolete Polyline syntax assertions. |
| `pytest ... tests/test_feature_integrity.py` | Exit 0; 47 passed, 32 FastAPI deprecation warnings in 3.25 seconds. |
| Complete `pytest` suite | Exit 0; 47 passed, the same 32 warnings in 2.83 seconds. |
| Earlier agent-side Compose check | Exit 1 in the agent execution environment: `/usr/bin/docker` pointed to a missing Docker Desktop WSL CLI target. This records the earlier environment limitation, not a Compose configuration failure. |
| User-executed Compose check | **Passed, exit 0**, reported by the user on 2026-09-05 from their Ubuntu-26.04 terminal against the current working tree. Docker Compose **v5.5.0**; exact command: `docker compose --env-file /dev/null config --no-interpolate --no-env-resolution --quiet`. No new agent-side Compose check was run for closure. |
| `git diff --check` | Exit 0. |
| `git status --short --branch` | Exit 0; branch `codex/project-completion`; the existing overlay and new Phase 1.5 files remain uncommitted. |

No application test failures remain. The **Phase 0/1/1.5 scoped validation report is
closed**, combining the existing agent-executed passing results with the explicitly
user-executed Compose result. No unchanged tests, audits, builds, or installations
were repeated to close this report. This accepts a local recovery checkpoint, not
production deployment readiness or live container validation.

The exact proposed checkpoint allowlist, exclusions, review findings, commit
message, and remaining Phase 2 work are recorded in
[`checkpoint-plan.md`](checkpoint-plan.md). Nothing is staged or committed. The 59
inventoried artifact paths remain excluded from proposed staging and preserved
locally; because they are already tracked, they also remain in the existing Git tree
until separate untracking approval.

### Phase 1.5 file inventory

- `AGENTS.md`: model rule with user-controlled reasoning effort.
- `services/visualization/package.json`, `package-lock.json`, `.nvmrc`: scripts,
  supported tooling, dependency classification/security, and reproducible lockfile.
- `services/visualization/tsconfig.json`, `eslint.config.mjs`, `vitest.config.ts`,
  `vite.config.ts`: quality gates and explicit no-dotenv frontend configuration.
- `services/visualization/tests/setup.ts`, `api.test.ts`, `App.test.tsx`,
  `RouteCard.test.tsx`, `MapView.test.tsx`: test environment and regressions.
- `services/visualization/app/App.tsx`, `app/lib/api.ts`,
  `app/components/MapView.tsx`: the scoped defects described above.
- `tests/test_feature_integrity.py`: preserve map assertions using valid React props.
- `docs/frontend-quality.md`: scope, security decisions, evidence, and handoff.

### Storage snapshot

Rounded allocated sizes, all under the D:-backed WSL checkout: frontend
`node_modules` **249 MiB**, npm cache/helpers **491 MiB**, retained old node_modules
backup **162 MiB**, build output **688 KiB**. The existing Python environment is
**429 MiB**; the uv cache adds **16 MiB** when shared hardlinks with that environment
are counted once. These are cumulative on-disk sizes, not measured download deltas.
All dependency/cache/backup/build paths were verified ignored by Git.
