# Examples

End-to-end examples for the ITACA API, based on the example datasets and
model configuration bundled with the
[ITACA library](https://github.com/Eticas-AI/itaca) (see
[`files/`](https://github.com/Eticas-AI/itaca/tree/main/files) and
[`example.ipynb`](https://github.com/Eticas-AI/itaca/blob/main/example.ipynb)
there). The datasets are downloaded on first run from the ITACA
repository — the canonical copies live there and are not duplicated here.

## Run

Start a local server without auth:

```bash
AUTH_ENABLED=false uvicorn app.main:app --port 8080
```

Then, in another terminal:

```bash
pip install requests   # the only dependency
python examples/run_examples.py
```

Against an authenticated deployment:

```bash
ITACA_API_URL=https://your-deployment ITACA_API_TOKEN=$TOKEN \
    python examples/run_examples.py
```

The script uploads the three binary-classifier datasets, runs all four
audit types and prints the normalized (0–100) fairness scores per
sensitive attribute.

## Mapping: library notebook → API

Same data, same configuration, two interfaces:

| ITACA notebook (`example.ipynb`) | ITACA API |
|---|---|
| `MLModel(model_name=…, sensitive_attributes=…)` | `"model"` block ([`model_config.json`](model_config.json)) |
| `run_labeled_audit('files/example_training_binary_2.csv', label_column='outcome', output_column='predicted_outcome', positive_output=[1])` | `POST /audits` with `"audit_type": "labeled"` on the uploaded training dataset |
| `run_production_audit('files/example_operational_binary_2.csv', …)` | `"audit_type": "production"` on the operational dataset |
| `run_impacted_audit('files/example_impact_binary_2.csv', output_column='recorded_outcome', …)` | `"audit_type": "impacted"` on the impact dataset |
| `run_drift_audit(dev=training, prod=operational, …)` | `"audit_type": "drift"` referencing both dataset ids |
| `model.json_results(norm_values=True)` | `GET /audits/{id}/results` (default `normalized=true`) |
| `model.json_results(norm_values=False)` | `GET /audits/{id}/results?normalized=false` |

The model configuration exercises all sensitive-attribute forms:
`simple` with `underprivileged` values (`sex`), `simple` with
`privileged` values (`ethnicity`, `age`), and `complex` intersections
(`sex_ethnicity`).

The ITACA repo also ships a *scoring* (regression, 0–1 outputs) variant
of the same three datasets (`example_*_scoring.csv`); the API calls are
identical apart from the filenames and columns — see the notebook for
the column mapping.
