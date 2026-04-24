# current-datetime

Return the current UTC and operator-local datetimes.

## Parameters

This op takes no input.

## Returns

An object with:
- `utc_timestamp`: ISO 8601 UTC datetime string.
- `local_timestamp`: ISO 8601 datetime string in the operator's preferred timezone.
- `local_timezone`: Operator preferred IANA timezone name.
