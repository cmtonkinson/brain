# Coding Adapter
Tier 1 *Adapter* resource that wraps coding-agent CLIs (Claude Code,
Codex, OpenCode) inside ephemeral containers and exposes a uniform
Protocol to the Software Service.

------------------------------------------------------------------------
## What This Component Is
`resources/adapters/coding/` is the Tier 1 *Adapter* under the Software
Service. It launches one ephemeral container per coding task, runs the
configured executor against bind-mounted worktree and workspace
directories, and reports status / collects results back to its caller.

Core module roles:
* `component.py`: `ResourceManifest` registration (`adapter_coding`,
  owned by `service_software`)
* `adapter.py`: `CodingAdapter` Protocol + cross-boundary domain types
  (`CodingTaskSpec`, `CodingTaskHandle`, `CodingTaskStatusSnapshot`,
  `CodingTaskResult`, `ExecutorInfo`, `ExecutorHealthStatus`) + error
  taxonomy
* `runtime.py`: `ContainerRuntime` Protocol + supporting types — the
  swappable substrate for container lifecycle (launch / supervise / reap)
* `image_builder.py`: `ImageBuilder` Protocol + concrete
  `DockerImageBuilder` — the swappable substrate for image inspect /
  build (lazy per-workspace customization layers)
* `config.py`: settings (`coding.executors.*` catalog, owner label,
  Docker socket path, base image tag, workspace-image repo and root)
* `docker_coding_adapter.py`: default `CodingAdapter` implementation
* `docker_runtime.py`: host-Docker `ContainerRuntime` implementation
* `runtime/Dockerfile.base`: the only Brain-shipped runtime image
  definition
* `runtime/<executor_id>.sh`: one install script per agent CLI
  (`claude.sh`, `codex.sh`, `opencode.sh`); each runs in turn during
  the base-image build to bake every configured agent into one image

------------------------------------------------------------------------
## Boundary and Ownership
The Adapter is single-purpose: launch one container per task using the
configured base image (or a per-workspace customization layer),
supervise it, capture stdout/stderr, and reap it. It does **not**
interpret the prompt, read or modify the worktree, run tests, create
branches or commits, or enforce approval policy. Those concerns belong
upstream in the Software Service or above.

### Three Protocols, Three Boundaries
```
Software Service
       │     ← Boundary 3: CodingAdapter Protocol
Coding Adapter
   │       │
   │       └──── Boundary 2: ContainerRuntime Protocol  →  host Docker (v1)
   └──────────── Boundary 1: ImageBuilder Protocol      →  host Docker (v1)
```

* **`CodingAdapter`** — the executor-aware contract. Knows there are
  things called "Claude Code", "Codex", "OpenCode"; knows how each
  one's CLI is invoked.
* **`ContainerRuntime`** — the executor-agnostic substrate for
  container lifecycle (launch / supervise / reap). Implemented v1
  against the host Docker daemon.
* **`ImageBuilder`** — the substrate for image inspect / build, used
  to lazily build per-workspace customization layers. Kept on a
  separate Protocol from the runtime so the runtime stays
  single-purpose; both ride the same host Docker socket today.

This split exists so the runtime substrate can be swapped (Podman,
Apple Container) without touching executor logic, the image-build
substrate can be swapped independently of container lifecycle, and new
executors can be added without touching either runtime.

### v1 Container Substrate: DooD
The v1 `ContainerRuntime` and `ImageBuilder` both talk to the host
Docker daemon via a bind-mounted socket (`/var/run/docker.sock`),
spawning sibling task containers (Docker-outside-of-Docker, "DooD").
No nested daemon, no `--privileged` Brain Core.

The DooD trust expansion is explicit and accepted: the Docker socket
grants effective host-root capability to whichever process can talk to
it. Brain Core, by mounting the socket, gains that capability. For
Brain's single-user, local threat model — already trusted with the
user's API keys, vault, Signal credentials, and calendar tokens — this
is acceptable. Revisit if Brain becomes multi-tenant or hosted, if a
packaged install path for less-technical operators is created, if Apple
Container stabilizes, or if the executor catalog grows to include
known-untrusted tools.

Alternatives considered and deferred:
* **Docker-in-Docker (DinD)** — rejected. Requires `--privileged`,
  which negates the isolation we'd be gaining; nested overlay
  filesystems add overhead; bind-mounting host worktree paths is awkward.
* **Podman (rootless, daemonless)** — viable. Per-user socket replaces
  host-root capability with per-user capability. OCI-compatible; the
  Docker SDK works unchanged against `podman system service`. Deferred
  to keep the v1 install surface to a single runtime.
* **Apple Container (per-task microVM)** — promising but immature
  (2025 GA). Per-container VM isolation is a strong fit for executing
  under-trusted coding agents. The `ContainerRuntime` Protocol lets
  this be added later without disturbing other code.
* **Host-side coding gateway companion** (analogue of Host MCP Gateway)
  — would keep the Docker socket out of Brain Core entirely. Deferred;
  an extra installable component for a single-user tool.

------------------------------------------------------------------------
## Image Model
Brain ships **one** runtime image, `brain/coding-runtime:base`, built
from `runtime/Dockerfile.base` plus every sibling `<executor_id>.sh`
script. Each agent install script runs in turn during the base build,
so the resulting image carries Claude Code, Codex, OpenCode, and any
future agent CLI side-by-side. The Adapter selects which one to invoke
at task spawn from the spec's `executor` field; no per-executor image.

Operators add project-specific tooling without touching Brain's
Dockerfile by dropping a bash script under
`<workspace_image_root>/<workspace_relative_path>.sh`. With
`workspace_image_root: ~/.config/brain/coding_images` (default), the
workspace registered as `--path repo/brain` is customized by
`~/.config/brain/coding_images/repo/brain.sh`. Brain Core builds a
layer tagged `<workspace_image_repo>:<slug>` (slug = relative path with
`/` → `_`) on demand.

Image resolution at task dispatch:
1. If no script is present at the expected path → image tag = `base_image`.
2. If a script is present:
   * Compute tag `<workspace_image_repo>:<slug>`.
   * Inspect the local image's creation timestamp via `ImageBuilder`.
   * If absent or older than the script's mtime → build via the
     `ImageBuilder` from a synthesized Dockerfile that does
     `FROM base_image; USER root; COPY install.sh; RUN bash install.sh;
     USER coder`.
   * Spawn from the resolved tag.

Build failures translate to `CodingTaskRuntimeError` carrying the
captured Docker build output so the Software Service can surface the
operator's broken script in the task lineage. Daemon-unreachable
errors translate to `CodingAdapterUnavailable`.

------------------------------------------------------------------------
## Lifecycle
For each task:
1. `run_task(spec) -> handle` — resolve the workspace's image (build a
   per-workspace layer first if its install script is newer than the
   cached image), launch a container with worktree and workspace bind-
   mounted, env injected, and Brain-owned labels attached. Returns
   immediately once the runtime has accepted the launch.
2. `poll(handle) -> snapshot` — cheap, repeatable status check. Phases:
   `PENDING → RUNNING → {SUCCEEDED, FAILED, CANCELLED}`.
3. `cancel(handle)` — idempotent stop request. Honours the configured
   stop timeout before forcing termination.
4. `collect(handle) -> result` — once a terminal phase has been observed,
   drain stdout/stderr to the Object Store, return the final result, and
   reap the container.

Outside the per-task lifecycle, the Software Service also calls
`resolve_workspace_host_path(workspace_path)` at workspace registration
to fail-fast on paths that no bind in brain-core's container covers —
the same `host_path_for` lookup the Adapter uses at spawn, exposed at
the Adapter Protocol so the Service does not need to know about
`ContainerRuntime`.

Errors at the Adapter level (runtime down, image build failed, image
unavailable, container launch failure) are surfaced as exceptions
(`CodingAdapterUnavailable`, `CodingTaskRuntimeError`,
`CodingTaskNotFoundError`). Errors at the *task* level (timeout,
cancel, budget exceeded) are recorded on
`CodingTaskResult.termination_reason` so the Software Service can
branch without parsing logs.

Orphan reaping: on Brain Core startup, the Adapter calls
`runtime.list_owned(owner_label=...)` to enumerate stragglers from the
prior process and reap them. Orphan handles derive `task_id` from the
container's `brain.coding.task_id` label and a deterministic `handle_id`,
so reattach matches existing rows.

------------------------------------------------------------------------
## Container Conventions
Every task container carries Brain-owned labels:
* `brain.coding.task_id=<id>` — links the container to the Software
  Service's `tasks` row.
* `brain.coding.owner=<brain-core-instance-id>` — used by the orphan
  sweeper on Brain Core startup.
* `brain.coding.executor=<executor-id>` — for ad-hoc operator filtering.

Bind mounts (two, both `:rw`):
* **Worktree** at `WORKTREE_MOUNT_TARGET` (`/work`) — the executor's CWD.
  Source is the per-task worktree under `software.staging_root`.
* **Workspace** at its registered virtual path (e.g.
  `/mount/software/repo/brain`) — host source is resolved fresh at
  spawn time via `ContainerRuntime.host_path_for`, which inspects
  brain-core's own bind-mount table on the Docker daemon. Docker is the
  source of truth for the live mount, so brain-core does not cache the
  host path on the workspace row. Required so the worktree's `.git`
  link resolves and the task container sees the workspace at the same
  absolute path brain-core does. No host-vs-container path translation
  leaks into the executor's view.

Network policy — **open egress (current posture).** Per-task
containers run on a dedicated user-defined bridge network with
`internal=False`; outbound traffic is unrestricted. Combined with the
read-write workspace bind mount and an LLM-driven CLI as the only
process, that means a task that goes off the rails (prompt-injected
agent, poisoned dependency, malicious URL the agent decides to fetch)
can reach anything the operator's host can reach: pastebins, internal
LAN services, attacker-controlled hosts. Workspace allowlist gating is
the only trust boundary; once a workspace is registered, every
dispatched task has unattended egress. **This posture is intentional
for the private-beta-of-one phase. It is unsafe for multi-tenant use,
hosts with sensitive non-Brain data, or any setup where the prompt
input surface is not exclusively the operator.** See
[`todo/network-egress-filtering.md`](../../../todo/network-egress-filtering.md)
for the planned default-deny proxy + URI-classification design.

Secret injection: each value named in `coding.executors.<id>.env_keys`
is read from brain-core's own process environment (operator-supplied
via Compose `environment:` / `.env`) and injected into the task
container. The allowlist is default-deny: an empty tuple passes zero
env vars. Keys absent from brain-core's env are silently skipped — the
agent CLI inside the task will then fail to authenticate, which is the
desired loud-failure behavior.

Runtime user: containers spawn as `coder` (UID 1000), the user the
base image leaves as default. Workspace customization scripts run as
root during their image build, but the resulting image's runtime user
is reset to `coder`.

------------------------------------------------------------------------
## Configuration
Adapter-level settings live under `coding.*`:

```yaml
coding:
  docker_socket: /var/run/docker.sock
  owner_label: brain.coding.owner
  client_timeout_seconds: 30
  stop_timeout_seconds_max: 30
  base_image: brain/coding-runtime:base
  workspace_image_repo: brain/coding-runtime
  workspace_image_root: ~/.config/brain/coding_images
  executors:
    claude_code:
      cli: claude
      env_keys: [ANTHROPIC_API_KEY]
    codex:
      cli: codex
      env_keys: [OPENAI_API_KEY]
    opencode:
      cli: opencode
      env_keys: [OPENCODE_API_KEY]
```

Each executor entry now describes only how to invoke an agent inside
whichever runtime image the Adapter picks (CLI binary name + secret
allowlist). Image selection is no longer per-executor.

Operator workflow:
1. `make coding-runtime-images` builds `brain/coding-runtime:base` once
   per operator install (or after Brain ships a new agent script).
2. Drop optional per-workspace customization scripts under
   `workspace_image_root`. Brain Core builds the layer image lazily on
   the next task dispatch against that workspace, rebuilding when the
   script's mtime moves past the image's creation timestamp.

Service-level concerns (staging root, defaults, commit identity) live
under `software.*` (see `services/effect/software/README.md`).


------------------------------------------------------------------------
_End of Coding Adapter README_
