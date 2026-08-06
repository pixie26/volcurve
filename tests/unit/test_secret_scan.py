from scripts.secret_scan import _configured_values, _generic_findings


def test_secret_scanner_detects_without_returning_value():
    value = b"a-real-looking-secret-value"
    findings = _generic_findings(b'BNP_CLIENT_SECRET="' + value + b'"', "settings.txt")

    assert [(finding.detector, finding.location) for finding in findings] == [
        ("assigned_secret", "settings.txt")
    ]
    assert all(value.decode() not in repr(finding) for finding in findings)


def test_secret_scanner_allows_blank_and_placeholder_values():
    assert not _generic_findings(b"BNP_CLIENT_SECRET=", ".env.example")
    assert not _generic_findings(b'client_secret="your_client_secret"', "README.md")


def test_configured_values_can_be_loaded_from_dotenv(monkeypatch, tmp_path):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "BNP_CLIENT_ID=test-client-id-from-file\nBNP_CLIENT_SECRET=test-client-secret-from-file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("BNP_CLIENT_ID", raising=False)
    monkeypatch.delenv("BNP_CLIENT_SECRET", raising=False)
    monkeypatch.setattr("scripts.secret_scan.PROJECT_ROOT", tmp_path)

    assert _configured_values() == [
        b"test-client-id-from-file",
        b"test-client-secret-from-file",
    ]
