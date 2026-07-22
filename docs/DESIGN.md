# ITACA API — Design

**Date:** 2026-07-22 · **Status:** implemented (v0.1.0)

REST API on top of the ITACA package (`eticas-audit`) with Keycloak
integration, built as Eticas's integration artifact for the DataPACT
toolkit, following the integration pattern agreed with ASSIST (Jul 2026):
partners develop and test locally, externalise all configuration to
environment variables, and ASSIST handles the shared deployment
(Docker orchestration, Keycloak repointing, credential swapping).

## Design decisions

**D1 — Separate repo from the ITACA library.** The wrapper lives in its
own repository and depends on `eticas-audit` as a normal pip dependency —
exactly how a third party would consume it. The library keeps its own
release cycle (PyPI/Zenodo/CITATION); the wrapper is the DataPACT
deliverable and can be pushed (or pointed to, `AILegalAssistant`-style)
from the `github.com/DATAPACT` org without dragging the library along.

**D2 — Asynchronous execution, filesystem job store, no database.**
Audits over large datasets can outlive reverse-proxy timeouts, so
`POST /audits` returns `202 + audit_id` and clients poll. Records and
results are JSON files under `RESULTS_DIR` (atomic writes via temp file +
`os.replace`). Zero infrastructure dependencies — the deployment is one
container plus a volume. `FastAPI BackgroundTasks` suffices at expected
volume; if a real queue is ever needed, the HTTP contract is unchanged.

**D3 — Dataset upload restricted to CSV and Parquet.** The library reads
from local paths, so the API uploads to `DATA_DIR` and passes the path.
`.pkl` is deliberately rejected: unpickling third-party uploads is
arbitrary code execution — unacceptable on a shared consortium service.

**D4 — Auth decoupled behind `AUTH_ENABLED`.** Offline JWT validation
against the realm JWKS (cached; no per-request Keycloak call). Signature,
`exp`, `iss` and `aud` are verified. Repointing to the DataPACT Keycloak
is a pure env-var change. Fine-grained role authorisation is out of scope
for now; the hook is in `app/auth.py::require_auth`.

**D5 — Minimal but functional Docker.** `Dockerfile` (slim, non-root) +
`docker-compose.yml` with a `dev` profile that brings up a local Keycloak
with the `datapact-dev` realm pre-imported. ASSIST may replace all of it;
the only contract is `example.env`.

## Architecture

```
┌─────────────┐   Bearer JWT    ┌──────────────────────────┐
│   Client     │ ──────────────▶ │  itaca-api (FastAPI)      │
│ (AssessR /   │                 │  ├─ auth (OIDC/JWKS)      │
│  ASSIST)     │ ◀────────────── │  ├─ routers: meta,        │
└─────────────┘   JSON results  │  │   datasets, audits      │
                                 │  ├─ services: AuditRunner  │
       ▲ token                   │  │   (BackgroundTasks)     │
       │                         │  └─ storage: DATA_DIR,     │
┌─────────────┐                 │      RESULTS_DIR (fs)      │
│  Keycloak    │ ◀── JWKS fetch ─┤                            │
│ (local dev / │                 │  depends on:               │
│  DataPACT)   │                 │  eticas-audit (pip)        │
└─────────────┘                 └──────────────────────────┘
```

## Audit request schema

Maps **1:1** to the library surface — `model` → `BaseModel.__init__`
passthrough (including ITACA's native `sensitive_attributes` structure),
`params` → the matching `run_*_audit` call. `params` is a Pydantic
discriminated union over `audit_type` (`labeled` / `production` /
`impacted` / `drift`), so type-specific parameters are validated
statically (HTTP 422, not tracebacks). Pre-flight validation additionally
checks that referenced datasets exist and that every referenced column
(audit params + sensitive attributes) exists in the dataset.

Two result views are persisted per audit: `raw` (the library's per-audit
metric dict, structured `{metric: {sensitive_attribute: values}}`) and
`normalized` (`json_results(norm_values=True)`, ITACA's 0–100 scale,
computed best-effort).

## Environment variable contract

See `example.env` — it is the complete interface for deployment
operators. Groups: API (host/port/log/CORS), Storage (dirs, upload
limit), Auth (`AUTH_ENABLED` + the three Keycloak variables ASSIST
repoints + `KEYCLOAK_VERIFY_AUD`). Configuration is loaded via a single
`pydantic-settings` class (`app/config.py`); nothing is hardcoded.

## Implementation plan (as executed)

1. **Scaffold** — pyproject, `Settings`, app factory, `/health` + `/info`.
2. **Datasets** — storage service + upload/list/get/delete with format
   and size validation at upload time.
3. **Audits** — discriminated schemas, `AuditRunner` (4 types),
   BackgroundTasks, result persistence, endpoints. E2E-tested with a
   synthetic biased binary-classifier dataset.
4. **Keycloak** — JWKS auth dependency, dev realm export, auth tests
   with locally generated RSA keys (no live Keycloak needed in CI).
5. **Docker** — Dockerfile + compose with dev profile.
6. **Delivery docs** — README with ASSIST deployment notes, curl
   walkthrough, OpenAPI at `/docs`.

## External follow-ups (outside this repo)

- Request **write access** to `github.com/DATAPACT` (currently
  read-only) before pushing/pointing the deliverable there.
- Confirm with ASSIST (Dumitru Cenusa) whether the DATAPACT org expects
  full source or a documentation/pointer repo (the `AILegalAssistant`
  precedent suggests pointer repos are acceptable).
- ~~`eticas-audit` 0.1.7 (PyPI) vs 0.1.8 (repo)~~ **Resolved
  (2026-07-22):** the full `v0.1.7 → v0.1.8` diff touches only citation
  metadata (`.zenodo.json`, `CITATION.cff`, README, notebook) — zero
  code changes. The PyPI range pin `>=0.1.7,<0.2` stands; future
  functional releases published to PyPI will be picked up by the range.
