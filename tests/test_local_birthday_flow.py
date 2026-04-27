from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_local_birthday_uses_spinner_hint_bounds_not_label_text_only():
    src = (ROOT / "scenarios" / "google_register.py").read_text()
    assert "Local birthday via ADB Spinner/EditText bounds path" in src
    assert "Month Please fill in a complete birthday" in src
    assert "Day Please fill in a complete birthday" in src
    assert "Year Please fill in a complete birthday" in src
    assert "hint_prefix=\"Gender\"" in src


def test_google_register_has_adb_hint_helpers_for_spinners_and_edittexts():
    src = (ROOT / "scenarios" / "google_register.py").read_text()
    assert "async def _tap_node_by_class_and_hint" in src
    assert "async def _type_edittext_by_hint" in src
    assert "android.widget.Spinner" in src
    assert "android.widget.EditText" in src
