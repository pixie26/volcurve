# Fixture provenance

- `implied_vol_surface.json` and `instruments_equity.json` are the existing sanitized fixtures derived from the earlier sliding-moneyness work.
- `schema/` contains synthetic contract fixtures built strictly from Cortex OpenAPI 1.60.0 field and axis rules. They validate parsers but are **not** evidence of live market behavior.
- `market/` contains internally consistent synthetic observations with deterministic values for analytics tests.
- `errors/` contains synthetic malformed or adverse payloads for normalized-error tests.

Only a successful controlled live probe may change a request mode from `enabled=false` to `enabled=true` in capabilities.
