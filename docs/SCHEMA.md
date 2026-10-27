# Data schema

Business data lives in `/knowledge` (approved policy) and `/fixtures` (synthetic
operational data). Application code in `/app` never hard-codes business facts.

## Knowledge pack — `knowledge/policies.json` (real) and `policies.sample.json` (synthetic)

```jsonc
{
  "meta": { "business": str, "status": "template|synthetic_demo", "synthetic": bool, "note": str },
  "items": [
    {
      "id": "fees.monthly",          // stable citation id (topic.key)
      "topic": "fees",
      "status": "confirmed|unknown", // 'unknown' items MUST NOT be used to answer
      "synthetic": bool,             // true only in the sample pack
      "answer_en": str|null,
      "answer_hi": str|null,
      "source": str|null,            // human-readable provenance label
      "last_verified": "YYYY-MM-DD"|null,
      "required": str                // (template only) what fact must be filled
    }
  ]
}
```

Rules: a fact is served only if its item is `confirmed`. `unknown` → the assistant
hands off. Real fees, timings, and admission requirements are never invented; they
stay `unknown` in `policies.json` until the operator confirms them. The sample pack
carries clearly-labelled synthetic values for development and demo.

## Fixtures (all synthetic, `"synthetic": true`)

`seats.json` → `seats[]`: `{ seat_id, label, zone }`

`slots.json` → `slots[]`: `{ slot_id, label, start "HH:MM", end "HH:MM" }` (Asia/Kolkata)

`memberships.json` → `memberships[]`:
`{ member_id, name, valid_from "YYYY-MM-DD", valid_to "YYYY-MM-DD", status "active|suspended" }`

`occupancy.json` → `occupancy[]`:
`{ seat_id, date "YYYY-MM-DD", start "HH:MM", end "HH:MM", member_id, note }`
Intervals are half-open `[start, end)` in Asia/Kolkata. Source records may overlap
each other; the engine handles that.

`demo_clock.json` → `{ as_of ISO8601 with offset, timezone "Asia/Kolkata" }`
The explicit "now" used for every availability query. No real system time is read.

## Availability result (returned by `query_availability`)

```jsonc
{
  "as_of": "2026-10-27T10:00:00+05:30",
  "timezone": "Asia/Kolkata",
  "query": { "date", "start", "end", "slot", "seat_id", "member_id" },
  "membership": { "member_id", "known", "valid", "reason" } | null,
  "errors": [str], "warnings": [str],
  "valid_request": bool,
  "seats": [ { "seat_id", "label", "zone", "available", "conflicts": [ {start,end,member_id,note} ], "reason" } ],
  "summary": { "available": int, "considered": int }
}
```

Read-only: the engine never books, pays, or writes a member record.
