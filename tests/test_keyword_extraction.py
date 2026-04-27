import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scenarios.base import BaseScenario


def test_quoted_ui_labels_are_prioritized_without_fragmented_quoted_words():
    keywords = BaseScenario._extract_keywords_from_description(
        "'Create account' link or button at bottom-left of Google sign-in screen"
    )

    assert keywords[0] == "Create account"
    assert "'Create" not in keywords
    assert "account'" not in keywords


def test_multiple_quoted_ui_labels_do_not_fall_back_to_generic_screen_words_first():
    keywords = BaseScenario._extract_keywords_from_description(
        "'For my personal use' or 'For myself' option in dropdown"
    )

    assert keywords[:2] == ["For my personal use", "For myself"]
    assert "'For" not in keywords
    assert "myself'" not in keywords
