---
id: DEF-0006
type: defect
status: specified
priority: P2
area: operations
baseline: 2026-09-22-corpus-audit
---

# DEF-0006 — Docker writes runtime evidence as root with raw files mode 0600

## Summary

The application container runs as root. The bind-mounted `data/` tree and archived raw files are therefore created as root-owned host files; raw evidence is mode 0600 and cannot be read by the normal runtime account `user`.

## Observed behavior

On the audited server:

- application account: `user`, UID 1000;
- `data/`: `root:root`;
- raw SHA directories: `root:root`;
- raw HTML example: `-rw------- root root`;
- SQLite itself is readable, but raw files cannot be opened by `user` outside Docker.

The Dockerfile declares no `USER`, therefore the default root user is used.

## Impact

- local MCP/CLI processes running as `user` cannot inspect raw evidence directly;
- backups and host-side verification require Docker/root;
- generated files can have mixed ownership;
- least-privilege operation is not achieved.

No evidence loss was observed.

## Proposed solution

Run the container with a stable non-root UID/GID compatible with the host bind mount.

Preferred approach:

1. parameterize runtime UID/GID (default 1000:1000 for this deployment);
2. create/use an unprivileged application user in the image or set Compose `user:`;
3. ensure `/app/data` bind-mounted content is writable/readable by that UID/GID;
4. use an explicit safe umask (for example 0022 or project-approved equivalent);
5. migrate existing `data/` ownership once after the crawler is stopped;
6. restart and verify all new raw/extracted/state files are owned by the runtime user.

Do not recursively change ownership while the active crawler is writing files unless the migration procedure explicitly stops it first.

## Non-goals

- Do not make evidence world-writable.
- Do not require root for normal crawling or querying.
- Do not alter raw contents while fixing ownership.

## Reprocessing plan

No legal-data reprocessing is required.

Operational migration:

1. stop crawler;
2. backup/verify SQLite and raw SHA state;
3. correct ownership/permissions;
4. start container as unprivileged UID/GID;
5. fetch/process a controlled item;
6. verify ownership and hash stability.

## Acceptance criteria

- container process does not run as UID 0;
- host `user` can read raw and normalized evidence;
- application can create new raw/extracted/state files;
- newly created raw files have approved permissions;
- pre-existing raw SHA-256 values remain unchanged;
- crawler restart and SQLite writes succeed.

## Regression tests

Deployment smoke test:
- create a temporary/new fetched manifestation;
- verify host ownership;
- verify host read access;
- verify container write access;
- verify SHA256.

## Dependencies / ordering

Operationally independent. Apply during a planned crawler restart, not during active ingestion.
