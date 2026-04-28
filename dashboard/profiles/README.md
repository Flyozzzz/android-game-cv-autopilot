# Dashboard Game Profiles

Custom profiles created from the dashboard or MCP are saved here as JSON files.
Built-in profiles remain in `core/game_profiles.py`; a JSON file with the same
`id` overrides the built-in profile at runtime.

Profile status is evidence-backed. Use the live validator to promote a profile
only after a real device run:

```bash
python3 scripts/profile_live_validator.py --serial 47d33e1c --profile subway-surfers --promote validated
```

`validated` is scoped: check `validation_scope` before treating a profile as
ready for fast gameplay, match-3 solving, purchase preview, or tutorial routes.
