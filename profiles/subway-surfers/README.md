# subway-surfers

Genre: runner helper.

Current maturity: validated for the evidence scope below, not universal automation.

Latest evidence:

- Result: passed
- Device: 47d33e1c (not_captured_by_validator, Android not_captured_by_validator, 1080x2400)
- App: com.kiloo.subwaysurf version not_captured_by_validator
- Scope: launch, capture, safe_exploration
- Live report: `profiles/subway-surfers/validation/live_20260428/live_report.json`
- Replay/proof frames: `profiles/subway-surfers/validation/live_20260428/frames`

Limits:

- This proof pack validates launch, capture, and safe exploration only.
- Fast runner gameplay still requires realtime frame-source validation with scrcpy_raw or equivalent streaming.
