# candy-crush

Genre: match-3 solver helper.

Current maturity: validated for the evidence scope below, not universal automation.

Latest evidence:

- Result: passed
- Device: 47d33e1c (not_captured_by_validator, Android not_captured_by_validator, 1080x2400)
- App: com.king.candycrushsaga version not_captured_by_validator
- Scope: launch, capture, safe_exploration
- Live report: `profiles/candy-crush/validation/live_20260428/live_report.json`
- Replay/proof frames: `profiles/candy-crush/validation/live_20260428/frames`

Limits:

- This proof pack validates launch, capture, and safe exploration on the listed device.
- Match-3 board solving is covered by deterministic solver tests; this live run is not a universal gameplay proof.
