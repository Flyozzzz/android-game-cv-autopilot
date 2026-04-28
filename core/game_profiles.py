"""Game profile registry for CV-driven Android game automation."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import re
from collections.abc import Mapping


ScreenZone = tuple[float, float, float, float]


COMMON_SCREEN_ZONES: dict[str, ScreenZone] = {
    "bottom_buttons": (0.05, 0.72, 0.95, 0.96),
    "top_currency": (0.0, 0.0, 1.0, 0.14),
    "popup_center": (0.15, 0.20, 0.85, 0.80),
}


RUNNER_SCREEN_ZONES: dict[str, ScreenZone] = {
    **COMMON_SCREEN_ZONES,
    "runner_lanes": (0.10, 0.58, 0.90, 0.86),
}


MATCH3_SCREEN_ZONES: dict[str, ScreenZone] = {
    **COMMON_SCREEN_ZONES,
    "match3_board": (0.07, 0.30, 0.93, 0.78),
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "custom-game"


def _tuple_value(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in re.split(r"[\n,]+", value) if item.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),) if str(value).strip() else ()


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "validated", "proven"}


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _screen_zones_value(value: object) -> dict[str, ScreenZone]:
    if not isinstance(value, Mapping):
        return {}
    zones: dict[str, ScreenZone] = {}
    for raw_name, raw_box in value.items():
        name = str(raw_name or "").strip()
        if not name or not isinstance(raw_box, (list, tuple)) or len(raw_box) != 4:
            continue
        try:
            x1, y1, x2, y2 = (float(part) for part in raw_box)
        except (TypeError, ValueError):
            continue
        if 0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0:
            zones[name] = (x1, y1, x2, y2)
    return zones


@dataclass(frozen=True)
class GameProfile:
    """Configuration hints for one game.

    The generic CV autopilot remains the default engine. A profile describes
    what is realistically supported and adds game-specific hints without
    hard-coding a full bot for every title.
    """

    id: str
    name: str
    package: str
    aliases: tuple[str, ...] = ()
    player_name_prefix: str = "Player"
    install_query: str = ""
    tutorial_hints: tuple[str, ...] = ()
    purchase_hints: tuple[str, ...] = ()
    blocker_words: tuple[str, ...] = ()
    gameplay_strategy: str = "none"  # none | fast_runner | match3_solver | solver_required
    proven: bool = False
    notes: str = ""
    max_tutorial_steps: int = 0
    max_purchase_steps: int = 0
    screen_zones: dict[str, ScreenZone] = field(default_factory=dict)

    @property
    def selectors(self) -> tuple[str, ...]:
        return (
            self.id,
            self.name,
            self.package,
            self.install_query,
            *self.aliases,
        )

    def with_overrides(self, *, name: str = "", package: str = "") -> "GameProfile":
        updates: dict[str, str] = {}
        if name:
            updates["name"] = name
        if package:
            updates["package"] = package
        return replace(self, **updates) if updates else self


BUILTIN_GAME_PROFILES: tuple[GameProfile, ...] = (
    GameProfile(
        id="brawl-stars",
        name="Brawl Stars",
        package="com.supercell.brawlstars",
        aliases=("brawl", "brawlstars", "bs"),
        install_query="Brawl Stars",
        player_name_prefix="Player",
        tutorial_hints=(
            "Prefer guest/skip/later for optional Supercell ID sign-in.",
            "If a server/login failed dialog repeats, report an external blocker.",
        ),
        purchase_hints=(
            "Open the shop/store tab only after the main lobby is reachable.",
        ),
        blocker_words=(
            "supercell id",
            "login failed",
            "server connection failed",
            "войти не удалось",
            "попробуй позже",
        ),
        notes="Installed in validation, but current device/network hit a login/server blocker.",
        screen_zones=dict(COMMON_SCREEN_ZONES),
    ),
    GameProfile(
        id="talking-tom",
        name="My Talking Tom",
        package="com.outfit7.mytalkingtomfree",
        aliases=("my-talking-tom", "tom", "talking tom", "my talking tom"),
        install_query="My Talking Tom",
        player_name_prefix="Player",
        tutorial_hints=(
            "Age gates can use any adult-safe year such as 2004.",
            "Skip optional external sign-in and microphone/social prompts.",
            "The main room with Tom and bottom navigation means onboarding is complete.",
        ),
        purchase_hints=(
            "The store/cart entry is usually in the bottom-left navigation area.",
            "Tap Shop/Store and stop on the first real-money Remove Ads or currency offer.",
        ),
        proven=True,
        notes="Validated end-to-end on the connected Android phone up to purchase preview.",
        max_tutorial_steps=80,
        max_purchase_steps=35,
        screen_zones=dict(COMMON_SCREEN_ZONES),
    ),
    GameProfile(
        id="subway-surfers",
        name="Subway Surfers",
        package="com.kiloo.subwaysurf",
        aliases=("subway", "subway surfers", "subway-surfer"),
        install_query="Subway Surfers",
        player_name_prefix="Runner",
        tutorial_hints=(
            "Complete age/consent screens and start the first run.",
            "When active runner gameplay begins, use done so the fast local gameplay loop can take over.",
        ),
        purchase_hints=(
            "Use store/shop buttons from the home screen; never tap price or buy confirmations.",
        ),
        gameplay_strategy="fast_runner",
        notes="Needs local realtime gestures; LLM CV is too slow for active running.",
        max_tutorial_steps=90,
        max_purchase_steps=40,
        screen_zones=dict(RUNNER_SCREEN_ZONES),
    ),
    GameProfile(
        id="candy-crush",
        name="Candy Crush Saga",
        package="com.king.candycrushsaga",
        aliases=("candy", "candy crush", "candy-crush-saga"),
        install_query="Candy Crush Saga",
        player_name_prefix="Player",
        tutorial_hints=(
            "Accept terms, skip optional account links, and follow only clearly guided tutorial moves.",
            "Free guided moves are safe; unguided match-3 levels require a separate solver.",
        ),
        purchase_hints=(
            "Stop before any gold-bar, bundle, booster, or price button purchase confirmation.",
        ),
        gameplay_strategy="match3_solver",
        notes="Install/onboarding works partially; full play uses the generic match-3 solver.",
        max_tutorial_steps=120,
        max_purchase_steps=45,
        screen_zones=dict(MATCH3_SCREEN_ZONES),
    ),
    GameProfile(
        id="clash-royale",
        name="Clash Royale",
        package="com.supercell.clashroyale",
        aliases=("clash royale", "cr"),
        install_query="Clash Royale",
        player_name_prefix="Player",
        tutorial_hints=(
            "Skip optional Supercell ID sign-in and stop on repeated server/login blockers.",
        ),
        purchase_hints=(
            "Use the shop tab after the lobby is reachable and stop on any price/billing prompt.",
        ),
        blocker_words=("supercell id", "server", "войти не удалось"),
        notes="Generic CV profile; not yet proven on this phone.",
        screen_zones=dict(COMMON_SCREEN_ZONES),
    ),
    GameProfile(
        id="clash-of-clans",
        name="Clash of Clans",
        package="com.supercell.clashofclans",
        aliases=("coc", "clash of clans", "cash of clans"),
        install_query="Clash of Clans",
        player_name_prefix="Player",
        tutorial_hints=(
            "Skip optional Supercell ID sign-in and stop on repeated server/login blockers.",
        ),
        purchase_hints=(
            "Use the shop/store after village access and stop before any price/billing prompt.",
        ),
        blocker_words=("supercell id", "server", "войти не удалось"),
        notes="Generic CV profile; not yet proven on this phone.",
        screen_zones=dict(COMMON_SCREEN_ZONES),
    ),
)


def custom_profiles_dir() -> Path:
    return Path(
        os.getenv(
            "GAME_PROFILE_DIR",
            Path(__file__).resolve().parents[1] / "dashboard" / "profiles",
        )
    )


def game_profile_from_mapping(data: dict) -> GameProfile:
    """Build a profile from dashboard/MCP JSON data."""

    name = str(data.get("name") or data.get("install_query") or data.get("id") or "Custom Game").strip()
    profile_id = _slug(str(data.get("id") or name))
    strategy = str(data.get("gameplay_strategy") or data.get("gameplayStrategy") or "none").strip().lower()
    if strategy not in {"none", "fast_runner", "match3_solver", "solver_required"}:
        strategy = "none"
    return GameProfile(
        id=profile_id,
        name=name,
        package=str(data.get("package") or "").strip(),
        aliases=_tuple_value(data.get("aliases")),
        player_name_prefix=str(data.get("player_name_prefix") or data.get("playerNamePrefix") or "Player").strip() or "Player",
        install_query=str(data.get("install_query") or data.get("installQuery") or name).strip(),
        tutorial_hints=_tuple_value(data.get("tutorial_hints") or data.get("tutorialHints")),
        purchase_hints=_tuple_value(data.get("purchase_hints") or data.get("purchaseHints")),
        blocker_words=_tuple_value(data.get("blocker_words") or data.get("blockerWords")),
        gameplay_strategy=strategy,
        proven=_bool_value(data.get("proven")),
        notes=str(data.get("notes") or "").strip(),
        max_tutorial_steps=_int_value(data.get("max_tutorial_steps") or data.get("maxTutorialSteps")),
        max_purchase_steps=_int_value(data.get("max_purchase_steps") or data.get("maxPurchaseSteps")),
        screen_zones=_screen_zones_value(data.get("screen_zones") or data.get("screenZones")),
    )


def load_custom_game_profiles(directory: Path | None = None) -> tuple[GameProfile, ...]:
    directory = directory or custom_profiles_dir()
    if not directory.exists():
        return ()
    profiles: list[GameProfile] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                profiles.append(game_profile_from_mapping(payload))
        except Exception:
            continue
    return tuple(profiles)


def list_game_profiles() -> tuple[GameProfile, ...]:
    custom = {profile.id: profile for profile in load_custom_game_profiles()}
    result: list[GameProfile] = []
    for profile in BUILTIN_GAME_PROFILES:
        result.append(custom.pop(profile.id, profile))
    result.extend(custom.values())
    return tuple(result)


def resolve_game_profile(
    selector: str = "",
    *,
    game_name: str = "",
    package: str = "",
) -> GameProfile:
    """Resolve a known profile or create a custom package-backed profile."""

    selector = (selector or "").strip()
    game_name = (game_name or "").strip()
    package = (package or "").strip()
    lookup_values = [selector, game_name, package]
    lookup = {_norm(v) for v in lookup_values if v}

    if not lookup:
        return BUILTIN_GAME_PROFILES[0]

    for profile in list_game_profiles():
        profile_keys = {_norm(v) for v in profile.selectors if v}
        if lookup & profile_keys:
            return profile.with_overrides(name=game_name, package=package)

    custom_name = game_name or selector or package or "Custom Game"
    custom_package = package
    return GameProfile(
        id="custom",
        name=custom_name,
        package=custom_package,
        aliases=(selector,) if selector and selector != custom_name else (),
        install_query=custom_name,
        notes="Custom game profile. Provide GAME_PACKAGE for install/launch polling.",
    )


def format_profiles_for_cli() -> str:
    lines = ["Available game profiles:"]
    for profile in list_game_profiles():
        status = "proven" if profile.proven else profile.gameplay_strategy
        if status == "none":
            status = "generic-cv"
        lines.append(
            f"  {profile.id:16} {profile.package:34} {profile.name} [{status}]"
        )
    return "\n".join(lines)


def env_lines_for_profile(profile: GameProfile) -> str:
    return "\n".join(
        (
            f"GAME_PROFILE={profile.id}",
            f"GAME_NAME={profile.name}",
            f"GAME_PACKAGE={profile.package}",
        )
    )
