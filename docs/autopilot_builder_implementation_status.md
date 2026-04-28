# Autopilot Builder Implementation Status

Status: implemented and regression-audited.

This ledger tracks the approved `docs/autopilot_builder_plan.md` items against
the current code and tests.

| PR | Plan Item | Code | Tests | Status |
| --- | --- | --- | --- | --- |
| PR15 | GoalSpec / Task Parser / Schemas / Budgets | `core/autobuilder/goal_spec.py`, `task_parser.py`, `schemas.py`, `budgets.py` | `tests/test_goal_spec.py`, `test_task_parser.py`, `test_autobuilder_schemas.py`, `test_autobuilder_budgets.py` | Done |
| PR16 | SafetyPolicy / PolicyGuard / Redaction | `safety_policy.py`, `policy_guard.py`, `redaction.py` | `tests/test_autobuilder_safety_policy.py`, `test_autobuilder_redaction.py` | Done |
| PR17 | AppManager | `app_manager.py` | `tests/test_app_manager.py` | Done |
| PR18 | ScreenGraph | `screen_graph.py` | `tests/test_screen_graph.py` | Done |
| PR19 | Explorer + BuildContext | `explorer.py`, `exploration_state.py`, `context.py` | `tests/test_explorer.py`, `test_build_context.py` | Done |
| PR20 | LLM Screen Analyst | `screen_analyst.py` | `tests/test_screen_analyst.py` | Done |
| PR21 | Profile Generator | `profile_generator.py` | `tests/test_profile_generator.py` | Done |
| PR22 | ROI Generator | `roi_generator.py` | `tests/test_roi_generator.py` | Done |
| PR23 | Template Auto-Miner | `template_miner.py` | `tests/test_template_miner.py` | Done |
| PR24 | Scenario Generator | `scenario_generator.py` | `tests/test_scenario_generator.py` | Done |
| PR25 | Autopilot Bundle / Atomic Artifacts | `artifact_store.py`, `bundle.py` | `tests/test_artifact_store.py`, `test_autopilot_bundle.py` | Done |
| PR26 | Replay Test Runner | `replay_test_runner.py` | `tests/test_replay_test_runner.py` | Done |
| PR27 | Live Validation Runner | `live_validation.py` | `tests/test_live_validation.py` | Done |
| PR28 | Self-Healing Engine | `self_healing.py`, `patches.py` | `tests/test_self_healing.py` | Done |
| PR29 | Patch Review / Human Approval | `review.py` | `tests/test_patch_review.py` | Done |
| PR30 | Builder Dashboard UI/API | `dashboard/api_builder.py`, `dashboard/static/autopilot_builder.js`, `dashboard/static/autopilot_builder.css`, `dashboard/server.py`, `dashboard/static/index.html` | `tests/test_dashboard_builder_api.py`, `test_dashboard_builder_static_ui.py` | Done |
| PR31 | Autopilot Versioning | `versioning.py` | `tests/test_autopilot_versioning.py` | Done |
| PR32 | Autopilot Eval Suite | `eval_suite.py` | `tests/test_autopilot_eval_suite.py` | Done |

## Verified Rules

- Generated JSON artifacts use schema validation before persistence.
- Bundle JSON is written through atomic temp-file replacement.
- Template registry and version rollback also use temp-file replacement.
- Secrets are redacted from persisted JSON/report payloads.
- Budget counters stop exploration, LLM analysis, and repair loops when limits
  are exhausted.
- Risky actions can be represented as review-required, but `PolicyGuard`
  rejects them by default unless an explicit review path allows them.
- LLM screen analysis is structured output only; the analyst never executes an
  action directly.
- Fast gameplay validation requires `runtime.fast_gameplay == "local_only"`.

## Latest Focused Test Command

```bash
python3 -m pytest \
  tests/test_goal_spec.py \
  tests/test_task_parser.py \
  tests/test_autobuilder_budgets.py \
  tests/test_autobuilder_schemas.py \
  tests/test_autobuilder_safety_policy.py \
  tests/test_autobuilder_redaction.py \
  tests/test_app_manager.py \
  tests/test_screen_graph.py \
  tests/test_build_context.py \
  tests/test_explorer.py \
  tests/test_screen_analyst.py \
  tests/test_profile_generator.py \
  tests/test_roi_generator.py \
  tests/test_scenario_generator.py \
  tests/test_template_miner.py \
  tests/test_artifact_store.py \
  tests/test_autopilot_bundle.py \
  tests/test_replay_test_runner.py \
  tests/test_live_validation.py \
  tests/test_self_healing.py \
  tests/test_patch_review.py \
  tests/test_autopilot_versioning.py \
  tests/test_autopilot_eval_suite.py \
  tests/test_autopilot_builder_e2e.py \
  tests/test_dashboard_builder_api.py \
  tests/test_dashboard_builder_static_ui.py
```

Result: `44 passed`, `100.00%` coverage for `core.autobuilder` and
`dashboard.api_builder`.

## Completed Audit Steps

- Full repository regression: `350 passed`.
- JSON/static validation: `dashboard/static/i18n.json` parsed successfully,
  `node --check` passed for dashboard JS.
- Dashboard Builder API/static contract tests: passed.
- Autopilot Builder line coverage gate: `100.00%`.

## Live Smoke Note

The code includes deterministic replay validation and a mocked live validation
runner. A real-device builder smoke can be run from the dashboard Builder tab
with a connected Android device and a temporary Vision key; fast gameplay still
remains `local_only`.
