# Memory Layer deployment

The existing hosted service is **https://memorylayer.run**, backed by `/opt/engram-cloud` on the configured VPS. `memorylayer.dev` is not configured here. Engram core documentation at https://engram-memory.dev is a separate GitHub Pages deployment.

## Build a candidate

`scripts/deploy.sh <commit>` runs local checks, archives that exact commit into `/opt/engram-cloud-releases/<commit>`, and builds `engram-cloud:<commit>`. It does not activate an untested image. The image carries its source revision in an OCI label and `ENGRAM_CLOUD_SOURCE_REVISION`; the service manifest reports it alongside the pinned Engram source revision.

Engram and Mythic dependencies are pinned to exact Git commits. Mythic requires no Kiln service or private workstation data. The Engram dependency is pinned to a Git commit. Its Python package version remains 0.5.2; the version alone does not identify the source. Docker installs Git for the pinned requirement. Preserve the built image digest as the release artifact.

## Validate and activate

1. Run the full suite against the built image with a disposable PostgreSQL database and isolated data directory. Include authenticated workspace lifecycle, token/CSRF isolation, evidence, dormant review and legacy diary tests. Never write synthetic memories into production.
2. Browser-check public pages and signed-in workspace journeys on desktop and mobile using the candidate/local preview. Verify real forms, search, ingestion, key creation/revocation and navigation.
3. Before activation, retain the running image ID, a restricted `pg_dump -Fc` of the complete `engram_cloud` database, and a restricted archive of the current source, `.env`, Compose configuration and `data/`. Store backups outside the deployed tree, and verify the dump with `pg_restore --list`. Mythic SQLite databases and settings live under `data/<workspace>/mythic/`; quiesce writes or use SQLite backup for a consistent copy once those stores are active.
4. Keep the existing `.env`, PostgreSQL volume and `data/` mount. Write `.release-image.yml` containing `services.web.image: engram-cloud:<commit>`, then run `docker compose -f docker-compose.yml -f .release-image.yml up -d --no-build --no-deps web` from `/opt/engram-cloud`. Do not recreate PostgreSQL or run volume cleanup.
5. Verify readiness, manifest source SHA, architecture, public rendered content and unchanged account/workspace/key/memory counts at the origin. Verify the external canonical URL and browser rendering when that surface is available; report any access limitation explicitly.

For rollback, replace the release override's image with the retained previous image ID and repeat the Compose command. New core telemetry tables are additive. Restore a database backup only after assessing writes made since the backup; an image rollback should not discard new user data.

`scripts/live-check.sh` checks the public URL by default. For an independently authorized origin check, set `MEMORYLAYER_BASE_URL=http://127.0.0.1:8090` on the VPS. An origin check does not establish external DNS, TLS, or browser availability.

For an application-only iteration using already built dependencies, `Dockerfile.release` accepts `RUNTIME_IMAGE=<immutable sha256 image ID>` from the reviewed `Dockerfile` build. It copies the exact release source and resets its revision label. The release build resolves the reviewed dependency declarations over that base; verify both installed Git revisions and run the full release suite against the resulting image before activation. Never use a mutable third-party image tag as this release base.
