"""Game profile registry for CV-driven Android game automation."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re


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
