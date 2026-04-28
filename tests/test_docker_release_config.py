from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_beta_0115c():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.1.15c-beta"
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "0.1.15c-beta" in changelog
    assert "2026-04-27" in changelog


def test_docker_pipeline_uses_safe_dashboard_defaults():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "FROM python:3.13-slim" in dockerfile
    assert "android-tools-adb" in dockerfile
    assert "DASHBOARD_PASSWORD=" not in dockerfile
    assert "DASHBOARD_MCP_API_KEY=" not in dockerfile
    assert 'CMD ["python", "-m", "dashboard.server"]' in dockerfile
    assert "android-game-cv-autopilot:0.1.15c-beta" in compose
    assert "127.0.0.1:${DASHBOARD_PORT:-8765}:8765" in compose
    assert 'DASHBOARD_HOST: "127.0.0.1"' in compose
    assert 'DASHBOARD_PASSWORD: "${DASHBOARD_PASSWORD:-change-me}"' in compose
    assert 'DASHBOARD_MCP_API_KEY: "${DASHBOARD_MCP_API_KEY:-change-me}"' in compose
    assert 'PURCHASE_MODE: "preview"' in compose
    assert 'GOOGLE_PHONE_MODE: "manual"' in compose
    assert 'CV_MODELS: "${CV_MODELS:-xiaomi/mimo-v2.5}"' in compose
    assert 'CV_MODEL_ATTEMPTS: "${CV_MODEL_ATTEMPTS:-2}"' in compose
    assert "ADB_SERVER_SOCKET" in compose
    assert "OPENROUTER_API_KEY" in env_example
    assert "DASHBOARD_PASSWORD=change-me" in env_example
    assert "PERCEPTION_MODE=local_first" in env_example
    assert "CV_MODELS=xiaomi/mimo-v2.5" in env_example
    assert "CV_MODEL_ATTEMPTS=2" in env_example


def test_requirements_pin_local_first_image_matching_dependencies():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "Pillow==10.4.0" in requirements
    assert "numpy>=2.0,<3" in requirements
    assert "opencv-python-headless>=4.10,<5" in requirements


def test_public_release_ignores_local_sensitive_artifacts():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    for pattern in ("credentials.json", "legacy/", "logs/", "reports/", "trace/", ".env"):
        assert pattern in gitignore
    for pattern in ("credentials.json", "legacy", "logs", "reports", "trace", ".env"):
        assert pattern in dockerignore


def test_release_scripts_cover_docker_and_secret_scan():
    docker_check = (ROOT / "scripts/docker_check.sh").read_text(encoding="utf-8")
    secret_scan = (ROOT / "scripts/secret_scan.sh").read_text(encoding="utf-8")

    assert "docker build" in docker_check
    assert "python -m pytest -q" in docker_check
    assert "--cov-fail-under=100" in docker_check
    assert "rg -n --hidden --pcre2" in secret_scan
    assert "legacy/**" in secret_scan
    assert "scripts/secret_scan.sh" in secret_scan
