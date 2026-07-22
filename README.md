# ITACA API

REST API wrapper for [ITACA](https://github.com/Eticas-AI/itaca)
(`eticas-audit`), the open-source AI fairness auditing library by
[Eticas](https://eticas.ai). Developed as part of the
[DataPACT](https://datapact-project.eu) project (Horizon Europe, GA
101189771) for integration into the DataPACT toolkit.

The API exposes ITACA's four audit types — **labeled**, **production**,
**impacted** and **drift** — over HTTP, with dataset upload, asynchronous
audit execution, and Keycloak (OIDC) authentication.

## Quickstart (local, no auth)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
AUTH_ENABLED=false uvicorn app.main:app --reload --port 8080
```

Interactive OpenAPI docs: <http://localhost:8080/docs>

Run the test suite:

```bash
pytest
```

## Quickstart (Docker, with local Keycloak)

```bash
cp example.env .env
docker compose --profile dev up --build
```

This starts the API on `:8080` and a development Keycloak on `:8081`
with the `datapact-dev` realm pre-imported (clients `itaca-api` and
`itaca-test-client`).

Get a token and call the API:

```bash
TOKEN=$(curl -s -X POST \
  "http://localhost:8081/realms/datapact-dev/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=itaca-test-client" \
  -d "client_secret=dev-only-secret-test-client" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/info
```

## API walkthrough

**1. Upload a dataset** (CSV or Parquet):

```bash
curl -H "Authorization: Bearer $TOKEN" \
  -F "file=@my_dataset.csv" http://localhost:8080/datasets
# → {"dataset_id": "ds_1a2b3c4d5e6f", "rows": 500, "columns": [...], ...}
```

**2. Launch an audit** (asynchronous — returns `202` immediately):

```bash
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "model": {
      "model_name": "loan-approval-v2",
      "sensitive_attributes": {
        "gender": {
          "columns": [{"name": "sex", "underprivileged": [2]}],
          "type": "simple"
        }
      }
    },
    "params": {
      "audit_type": "labeled",
      "dataset_id": "ds_1a2b3c4d5e6f",
      "label_column": "y_true",
      "output_column": "y_pred",
      "positive_output": [1]
    }
  }' http://localhost:8080/audits
# → {"audit_id": "audit_9f8e7d6c5b4a", "status": "pending"}
```

**3. Poll status and fetch results:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/audits/audit_9f8e7d6c5b4a
# → {"status": "completed", ...}

# Normalized view (0 = bad … 100 = good, ITACA's own normalisation):
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/audits/audit_9f8e7d6c5b4a/results

# Raw metric values:
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/audits/audit_9f8e7d6c5b4a/results?normalized=false"
```

The `model` block and per-type `params` map 1:1 to the `eticas-audit`
library surface (`MLModel` constructor and `run_*_audit` methods) — see
the [ITACA documentation](https://github.com/Eticas-AI/itaca) for the
semantics of `sensitive_attributes`, audit modes, and metrics.

### Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | no | Liveness probe |
| GET | `/info` | yes | Versions, audit types, accepted formats |
| POST | `/datasets` | yes | Upload dataset (multipart; csv/parquet) |
| GET | `/datasets` | yes | List datasets |
| GET | `/datasets/{id}` | yes | Dataset metadata |
| DELETE | `/datasets/{id}` | yes | Delete dataset |
| POST | `/audits` | yes | Create + launch audit (`202`) |
| GET | `/audits` | yes | List audits with status |
| GET | `/audits/{id}` | yes | Audit status/record |
| GET | `/audits/{id}/results` | yes | Results (`?normalized=true\|false`) |
| DELETE | `/audits/{id}` | yes | Delete audit + results |

## Deployment notes

The integration contract is **`example.env` and nothing else** — no code
or image changes should be needed to deploy this service in any
environment. (In the DataPACT shared deployment, this configuration is
managed by the consortium's integration partner.)

**What to change:**

- `KEYCLOAK_SERVER_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID` — point
  at your Keycloak instance. Token validation is offline against
  the realm JWKS (signature, `exp`, `iss`, `aud`); the API only needs
  network access to the JWKS endpoint
  (`{server}/realms/{realm}/protocol/openid-connect/certs`).
- `CORS_ORIGINS` — restrict to the actual consuming origins.
- `MAX_UPLOAD_MB` — align with your ingress body-size limit.

**What to mount:** a persistent volume on `/data` (datasets and audit
results live there; the service is otherwise stateless and a single
container).

**What not to touch:** nothing else requires configuration. The provided
`Dockerfile`/`docker-compose.yml` are intentionally minimal and may be
replaced by your own orchestration; the env-var contract is the only
interface.

**Notes:**

- `/health` is unauthenticated by design, for liveness probes.
- If your Keycloak does not stamp the API's client id into token
  audiences, set `KEYCLOAK_VERIFY_AUD=false` (issuer and signature are
  still verified).
- Pickle datasets are **deliberately rejected** at the API boundary
  (unpickling third-party uploads is a code-execution risk); only CSV
  and Parquet are accepted.

## Design

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full design document:
architecture, decision rationale (async job model, no-database storage,
auth decoupling), and the implementation plan this repo followed.

## License

Apache 2.0 — same as ITACA.
