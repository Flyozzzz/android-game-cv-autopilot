# Local-First Perception Roadmap

This file tracks the implementation status of the local-first perception
roadmap. Each item must include real code and tests before it is marked done.

## Rollout Rules

- Keep `llm_first` behavior available for compatibility, but default runtime
  configuration should start in `local_first`.
- Use `shadow` mode to compare local perception against current behavior before
  letting local providers drive actions.
- Do not add empty provider shells as completed work.
- Every completed roadmap item must list its tests.

## Status

| ID | Item | Status | Implemented files | Tests |
| --- | --- | --- | --- | --- |
| PR 0 | Config / feature flags | Done | `config.py`, `.env.example` | `tests/test_config_feature_flags.py` |
| PR 1 | Metrics + trace schema | Done | `core/metrics.py`, `core/action_engine.py`, `core/cv_engine.py`, `scenarios/fast_runner_gameplay.py` | `tests/test_metrics.py`, `tests/test_fast_runner_gameplay.py` |
| PR 2 | InputScheduler + cooldowns | Done | `core/input_scheduler.py`, `core/action_engine.py`, `scenarios/fast_runner_gameplay.py` | `tests/test_input_scheduler.py`, `tests/test_fast_runner.py`, `tests/test_fast_runner_gameplay.py` |
| PR 3 | FrameSource + replay/scrcpy/minicap | Done | `core/frame_source.py`, `core/reaction_benchmark.py`, `scripts/reaction_benchmark.py` | `tests/test_frame_source_replay.py`, `tests/test_setup_doctor.py` |
| PR 4 | Profile zones + ROISelector | Done | `core/game_profiles.py`, `core/perception/roi.py` | `tests/test_game_profiles.py`, `tests/test_roi_selector.py` |
| PR 5 | ScreenStability | Done | `core/perception/screen_stability.py` | `tests/test_screen_stability.py` |
| PR 6 | Element model + finder | Done | `core/perception/element.py`, `core/perception/fusion.py`, `core/perception/finder.py`, `core/perception/defaults.py`, `core/perception/providers/base.py` | `tests/test_element_fusion.py`, `tests/test_element_finder_contract.py`, `tests/test_default_perception_factory.py`, `tests/test_cv_autopilot.py` |
| PR 7 | TemplateRegistry + TemplateProvider | Done | `core/perception/template_registry.py`, `core/perception/providers/template_provider.py`, `assets/templates/README.md` | `tests/test_template_provider.py` |
| PR 8 | UIAutomatorProvider | Done | `core/perception/providers/uiautomator_provider.py` | `tests/test_uiautomator_provider.py` |
| PR 9 | ScreenStateCache | Done | `core/perception/state_cache.py` | `tests/test_screen_state_cache.py` |
| PR 10 | LLMProvider fallback | Done | `core/perception/providers/llm_provider.py` | `tests/test_llm_provider.py` |
| PR 11a | Dashboard inspector read-only | Done | `dashboard/api_vision.py`, `dashboard/server.py`, `dashboard/static/index.html`, `dashboard/static/vision_inspector.js`, `dashboard/static/vision_overlay.css` | `tests/test_dashboard_vision_inspector.py`, `tests/test_dashboard_static_ui.py` |
| PR 11b | Dashboard inspector editing | Done | `dashboard/api_vision.py`, `dashboard/server.py`, `dashboard/static/index.html`, `dashboard/static/vision_inspector.js`, `dashboard/static/vision_overlay.css` | `tests/test_dashboard_vision_editing.py`, `tests/test_dashboard_static_ui.py` |
| PR 12 | Fast runner v2 | Done | `core/gameplay/base_plugin.py`, `core/gameplay/runner_plugin.py`, `scenarios/fast_runner_gameplay.py` | `tests/test_runner_plugin.py`, `tests/test_fast_runner.py`, `tests/test_fast_runner_gameplay.py` |
| PR 13 | Match-3 v2 | Done | `core/match3_solver.py`, `scenarios/match3_gameplay.py` | `tests/test_match3_solver.py`, `tests/test_match3_scoring.py`, `tests/test_match3_gameplay.py` |
| PR 14 | Optional ONNX detector | Done | `core/perception/providers/detector_provider.py`, `config.py`, `.env.example` | `tests/test_detector_provider.py`, `tests/test_config_feature_flags.py` |

## Acceptance Criteria

- Fast gameplay does not call Vision LLM.
- Fast gestures do not pay the default 0.3 second action pause.
- Menu/tutorial perception tries local providers before LLM when enabled.
- Repeated screens reuse cached perception before providers/LLM.
- Replay-based tests run without a connected Android device.
- ADB PNG, ADB raw, replay, scrcpy one-shot, scrcpy raw stream, screenrecord, and minicap frame-source
  selections have real backends and explicit runtime prerequisite errors.
- Dashboard overlay shows ROI, boxes, confidence, source, latency, and whether
  LLM was called.

## Completed Implementation Notes

### PR 0: Config / Feature Flags

- Added rollout flags for perception mode, frame source, action mode, template
  provider, UIAutomator provider, and LLM fallback.
- Invalid enum values fall back to safe defaults.
- `.env.example` documents the rollout flags.

### PR 1: Metrics + Trace Schema

- Added `MetricsCollector`, `TraceEvent`, global metrics helpers, and run ID
  helper.
- `ActionEngine.screenshot()` records `capture_ms`.
- `ActionEngine.tap()` and `ActionEngine.swipe()` record `action_ms`.
- `CVEngine._call_vision()` records `provider_llm_ms` and provider call count.
- Fast runner records `loop_total_ms` and `fps`.

### PR 2: InputScheduler + Cooldowns

- Added mode-aware `tap`, `swipe`, and `batch` execution.
- `menu` mode keeps safe pauses; `fast` mode uses no pause by default.
- Added cooldowns for lane changes, jumps, ducks, and confirm taps.
- Fast runner now uses the scheduler for runner gestures.

### PR 3: FrameSource + Replay

- Added `Frame`, `FrameSource`, `AdbScreencapSource`,
  `AdbRawFrameSource`, `AdbScreenrecordFrameSource`, `ReplayFrameSource`,
  `ScrcpyFrameSource`, `ScrcpyRawStreamFrameSource`, and `MinicapFrameSource`.
- Replay source reads PNG frames from disk, advances deterministically, and can
  repeat or hold the final frame.
- ADB source can wrap an existing action object's `screenshot()` method.
- ADB raw source uses `adb exec-out screencap` without `-p`, parses Android
  raw framebuffer headers, and lets local providers consume RGB bytes without a
  PNG roundtrip.
- Screenrecord source starts an H.264 stream and attempts local ffmpeg decoding;
  this is real code, but device support must be verified because some Android
  builds buffer screenrecord output until the stream closes.
- Scrcpy one-shot source invokes host `scrcpy` and `ffmpeg` to produce a PNG
  frame.
- Scrcpy raw stream source starts `scrcpy-server`, forwards
  `localabstract:scrcpy`, reads raw H.264, and decodes through persistent host
  `ffmpeg`; this is the validated realtime path for USB device `47d33e1c`.
- Minicap source forwards the minicap localabstract socket and decodes JPEG
  frames from the minicap banner/frame-size protocol.

### PR 4: Profile Zones + ROISelector

- Added percent-based `screen_zones` to game profiles.
- Built-in profiles now include common zones, runner lanes for Subway Surfers,
  and match-3 board bounds for Candy Crush.
- Added ROI validation and conversion from normalized coordinates to pixels.

### PR 5: ScreenStability

- Added `ScreenStabilityDetector` for low-resolution frame diffing.
- Added ROI-aware stability checks for popups, boards, and transition-sensitive
  regions.
- Added `wait_until_stable()` for async loops that should avoid acting during
  loading or animation transitions.

### PR 6: Element Model + Finder Skeleton

- Added `ElementCandidate` as the shared provider result model.
- Added provider context/contract for local and fallback providers.
- Added `FusionEngine` scoring for confidence, ROI, text match, source priority,
  recency, and stale-frame penalty.
- Added `ElementFinder` rollout behavior for `llm_first`, `shadow`,
  `local_first`, and `local_only`.
- Added default provider wiring for CVAutopilot so menu/tutorial target
  resolution uses UIAutomator/template/detector before LLM according to flags.
- Added cache lookup before provider execution.

### PR 7: TemplateRegistry + TemplateProvider

- Added template specs with paths, thresholds, scales, ROI labels, tap offsets,
  negative templates, and search step.
- Added registry loading from mappings or JSON files.
- Added template matching provider with optional OpenCV path and a PIL fallback
  for baseline installs/tests.
- Added ROI-limited matching, scaled templates, and negative-template
  suppression.

### PR 8: UIAutomatorProvider

- Added a provider that wraps the existing action `get_visible_texts()` contract.
- Supports tuple and dict visible-text rows.
- Filters by goal text and ROI before emitting element candidates.
- Produces stable native-UI candidates for system dialogs, Play Store screens,
  settings, and permission prompts when UIAutomator text is available.

### PR 9: ScreenStateCache

- Added average-hash screen state cache with a brightness prefix so uniform
  screens do not collapse to the same hash.
- Cache entries store screen ID, elements, last action, last seen timestamp,
  resolution, profile ID, and screen hash.
- Added ROI hashing for repeated popups/boards where outside-screen motion
  should not invalidate the state.
- Added max-entry eviction.
- `ElementFinder` uses cache hits before providers/LLM and writes candidates
  back after provider/LLM resolution.

### PR 10: LLMProvider Fallback

- Added an adapter that turns `CVEngine.find_element()` into an
  `ElementProvider`.
- Converts current `UIElement` output into `ElementCandidate`.
- Supports ROI filtering so fallback results still respect local search bounds.
- Returns empty results when no PNG or no LLM element is available.

### PR 11a: Dashboard Inspector Read-Only

- Added `/api/vision/inspector` payload for latest metrics, trace candidates,
  ROI, selected candidate, provider list, LLM call flag, and screenshot URL.
- Added a read-only Vision Inspector panel to the dashboard.
- Added overlay JS/CSS for drawing ROI and candidate boxes over the current
  device screenshot.
- Editing tools remain intentionally out of scope for PR 11a.

### PR 11b: Dashboard Inspector Editing

- Added backend helpers/endpoints for saving selected screenshot crops as
  templates, creating ROI zones in profiles, and exporting label JSON.
- Template saving writes cropped PNGs under `assets/templates` and updates
  `assets/templates/registry.json`.
- ROI creation updates custom profile JSON with normalized coordinates.
- Inspector UI now exposes Save Template, Create ROI From Selected, and Export
  Label actions.
- Inspector overlay also supports manual drag-to-draw regions. The drawn box is
  used for template/ROI saving before falling back to the selected candidate.
- Inspector save actions display the saved artifact response. ROI saves expose a
  shortcut to open the changed custom profile JSON in the dashboard Project
  editor.
- Inspector exposes a template library backed by `assets/templates/registry.json`
  so saved templates can be listed and loaded back into the form.

### PR 12: Fast Runner v2

- Added gameplay plugin result model and a stateful runner plugin.
- Runner plugin tracks state, lane score velocity, danger, frame skipping, and
  cooldown keys for emitted gestures.
- Fast runner scenario now uses `RunnerPlugin` plus `InputScheduler` instead of
  calling the detector and raw action directly.

### PR 13: Match-3 v2

- Added `ScoredSwap`, `find_all_swaps()`, and `score_swap()`.
- Preserved the existing `find_best_swap()` API while changing it to return the
  highest-scoring move instead of the first valid move.
- Scoring now accounts for match length, multi-match moves, target cells,
  blocked cells, and unknown-cell penalties.
- Match-3 gameplay now waits for board stability before each move and skips the
  swap when cascades/animations do not settle before timeout.

### PR 14: Optional ONNX Detector

- Added `DetectorProvider` with injected detector support for tests/local
  custom detectors and optional ONNX Runtime loading when a model path exists.
- Added threshold and ROI filtering.
- Added config flags for enabling detector provider and model path/threshold.
- Missing ONNX runtime or model path is non-fatal and returns no candidates.

## Verification Log

- `python3 -m pytest tests/test_config_feature_flags.py tests/test_metrics.py tests/test_input_scheduler.py tests/test_frame_source_replay.py tests/test_fast_runner.py tests/test_fast_runner_gameplay.py tests/test_default_perception_factory.py -q`
  - Result: passed
- `python3 -m pytest tests/test_cv_autopilot.py tests/test_dashboard_cv_bridge.py tests/test_local_appium_action_engine.py tests/test_match3_solver.py tests/test_game_profiles.py tests/test_dashboard_server.py -q`
  - Result: `48 passed`
- `python3 -m pytest tests/test_game_profiles.py tests/test_roi_selector.py -q`
  - Result: `13 passed`
- `python3 -m pytest tests/test_screen_stability.py -q`
  - Result: `4 passed`
- `python3 -m pytest tests/test_element_fusion.py tests/test_element_finder_contract.py -q`
  - Result: `7 passed`
- `python3 -m pytest tests/test_template_provider.py -q`
  - Result: `5 passed`
- `python3 -m pytest tests/test_uiautomator_provider.py -q`
  - Result: `5 passed`
- `python3 -m pytest tests/test_screen_state_cache.py -q`
  - Result: `5 passed`
- `python3 -m pytest tests/test_llm_provider.py -q`
  - Result: `3 passed`
- `python3 -m pytest tests/test_dashboard_vision_inspector.py tests/test_dashboard_static_ui.py -q`
  - Result: `6 passed`
- `python3 -m pytest tests/test_dashboard_vision_editing.py tests/test_dashboard_vision_inspector.py tests/test_dashboard_static_ui.py tests/test_dashboard_server.py -q`
  - Result: `27 passed`
- `python3 -m pytest tests/test_runner_plugin.py tests/test_fast_runner.py -q`
  - Result: `8 passed`
- `python3 -m pytest tests/test_match3_gameplay.py tests/test_match3_solver.py tests/test_match3_scoring.py -q`
  - Result: `8 passed`
- `python3 -m pytest tests/test_detector_provider.py tests/test_config_feature_flags.py -q`
  - Result: `8 passed`
- `python3 -m compileall -q core scenarios tests config.py`
  - Result: passed
- `python3 -m pytest -q`
  - Result: `378 passed, 3 skipped` without `OPENROUTER_API_KEY`; two live ADB
    smoke cases skipped because the connected screen was locked/too flat for
    template matching.
- Vision planner hardening:
  - CV action JSON is schema-validated, normalized through an action whitelist,
    coordinate-checked against the current frame, and optionally repaired once
    via `CV_JSON_REPAIR_ATTEMPTS`.
  - Invalid plans produce a safe wait result and trace payloads are redacted
    before persistence.
- Clean requirements venv
  - Command: create a temporary venv, `pip install -r requirements.txt`,
    `pip check`, import `PIL`, `numpy`, `cv2`, `httpx`, and `appium`.
  - Result: passed
- Live local-first ADB smoke on `emulator-5554`
  - Command: `LOCAL_DEVICE=emulator-5554 python3 -m pytest tests/test_live_adb_smoke.py -q`
  - Result: `3 passed`; captured a real frame, matched a real crop through
    `TemplateProvider`, ran `ElementFinder` in `local_only`, and did not call
    LLM.
- Live OpenRouter CV+Builder smoke on USB device `47d33e1c`
  - Command: `OPENROUTER_API_KEY=... CV_MODELS=xiaomi/mimo-v2.5 LOCAL_DEVICE=47d33e1c python3 -m pytest tests/test_live_openrouter_smoke.py -q`
  - Result: passed; planned one real Vision action, launched
    `com.android.settings`, executed four real ADB exploration gestures, saved
    five replay frames, recorded four ScreenGraph transitions, and generated an
    Autopilot Builder bundle from the live run.
- `python3 -m pytest tests/test_dashboard_mcp_server.py tests/test_cv_prompt_templates.py tests/test_dashboard_cv_bridge.py tests/test_game_profiles.py --cov=dashboard.mcp_server --cov=core.cv_prompt_templates --cov=dashboard.cv_bridge --cov=core.game_profiles --cov-report=term-missing --cov-fail-under=100 -q`
  - Result: `32 passed`, `100.00%` deterministic constructor/MCP/CV coverage
- `python3 -m pytest tests/test_config_feature_flags.py tests/test_metrics.py tests/test_input_scheduler.py tests/test_frame_source_replay.py tests/test_default_perception_factory.py tests/test_roi_selector.py tests/test_screen_stability.py tests/test_element_fusion.py tests/test_element_finder_contract.py tests/test_template_provider.py tests/test_uiautomator_provider.py tests/test_screen_state_cache.py tests/test_llm_provider.py tests/test_dashboard_vision_inspector.py tests/test_dashboard_vision_editing.py tests/test_runner_plugin.py tests/test_fast_runner_gameplay.py tests/test_match3_gameplay.py tests/test_match3_scoring.py tests/test_detector_provider.py tests/test_cv_autopilot.py --cov=core.metrics --cov=core.input_scheduler --cov=core.frame_source --cov=core.perception.defaults --cov=core.perception.roi --cov=core.perception.screen_stability --cov=core.perception.element --cov=core.perception.fusion --cov=core.perception.finder --cov=core.perception.template_registry --cov=core.perception.providers.template_provider --cov=core.perception.providers.uiautomator_provider --cov=core.perception.state_cache --cov=core.perception.providers.llm_provider --cov=dashboard.api_vision --cov=core.gameplay.base_plugin --cov=core.gameplay.runner_plugin --cov=core.perception.providers.detector_provider --cov=scenarios.fast_runner_gameplay --cov=scenarios.match3_gameplay --cov=core.cv_autopilot --cov-report=term-missing --cov-fail-under=100 -q`
  - Result: `143 passed`, `100.00%` coverage for the local-first modules and CVAutopilot integration
- Real Android game smoke, device `47d33e1c`, package `com.kiloo.subwaysurf`
  - Result: launched Subway Surfers, captured real 1080x2400 frame through `AdbScreencapSource`, processed it through `ScreenStabilityDetector` and `RunnerPlugin`, no LLM call used.
  - Latest observed: `png_bytes=992727`, `capture_latency_ms=741.568`, `stability_reason=warming_up`, `runner_state=JUMPING`, `runner_gesture=up`, `lane_scores=(71.59, 60.81, 69.25)`.
- Real capture benchmarks on 2026-04-28:
  - `python3 scripts/reaction_benchmark.py --serial emulator-5554 --samples 5 --source adb`
    -> `adb_screencap avg_ms=126.539`, status `usable`.
  - `python3 scripts/reaction_benchmark.py --serial emulator-5554 --samples 5 --source adb_raw`
    -> `adb_raw_screencap avg_ms=137.974`, status `usable`.
  - `python3 scripts/reaction_benchmark.py --serial 47d33e1c --samples 3 --source adb`
    -> `adb_screencap avg_ms=617.144`, status `slow`.
  - `python3 scripts/reaction_benchmark.py --serial 47d33e1c --samples 5 --source adb_raw`
    -> latest `adb_raw_screencap avg_ms=841.762`, status `slow`.
  - `python3 scripts/reaction_benchmark.py --serial 47d33e1c --samples 5 --source scrcpy_raw --nudge-key 82`
    -> `scrcpy_raw_stream avg_ms=28.235`, `p95_ms=39.183`, status `fast`.
  - `ScrcpyFrameSource` with host `scrcpy 3.3.4` produced a real 1080x2400
    frame, but the one-shot record/extract path measured about `4968 ms`; it is
    not a realtime loop.
  - `AdbScreenrecordFrameSource` did not produce a live decoded frame on
    `47d33e1c` within 10 seconds because this device buffers screenrecord
    output until close. Do not use it for fast gameplay on this phone.
- Benchmark matrix on `47d33e1c`:
  - `python3 scripts/benchmark_matrix.py --serial 47d33e1c --profile subway-surfers --runs 1 --no-explore`
  - Result: 1 passed, 0 failed for launch+capture on Android 13, 1080x2400.
    Release evidence should use `--runs 20` and keep the generated JSON report.
- Profile live validation on `47d33e1c`:
  - `python3 scripts/profile_live_validator.py --serial 47d33e1c --profile talking-tom --profile subway-surfers --profile candy-crush --profile brawl-stars --output reports/profile_validation --promote validated`
  - Result: 4 passed, 0 failed. Each run launched the app, measured `adb` and
    `adb_raw` capture, executed four safe exploration gestures, saved five
    frames, and wrote a ScreenGraph with four transitions.
