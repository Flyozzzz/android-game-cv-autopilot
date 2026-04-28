import importlib


def _reload_config(monkeypatch, **env):
    keys = (
        "PERCEPTION_MODE",
        "FRAME_SOURCE",
        "ACTION_MODE",
        "ENABLE_TEMPLATE_PROVIDER",
        "ENABLE_UIAUTOMATOR_PROVIDER",
        "ENABLE_LLM_FALLBACK",
        "ENABLE_DETECTOR_PROVIDER",
        "DETECTOR_MODEL_PATH",
        "DETECTOR_CONFIDENCE_THRESHOLD",
        "CV_MODELS",
    )
    for key in keys:
        if key in env:
            monkeypatch.setenv(key, env[key])
        else:
            monkeypatch.delenv(key, raising=False)
    import config

    return importlib.reload(config)


def test_perception_feature_flags_default_to_safe_rollout_values(monkeypatch):
    cfg = _reload_config(monkeypatch)

    assert cfg.PERCEPTION_MODE == "llm_first"
    assert cfg.FRAME_SOURCE == "adb"
    assert cfg.ACTION_MODE == "menu"
    assert cfg.ENABLE_TEMPLATE_PROVIDER is True
    assert cfg.ENABLE_UIAUTOMATOR_PROVIDER is True
    assert cfg.ENABLE_LLM_FALLBACK is True
    assert cfg.ENABLE_DETECTOR_PROVIDER is False
    assert cfg.DETECTOR_MODEL_PATH == ""
    assert cfg.DETECTOR_CONFIDENCE_THRESHOLD == 0.50
    assert cfg.CV_MODELS == ["xiaomi/mimo-v2.5"]


def test_perception_feature_flags_accept_supported_values(monkeypatch):
    cfg = _reload_config(
        monkeypatch,
        PERCEPTION_MODE="shadow",
        FRAME_SOURCE="replay",
        ACTION_MODE="fast",
        ENABLE_TEMPLATE_PROVIDER="0",
        ENABLE_UIAUTOMATOR_PROVIDER="false",
        ENABLE_LLM_FALLBACK="no",
        ENABLE_DETECTOR_PROVIDER="yes",
        DETECTOR_MODEL_PATH="/tmp/detector.onnx",
        DETECTOR_CONFIDENCE_THRESHOLD="0.72",
    )

    assert cfg.PERCEPTION_MODE == "shadow"
    assert cfg.FRAME_SOURCE == "replay"
    assert cfg.ACTION_MODE == "fast"
    assert cfg.ENABLE_TEMPLATE_PROVIDER is False
    assert cfg.ENABLE_UIAUTOMATOR_PROVIDER is False
    assert cfg.ENABLE_LLM_FALLBACK is False
    assert cfg.ENABLE_DETECTOR_PROVIDER is True
    assert cfg.DETECTOR_MODEL_PATH == "/tmp/detector.onnx"
    assert cfg.DETECTOR_CONFIDENCE_THRESHOLD == 0.72


def test_perception_feature_flags_fall_back_on_unknown_choices(monkeypatch):
    cfg = _reload_config(
        monkeypatch,
        PERCEPTION_MODE="experimental",
        FRAME_SOURCE="webcam",
        ACTION_MODE="turbo",
    )

    assert cfg.PERCEPTION_MODE == "llm_first"
    assert cfg.FRAME_SOURCE == "adb"
    assert cfg.ACTION_MODE == "menu"


def test_cv_models_env_override_is_trimmed(monkeypatch):
    cfg = _reload_config(monkeypatch, CV_MODELS=" model-a, ,model-b ")

    assert cfg.CV_MODELS == ["model-a", "model-b"]
