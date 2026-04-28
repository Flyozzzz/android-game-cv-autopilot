# Profile Evidence

This directory is the profile/plugin evidence layer. Runtime profile hints can
still live in `dashboard/profiles`, but maturity claims should be backed by
evidence records here or by live validation reports under
`reports/profile_validation`.

Recommended shape:

```text
profiles/
  talking-tom/
    evidence/
      live_20260428.json
    validation/
      live_20260428/
        live_report.json
        frames/
    README.md
  schema/
    profile_evidence.schema.json
```

`evidence/*.json` is the dashboard-facing index. `validation/*/live_report.json`
is the per-profile report excerpt, and `validation/*/frames` keeps small tracked
proof frames for review. Full raw runtime reports can still be written under the
ignored `reports/profile_validation` directory during local live validation.

Maturity labels:

- `proven`: repeatable evidence for the claimed scope.
- `validated`: live/replay evidence exists, but scope is narrower than proven.
- `beta`: useful but not yet repeated across enough devices/app versions.
- `experimental`: early helper or smoke coverage only.
- `template-only`: static profile/template data with no live proof.
- `deprecated`: app/profile is stale or blocked.

`proven` means proven only for the exact recorded scope, device/app version,
language, resolution, and runtime settings. It must not imply universal game
automation.
