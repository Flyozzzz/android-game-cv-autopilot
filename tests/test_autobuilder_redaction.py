from core.autobuilder.redaction import redact_obj, redact_text


def test_redaction_removes_keys_tokens_emails_and_phones():
    text = "email tester@example.com key sk-or-v1-abcdef phone +15551234567 password hunter2"

    redacted = redact_text(text)

    assert "tester@example.com" not in redacted
    assert "sk-or-v1" not in redacted
    assert "+15551234567" not in redacted
    assert "hunter2" not in redacted


def test_redaction_recurses_objects():
    payload = redact_obj({"api_key": "secret", "nested": [{"token": "abc"}, {"safe": "ok"}]})

    assert payload["api_key"] == "[REDACTED]"
    assert payload["nested"][0]["token"] == "[REDACTED]"
    assert payload["nested"][1]["safe"] == "ok"
