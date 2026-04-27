import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.credentials import CredentialsGenerator


def test_generated_gmail_username_has_high_entropy_numeric_suffix():
    creds = CredentialsGenerator().generate()

    username = creds["email_username"]
    local_suffix = ""
    for ch in reversed(username):
        if not ch.isdigit():
            break
        local_suffix = ch + local_suffix

    assert len(local_suffix) >= 10
    assert username == username.lower()
    assert "_" not in username
    assert creds["full_email"] == f"{username}@gmail.com"


def test_generated_password_uses_adb_stable_special_characters_only():
    password = CredentialsGenerator()._generate_password()

    assert len(password) == 14
    assert any(ch.islower() for ch in password)
    assert any(ch.isupper() for ch in password)
    assert any(ch.isdigit() for ch in password)
    assert any(ch == "!" for ch in password)
    assert not any(ch in "@#$%&*;|<>()`'\"\\" for ch in password)
