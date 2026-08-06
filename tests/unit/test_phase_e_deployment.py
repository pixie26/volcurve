from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_docker_image_is_non_root_single_worker_and_keeps_data_external():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "USER volcurve" in dockerfile
    assert "COPY schemas ./schemas" in dockerfile
    assert 'VOLUME ["/app/data"]' in dockerfile
    assert '"--workers", "1"' in dockerfile
    assert dockerfile.index("USER volcurve") < dockerfile.index("CMD ")
    assert {".env", "data"}.issubset(dockerignore)
    assert "schemas" not in dockerignore


def test_production_lock_contains_audited_security_floors():
    locked = (PROJECT_ROOT / "requirements.prod.lock").read_text(encoding="utf-8").splitlines()

    assert "idna==3.15" in locked
    assert "python-dotenv==1.2.2" in locked
    assert "starlette==1.3.1" in locked
    assert "annotated-doc==0.0.5" in locked


def test_runbook_requires_single_worker_and_pre_release_gates():
    runbook = (PROJECT_ROOT / "docs" / "operations_runbook_zh.md").read_text(encoding="utf-8")

    assert "--workers 1" in runbook
    assert "python scripts/secret_scan.py" in runbook
    assert "python scripts/audit_raw_hashes.py" in runbook
    assert "python -m pip_audit -r requirements.prod.lock --strict" in runbook
