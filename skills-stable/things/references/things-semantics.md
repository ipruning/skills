# Things Semantics

Use this reference when a Things result looks surprising or the user asks about date accuracy.

## Data Source

`things_query.py` reads the local Things SQLite database in read-only mode. Default paths are under:

- `~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/ThingsData-*/Things Database.thingsdatabase/main.sqlite`
- Older fallback: `~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/Things Database.thingsdatabase/main.sqlite`

If access fails, check whether the process running this skill has macOS file permissions for the Group Containers path. If the user provides a copied database, pass it with `--db-path`.

## Date Fields

The common returned fields are:

- `start_date`: Things scheduled date.
- `deadline`: Things deadline date.
- `reminder_time`: reminder clock time.
- `created`, `modified`, `stop_date`: local datetimes derived from Unix timestamps.
- `today_index`: order inside the Things Today list.

Always confirm the local date with `date` before interpreting "today".

## Today View

`things.today()` is a Things Today view, not a strict `start_date == today` filter. It combines:

- tasks already scheduled into Today / Anytime,
- scheduled Someday tasks whose start date is in the past, and
- unscheduled tasks with past deadlines that have not been suppressed.

The library documents one important limitation: its Today prediction does not include repeating tasks that Things has not generated yet. If repeating tasks matter, say this explicitly.

## Privacy Defaults

Return counts or summaries unless the user asks to see task titles. Do not include `notes`, UUIDs, or raw database paths by default. Use `--include-notes` only when the user explicitly needs notes.
