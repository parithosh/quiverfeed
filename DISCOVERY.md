# Discovery Notes

These notes capture empirical or externally advertised facts about the Quiver
API that affect `quiverfeed` behavior. They should be updated when live
diagnostics prove something changed.

## Current Sources

- Quiver advertises an OpenAPI file from its plugin manifest at
  `https://api.quiverquant.com/static/openapi.yaml`.
- The advertised OpenAPI file currently covers a small subset of the API:
  congressional trading, lobbying search, insiders, and bill summaries.
- Quiver's current Python package on PyPI is `quiverquant`.

## Current Package Positioning

`quiverquant` is active again: PyPI shows `0.2.5` released on 2026-05-06. It is
still a lightweight convenience wrapper: direct URL methods, direct DataFrame
conversion, no cache, no local rate-limit coordination, no point-in-time
canonical date columns, and no catalog drift checks.

`quiverfeed` exists to provide the correctness and operations layer rather than
to clone those convenience methods.

## Date Semantics

Known canonical mappings:

- `congresstrading`: `Traded` -> `event_time`, `Filed` -> `available_at`
- `insiders`: `Date` -> `event_time`, `fileDate` -> `available_at`
- `lobbying`: `Date` -> `event_time`; no separate advertised disclosure date
- `bill_summaries`: `lastActionDate` -> `event_time`; no separate advertised
  disclosure date

Do not fabricate `available_at` when the catalog does not know a disclosure
column.

## Rate Limits

The initial local default is 20 requests per hour. This is intentionally
conservative and should be revised only when Quiver publishes contractual
limits or repeated live tests prove a better default.

## Known Ignored Params

`date_from` and `date_to` have been observed as ignored on the
`congresstrading` bulk endpoint. `quiverfeed` warns when callers pass them but
still sends them through.
