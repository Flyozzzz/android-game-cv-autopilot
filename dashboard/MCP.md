# Android Autopilot Dashboard MCP

The dashboard can be controlled by any MCP-compatible AI client through:

```bash
python3 -m dashboard.mcp_server
```

Example client config:

```json
{
  "mcpServers": {
    "android-autopilot-dashboard": {
      "command": "python3",
      "args": ["-m", "dashboard.mcp_server"],
      "cwd": "/Users/flyoz/android",
      "env": {
        "DASHBOARD_URL": "http://127.0.0.1:8765",
        "MCP_AUTOSTART_DASHBOARD": "1",
        "DASHBOARD_MCP_API_KEY": "change-me"
      }
    }
  }
}
```

The MCP server forwards tool calls to the dashboard HTTP API, so web UI and MCP
clients share the same run state, logs, presets, game profiles, recordings, CV
tools, and guarded data-file editor.

The MCP server sends `DASHBOARD_MCP_API_KEY` as `X-Dashboard-Api-Key` on every
dashboard API request. The local example value is `change-me`; set a strong
value in both the dashboard environment and MCP client config for real use.

Available tool groups:

- State and reports: `dashboard_state`, `tail_run_log`, `latest_report`
- Runs and tests: `start_safe_run`, `stop_run`, `run_checks`, `run_benchmark_matrix`
- Safe data editing: `list_project_files`, `read_project_file`, `write_project_file`
- Recordings: `list_recordings`, `read_recording`, `save_recording`, `replay_recording`
- Constructor: `list_game_profiles`, `save_game_profile`, `delete_game_profile`, `list_presets`, `save_preset`, `delete_preset`
- CV: `cv_plan_next_action`, `cv_run_goal`
- Vision Inspector: `vision_inspector_state`, `list_vision_templates`, `save_vision_template`, `create_vision_roi`, `export_vision_label`
- Autopilot Builder: `autopilot_builder_state`, `build_autopilot`
- Android control: `adb_devices`, `device_screenshot`, `device_tap`, `device_swipe`, `device_key`, `device_text`
- Manual checkpoints: `manual_continue`

The web dashboard also includes a CV Test Bench in the Manual section. It uses
the same `/api/cv/plan` and `/api/cv/run` endpoints as MCP, so an operator can
type a goal prompt, inspect one planned action, or run a short guarded CV loop
before saving a preset.

Vision Inspector also shares the same API with MCP. A model can read the latest
ROI/candidate overlay, inspect provider output, save a template from the latest
screenshot, create a normalized ROI zone in a profile, or export a label JSON
without touching dashboard source code.

Autopilot Builder is also exposed over MCP. A model can read saved bundles and
run a prompt-to-autopilot build that writes `autopilots/<id>/` artifacts,
including GoalSpec, safety policy, screen graph, profile, ROI, template
registry entries, scenario, replay/live reports, and version history.

## Smart Model Workflow

Connect any strong MCP-compatible model and give it a high-level assignment:

```text
Configure Android Game CV Autopilot for <game name>. Create or update a game
profile, build a safe preset, tune CV prompts, inspect the device screen, run
checks, test CV planning, and stop the automation at purchase preview.
```

The model can use the tools in this order:

1. `dashboard_state` and `adb_devices` to understand the current setup.
2. `save_game_profile` to define package name, install query, tutorial hints,
   purchase-preview hints, blockers, and gameplay strategy for any new game.
3. `save_preset` to store the selected profile, stages, methods, recordings,
   CV prompt overrides, and safe preview settings.
4. `device_screenshot`, `cv_plan_next_action`, and `cv_run_goal` to test what
   CV sees and how it behaves on the current screen.
5. `vision_inspector_state` to inspect the latest selected ROI/candidate and
   `save_vision_template` / `create_vision_roi` to turn a useful region into
   reusable local perception assets.
6. `autopilot_builder_state` and `build_autopilot` to generate a reusable
   autopilot bundle from a goal prompt.
7. `run_checks` to verify project health after safe data-file changes.
8. `start_safe_run`, `tail_run_log`, and `latest_report` to execute and observe
   the guarded route.

This lets a model configure automation for another game through MCP without
editing server code. The file tools are limited to safe dashboard data files:
presets, profiles, recordings, and prompt notes. Purchase confirmation remains
blocked by the dashboard guard.

Safety rules are enforced by the dashboard API:

- Purchase mode is always `preview`.
- Google phone verification stays manual.
- Dashboard file editing is limited to `dashboard/presets`,
  `dashboard/profiles`, `dashboard/recordings`, and `dashboard/prompts`.
- Server code, Python files, dashboard JS/CSS/HTML, legacy files, logs, reports,
  caches, virtualenvs, and secret files are blocked.
