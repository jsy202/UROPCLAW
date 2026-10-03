# Validation defects

## DEF-PY37-001 — production imports fail on Python 3.7

Status: fixed on `validation-carla-e2e`; not merged to `main`.

The required Python 3.7 environment raised
`TypeError: 'type' object is not subscriptable` while importing
`harness/config.py`. Runtime evaluation of Python 3.9 built-in generic
annotations such as `dict[str, ...]` caused the failure. A subsequent import
also showed that `typing.Literal` is unavailable in Python 3.7.

The minimal compatibility change postpones annotation evaluation by adding
`from __future__ import annotations` to these files without changing runtime
algorithms:

- `harness/config.py`
- `harness/harness.py`
- `harness/core/session_store.py`
- `harness/core/orchestrator.py`
- `harness/debug_snap.py`
- `harness/evaluation/metrics.py`
- `harness/gateway/proxy.py`
- `harness/obs/evaluator.py`
- `harness/sensors/camera.py`
- `harness/sensors/manager.py`
- `harness/start.py`

`harness/core/envelope.py` now imports `Literal` from `typing_extensions`.
The already installed Python 3.7-compatible version `4.7.1` is pinned in the
validation requirements.

Evidence:

- RED: the Python 3.7 subprocess import test failed in `harness/config.py`.
- GREEN: the same Python 3.7 import test passed.
- Regression: 36 existing unit/integration tests passed; two pre-existing
  NumPy deprecation warnings remain.

No queue, detector, HSV, tracking, temporal, VLM, alert, or scenario behavior
was changed by this defect fix.
