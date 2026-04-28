# LLM Autopilot Builder Roadmap

Status: approved and implemented. Implementation ledger:
`docs/autopilot_builder_implementation_status.md`.

This document is the approved implementation plan for the next roadmap after
the completed local-first perception work. The goal is to add an autopilot
builder where an LLM creates, validates, saves, and repairs reusable autopilots,
while the runtime continues to use the fast local engine.

## Core Principle

Do not make the LLM play or operate every frame.

- LLM role: builder, screen analyst, profile/scenario generator, repair analyst.
- Local engine role: frame capture, stability, ROI, element finding, templates,
  UIAutomator, cache, policy checks, input scheduling, fast gameplay execution.
- Fast gameplay must stay `local_only`.
- Menu/tutorial/unknown screens can use `local_first` with LLM fallback when the
  safety policy allows it.

## Target Pipeline

```text
User Prompt
  -> Goal Parser
  -> Safety Policy Check
  -> App Resolver / App Manager
  -> ScreenGraph Init
  -> Explorer writes screens/transitions
  -> LLM Screen Analyst
  -> Profile Generator
  -> ROI Generator
  -> Template Auto-Miner
  -> Scenario Generator
  -> Replay / Live Test Runner
  -> Autopilot Bundle
  -> Runtime Local Engine
  -> Self-Healing when broken
```

Runtime pipeline for a completed autopilot:

```text
FrameSource.latest_frame()
  -> ScreenStability
  -> ScreenHasher / ScreenStateCache
  -> ROISelector
  -> ElementFinder
  -> Template/UIAutomator/OCR/Color/Detector providers
  -> LLM only when allowed and needed
  -> PolicyGuard
  -> InputScheduler
  -> ActionEngine
  -> Trace + Metrics
```

## Builder Modes

| Mode | Behavior |
| --- | --- |
| `create` | Build a new autopilot from a prompt. |
| `improve` | Improve an existing autopilot using reports, traces, and recordings. |
| `repair` | Diagnose a broken autopilot and generate a patch. |
| `validate` | Run replay/live validation without changing files. |
| `shadow` | Let the LLM propose analysis or patches without applying them. |

## Safety Boundaries

Allowed scope:

- QA automation.
- Onboarding and tutorial testing.
- UI testing and visual regression.
- Single-player/local gameplay helpers.
- Testing on owned test devices or emulators.

Forbidden or review-gated scope:

- Real purchases.
- Anti-cheat bypass or stealth automation.
- Unfair PvP/multiplayer automation.
- CAPTCHA bypass.
- Mass account registration.
- Use of real personal accounts without explicit user approval.
- Saving passwords, tokens, or account secrets into trace/report files.
- Downloading APKs from unknown websites.
- Any network download or install source must be allowlisted or user-provided.
- Installing apps with elevated permissions without review.

The product positioning is AI-powered QA and app automation builder, not
unfair game automation.

## Output Bundle Layout

```text
autopilots/
  <autopilot_id>/
    autopilot.json
    profile.json
    scenario.json
    screen_graph.json
    safety_policy.json
    templates/
    recordings/
      bootstrap_run.json
    replays/
      frames/
    reports/
      build_report.json
      test_report.json
    patches/
```

`autopilot.json` must reference the generated profile, scenario, graph, safety
policy, reports, and current version.

## Non-Negotiable Engineering Rules

- All generated JSON artifacts must be validated against explicit schemas before
  saving or execution: GoalSpec, SafetyPolicy, ScreenGraph, Profile, Scenario,
  Autopilot Bundle, Patch, Eval Report, and run reports.
- Generated artifacts must be written atomically: write a temporary file,
  validate it, then rename it over the previous artifact only after validation
  passes.
- Trace, reports, screenshot metadata, and LLM prompts/responses must pass
  through secret redaction before persistence.
- Secret redaction must cover emails, passwords, API tokens, phone numbers,
  account identifiers, payment screen text, and login dialog content where
  possible.
- Builder and runtime flows must enforce budgets:
  `max_build_steps`, `max_exploration_depth`, `max_actions_per_screen`,
  `max_llm_calls_per_build`, `max_llm_calls_per_screen`,
  `max_repair_attempts_per_run`, and `max_runtime_minutes`.
- Budget exhaustion must stop with a clear report instead of silently looping or
  escalating to more LLM calls.
- Fast gameplay remains `local_only`; builder/repair LLM calls are never allowed
  inside the active fast gameplay loop.

Implementation ownership:

- Schema validation starts in PR15 through `core/autobuilder/schemas.py` and is
  expanded by every artifact-producing PR.
- Secret redaction starts in PR16 through `core/autobuilder/redaction.py` and is
  required by traces, reports, screenshots metadata, and LLM prompt/response
  persistence.
- Budget parsing starts in PR15 through `core/autobuilder/budgets.py`; budgets
  are enforced by PR19 Explorer, PR20 LLM Screen Analyst, PR28 Self-Healing, and
  runtime validation paths.
- Atomic artifact writes start in PR25 through
  `core/autobuilder/artifact_store.py`; later patch/version/eval writes must use
  the same store instead of direct file replacement.

## Shared BuildContext

The builder should pass a narrow shared context instead of letting modules
directly import and mutate each other.

`BuildContext` is introduced with PR19 and then expanded as later PRs land:

```text
core/autobuilder/context.py
```

Suggested fields:

- `run_id`
- `goal_spec`
- `safety_policy`
- `app_info`
- `frame_source`
- `screen_graph`
- `profile`
- `artifact_paths`
- `metrics`
- `trace`

The context is an internal coordination model, not a dumping ground. Each module
still owns its own data structures and schema validation.
`BuildContext` must be passed explicitly, avoid hidden global state, and avoid
uncontrolled mutation. Modules should return updated artifacts/results instead
of mutating unrelated context fields.

## Roadmap Status

This roadmap depends on the completed local-first perception foundation tracked
in `docs/perception_roadmap.md`. PR15 starts after PR0-14 are implemented and
validated.

| ID | Item | Status |
| --- | --- | --- |
| PR 15 | GoalSpec / Task Parser | Implemented |
| PR 16 | SafetyPolicy Engine | Implemented |
| PR 17 | AppManager | Implemented |
| PR 18 | ScreenGraph | Implemented |
| PR 19 | Explorer + BuildContext | Implemented |
| PR 20 | LLM Screen Analyst | Implemented |
| PR 21 | Profile Generator | Implemented |
| PR 22 | ROI Generator | Implemented |
| PR 23 | Template Auto-Miner | Implemented |
| PR 24 | Scenario Generator | Implemented |
| PR 25 | Autopilot Bundle | Implemented |
| PR 26 | Replay Test Runner | Implemented |
| PR 27 | Live Validation Runner | Implemented |
| PR 28 | Self-Healing Engine | Implemented |
| PR 29 | Patch Review / Human Approval | Implemented |
| PR 30 | Builder Dashboard UI | Implemented |
| PR 31 | Autopilot Versioning | Implemented |
| PR 32 | Autopilot Eval Suite | Implemented |

## PR 15: GoalSpec / Task Parser

Files:

- `core/autobuilder/goal_spec.py`
- `core/autobuilder/task_parser.py`
- `core/autobuilder/budgets.py`
- `core/autobuilder/schemas.py`
- `tests/test_goal_spec.py`
- `tests/test_task_parser.py`
- `tests/test_autobuilder_budgets.py`
- `tests/test_autobuilder_schemas.py`

Goal:

Turn a user prompt into a structured goal specification.

Example output:

```json
{
  "app_name": "Subway Surfers",
  "goal": "Start a run and survive for 60 seconds",
  "mode": "create",
  "allowed_actions": ["install", "launch", "tap", "swipe", "wait", "analyze"],
  "forbidden_actions": ["purchase", "real_login", "subscribe", "bypass_anticheat"],
  "runtime_strategy": "runner",
  "max_build_steps": 100,
  "requires_human_review": true
}
```

Implementation requirements:

- Parse app name, goal, constraints, and builder mode.
- Infer app/game type and runtime strategy: `menu`, `runner`, `match3`,
  `generic_app`.
- Normalize allowed and forbidden actions.
- Parse build/runtime budget limits from prompt/defaults.
- Validate GoalSpec JSON against the explicit schema before persistence.
- Persist GoalSpec as JSON.

Definition of done:

- A prompt produces a deterministic GoalSpec usable by the rest of the builder.
- Tests cover safe prompts, risky prompts, game/app strategy inference, and
  explicit restrictions.
- Tests cover schema rejection and budget defaults/overrides.

## PR 16: SafetyPolicy Engine

Files:

- `core/autobuilder/safety_policy.py`
- `core/autobuilder/policy_guard.py`
- `core/autobuilder/redaction.py`
- `tests/test_autobuilder_safety_policy.py`
- `tests/test_autobuilder_redaction.py`

Goal:

Block unsafe builder and runtime actions before they can execute.

Rules:

- No real purchases.
- No real account login unless explicitly approved.
- No anti-cheat bypass or stealth automation.
- No mass registration.
- No unknown APK sources.
- No password/token persistence in traces.
- Risky patches require human review.
- Any network download or install source requires an allowlist entry or a
  user-provided local artifact.

Example result:

```json
{
  "allowed": false,
  "reason": "Real purchase action is forbidden",
  "required_review": true
}
```

Definition of done:

- Every builder action and generated scenario action passes through
  SafetyPolicy.
- Tests cover allow, block, review-required, and secret-redaction behavior.

## PR 17: AppManager

Files:

- `core/autobuilder/app_manager.py`
- `core/autobuilder/domain.py`
- `tests/test_app_manager.py`
- `tests/test_benchmark_matrix.py`

Goal:

Manage app lifecycle in a controlled way.

Functions:

- `install_apk()`
- `launch_app()`
- `stop_app()`
- `reset_app_data()`
- `check_installed()`
- `get_package_info()`
- `get_current_activity()`
- `resolve_launch_activity()`

Rules:

- Install only from user-provided APK, allowlist, already-installed app, or
  trusted internal catalog.
- Do not download APKs from arbitrary websites.
- Reset data only on a test device/emulator and only through policy approval.
- Launches resolve the package launcher activity and use `am start -n`; do not
  use `monkey -p` for Builder launches.
- ADB calls use bounded retry/backoff for common transport race conditions.

Definition of done:

- Builder can launch, stop, inspect, and optionally install/reset apps under
  policy control.
- MVP 1 implements `launch_app()`, `stop_app()`, `check_installed()`,
  `get_package_info()`, and `get_current_activity()`.
- `install_apk()` and `reset_app_data()` are present as policy-gated methods;
  they may remain disabled in MVP 1 unless the source/device policy explicitly
  allows them.
- Tests use fake action/ADB runners and verify blocked unsafe operations.
- Benchmark matrix records device/app validation outcomes across repeated runs.

## PR 18: ScreenGraph

Files:

- `core/autobuilder/screen_graph.py`
- `tests/test_screen_graph.py`

Goal:

Store the discovered screen map.

Example structure:

```json
{
  "screens": [
    {
      "screen_id": "main_menu",
      "hash": "abc123",
      "type": "menu",
      "texts": ["Play", "Settings"],
      "elements": ["play_button", "settings_button"],
      "safe_actions": ["tap_play"],
      "risky_actions": ["tap_shop"]
    }
  ],
  "transitions": [
    {
      "from": "main_menu",
      "action": "tap_play",
      "to": "gameplay_start"
    }
  ]
}
```

Definition of done:

- Each discovered screen has an ID, hash, type, texts, elements, and safe/risky
  actions.
- Transitions can be added, queried, serialized, and loaded.
- ScreenGraph JSON validates against the schema from
  `core/autobuilder/schemas.py`.

## PR 19: Explorer + BuildContext

Files:

- `core/autobuilder/explorer.py`
- `core/autobuilder/exploration_state.py`
- `core/autobuilder/context.py`
- `tests/test_explorer.py`
- `tests/test_build_context.py`

Goal:

Explore an app safely and write screens/transitions into ScreenGraph.

Explorer behavior:

- Launch app.
- Wait for screen stability.
- Capture frame/screenshot.
- Collect visible texts.
- Find safe buttons using local providers.
- Try safe actions only.
- Record transitions into ScreenGraph.
- Enforce exploration budgets from GoalSpec/BuildContext.

Example:

```text
screen_001 -> tap Continue -> screen_002
screen_002 -> tap Play -> screen_003
screen_003 -> swipe up -> gameplay_state
```

Definition of done:

- Explorer can traverse several safe screens and produce an exploration state
  backed by ScreenGraph.
- Tests cover stable screen waiting, provider use, transition recording, budget
  exhaustion, and policy-blocked actions.
- BuildContext carries the current run ID, GoalSpec, policy, app info, graph,
  metrics, and artifact paths without bypassing module ownership.

## PR 20: LLM Screen Analyst

Files:

- `core/autobuilder/screen_analyst.py`
- `tests/test_screen_analyst.py`

Goal:

Analyze unknown stable screens one time and return structured analysis.

Input:

- Screenshot.
- Visible texts.
- Current GoalSpec.
- SafetyPolicy.
- Known ScreenGraph.

Output:

```json
{
  "screen_type": "main_menu",
  "summary": "Main menu with Play button and shop button",
  "safe_elements": [
    {
      "name": "play_button",
      "description": "Green Play button in bottom center",
      "roi": "bottom_buttons",
      "recommended_action": "tap"
    }
  ],
  "risky_elements": [
    {
      "name": "shop_button",
      "reason": "May lead to purchase screen"
    }
  ],
  "next_best_goal": "tap_play_button"
}
```

Rules:

- The LLM returns analysis only.
- It does not directly execute actions.
- LLM output must be schema-validated before use.
- Invalid LLM output is discarded or retried only within the configured budget.
- Analysis is filtered by SafetyPolicy before use.

Definition of done:

- Unknown screens can be analyzed and saved into ScreenGraph/Profile data.
- Tests use deterministic fake LLM responses and cover safety filtering.
- Tests cover invalid structured output, schema rejection, and retry budget
  exhaustion.

## PR 21: Profile Generator

Files:

- `core/autobuilder/profile_generator.py`
- `tests/test_profile_generator.py`

Goal:

Generate a reusable app/game profile.

Profile fields:

- `app_name`
- `package`
- `strategy`
- `screen_zones`
- `blocker_words`
- `safe_words`
- `forbidden_words`
- `runtime_mode`
- `llm_policy`
- `provider_priority`

Example:

```json
{
  "app_name": "Subway Surfers",
  "package": "com.kiloo.subwaysurf",
  "strategy": "runner",
  "screen_zones": {
    "bottom_buttons": [0.05, 0.72, 0.95, 0.96],
    "popup_center": [0.15, 0.20, 0.85, 0.80],
    "runner_lanes": [0.10, 0.58, 0.90, 0.86]
  },
  "blocker_words": ["buy", "purchase", "subscribe", "shop", "купить", "оплатить"],
  "runtime": {
    "fast_gameplay": "local_only",
    "menu": "local_first"
  }
}
```

Definition of done:

- Exploration data and GoalSpec produce a valid `profile.json`.
- If PR22 ROI Generator is not available yet, Profile Generator creates basic
  strategy default zones:
  `runner` uses `runner_lanes`, `bottom_buttons`, and `popup_center`;
  `match3` uses `match3_board`, `bottom_buttons`, and `popup_center`;
  `generic_app` uses `dialog_actions`, `bottom_buttons`, and `main_canvas`.
- Tests cover runner, match-3, generic app, blocker words, runtime modes, and
  provider priorities.
- Tests cover default zone generation before the ROI Generator exists.

## PR 22: ROI Generator

Files:

- `core/autobuilder/roi_generator.py`
- `tests/test_roi_generator.py`

Goal:

Automatically suggest normalized screen zones.

Inputs:

- LLM screen analysis.
- Detected element boxes.
- Screen layout.
- Runtime strategy.
- Manual dashboard labels.

Common zones:

- `bottom_buttons`
- `top_currency`
- `popup_center`
- `runner_lanes`
- `match3_board`
- `dialog_actions`
- `main_canvas`

Definition of done:

- Builder creates percent-based ROI zones consumed by local providers.
- Tests cover clamping, merging, strategy defaults, and element-derived zones.

## PR 23: Template Auto-Miner

Files:

- `core/autobuilder/template_miner.py`
- `tests/test_template_miner.py`

Goal:

Save templates from high-confidence discovered elements.

Examples:

- Play button.
- Continue/Skip button.
- Close X.
- Runner obstacle.
- Match-3 item.

Template config:

```json
{
  "id": "play_button",
  "roi": "bottom_buttons",
  "threshold": 0.82,
  "scales": [0.75, 0.9, 1.0, 1.15, 1.3],
  "tap_offset": [0.5, 0.5],
  "source_screen_id": "main_menu"
}
```

Rules:

- Do not save random low-confidence crops.
- Save source screenshot metadata.
- Verify the template on replay frames before accepting it.

Definition of done:

- Builder can create `assets/templates/<app>/...` entries and confirm that each
  accepted template is found locally in replay tests.

## PR 24: Scenario Generator

Files:

- `core/autobuilder/scenario_generator.py`
- `tests/test_scenario_generator.py`

Goal:

Generate a reusable automation scenario.

Game example:

```json
{
  "name": "subway_surfers_autopilot",
  "steps": [
    {"type": "launch_app"},
    {"type": "wait_until_stable"},
    {"type": "tap_goal", "goal": "play_button"},
    {"type": "handle_optional_popup", "goal": "close_or_skip"},
    {"type": "enter_fast_gameplay", "plugin": "runner", "duration_sec": 60},
    {"type": "stop_and_report"}
  ]
}
```

Generic app example:

```json
{
  "name": "app_onboarding",
  "steps": [
    {"type": "launch_app"},
    {"type": "accept_permissions_if_safe"},
    {"type": "skip_intro_if_present"},
    {"type": "open_main_screen"},
    {"type": "verify_goal_reached"}
  ]
}
```

Definition of done:

- ScreenGraph and Profile produce a policy-checked `scenario.json`.
- Tests cover game, onboarding, optional popup handling, and forbidden action
  rejection.

## PR 25: Autopilot Bundle

Files:

- `core/autobuilder/bundle.py`
- `core/autobuilder/artifact_store.py`
- `tests/test_autopilot_bundle.py`
- `tests/test_artifact_store.py`

Goal:

Save and load a complete autopilot artifact.

Bundle contents:

- `autopilot.json`
- `profile.json`
- `scenario.json`
- `screen_graph.json`
- `safety_policy.json`
- `templates/`
- `recordings/`
- `reports/`
- `patches/`

Example `autopilot.json`:

```json
{
  "name": "subway_surfers_autopilot",
  "version": "0.1.0",
  "created_by": "llm_autopilot_builder",
  "app_name": "Subway Surfers",
  "strategy": "runner",
  "profile_path": "profile.json",
  "scenario_path": "scenario.json",
  "screen_graph_path": "screen_graph.json",
  "safety_policy_path": "safety_policy.json"
}
```

Definition of done:

- A generated autopilot can be saved, loaded, validated, and run again from disk.
- Bundle writes use `ArtifactStore` atomic write/validate/rename behavior.
- Tests prove failed validation does not replace the previous working bundle.

## PR 26: Replay Test Runner

Files:

- `core/autobuilder/replay_test_runner.py`
- `tests/test_replay_test_runner.py`

Goal:

Validate an autopilot without a phone using saved frames.

Checks:

- Templates are found on replay frames.
- ROI zones are valid.
- ElementFinder selects expected elements.
- Scenario steps match expected screens.
- No forbidden actions occur.
- LLM is not called in `local_only`.

Definition of done:

- Builder can produce a replay report for generated autopilots.
- Tests cover passing, failing, forbidden-action, and missing-template cases.

## PR 27: Live Validation Runner

Files:

- `core/autobuilder/live_validation.py`
- `tests/test_live_validation.py`

Goal:

Run the generated autopilot on a real test device or emulator and save a report.

Checks:

- App launches.
- First screens are recognized.
- Safe actions work.
- Fast gameplay does not call LLM.
- No forbidden actions are triggered.
- Final goal is reached or a clear failure report is saved.

Definition of done:

- Live validation produces a structured report with screenshots, actions,
  failures, metrics, and final status.
- Unit tests use fake device/action engines; real-device smoke is documented
  separately when available.

## PR 28: Self-Healing Engine

Files:

- `core/autobuilder/self_healing.py`
- `core/autobuilder/patches.py`
- `tests/test_self_healing.py`

Goal:

Generate and validate patches when an autopilot breaks.

Example failure:

```text
expected: continue_button
actual: no candidate found
screen: stable
local providers: failed
cache: failed
```

Repair flow:

1. Check builder/runtime mode.
2. Do not call LLM inside active fast gameplay.
3. For menu/tutorial, call LLM if policy allows.
4. Analyze the new screen.
5. Generate patch.
6. Validate patch in shadow/replay.
7. Apply only safe patches; save risky patches as pending review.
8. Continue runtime if safe.

Patch types:

- `add_template`
- `update_template_threshold`
- `add_roi`
- `update_roi`
- `add_screen`
- `add_transition`
- `update_scenario_step`
- `mark_risky_element`
- `add_blocker_word`

Limits:

- `max_repair_attempts_per_run`
- `max_llm_calls_per_screen`
- `max_unknown_screens`
- `max_patch_size`

Before PR29:

- Self-Healing may generate, validate, and save patches.
- Risky patches must be saved as pending and referenced in the repair report.
- Risky patches must not be auto-applied before the Patch Review / Human
  Approval layer exists.
- Risky categories include login, purchase, permissions, install source,
  account/data mutation, and templates mined from sensitive screens.

Definition of done:

- Safe broken menu/tutorial screens can produce replay-validated patches.
- Risky or repeated failures stop with a clear report and pending patch when
  applicable.

## PR 29: Patch Review / Human Approval

Files:

- `core/autobuilder/review.py`
- `dashboard/api_builder_review.py`
- `tests/test_patch_review.py`

Goal:

Prevent risky changes from applying automatically.

Human approval required for:

- New install source.
- Login-related screen.
- Purchase-related screen.
- Permission escalation.
- Scenario action that affects account/data.
- Template mined from sensitive screen.

Definition of done:

- Risky patches are persisted as pending review and cannot be applied until
  approved.
- Tests cover approve, reject, expire, and audit-log behavior.

## PR 30: Builder Dashboard UI

Files:

- `dashboard/api_builder.py`
- `dashboard/static/autopilot_builder.js`
- `dashboard/static/autopilot_builder.css`
- Dashboard tests.

Goal:

Let a user create, validate, and review autopilots from the dashboard.

UI features:

- Prompt input.
- App source selection: installed package, APK, allowlist, internal catalog.
- Builder mode selector: create, improve, repair, validate, shadow.
- Forbidden action settings.
- Build progress.
- Current screen.
- Detected elements.
- Screen graph.
- Generated profile.
- Generated scenario.
- Templates and ROI zones.
- Test report.
- Patch review.
- Download generated autopilot bundle.
- Run generated autopilot only after validation and policy checks pass.

Build progress labels:

1. Parsing goal.
2. Safety check.
3. Launching app.
4. Exploring screens.
5. Building profile.
6. Mining templates.
7. Generating scenario.
8. Running replay tests.
9. Running live validation.
10. Autopilot ready.

Definition of done:

- A user can create an autopilot through dashboard without manually editing JSON.
- Dashboard run actions call validation and PolicyGuard before execution.
- Dashboard tests cover API payloads and static UI contract.

## PR 31: Autopilot Versioning

Files:

- `core/autobuilder/versioning.py`
- `tests/test_autopilot_versioning.py`

Goal:

Store version history and rollback points.

Examples:

- `v0.1.0` initial build.
- `v0.1.1` added new continue template.
- `v0.1.2` updated popup ROI.
- `v0.2.0` new runner strategy.

Track:

- Patch history.
- Who/what changed the autopilot.
- Test result before/after.
- Rollback point.

Definition of done:

- Autopilot changes create version entries and previous working versions can be
  restored.

## PR 32: Autopilot Eval Suite

Files:

- `core/autobuilder/eval_suite.py`
- `tests/test_autopilot_eval_suite.py`

Goal:

Measure generated autopilot quality.

Metrics:

- `success_rate`
- `avg_loop_ms`
- `llm_calls_per_run`
- `forbidden_actions_count`
- `template_hit_rate`
- `cache_hit_rate`
- `unknown_screen_count`
- `repair_success_rate`
- `action_failure_rate`

Definition of done:

- Each autopilot has an evaluation report showing speed, stability, safety, and
  repair quality.

## MVP Order

MVP 1:

- PR 15 GoalSpec / Task Parser.
- PR 16 SafetyPolicy Engine.
- PR 17 AppManager launch-only path.
- PR 18 ScreenGraph.
- PR 19 Explorer for 3-5 screens + BuildContext.
- PR 20 LLM Screen Analyst.
- PR 21 Profile Generator.
- PR 24 Scenario Generator.
- PR 25 Autopilot Bundle.

MVP 2:

- PR 22 ROI Generator.
- PR 23 Template Auto-Miner.
- PR 26 Replay Test Runner.
- PR 28 Self-Healing basic.

MVP 3:

- PR 27 Live Validation Runner.
- PR 29 Patch Review / Human Approval.
- PR 30 Builder Dashboard UI.
- PR 31 Autopilot Versioning.
- PR 32 Autopilot Eval Suite.

## Acceptance Criteria

The feature is complete when:

1. A user can provide a prompt to create an autopilot.
2. The system creates a GoalSpec.
3. SafetyPolicy blocks forbidden actions.
4. AppManager launches the app.
5. Explorer collects screens.
6. LLM analyzes unknown screens as structured data only.
7. ProfileGenerator creates `profile.json`.
8. ROI Generator creates normalized zones.
9. TemplateMiner saves and verifies templates.
10. ScenarioGenerator creates `scenario.json`.
11. AutopilotBundle is saved and loadable.
12. Replay tests pass without a phone.
13. Runtime uses local-first/local-only execution.
14. LLM is not called in fast gameplay.
15. SelfHealing proposes a patch when a safe screen changes.
16. Risky patches require human review.
17. Dashboard shows the full build, validation, and repair process.
18. Generated JSON artifacts pass schema validation before save or execution.
19. Artifact writes are atomic and do not corrupt the last working autopilot.
20. Persisted traces, reports, screenshot metadata, and LLM messages are
    secret-redacted.
21. Build, exploration, LLM, repair, action, and runtime budgets are enforced.
22. Profile/device reliability can be measured with a benchmark matrix that
    records device, Android version, resolution, profile, success count, and
    break stage across repeated runs.

## Required Test Discipline

- No roadmap item is done without tests.
- No empty provider/module shells should be marked complete.
- Fake LLM/device/action runners must be used for deterministic unit tests.
- Schema tests must cover every generated artifact type.
- Atomic-write tests must prove failed validation does not replace the previous
  working artifact.
- Redaction tests must cover emails, tokens, phone numbers, and password-like
  fields.
- Replay tests must validate generated templates and scenarios without a phone.
- Live-device smoke tests are separate evidence and must save clear reports.

## Short Formula

LLM creates the autopilot.
Local engine runs the autopilot.
LLM repairs the autopilot when safe and necessary.
Dashboard shows and controls the full process.
