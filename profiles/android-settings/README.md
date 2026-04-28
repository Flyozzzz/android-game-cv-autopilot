# android-settings

Genre: ordinary Android app.

Current maturity: validated for the evidence scope below, not universal automation.

Latest evidence:

- Result: passed
- Device: emulator-5554 (sdk_gphone64_arm64, Android 16, 1080x2400)
- App: com.android.settings version 16
- Scope: launch, capture
- Live report: `profiles/android-settings/validation/live_20260428/live_report.json`
- Replay/proof frames: `profiles/android-settings/validation/live_20260428/frames`

Limits:

- This proof pack validates launch and capture for a normal Android app profile on emulator-5554.
- No account, password, biometric, payment, or security-sensitive flow was automated.
