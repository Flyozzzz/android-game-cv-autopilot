"""Editable prompt templates for CV-driven automation stages."""
from __future__ import annotations

from collections import defaultdict
from string import Formatter


INSTALL_GOAL_TEMPLATE = (
    "Install {game_name} from the Google Play Store app page. Tap safe "
    "buttons only. If the Play Store home screen is shown, tap Search/Поиск, "
    "type text_value_key=install_query, press enter, and open the matching "
    "result. If a local recommendations popup appears, dismiss it with "
    "Нет, спасибо or Continue. Use buttons such as Install, Установить, "
    "Update, Обновить, Continue, OK, Accept, or Wi-Fi/download confirmation "
    "if they are needed. If the page shows Open/Открыть or the app is already "
    "installed, use done. If the download/install progress is visible, use "
    "done so the script can poll package installation. Do not tap buy, "
    "purchase, payment, or subscription. Profile hints: {profile_hints} "
    "Extra operator instructions: {operator_instructions}"
)


TUTORIAL_GOAL_TEMPLATE = (
    "Complete the safe first-run onboarding, tutorial, and in-game registration "
    "for {game_name} until the main lobby/home screen is visible. Use tap, "
    "swipe, press, and type actions. Accept required terms/privacy notices, "
    "choose guest/skip/later for optional external sign-in, complete required "
    "training battles, claim only free tutorial rewards, and continue through "
    "OK, Continue, Next, Start, Play, and close popups when needed. If asked "
    "for a player name, type text_value_key=player_name. Do not tap any "
    "purchase, buy, payment, subscribe, paid offer, price, or shop purchase "
    "CTA. Use done when the main lobby is reached or if a purchase/payment "
    "prompt appears. {strategy_hint}{profile_hints} "
    "Extra operator instructions: {operator_instructions}"
)


PURCHASE_GOAL_TEMPLATE = (
    "In {game_name}, navigate to the shop/store/offers area and stop at the "
    "first real-money purchase opportunity without confirming any payment. It "
    "is safe to tap Shop/Store, offer cards, item cards, currency packs, and "
    "non-final preview surfaces. Do not tap Buy, 1-tap buy, Purchase, Pay, "
    "Subscribe, Confirm, Verify, password, fingerprint, visible price buttons, "
    "or any Google Play Billing confirmation. If a Google Play purchase dialog, "
    "payment sheet, billing sheet, password prompt, biometric prompt, or final "
    "buy/confirm button is visible, use done immediately. If a paid item "
    "purchase CTA or price button is visible and the next safe step would be a "
    "buy/payment confirmation, use done. Profile-specific hints: "
    "{profile_hints} Extra operator instructions: {operator_instructions}"
)


class _MissingPlaceholder(defaultdict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_prompt_template(template: str, values: dict[str, object]) -> str:
    """Render dashboard-editable templates while tolerating unknown fields."""

    safe_values = _MissingPlaceholder(str)
    safe_values.update({key: "" if value is None else str(value) for key, value in values.items()})
    try:
        return Formatter().vformat(template, (), safe_values).strip()
    except (KeyError, IndexError, ValueError):
        return template.strip()
