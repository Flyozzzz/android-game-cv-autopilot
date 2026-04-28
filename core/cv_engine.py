"""
CV Engine — компьютерное зрение через Vision LLM (OpenRouter).
Анализирует скриншоты Android-устройства и находит UI-элементы.
"""
import base64
from io import BytesIO
import json
import os
import re
import struct
from time import perf_counter
from typing import Any, Optional

import httpx
from loguru import logger
from pydantic import BaseModel

import config
from core.metrics import GLOBAL_METRICS


def _safe_snippet(text: str, limit: int = 2000) -> str:
    if text is None:
        return ""
    return str(text)[:limit]


def _message_content_text(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts) if parts else None
    return None


def _draw_sparse_coordinate_grid(image_bytes: bytes) -> bytes:
    """Draw light rulers on the screenshot so Vision models can return better x/y coordinates."""

    from PIL import Image, ImageDraw

    image = Image.open(BytesIO(image_bytes)).convert("RGBA")
    width, height = image.size
    step = max(80, int(getattr(config, "CV_COORDINATE_GRID_STEP", 240) or 240))
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    line_color = (0, 255, 255, 82)
    label_fill = (0, 0, 0, 170)
    label_text = (255, 255, 64, 255)

    for x in _grid_positions(width, step):
        draw.line([(x, 0), (x, height)], fill=line_color, width=2)
        label_x = min(max(4, x + 4), max(4, width - 48))
        _draw_grid_label(draw, f"x{x}", label_x, 6, label_fill, label_text)
        _draw_grid_label(draw, f"x{x}", label_x, max(6, height - 24), label_fill, label_text)

    for y in _grid_positions(height, step):
        draw.line([(0, y), (width, y)], fill=line_color, width=2)
        label_y = min(max(4, y + 4), max(4, height - 20))
        _draw_grid_label(draw, f"y{y}", 6, label_y, label_fill, label_text)
        _draw_grid_label(draw, f"y{y}", max(6, width - 58), label_y, label_fill, label_text)

    combined = Image.alpha_composite(image, overlay).convert("RGB")
    buffer = BytesIO()
    combined.save(buffer, format="PNG")
    return buffer.getvalue()


def _grid_positions(limit: int, step: int) -> list[int]:
    positions = list(range(0, max(1, limit), step))
    edge = max(0, limit - 1)
    if not positions or positions[-1] != edge:
        positions.append(edge)
    return positions


def _draw_grid_label(draw: Any, text: str, x: int, y: int, fill: tuple[int, int, int, int], text_fill: tuple[int, int, int, int]) -> None:
    width = max(28, len(text) * 7)
    height = 16
    draw.rectangle((x, y, x + width, y + height), fill=fill)
    draw.text((x + 3, y + 2), text, fill=text_fill)


class UIElement(BaseModel):
    """Один UI-элемент, найденный на экране."""
    name: str
    x: int
    y: int
    width: int = 50
    height: int = 50
    element_type: str = "unknown"
    text: Optional[str] = None
    confidence: float = 0.5


class ScreenAnalysis(BaseModel):
    """Результат полного анализа экрана."""
    screen_name: str = "unknown"
    description: str = ""
    elements: list[UIElement] = []
    suggested_action: Optional[str] = None


class UIActionPlan(BaseModel):
    """План одного следующего действия на экране."""
    action: str = "wait"  # tap | type | press | swipe | wait | done | fail
    target: str = ""
    text_value_key: str = ""  # first_name, last_name, email_username, password, phone, code, etc.
    text: str = ""
    x: int = 0
    y: int = 0
    direction: str = ""  # up | down | left | right
    key: str = ""  # enter | back | tab
    wait_seconds: float = 1.0
    reason: str = ""


class CVEngine:
    """
    Движок компьютерного зрения.
    Отправляет скриншоты в Vision LLM и получает
    структурированные данные о UI-элементах.
    """

    def __init__(self, api_key: str = None, models: list[str] = None):
        self.api_key = str(api_key or config.OPENROUTER_API_KEY or "").strip()
        self.models = models or config.CV_MODELS
        self.current_model_index = 0
        self.client = httpx.AsyncClient(timeout=config.CV_REQUEST_TIMEOUT)
        self._call_count = 0
        self.trace_enabled = bool(getattr(config, "TRACE_ENABLED", False))
        self.trace_save_cv = bool(getattr(config, "TRACE_SAVE_CV", False))
        self.trace_dir = getattr(config, "TRACE_DIR", "trace")
        if self.trace_enabled and self.trace_save_cv:
            os.makedirs(os.path.join(self.trace_dir, "cv"), exist_ok=True)

    async def close(self):
        """Close the underlying HTTP client to release connections."""
        try:
            await self.client.aclose()
        except Exception:
            pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    @property
    def current_model(self) -> str:
        return self.models[self.current_model_index]

    def _rotate_model(self):
        """Переключиться на следующую модель (fallback)."""
        self.current_model_index = (
            (self.current_model_index + 1) % len(self.models)
        )
        logger.warning(f"Rotated to model: {self.current_model}")

    @staticmethod
    def _get_png_dimensions(image_bytes: bytes) -> tuple[int, int]:
        """Extract width, height from PNG bytes without PIL."""
        if image_bytes and len(image_bytes) > 24 and image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            w = struct.unpack('>I', image_bytes[16:20])[0]
            h = struct.unpack('>I', image_bytes[20:24])[0]
            return w, h
        return config.SCREEN_WIDTH, config.SCREEN_HEIGHT

    def _encode_image(self, image_bytes: bytes) -> str:
        """Base64-кодировка изображения."""
        return base64.b64encode(image_bytes).decode("utf-8")

    def _prepare_coordinate_vision_image(self, image_bytes: bytes) -> tuple[str, int, int, str]:
        """Return an image payload with a sparse coordinate ruler for coordinate-sensitive CV."""

        width, height = self._get_png_dimensions(image_bytes)
        note = (
            "The screenshot has a sparse coordinate ruler overlay: cyan guide lines and "
            "yellow x/y labels on the image edges. Use those labels to estimate precise "
            "coordinates in the original full-resolution screenshot."
        )
        if not getattr(config, "CV_COORDINATE_GRID", True):
            return self._encode_image(image_bytes), width, height, ""
        try:
            return self._encode_image(_draw_sparse_coordinate_grid(image_bytes)), width, height, note
        except Exception as exc:
            logger.warning(f"Failed to draw CV coordinate grid, using raw screenshot: {exc}")
            return self._encode_image(image_bytes), width, height, ""

    def _extract_json_from_text(self, text: str) -> dict | None:
        """
        Извлечь JSON из ответа LLM.
        Модели часто оборачивают JSON в ```json ... ``` блоки.
        """
        # Strategy 1: code block — use brace-matching to handle nested JSON
        code_block = re.search(r"```(?:json)?\s*", text, re.DOTALL)
        if code_block:
            start = code_block.end()
            # Find matching ``` end marker
            end_marker = text.find("```", start)
            if end_marker > start:
                candidate = text[start:end_marker].strip()
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass

        # Strategy 2: find first { and use brace-matching to extract full JSON
        brace_start = text.find("{")
        if brace_start >= 0:
            depth = 0
            in_string = False
            escape = False
            for i in range(brace_start, len(text)):
                c = text[i]
                if escape:
                    escape = False
                    continue
                if c == '\\' and in_string:
                    escape = True
                    continue
                if c == '"' and not escape:
                    in_string = not in_string
                    continue
                if not in_string:
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            candidate = text[brace_start:i+1]
                            try:
                                return json.loads(candidate)
                            except json.JSONDecodeError:
                                pass
                            break

        # Strategy 3: try the entire text
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        logger.warning(f"Could not extract JSON from: {text[:200]}...")
        return None

    def _extract_json_array_from_text(self, text: str) -> list:
        """Извлечь JSON-массив из текста."""
        # code-блок с массивом
        code_block = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass
        # Прямой массив
        arr_match = re.search(r"\[.*\]", text, re.DOTALL)
        if arr_match:
            try:
                return json.loads(arr_match.group(0))
            except json.JSONDecodeError:
                pass
        return []

    async def _call_vision(self, prompt: str, image_b64: str) -> str:
        """
        Вызов Vision LLM через OpenRouter API.
        С автоматическим fallback на другую модель при ошибке.
        """
        # Guard: empty or too-short image — don't send to Vision LLM, it returns 401/error
        if not image_b64 or len(image_b64) < 100:
            logger.warning(
                f"_call_vision: skipping (image_b64 too short: {len(image_b64 or '')} chars)"
            )
            raise RuntimeError("No screenshot available — cannot call Vision LLM")
        if not self.api_key:
            raise RuntimeError(
                "OpenRouter / Vision API key is required. Set OPENROUTER_API_KEY "
                "or enter the key in the dashboard Keys section."
            )

        self._call_count += 1
        call_id = self._call_count
        metric_started = perf_counter()
        GLOBAL_METRICS.increment("provider_llm_calls")

        last_errors: list[str] = []
        attempts_per_model = max(1, int(getattr(config, "CV_MODEL_ATTEMPTS", 2) or 2))
        for model_slot in range(len(self.models)):
            model = self.current_model
            for retry in range(attempts_per_model):
                attempt = model_slot * attempts_per_model + retry
                logger.debug(
                    f"[CV call #{call_id}] Model: {model}, "
                    f"attempt {attempt + 1}, retry {retry + 1}/{attempts_per_model}"
                )

                try:
                    resp = await self.client.post(
                        f"{config.OPENROUTER_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://replit.com/@clashbot",
                            "X-Title": "ClashRoyaleBot",
                        },
                        json={
                            "model": model,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": prompt},
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:image/png;base64,{image_b64}"
                                            },
                                        },
                                    ],
                                }
                            ],
                            "max_tokens": 2500,
                            "temperature": 0.1,
                        },
                    )

                    if resp.status_code != 200:
                        error_message = _safe_snippet(resp.text, 300)
                        last_errors.append(f"{model}: HTTP {resp.status_code}: {error_message}")
                        logger.warning(
                            f"[CV call #{call_id}] HTTP {resp.status_code}: {error_message}"
                        )
                        if 400 <= resp.status_code < 500:
                            break
                        continue

                    data = resp.json()

                    if "error" in data:
                        last_errors.append(f"{model}: API error: {_safe_snippet(data['error'], 300)}")
                        logger.warning(f"[CV call #{call_id}] API error: {data['error']}")
                        break

                    message = data["choices"][0]["message"]
                    content = _message_content_text(message)
                    if not content:
                        last_errors.append(f"{model}: empty content")
                        logger.warning(f"[CV call #{call_id}] API returned empty content")
                        self._save_cv_trace(
                            call_id=call_id,
                            attempt=attempt + 1,
                            model=model,
                            prompt=prompt,
                            response="",
                            status_code=resp.status_code,
                            error="empty content",
                        )
                        continue
                    logger.debug(f"[CV call #{call_id}] Response length: {len(content)}")
                    self._save_cv_trace(
                        call_id=call_id,
                        attempt=attempt + 1,
                        model=model,
                        prompt=prompt,
                        response=content,
                        status_code=resp.status_code,
                        error=None,
                    )
                    GLOBAL_METRICS.record_latency(
                        "provider_llm_ms",
                        (perf_counter() - metric_started) * 1000.0,
                    )
                    return content

                except httpx.TimeoutException:
                    last_errors.append(f"{model}: timeout")
                    logger.warning(f"[CV call #{call_id}] Timeout with {model}")
                    self._save_cv_trace(
                        call_id=call_id,
                        attempt=attempt + 1,
                        model=model,
                        prompt=prompt,
                        response="",
                        status_code=None,
                        error="timeout",
                    )
                    continue
                except Exception as e:
                    last_errors.append(f"{model}: {e}")
                    logger.error(f"[CV call #{call_id}] Error: {e}")
                    self._save_cv_trace(
                        call_id=call_id,
                        attempt=attempt + 1,
                        model=model,
                        prompt=prompt,
                        response="",
                        status_code=None,
                        error=str(e),
                    )
                    continue
            self._rotate_model()

        suffix = f" Last errors: {' | '.join(last_errors[-3:])}" if last_errors else ""
        GLOBAL_METRICS.record_latency(
            "provider_llm_ms",
            (perf_counter() - metric_started) * 1000.0,
        )
        raise RuntimeError(f"All {len(self.models)} CV models failed.{suffix}")

    def _save_cv_trace(
        self,
        call_id: int,
        attempt: int,
        model: str,
        prompt: str,
        response: str,
        status_code: Optional[int],
        error: Optional[str],
    ):
        if not (self.trace_enabled and self.trace_save_cv):
            return
        try:
            payload = {
                "call_id": call_id,
                "attempt": attempt,
                "model": model,
                "status_code": status_code,
                "error": _safe_snippet(error, 400),
                "prompt": prompt,
                "response": response,
            }
            file_path = os.path.join(
                self.trace_dir,
                "cv",
                f"cv_call_{call_id:05d}_attempt_{attempt}.json",
            )
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"Failed to save CV trace: {e}")

    # ══════════════════════════════════════════
    # Публичные методы
    # ══════════════════════════════════════════

    async def analyze_screen(
        self,
        screenshot_bytes: bytes,
        context: str = "",
        target: str = "",
    ) -> ScreenAnalysis:
        """
        Полный анализ экрана:
        - определить какой это экран
        - найти все интерактивные элементы с координатами
        - предложить следующее действие
        """
        image_b64, img_w, img_h, coordinate_note = self._prepare_coordinate_vision_image(screenshot_bytes)

        prompt = f"""You are an Android UI automation assistant. Analyze this screenshot.

CONTEXT: {context or 'General analysis'}
TARGET: {target or 'Find all interactive elements'}
SCREEN RESOLUTION: {img_w}x{img_h}
COORDINATE_OVERLAY: {coordinate_note or 'none'}

Return ONLY valid JSON (no extra text) in this exact format:
{{
  "screen_name": "short_screen_id",
  "description": "what is shown on screen",
  "elements": [
    {{
      "name": "element description",
      "x": 285,
      "y": 615,
      "width": 200,
      "height": 60,
      "element_type": "button",
      "text": "visible text on element",
      "confidence": 0.95
    }}
  ],
  "suggested_action": "what to do next"
}}

RULES:
- x, y = CENTER of element in pixels
- element_type: button, input, text, icon, checkbox, link, image
- confidence: 0.0 to 1.0
- If TARGET is specified, put matching elements FIRST
- Find ALL interactive elements (buttons, inputs, links, icons)
- For icons/buttons, use the center of the visible element, not the nearest label.
- Coordinates must be relative to full {img_w}x{img_h} resolution"""

        response_text = await self._call_vision(prompt, image_b64)
        data = self._extract_json_from_text(response_text)

        if not data:
            return ScreenAnalysis(
                screen_name="parse_error",
                description=response_text[:200],
            )

        elements = []
        for el in data.get("elements", []):
            try:
                elements.append(UIElement(
                    name=el.get("name", "unknown"),
                    x=int(el.get("x", 0)),
                    y=int(el.get("y", 0)),
                    width=int(el.get("width", 50)),
                    height=int(el.get("height", 50)),
                    element_type=el.get("element_type", "unknown"),
                    text=el.get("text"),
                    confidence=float(el.get("confidence", 0.5)),
                ))
            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping bad element: {el}, error: {e}")

        return ScreenAnalysis(
            screen_name=data.get("screen_name", "unknown"),
            description=data.get("description", ""),
            elements=elements,
            suggested_action=data.get("suggested_action"),
        )

    async def plan_next_ui_action(
        self,
        screenshot_bytes: bytes,
        goal: str,
        available_values: dict[str, str],
        recent_actions: list[str] | None = None,
    ) -> UIActionPlan:
        """
        LLM-планировщик одного следующего действия.
        Возвращает структурированную команду, которую можно исполнить tool-like.
        """
        # Fallback: no screenshot → wait action
        if not screenshot_bytes or len(screenshot_bytes) < 100:
            logger.warning("plan_next_ui_action: no screenshot — returning wait action")
            return UIActionPlan(action="wait", wait_seconds=2.0, reason="no_screenshot")

        image_b64, img_w, img_h, coordinate_note = self._prepare_coordinate_vision_image(screenshot_bytes)
        recent = recent_actions or []
        values_json = json.dumps(available_values, ensure_ascii=False)
        recent_json = json.dumps(recent[-8:], ensure_ascii=False)

        prompt = f"""You are an Android UI agent.
Pick EXACTLY ONE next action to progress toward GOAL.

GOAL: {goal}
AVAILABLE_VALUES_JSON: {values_json}
RECENT_ACTIONS_JSON: {recent_json}
SCREEN_RESOLUTION: {img_w}x{img_h}
COORDINATE_OVERLAY: {coordinate_note or 'none'}

Return ONLY valid JSON:
{{
  "action": "tap|type|press|swipe|wait|done|fail",
  "target": "what element to interact with (for tap/type when using visual target)",
  "text_value_key": "optional key from AVAILABLE_VALUES_JSON for type action",
  "text": "optional literal text for type action if key not used",
  "x": 0,
  "y": 0,
  "direction": "up|down|left|right",
  "key": "enter|back|tab",
  "wait_seconds": 1.0,
  "reason": "short reason"
}}

Rules:
- For tap/type on a visible element, include both target and precise x/y center coordinates.
- Use the coordinate ruler labels on the image edges to estimate x/y. Do not guess from the resized chat preview.
- For icons/buttons, return the center of the visible icon/button. For a top-right gear, x should usually be near the right edge.
- Use type + text_value_key whenever possible.
- If screen asks for email OR phone and phone is available, prefer phone.
- Avoid repeating the same failing action from RECENT_ACTIONS_JSON.
- For sliders and carousels, use action=swipe with direction=left or direction=right.
  If the slider handle/drag start is visible, include x/y for the start point.
- Use "done" only when goal is reached.
- Use "fail" only if blocked and no safe action exists.
"""
        response_text = await self._call_vision(prompt, image_b64)
        data = self._extract_json_from_text(response_text)
        if not data:
            return UIActionPlan(action="wait", wait_seconds=1.5, reason="parse_error")
        try:
            return UIActionPlan(
                action=str(data.get("action", "wait")).strip().lower(),
                target=str(data.get("target", "") or ""),
                text_value_key=str(data.get("text_value_key", "") or ""),
                text=str(data.get("text", "") or ""),
                x=int(data.get("x", 0) or 0),
                y=int(data.get("y", 0) or 0),
                direction=str(data.get("direction", "") or "").strip().lower(),
                key=str(data.get("key", "") or "").strip().lower(),
                wait_seconds=float(data.get("wait_seconds", 1.0) or 1.0),
                reason=str(data.get("reason", "") or ""),
            )
        except Exception:
            return UIActionPlan(action="wait", wait_seconds=1.5, reason="bad_plan_shape")

    async def find_element(
        self,
        screenshot_bytes: bytes,
        element_description: str,
    ) -> Optional[UIElement]:
        """
        Найти ОДИН конкретный элемент на экране по описанию.
        Возвращает UIElement или None.
        """
        # Fallback: no screenshot
        if not screenshot_bytes or len(screenshot_bytes) < 100:
            logger.warning(f"find_element: no screenshot — cannot find '{element_description}'")
            return None

        image_b64, img_w, img_h, coordinate_note = self._prepare_coordinate_vision_image(screenshot_bytes)

        prompt = f"""Find this element on the Android screenshot: "{element_description}"

SCREEN RESOLUTION: {img_w}x{img_h}
COORDINATE_OVERLAY: {coordinate_note or 'none'}

Return ONLY valid JSON (no extra text):
{{
  "found": true,
  "name": "element description",
  "x": {img_w // 2},
  "y": {img_h // 2},
  "width": 200,
  "height": 60,
  "element_type": "button",
  "text": "visible text",
  "confidence": 0.95
}}

If element is NOT found, return:
{{"found": false}}

RULES:
- x, y = CENTER of element in pixels
- Use the coordinate ruler labels on the image edges to estimate precise x/y
- For icons/buttons, return the center of the visible icon/button, not nearby decoration
- Be precise with coordinates within {img_w}x{img_h}
- confidence: how sure you are (0.0 to 1.0)"""

        response_text = await self._call_vision(prompt, image_b64)
        data = self._extract_json_from_text(response_text)

        if not data or not data.get("found"):
            logger.debug(f"Element not found: '{element_description}'")
            return None

        try:
            element = UIElement(
                name=data.get("name", element_description),
                x=int(data.get("x", 0)),
                y=int(data.get("y", 0)),
                width=int(data.get("width", 50)),
                height=int(data.get("height", 50)),
                element_type=data.get("element_type", "unknown"),
                text=data.get("text"),
                confidence=float(data.get("confidence", 0.5)),
            )
            logger.debug(
                f"Found '{element_description}' at ({element.x}, {element.y}) "
                f"conf={element.confidence:.2f}"
            )
            return element
        except (ValueError, TypeError) as e:
            logger.warning(f"Bad element data: {data}, error: {e}")
            return None

    async def read_text(self, screenshot_bytes: bytes) -> str:
        """OCR — прочитать весь текст со скриншота."""
        if not screenshot_bytes or len(screenshot_bytes) < 100:
            logger.warning("read_text: no screenshot — returning empty string")
            return ""
        image_b64 = self._encode_image(screenshot_bytes)

        prompt = """Read ALL visible text on this Android screenshot.
Return the text as-is, preserving layout where possible.
Return ONLY the text, nothing else."""

        return await self._call_vision(prompt, image_b64)

    async def detect_registration_stage(self, screenshot_bytes: bytes) -> str:
        """
        Определить текущую стадию регистрации Google-аккаунта.
        Возвращает: name | birthday | email | password | phone_input | phone_code |
                    terms | extras | done | unknown
        """
        # Fallback: if no screenshot, return "unknown" (let page_source-based logic handle it)
        if not screenshot_bytes or len(screenshot_bytes) < 100:
            logger.warning("detect_registration_stage: no screenshot — returning 'unknown'")
            return "unknown"

        image_b64 = self._encode_image(screenshot_bytes)
        prompt = """Analyze this Android screenshot of Google account registration.

Identify the CURRENT STAGE and return EXACTLY ONE of these values:
- name        : First name / Last name form fields visible
- birthday    : Month / Day / Year / Gender fields visible
- email       : Gmail username or email address input visible
- password    : Create password / Confirm password fields visible
- phone_input : Phone number input field (for entering YOUR phone number)
- phone_code  : 6-digit verification code input field (SMS code entry)
- terms       : Privacy Policy / Terms of Service / "I agree" / "Accept" screen
- extras      : Optional screens with Skip/Not now/Later buttons (backup phone, recovery email, etc.)
- done        : Registration FULLY COMPLETE — new Google account confirmation shown, OR Accounts list with new email visible, OR home/Play Store with no further setup
- settings    : Android Settings main screen (NOT account confirmation — general settings menu)
- unknown     : None of the above or unclear

Return ONLY the stage name (one word), nothing else."""
        result = await self._call_vision(prompt, image_b64)
        stage = result.strip().lower().replace('"', "").replace("'", "").split()[0] if result.strip() else "unknown"
        valid = {"name", "birthday", "email", "password", "phone_input", "phone_code", "terms", "extras", "done", "settings", "unknown"}
        if stage not in valid:
            for s in valid:
                if s in stage:
                    return s
            return "unknown"
        # "settings" = general Android Settings, not registration complete
        if stage == "settings":
            return "settings"
        return stage

    async def get_screen_state(self, screenshot_bytes: bytes) -> str:
        """
        Быстрое определение текущего экрана (без поиска элементов).
        Возвращает короткий ID экрана.
        """
        # Fallback: if no screenshot, return "unknown"
        if not screenshot_bytes or len(screenshot_bytes) < 100:
            logger.warning("get_screen_state: no screenshot — returning 'unknown'")
            return "unknown"

        image_b64 = self._encode_image(screenshot_bytes)

        prompt = """What screen is shown on this Android screenshot?
Return ONLY ONE of these values (nothing else):
- home_screen
- lock_screen
- settings
- google_login_email
- google_login_password
- google_login_2fa
- google_login_terms
- google_account_done
- google_pay_main
- google_pay_add_card
- google_pay_card_form
- play_store_app_page
- play_store_installing
- play_store_installed
- clash_royale_loading
- clash_royale_tutorial
- clash_royale_main_menu
- clash_royale_shop
- google_play_purchase_dialog
- google_play_password
- purchase_complete
- popup_dialog
- unknown

Return ONLY the value, no quotes, no explanation."""

        result = await self._call_vision(prompt, image_b64)
        return result.strip().lower().replace('"', "").replace("'", "")

    async def check_api(self) -> bool:
        """Проверка работоспособности OpenRouter API."""
        if not str(self.api_key or "").strip():
            logger.warning("OpenRouter API: OPENROUTER_API_KEY не задан")
            return False
        try:
            resp = await self.client.get(
                f"{config.OPENROUTER_BASE_URL}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if resp.status_code == 200:
                logger.success("OpenRouter API: OK")
                return True
            else:
                logger.error(f"OpenRouter API: HTTP {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"OpenRouter API: {e}")
            return False
