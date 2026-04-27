"""
Genymotion Cloud SaaS — управление Android-устройствами.
Официальный HTTP API: https://developer.genymotion.com/saas
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from urllib.parse import urlparse

import httpx
from loguru import logger

import config


def _api_root(base_url: str) -> str:
    return (base_url or "").rstrip("/")


def _recipe_android_version(r: dict) -> str:
    """Версия Android из ответа v3/recipes (вложенный os_image)."""
    os_image = r.get("os_image") or {}
    os_ver = os_image.get("os_version") or {}
    return str(os_ver.get("os_version") or os_ver.get("android_version") or "")


def _recipe_api_level(r: dict) -> str:
    os_image = r.get("os_image") or {}
    os_ver = os_image.get("os_version") or {}
    return str(os_ver.get("sdk_version") or "")


def _normalize_recipe(r: dict) -> dict:
    """Добавляет плоские android_version / api_level для сценариев."""
    out = dict(r)
    out["android_version"] = _recipe_android_version(r)
    out["api_level"] = _recipe_api_level(r)
    return out


def _adb_serial_from_instance(info: dict) -> tuple[str, str, str]:
    """
    host, port, serial из инстанса (поле adb_url в SaaS API).
    serial = host:port для adb connect.
    """
    adb_url = (info.get("adb_url") or "").strip()
    if adb_url.startswith("tcp:"):
        rest = adb_url[4:]
        if ":" in rest:
            h, p = rest.rsplit(":", 1)
            return h, p, f"{h}:{p}"
    if "://" in adb_url:
        parsed = urlparse(adb_url)
        if parsed.hostname and parsed.port:
            h, p = parsed.hostname, str(parsed.port)
            return h, p, f"{h}:{p}"
        # Формат Genymotion часто: wss://host/40002 (порт в path)
        if parsed.hostname and parsed.path:
            path_port = parsed.path.strip("/").split("/", 1)[0]
            if path_port.isdigit():
                h, p = parsed.hostname, path_port
                return h, p, f"{h}:{p}"
    if adb_url and ":" in adb_url and not adb_url.startswith("http"):
        # host:port
        parts = adb_url.split(":")
        if len(parts) >= 2:
            h, p = parts[-2], parts[-1]
            return h, p, f"{h}:{p}"

    adb_data = info.get("adb") or {}
    host = str(adb_data.get("host") or info.get("adb_serial_host") or "")
    port = str(adb_data.get("port") or info.get("adb_serial_port") or "")
    if host and port:
        return host, port, f"{host}:{port}"
    serial = (info.get("adb_serial") or "").strip()
    return "", "", serial


class GenymotionCloud:
    """
    Клиент для Genymotion Cloud SaaS API (api.geny.io).
    """

    def __init__(self, api_token: str = None):
        self.api_token = api_token or config.GENYMOTION_API_TOKEN
        self.base_url = config.GENYMOTION_API_URL
        headers = {"Content-Type": "application/json;charset=utf-8"}
        if str(self.api_token or "").strip():
            headers["x-api-token"] = str(self.api_token).strip()
        self.client = httpx.AsyncClient(headers=headers, timeout=60.0)
        self.instance_uuid = None
        self.adb_host = None
        self.adb_port = None
        self.adb_serial = None

    def _root(self) -> str:
        return _api_root(self.base_url)

    # ══════════════════════════════════════════
    # Рецепты (образы устройств)
    # ══════════════════════════════════════════

    async def list_recipes(self) -> list:
        """
        Список рецептов (GET /v3/recipes/, с пагинацией по next).
        """
        logger.info("Fetching available recipes...")
        root = self._root()
        results: list[dict] = []
        next_url: str | None = f"{root}/v3/recipes/?page_size=100"

        while next_url:
            for attempt in range(1, 5):
                try:
                    resp = await self.client.get(next_url)
                    resp.raise_for_status()
                    break
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code if e.response else None
                    if status in (502, 503, 504, 520, 522, 524, 525) and attempt < 4:
                        logger.warning(f"Transient {status} on list_recipes, retry {attempt}/3...")
                        await asyncio.sleep(5 * attempt)
                        continue
                    raise
            payload = resp.json()
            if isinstance(payload, list):
                results.extend(payload)
                break
            batch = payload.get("results") or []
            results.extend(batch)
            next_url = payload.get("next") or None
            if not batch and not next_url:
                break

        recipes = [_normalize_recipe(r) for r in results]
        logger.info(f"Found {len(recipes)} recipes")
        for r in recipes:
            logger.debug(
                f"  Recipe: {r.get('name', '?')} | "
                f"Android {r.get('android_version', '?')} | "
                f"API {r.get('api_level', '?')} | "
                f"UUID: {r.get('uuid', '?')}"
            )
        return recipes

    async def find_best_recipe(
        self,
        android_version: str = None,
        keyword: str = None,
    ) -> dict:
        android_version = android_version or config.TARGET_ANDROID_VERSION
        keyword = keyword or config.TARGET_DEVICE_KEYWORD

        recipes = await self.list_recipes()
        if not recipes:
            raise RuntimeError("No recipes available in Genymotion Cloud")

        for r in recipes:
            name = r.get("name", "").lower()
            ver = str(r.get("android_version", ""))
            if android_version in ver and keyword.lower() in name:
                logger.success(f"Best match recipe: {r['name']} (Android {ver})")
                return r

        ver_matches = [r for r in recipes if android_version in str(r.get("android_version", ""))]
        if ver_matches:

            def _google_friendly_score(rec: dict) -> int:
                n = (rec.get("name") or "").lower()
                score = 0
                for hint in (
                    "google",
                    "pixel",
                    "play",
                    "gms",
                    "xiaomi",
                    "samsung",
                    "galaxy",
                ):
                    if hint in n:
                        score += 3
                if "genymotion phone" in n and "google" not in n and "pixel" not in n:
                    score -= 2
                return score

            ver_matches.sort(key=_google_friendly_score, reverse=True)
            best = ver_matches[0]
            if _google_friendly_score(best) <= 0:
                logger.info(
                    "Для этой версии Android выбран рецепт без слов Google/Pixel в названии — "
                    "Play Store может быть; при сбоях входа/маркета попробуй "
                    "TARGET_DEVICE_KEYWORD=pixel и версию под рецепт «Google Pixel …»."
                )
            logger.info(
                f"Version match recipe: {best['name']} (Android {best.get('android_version')})"
            )
            return best

        for r in recipes:
            name = r.get("name", "").lower()
            if keyword.lower() in name:
                logger.info(f"Keyword match recipe: {r['name']}")
                return r

        r = recipes[0]
        logger.warning(f"Fallback recipe: {r.get('name', '?')}")
        return r

    async def resolve_startup_recipe(self) -> dict:
        """
        Рецепт для старта инстанса: явный UUID / подстрока имени из env, иначе find_best_recipe.
        """
        uuid_hint = (getattr(config, "GENYMOTION_RECIPE_UUID", "") or "").strip()
        name_hint = (
            getattr(config, "GENYMOTION_RECIPE_NAME_CONTAINS", "") or ""
        ).strip()

        if uuid_hint.lower() in ("auto", "0", "false", "no", "best", "default"):
            return await self.find_best_recipe()

        if uuid_hint:
            recipes = await self.list_recipes()
            for r in recipes:
                if str(r.get("uuid", "")).lower() == uuid_hint.lower():
                    r = _normalize_recipe(r)
                    logger.success(
                        f"Recipe from GENYMOTION_RECIPE_UUID: {r.get('name')} "
                        f"(Android {r.get('android_version')}, {r.get('uuid')})"
                    )
                    return r
            logger.warning(
                f"UUID {uuid_hint!r} не найден в списке v3/recipes — "
                "пробуем старт по этому UUID всё равно (кастомный/скрытый рецепт)"
            )
            return _normalize_recipe(
                {
                    "uuid": uuid_hint,
                    "name": "GENYMOTION_RECIPE_UUID (not in list)",
                    "os_image": {},
                }
            )

        if name_hint:
            recipes = await self.list_recipes()
            needle = name_hint.lower()
            matches = [
                _normalize_recipe(r)
                for r in recipes
                if needle in (r.get("name") or "").lower()
            ]
            if not matches:
                raise RuntimeError(
                    f"No recipe whose name contains {name_hint!r}. "
                    "Проверь GENYMOTION_RECIPE_NAME_CONTAINS или список рецептов в портале."
                )
            if len(matches) > 1:
                names = [m.get("name") for m in matches[:8]]
                logger.warning(
                    f"Несколько рецептов по подстроке {name_hint!r}: {names} — берём первый"
                )
            r = matches[0]
            logger.success(
                f"Recipe from GENYMOTION_RECIPE_NAME_CONTAINS: {r.get('name')} "
                f"({r.get('uuid')})"
            )
            return r

        return await self.find_best_recipe()

    # ══════════════════════════════════════════
    # Инстансы
    # ══════════════════════════════════════════

    async def start_instance(self, recipe_uuid: str, name: str = "clash-bot") -> dict:
        """
        Старт disposable-инстанса по рецепту (POST /v1/recipes/{uuid}/start-disposable).
        """
        logger.info(f"Starting instance (recipe={recipe_uuid})...")
        root = self._root()
        resp = await self.client.post(
            f"{root}/v1/recipes/{recipe_uuid}/start-disposable",
            json={
                "instance_name": name,
                "rename_on_conflict": True,
                "stop_when_inactive": False,
            },
        )
        if resp.status_code >= 400:
            body = (resp.text or "")[:1000]
            logger.error(
                f"Start instance failed HTTP {resp.status_code} for recipe {recipe_uuid}: {body}"
            )
            raise RuntimeError(f"HTTP {resp.status_code}: {body[:200]}")
        data = resp.json()
        self.instance_uuid = data.get("uuid")
        logger.info(f"Instance created: {self.instance_uuid}")
        logger.debug(f"Instance data: {data}")
        return data

    async def get_instance(self) -> dict:
        if not self.instance_uuid:
            raise RuntimeError("No instance started")
        root = self._root()
        resp = await self.client.get(f"{root}/v1/instances/{self.instance_uuid}")
        resp.raise_for_status()
        return resp.json()

    async def list_instances(self) -> list:
        root = self._root()
        resp = await self.client.get(
            f"{root}/v2/instances",
            params={"ordering": "created_at"},
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            instances = data
        else:
            instances = data.get("results") or []
        logger.info(f"Running instances: {len(instances)}")
        return instances

    async def wait_for_ready(self, timeout: int = 120) -> dict:
        logger.info(f"Waiting for instance to become ready (timeout={timeout}s)...")
        elapsed = 0
        last_state = "unknown"
        transient_http_errors = 0

        while elapsed < timeout:
            try:
                info = await self.get_instance()
                transient_http_errors = 0
                state = (info.get("state") or "UNKNOWN").upper()
                last_state = state
                logger.debug(f"Instance state: {state} ({elapsed}s elapsed)")

                ready_states = ("ONLINE", "RUNNING", "READY", "BOOTED")
                if state in ready_states:
                    host, port, serial = _adb_serial_from_instance(info)
                    self.adb_host = host
                    self.adb_port = port
                    self.adb_serial = serial
                    if self.adb_serial:
                        logger.success(
                            f"Instance READY! State={state}, ADB={self.adb_serial}"
                        )
                        return info
                    logger.debug("Ready state but no ADB serial yet, waiting...")

                elif state in ("ERROR", "FAILED", "EXPIRED", "DELETED"):
                    raise RuntimeError(
                        f"Instance entered error state: {state}. Full info: {info}"
                    )

            except httpx.HTTPStatusError as e:
                status = e.response.status_code if e.response else None
                # Genymotion edge иногда отдаёт кратковременные 52x (в т.ч. 525 TLS),
                # это не означает, что инстанс умер — продолжаем polling.
                if status in (502, 503, 504, 520, 522, 524, 525):
                    transient_http_errors += 1
                    logger.warning(
                        "Transient HTTP polling error "
                        f"(status={status}, streak={transient_http_errors}): {e}"
                    )
                else:
                    logger.warning(f"HTTP status error polling instance: {e}")
            except httpx.HTTPError as e:
                transient_http_errors += 1
                logger.warning(
                    f"HTTP transport error polling instance (streak={transient_http_errors}): {e}"
                )

            await asyncio.sleep(5)
            elapsed += 5

        raise TimeoutError(
            f"Instance not ready after {timeout}s. Last state: {last_state}"
        )

    async def connect_adb(self) -> str:
        """
        Вернуть ADB serial для подключения.

        Для arm64/wss-инстансов используем gmsaas adbconnect, который
        пробрасывает устройство в localhost:<port>.
        """
        if not self.adb_serial:
            raise RuntimeError(
                "ADB serial not set; ensure instance is ready (wait_for_ready)."
            )

        # Если уже локальный serial — отдаем сразу.
        if self.adb_serial.startswith("localhost:"):
            return self.adb_serial

        # Для облачных arm64 инстансов adb_url часто wss://.../40002.
        # Прямой adb connect к ns-host:port может таймаутиться, используем gmsaas.
        # ADB порт может быть не готов сразу после state=ONLINE — retry до 3 раз.
        for attempt in range(1, 4):
            serial = self._try_gmsaas_adbconnect()
            if serial:
                self.adb_serial = serial
                logger.success(f"ADB mapped via gmsaas: {serial}")
                return serial
            if attempt < 3:
                logger.warning(f"gmsaas adbconnect attempt {attempt}/3 failed, waiting 20s...")
                await asyncio.sleep(20)

        # fallback — старое поведение
        return self.adb_serial

    def _try_gmsaas_adbconnect(self) -> str:
        if not self.instance_uuid:
            return ""
        gmsaas = shutil.which("gmsaas")
        if not gmsaas:
            logger.warning("gmsaas not found, fallback to direct adb serial")
            return ""

        env = os.environ.copy()
        if self.api_token:
            env["GENYMOTION_API_TOKEN"] = str(self.api_token)

        # Если SDK path не настроен в gmsaas, попробуем дефолтный macOS путь.
        default_sdk = "/Users/flyoz/Library/Android/sdk"
        try:
            if os.path.isdir(default_sdk):
                subprocess.run(
                    [gmsaas, "config", "set", "android-sdk-path", default_sdk],
                    env=env,
                    check=False,
                    capture_output=True,
                    text=True,
                )
        except Exception:
            pass

        try:
            proc = subprocess.run(
                [gmsaas, "instances", "adbconnect", self.instance_uuid],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            if proc.returncode != 0:
                logger.warning(
                    f"gmsaas adbconnect failed (rc={proc.returncode}): {err or out}"
                )
                return ""

            # Обычно stdout содержит "localhost:58744"
            m = re.search(r"(localhost:\d+)", out)
            if m:
                return m.group(1)
            # fallback: если вернулся просто порт
            m2 = re.search(r"\b(\d{4,6})\b", out)
            if m2:
                return f"localhost:{m2.group(1)}"
            return ""
        except Exception as e:
            logger.warning(f"gmsaas adbconnect exception: {e}")
            return ""

    async def stop_instance(self):
        if not self.instance_uuid:
            logger.warning("No instance to stop")
            return
        root = self._root()
        uuid = self.instance_uuid
        logger.info(f"Stopping instance {uuid}...")
        try:
            resp = await self.client.post(
                f"{root}/v1/instances/{uuid}/stop-disposable",
                json={},
            )
            resp.raise_for_status()
            logger.success("Instance stopped (disposable)")
        except Exception as e:
            logger.error(f"Error stopping instance: {e}")
        finally:
            self.instance_uuid = None

    async def stop_all_instances(self):
        instances = await self.list_instances()
        root = self._root()
        for inst in instances:
            uuid = inst.get("uuid")
            if not uuid:
                continue
            logger.info(f"Stopping instance {uuid}...")
            try:
                await self.client.post(
                    f"{root}/v1/instances/{uuid}/stop-disposable",
                    json={},
                )
            except Exception as e:
                logger.warning(f"Error stopping {uuid}: {e}")

    async def check_api(self) -> bool:
        if not str(self.api_token or "").strip():
            logger.warning("Genymotion API: GENYMOTION_API_TOKEN не задан")
            return False
        try:
            root = self._root()
            resp = await self.client.get(f"{root}/v3/recipes/?page_size=1")
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    logger.error(
                        "Genymotion API: ответ не JSON (проверьте GENYMOTION_API_URL)"
                    )
                    return False
                if isinstance(data, dict) and "results" in data:
                    n = data.get("count", len(data.get("results") or []))
                    logger.success(f"Genymotion API: OK (recipes доступны, count≈{n})")
                    return True
                if isinstance(data, list):
                    logger.success(f"Genymotion API: OK ({len(data)} recipes)")
                    return True
                logger.success("Genymotion API: OK")
                return True
            if resp.status_code == 401:
                logger.error("Genymotion API: UNAUTHORIZED (неверный токен)")
                return False
            logger.error(f"Genymotion API: HTTP {resp.status_code}")
            return False
        except Exception as e:
            logger.error(f"Genymotion API: {e}")
            return False

    async def close(self):
        await self.client.aclose()
