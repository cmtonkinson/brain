# Dashboard Host Widget Plan
This document defines the intended scope and behavior for the dashboard host
widget.

------------------------------------------------------------------------
## Purpose
The host widget exists to answer one question quickly:

_Is the host machine under pressure or constrained in a way that explains what
the operator is seeing in Brain?_

It is not intended to be a full system monitor.

------------------------------------------------------------------------
## Scope
The host widget should remain compact and high-signal.

It should provide:
- CPU pressure
- memory pressure
- system load
- disk capacity pressure
- disk I/O activity
- host uptime
- battery/power state when applicable

It should not try to replace:
- `top`
- `htop`
- `btop`
- Activity Monitor

------------------------------------------------------------------------
## Initial Metric Set
The initial host widget should include:

- CPU %
- memory %
- load average
- disk usage %
- disk I/O rate
- uptime
- battery/power state, when the host has a battery

------------------------------------------------------------------------
## Metric Definitions
### CPU %
One compact host-level CPU utilization percentage.

Purpose:
- fast signal for whether the machine is CPU-bound or thrashing

Render example:
- `CPU 23%`

### Memory %
One compact host-level memory utilization percentage.

Purpose:
- fast signal for memory pressure

Render example:
- `Mem 61%`

### Load Average
Standard host load averages:
- 1 minute
- 5 minute
- 15 minute

Purpose:
- fast signal for sustained system pressure

Render example:
- `Load 2.31 2.04 1.88`

### Disk Usage %
One compact usage percentage for the relevant filesystem(s).

Priority:
- the filesystem containing the Brain repo or working directory
- the filesystem containing Brain durable data if distinct

If Brain data and repo live on the same filesystem, one percentage is enough.

Purpose:
- fast signal for storage capacity pressure

Render example:
- `Disk 74%`

### Disk I/O Rate
One compact read/write rate summary.

Purpose:
- explain slow storage-bound behavior
- surface active disk churn from Postgres, Qdrant, Docker, or logs

Render example:
- `I/O r12M w4M`

### Uptime
One compact host uptime string.

Purpose:
- basic operational context

Render example:
- `Up 2d 04h`

### Power / Battery
Battery percentage plus charging state, only when a battery is present.

Purpose:
- useful for laptop-bound development and debugging
- can explain power-throttling or unplugged-machine situations

Render examples:
- `Power 82% charging`
- `Power 57% battery`

If the machine has no battery, omit this row entirely.

------------------------------------------------------------------------
## Explicit Exclusions
The following should not appear in the initial host widget:

- swap as a primary metric
- per-core CPU breakdowns
- process lists
- CPU temperature
- fan speed
- network interface breakdowns
- GPU metrics

------------------------------------------------------------------------
## Swap Policy
Swap is intentionally excluded from the initial host widget.

Reason:
- Linux swap metrics are generally straightforward
- macOS swap semantics are less clean and less useful in a compact, portable
  widget

Future policy:
- swap may be added later in a more detailed host drill-down
- if ever added, it should be platform-aware
- if shown on Linux, a swap percentage may be acceptable
- it should not be forced into the initial cross-platform compact widget

------------------------------------------------------------------------
## Power Policy
Power is conditional.

Rules:
- if the host has a battery, show battery percent and charging state
- if the host has no battery, omit power entirely
- do not render placeholder noise for battery-less hosts

------------------------------------------------------------------------
## Host Widget Philosophy
The host widget should be diagnostic, not exhaustive.

If a metric does not help explain:
- sluggishness
- resource pressure
- storage exhaustion
- host-state constraints

it likely does not belong in the initial widget.

------------------------------------------------------------------------
## Suggested Render Shape
Illustrative compact render:

```text
Host

CPU   23%
Mem   61%
Load  2.31 2.04 1.88
Disk  74%
I/O   r12M w4M
Power 82% charging
Up    2d 04h
```

If no battery is present:

```text
Host

CPU   23%
Mem   61%
Load  2.31 2.04 1.88
Disk  74%
I/O   r12M w4M
Up    2d 04h
```

------------------------------------------------------------------------
## Data Collection Guidance
Metrics should be collected through a dedicated host data source or host metrics
collector.

Do not scatter host probes across multiple panes or widgets.

The host widget should consume one normalized host snapshot model.

Suggested shape:

```text
HostSnapshot
- cpu_percent: float
- memory_percent: float
- load_1m: float
- load_5m: float
- load_15m: float
- disk_percent: float
- io_read_rate_bytes: float
- io_write_rate_bytes: float
- uptime_seconds: int
- battery_percent: float | None
- battery_charging: bool | None
```

------------------------------------------------------------------------
## Normalization Rules
The host widget should render normalized values, not raw platform output.

Rules:
- percentages should be rounded consistently
- load averages should be shown to two decimals
- I/O rates should be humanized consistently
- uptime should be rendered in a compact human-readable form
- missing battery values should suppress the power line entirely

------------------------------------------------------------------------
## Future Expansion
Possible future additions belong in a deeper host drill-down, not the initial
compact widget:
- swap
- per-device disk usage
- per-disk I/O
- network throughput
- temperature
- thermal throttling
- per-core CPU graphs

------------------------------------------------------------------------
## Testing Expectations
Host widget tests should cover:
- compact rendering of the required metrics
- omission of the power row when no battery exists
- consistent humanization of I/O rates
- consistent uptime formatting
- normalization behavior for load and percentage values

------------------------------------------------------------------------
## Contributor Notes
- Keep the host widget compact.
- Keep swap out of the initial widget.
- Keep power conditional on battery presence.
- Prefer one normalized host snapshot model.
- Add deeper host detail later only if it remains clearly useful.


------------------------------------------------------------------------
_End of Dashboard Host Widget Plan_
