# Zero Latency F — Project Instructions

## Mission

Complete and productionize the connectivity-aware routing system for autonomous vehicles. Bangalore is the primary supported region. Improve correctness, routing quality, reliability, testing, documentation, frontend usability, and deployment readiness.

## Current Repository State

- `origin/main` is the GitHub baseline.
- The current branch is `codex/project-completion`.
- The working tree contains an uncommitted overlay from the latest laptop build.
- Audit and understand the overlay before editing it.
- Never discard, restore, reset, or overwrite existing work without explicit approval.
- Treat `/home/rikon/code/zero-latency-f-laptop-snapshot` as read-only.
- Never modify the original project under `/mnt/d/final-working-edition/`.
- Preserve GitHub-only areas such as `app/`, `gateway/`, `.gitignore`, `.gitattributes`, and other files absent from the laptop snapshot.

## Architecture

- Python 3.11 and FastAPI backend services.
- Data service: port 8001.
- Routing engine: port 8002.
- Prediction service: port 8003.
- Telemetry service: port 8004.
- React/Vite visualization frontend.
- Nginx gateway.
- Docker Compose is the authoritative production runtime.
- Development occurs in WSL2 Ubuntu 26.04.
- Production runs on Ubuntu 26.04 with 4 CPU cores and 12 GB RAM.
- GPU acceleration must remain optional. A CPU-compatible deployment path is required.

## Data and Storage Safety

- Do not access, print, modify, or commit `.env` files or credentials.
- Never commit raw OpenCellID/OSM data, GraphML, pickle models, SQLite databases, logs, caches, archives, virtual environments, `node_modules`, build outputs, or generated tiles.
- Do not download or regenerate large datasets or Docker/CUDA images without approval.
- Keep development files, dependencies, caches, containers, models, and generated data inside the WSL filesystem on D:.
- Do not create project data under `/mnt/c`, the Windows user profile, or C:.
- Never modify unrelated server services, Docker projects, volumes, media drives, Jellyfin, Palworld, or their data.

## Working Method

- Use GPT-5.6 Sol. Reasoning effort is user-controlled; settings such as `xhigh`
  or `ultra` must not be treated as a project blocker.
- GPT-5.6 Sol may delegate bounded independent work to subagents.
- Do not allow parallel agents to edit overlapping files.
- The parent agent must review and validate subagent results.
- Plan broad or architectural changes before implementing them.
- Prefer small, reviewable changes with clear validation.
- Use existing project conventions and reuse existing code.
- Use `rg` for repository searching.
- Do not repeatedly read entire large files when a focused search or line range is sufficient.
- Keep progress summaries concise and evidence-based.

## RTK Usage

- Use RTK for verbose read-only output and test commands where it preserves relevant evidence.
- Suitable examples include Git status/diff, pytest, npm tests, builds, Docker logs, and directory searches.
- Do not use compressed output for destructive operations, deployments, database mutations, migrations, Git commits, or Git pushes.
- If RTK hides required evidence, inspect its saved full-output file or rerun with `RTK_DISABLED=1`.
- RTK savings refer to shell-output reduction, not total Codex usage.

## Git Safety

- Never run `git reset --hard`, destructive checkout, clean, force push, or history rewriting.
- Do not stage, commit, push, open a PR, merge, or deploy unless explicitly requested.
- Preserve unrelated user changes.
- Before staging anything, check for secrets, generated files, large files, and runtime data.
- Do not blindly replace GitHub files with laptop versions.
- Reconcile both versions semantically and preserve useful functionality from each.

## First Milestone

Before implementation:

1. Audit the complete uncommitted diff against `origin/main`.
2. Identify genuine laptop improvements and regressions.
3. Determine which frontend is authoritative.
4. Compare API contracts between services and frontends.
5. Identify missing dependencies and incompatible versions.
6. Determine why major files became smaller and what functionality was lost.
7. Produce a phased recovery plan with validation commands.
8. Wait for approval before applying broad reconciliation changes.

## Validation

For each relevant change:

- Run focused tests first, then the broader suite.
- Validate backend tests with pytest.
- Validate frontend lint/type checks and production builds.
- Run `docker compose config`.
- Validate service health endpoints and API contracts.
- Test fastest, balanced, and connected routing modes.
- Check route geometry, travel cost, connectivity score, and fallback behavior.
- Test CPU-only execution.
- Review `git diff` and run `git diff --check`.
- Report skipped or unavailable checks honestly.

Do not claim completion merely because code compiles.

## Browser and UI Workflow

- Stabilize functionality and API contracts before redesigning the interface.
- Use Playwright CLI and project-specific skills for browser validation.
- Convert stable manual user flows into repeatable end-to-end tests.
- For visual redesign, generate multiple mockups, choose a reference, implement it, and compare the browser result against the reference.
- Preserve screenshots, traces, and test artifacts outside Git unless intentionally required.

## Deployment

- Development and validation must complete before production deployment.
- Deployment must use an isolated Compose project and explicit resource limits.
- Provide health checks, persistent-data paths, backups, logging limits, and rollback instructions.
- Do not interrupt existing services on the home server.
- Production changes require explicit approval.
