# Dashboard Guide

This guide describes the operator workflow in the web dashboard.

## Main Tabs

| Tab | Purpose |
| --- | --- |
| `Launch` | Build and start guarded automation runs. |
| `MCP` | Connect an external MCP client to the same state and tools. |
| `Manual` | Tap, swipe, type, send keys, record and replay actions. |
| `CV Bench` | Plan one safe CV action or run a short guarded CV loop. |
| `Vision Inspector` | Review ROI, provider candidates, selected element, and save local assets. |
| `Builder` | Turn a goal prompt into a reusable autopilot bundle. |
| `Project` | Edit safe presets, profiles, recordings, and prompt notes. |
| `Profiles` | Create and tune reusable game profiles. |
| `Guide` | In-app operator help. |
| `Reports` / `Logs` | Inspect run timelines, checks, and live logs. |

## Vision Inspector

Vision Inspector is the local perception debug panel.

Color legend:

- Orange: active ROI
- Blue: provider candidates
- Green: selected candidate
- Purple: manual box drawn by the operator

Typical workflow:

1. Run a CV goal or automation step first.
2. Open `Vision Inspector`.
3. Click `Refresh Inspector`.
4. Inspect the selected element and provider candidates.
5. If the right region is not selected, drag a purple manual box.
6. Save one of three artifact types:
   - Template: crop a PNG and add a registry entry under `assets/templates/`
   - ROI: write a normalized screen zone into `dashboard/profiles/<profile>.json`
   - Label: export a JSON artifact for later debugging or model data prep

Use ROI when the area is a reusable screen region. Use a template when the
exact visual element should be found later by local matching.

## Autopilot Builder

Builder is the prompt-to-bundle workflow.

Inputs:

- Goal prompt
- Builder mode: `create`, `improve`, `repair`, `validate`, `shadow`
- Optional package
- Optional replay frame paths
- Vision model list
- Optional live validation toggle

Output bundle:

```text
autopilots/<id>/
  autopilot.json
  profile.json
  scenario.json
  screen_graph.json
  safety_policy.json
  recordings/
  reports/
  templates/
  versions.json
```

Builder uses LLM as a planner and analyst, not as a realtime player. Runtime
execution stays local-first or local-only depending on the mode and stage.

## Profile Maturity

Profiles are not all equally proven. The dashboard exposes maturity/readiness:

- `proven` / `validated`: replay/live validation passed in the stated scope.
- `helper`: a local gameplay helper exists, but it is not a universal bot.
- `starter`: reusable hints/ROI/blockers that still need validation.
- `blocked`: validation hit an external login/server/region/account blocker.

Treat `starter`, `helper`, and `blocked` profiles as build inputs, not as
finished autopilots. A profile should be promoted only after replay validation,
live validation, and a saved report for the target device, resolution, language,
and app version.

## Setup And Speed Checks

Before using a new machine:

```bash
python3 scripts/setup_doctor.py --latency
```

For reaction-speed decisions:

```bash
python3 scripts/reaction_benchmark.py --serial emulator-5554 --samples 5
```

ADB screencap above roughly `180 ms` is a menu/tutorial path, not a fast-gameplay
path. Use `replay`, `scrcpy`, or `minicap` and keep active gameplay local-only.

## MCP In Practice

The MCP bridge exposes the same dashboard state. A model can:

- inspect `dashboard_state`
- save profiles and presets
- run CV tools
- inspect Vision traces
- build autopilot bundles
- run checks

Use `python3 -m dashboard.mcp_server` and point the client at the local
dashboard URL with `DASHBOARD_MCP_API_KEY`.

## Files You Can Edit From The Dashboard

Safe editable areas:

- `dashboard/presets/`
- `dashboard/profiles/`
- `dashboard/recordings/`
- `dashboard/prompts/`

Blocked from the web editor:

- Python code
- dashboard JS/CSS/HTML
- logs and reports
- caches and virtualenvs
- secret files

## Screenshots

Current screenshot set in `docs/screenshots/`:

- `01-login.png`
- `02-command.png`
- `03-mcp.png`
- `04-manual-control.png`
- `05-cv-bench.png`
- `06-data-files.png`
- `07-profiles.png`
- `08-guide.png`
- `09-reports-logs.png`
- `10-device-screen-sanitized.png`
- `11-vision-inspector.png`
- `12-autopilot-builder.png`
