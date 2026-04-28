"""Optional local detector provider with injected or ONNX Runtime backends."""
from __future__ import annotations

import inspect
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from PIL import Image

import config
from core.perception.element import ElementCandidate
from core.perception.providers.base import ProviderContext
from core.perception.roi import PixelBox


DetectorCallable = Callable[[ProviderContext], Any]


class DetectorProvider:
    name = "detector"

    def __init__(
        self,
        *,
        detector: DetectorCallable | None = None,
        model_path: str | Path | None = None,
        labels: list[str] | None = None,
        threshold: float | None = None,
    ):
        self.detector = detector
        self.model_path = str(model_path or getattr(config, "DETECTOR_MODEL_PATH", "") or "")
        self.labels = labels or []
        self.threshold = float(
            threshold
            if threshold is not None
            else getattr(config, "DETECTOR_CONFIDENCE_THRESHOLD", 0.5)
        )
        self._session: Any | None = None
        self._onnx_error: str = ""

    async def find(self, context: ProviderContext) -> list[ElementCandidate]:
        detections = await self._raw_detections(context)
        candidates = [self._candidate_from_detection(item, context) for item in detections]
        return [
            candidate
            for candidate in candidates
            if candidate is not None
            and candidate.confidence >= self.threshold
            and (context.roi is None or _point_in_roi(candidate.center, context.roi))
        ]

    async def _raw_detections(self, context: ProviderContext) -> list[Any]:
        if self.detector is not None:
            result = self.detector(context)
            if inspect.isawaitable(result):
                result = await result
            return list(result or [])
        if not self.model_path:
            return []
        session = self._onnx_session()
        if session is None or not context.frame.png_bytes:
            return []
        return self._run_onnx(session, context)

    def _onnx_session(self) -> Any | None:
        if self._session is not None:
            return self._session
        path = Path(self.model_path)
        if not path.exists():
            self._onnx_error = "model_not_found"
            return None
        try:
            import onnxruntime as ort  # type: ignore
        except Exception as exc:
            self._onnx_error = f"onnxruntime_unavailable:{exc}"
            return None
        self._session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        return self._session

    def _run_onnx(self, session: Any, context: ProviderContext) -> list[dict[str, Any]]:
        try:
            import numpy as np  # type: ignore
        except Exception:
            self._onnx_error = "numpy_unavailable"
            return []
        input_meta = session.get_inputs()[0]
        input_name = input_meta.name
        height, width = _input_hw(input_meta.shape)
        image = Image.open(BytesIO(context.frame.png_bytes)).convert("RGB").resize((width, height))
        arr = np.asarray(image, dtype=np.float32) / 255.0
        arr = np.transpose(arr, (2, 0, 1))[None, :, :, :]
        outputs = session.run(None, {input_name: arr})
        return _parse_onnx_output(outputs[0], context.frame.width, context.frame.height, self.labels)

    def _candidate_from_detection(
        self,
        detection: Any,
        context: ProviderContext,
    ) -> ElementCandidate | None:
        parsed = _parse_detection(detection, labels=self.labels)
        if parsed is None:
            return None
        name, bbox, confidence = parsed
        return ElementCandidate.from_bbox(
            name=name,
            bbox=bbox,
            confidence=confidence,
            source=self.name,
            text=name,
            screen_id=context.screen_id or None,
        )


def _parse_detection(
    detection: Any,
    *,
    labels: list[str],
) -> tuple[str, tuple[int, int, int, int], float] | None:
    if isinstance(detection, dict):
        raw_bbox = detection.get("bbox") or detection.get("box")
        confidence = detection.get("confidence", detection.get("score", 0.0))
        name = str(detection.get("name") or detection.get("label") or "object")
    elif isinstance(detection, (list, tuple)) and len(detection) >= 5:
        raw_bbox = detection[:4]
        confidence = detection[4]
        class_id = int(detection[5]) if len(detection) >= 6 else -1
        name = labels[class_id] if 0 <= class_id < len(labels) else "object"
    else:
        return None
    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
        return None
    x1, y1, x2, y2 = (int(round(float(part))) for part in raw_bbox)
    if x2 <= x1 or y2 <= y1:
        return None
    return name, (x1, y1, x2, y2), max(0.0, min(1.0, float(confidence)))


def _parse_onnx_output(output: Any, frame_width: int, frame_height: int, labels: list[str]) -> list[dict[str, Any]]:
    try:
        import numpy as np  # type: ignore
    except Exception:
        return []
    arr = np.asarray(output)
    if arr.ndim == 3:
        arr = arr[0]
    if arr.ndim != 2 or arr.shape[1] < 5:
        return []
    detections: list[dict[str, Any]] = []
    for row in arr:
        x1, y1, x2, y2, score = (float(value) for value in row[:5])
        class_id = int(row[5]) if row.shape[0] >= 6 else -1
        if max(x1, y1, x2, y2) <= 1.0:
            x1, x2 = x1 * frame_width, x2 * frame_width
            y1, y2 = y1 * frame_height, y2 * frame_height
        detections.append({
            "bbox": [x1, y1, x2, y2],
            "confidence": score,
            "name": labels[class_id] if 0 <= class_id < len(labels) else "object",
        })
    return detections


def _input_hw(shape: Any) -> tuple[int, int]:
    try:
        height = int(shape[2]) if isinstance(shape[2], int) else 640
        width = int(shape[3]) if isinstance(shape[3], int) else 640
    except Exception:
        height = width = 640
    return height, width


def _point_in_roi(point: tuple[int, int], roi: PixelBox) -> bool:
    x, y = point
    x1, y1, x2, y2 = roi
    return x1 <= x <= x2 and y1 <= y <= y2
