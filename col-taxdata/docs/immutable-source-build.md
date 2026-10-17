# Immutable source build (#268)

The default `compose.remote.yaml` still builds from the moving `main` branch
for development convenience. It is **not** a reproducible revision identity.
Use `compose.pinned.yaml` and `tools/build_pinned_source.py` when an exact
Git commit is required, as part of parent provenance issue #11.

## Plan, validate, build

From `col-taxdata/`:

```bash
# PLAN ONLY. No Git/Docker mutation and no claim that the remote SHA exists.
python3 tools/build_pinned_source.py --commit FULL_40_HEX_SHA

# Optional: verify that a local Git checkout contains precisely that commit.
python3 tools/build_pinned_source.py --commit FULL_40_HEX_SHA --verify-local ..

# Explicit local image build; does not launch a container or touch corpus.
python3 tools/build_pinned_source.py --commit FULL_40_HEX_SHA --build

# Optional local preflight + build (both fail closed).
python3 tools/build_pinned_source.py --commit FULL_40_HEX_SHA --verify-local .. --build
```

The script validates a full lowercase hexadecimal commit, never a branch,
a tag, an abbreviation, `HEAD` or a guessed fallback. Docker's build context is
`https://github.com/balamacab/RustIDEAM.git#<sha>:col-taxdata`. Compose uses
the **same SHA** in its image tag, container environment and revision label.
This prevents a later move of `main` from silently changing the selected
source commit, and keeps the pinned image distinct from `col-taxdata:local`.

`--verify-local` checks the immutable commit object in the specified local
Git repository. If the repository/commit is missing, it reports an unavailable
revision and does **not** substitute the checkout's HEAD. During `--build`,
Docker must fetch precisely the requested remote revision or fail; a missing
Docker client, remote outage or inaccessible revision cannot silently redirect
to moving `main`.

## Scope and limitations

- This tool only **builds** a local image when `--build` is explicitly set.
  It does not create a deployment, run the crawler, change production data,
  reprocess evidence, create credentials or change GitHub visibility.
- A dry-run verifies SHA *syntax*, not remote existence, Docker availability,
  image digest, build output identity or correct source outside the Docker
  context. Runtime labels are metadata, not cryptographic attestation.
- The Dockerfile still uses a floating upstream base image tag. Pinning the
  application commit is only one layer of parent issue #11; immutable image
  digest, configuration and runtime manifest are separate concerns.
- `COL_TAXDATA_SOURCE_SHA` is untrusted if a caller bypasses the validated
  script and invokes Compose manually. Operators must not claim verified
  provenance based only on an environment value.
- CI unit tests use isolated temporary Git histories and mock Docker invocation;
  they do not build a real image or depend on an external host.
