# Install Guide
How to install Brain on macOS and reach your first conversation. If you plan to contribute code, also see the [Development Guide](development-guide.md).

------------------------------------------------------------------------
## Prerequisites
These are needed regardless of how you choose to talk to Brain.
* Docker Desktop with Docker Compose v2.
* [Obsidian] with the [Local REST API] plugin enabled. Brain reads and
  writes the vault through that plugin.
* [Ollama] is recommended. It serves a local embedding model and can
  optionally handle inference; without it you'll need to point Brain at a
  remote embedding provider.

Brain is developed and tested against macOS. Other platforms aren't
supported.

------------------------------------------------------------------------
## Clone the Repository
```sh
git clone https://github.com/cmtonkinson/brain.git
cd brain
```

All commands below are run from the repo root.

------------------------------------------------------------------------
## Configure
Brain has two configuration surfaces. The `.env` file at the repo root is
read by Docker Compose for image tags, port binds, and observability
secrets. Files under `~/.config/brain/` drive Brain itself: API keys,
model selection, and operator profile.

### `.env`
Copy the sample:
```sh
cp .env.sample .env
```

For the base stack, the only values that need to change from `replace-me`
are the SeaweedFS credentials:
* `BRAIN_SEAWEEDFS__ACCESS_KEY_ID`
* `BRAIN_SEAWEEDFS__SECRET_ACCESS_KEY`

The `LANGFUSE_*`, `GRAFANA_*`, `LOKI_*`, and `PROMETHEUS_*` entries are
only used when the observability overlay is enabled. Leave them at their
sample defaults until you opt in.

### `~/.config/brain/`
Run the install wizard:
```sh
make install
```

This walks you through identity (your display name, what to call Brain),
your Obsidian vault path, optional Signal enrollment (operator phone +
Brain's phone in E.164), the optional Software service, and LLM provider
selection. It writes the minimum override-only YAMLs to `~/.config/brain/`
and copies `docker-compose.override.yaml.sample` →
`docker-compose.override.yaml` if you opted into Software.

The default LLM provider is local Ollama for both chat and embeddings; the
wizard lists the chat tiers (`quick` / `standard` / `deep`) and embedding
profile pulled from `services/effect/language/config.py`. Accepting the
defaults requires Ollama running on the host with each listed model
already pulled (`ollama pull <name>`). If you'd rather use a hosted
provider, the wizard offers to record an Anthropic key (chat) and/or a
Voyage key (embeddings) into `secrets.yaml`; flipping a profile to that
provider is a separate edit in `~/.config/brain/effect.yaml` (see
`config/effect.yaml.sample`).

`make install` is re-runnable. To re-walk the wizard against an already-
configured install:
```sh
make install RECONFIGURE=1
```

The wizard records a skipped Obsidian key as the placeholder string
`replace-me` so you can grep for it and fill it in later. Skipped LLM
keys are simply omitted from `secrets.yaml`. Brain merges every
top-level `*.yaml` in `~/.config/brain/` in lexical order, so the sample
filenames are conventions, not requirements; combine or split them
however you prefer. The full key list is in the
[Configuration Reference](configuration.md).

Beyond first-install, host-side state changes that ship with new versions
of Brain (config-key migrations, cache resets, Qdrant collection
rebuilds) are managed by the [Upgrades system](upgrades.md). Routine
update flow:
```sh
git pull
make upgrade-dryrun   # see what's pending
make upgrade          # apply
make up               # start the stack
```

------------------------------------------------------------------------
## Start the Stack
Bring the application stack up:
```sh
make up
```

This builds and starts the application services in the background: Brain
Core, Assistant, Worker, Subagent, MCP Adapter, Postgres, Valkey, Qdrant,
SeaweedFS, and `signal-api`. On the first boot, Brain Core creates its
schemas and runs migrations automatically.

Check that everything came up:
```sh
make ps
```

All services should report `running` or `healthy`.

------------------------------------------------------------------------
## Software Workspaces
The Software Service registers operator-allowlisted git repositories and
runs per-task git worktrees against them. Brain Core has to be able to
see those repositories on its own filesystem, and the Coding Adapter has
to be able to bind-mount them into spawned task containers at the same
path. Both are handled with one Docker Compose override file.

> **Note** the Coding Adapter currently ships with open egress and read-write
> workspace mounts; review the threat model in
> [`resources/adapters/coding/README.md`](../resources/adapters/coding/README.md#container-conventions)

If you opted into the Software service during `make install`, the wizard
already copied the sample to `docker-compose.override.yaml`. Otherwise:
```sh
cp docker-compose.override.yaml.sample docker-compose.override.yaml
```

In either case, edit the override file and uncomment one or more
workspace mount entries.

Each entry binds a host directory under
`/mount/software/<group>` inside the container. Brain Core's
`software.workspace_root` defaults to `/mount/software`; operator
registration commands give a path relative to that root, so a directory
mounted at `/mount/software/repo` is addressable as
`repo/<dirname>`.

After editing the override file, restart so the new mounts take effect:
```sh
make down
make up
```

`make up` automatically includes `docker-compose.override.yaml` when
present, so the bind mounts you added are merged into the brain-core
container's spec.

Then register a workspace:
```
/workspace-register --path repo/brain
```

The Software Service resolves that to `/mount/software/repo/brain`,
validates it against the bind-mounted tree, and stores both the in-
container path and its host-side equivalent. The Coding Adapter reuses
the host equivalent as the bind-mount source when spawning task
containers, so brain-core and task containers see the workspace at the
same absolute path — no host-vs-container path translation leaks into
op handlers or executor code.

If the registered path isn't covered by a mount under
`software.workspace_root`, registration fails with a message pointing at
the override file. Add the missing mount and restart.

------------------------------------------------------------------------
## Coding-Runtime Customization
The Software Service spawns coding-task containers from one Brain-shipped
image, `brain/coding-runtime:base`. `make up` builds it automatically the
first time and on any subsequent change to its source files; you only
need `make coding-runtime-images` if you want to build it without
bringing the stack up.

The base contains every configured agent CLI (claude / codex / opencode),
plus standard system tools (git, curl, jq, ripgrep, Node 20). For
projects that only need those tools, the base is the entire story.

For projects that need extra tooling (a Rust toolchain, project-specific
Python build deps, custom Linux packages), drop a bash script at the
location matching the workspace's relative path:
```
~/.config/brain/coding_images/<workspace-relative-path>.sh
```

For example, the workspace registered as `--path repo/brain` reads
`~/.config/brain/coding_images/repo/brain.sh`. The script:
* runs as root during the image build, so `apt-get install -y ...` works
  without sudo;
* runs after Brain's standard tooling, so `git`, `curl`, `npm`, the agent
  CLIs, and friends are already on `PATH`;
* finishes with no special end-state — the image's runtime user is reset
  to `coder` automatically.

Example for a Rust project:
```sh
#!/usr/bin/env bash
set -euo pipefail
apt-get update
apt-get install -y --no-install-recommends rustc cargo
rm -rf /var/lib/apt/lists/*
```

Brain Core builds the per-workspace layer image lazily on the next task
spawn against that workspace, tagged `brain/coding-runtime:<slug>` (slug
is the relative path with `/` → `_`). Subsequent tasks reuse the cached
image until the script's mtime moves past the image's creation
timestamp; touching the script triggers a rebuild on the next task.

Build failures surface in the task lineage with the captured stderr —
`/code-status` will show what your script did wrong.

------------------------------------------------------------------------
## Surfaces
Brain has three ways to talk to it: a terminal-based console, a read-only
dashboard, and Signal. They are independent and optional — pick whichever
ones you want and skip the rest.

The console and dashboard run on the host under the project's Python
virtualenv. Signal runs entirely inside the Docker stack. If you only
plan to use Signal, you can skip everything in the next two sections.

### Console
The console is a Textual terminal UI for direct, interactive
conversation with Brain.

It needs Python at the version pinned in `.python-version` (currently
`3.14.4`). Any manager works — `pyenv`, `uv python install`, or similar
— as long as the pinned version is what your shell resolves.

Install the host-side Python dependencies into a managed virtualenv:
```sh
make deps
```

Launch the console:
```sh
bin/console
```

Type a message and Brain should reply in a few seconds. See
[`actors/console/README.md`](../actors/console/README.md) for keybindings.

### Dashboard
The dashboard is a read-only Textual app — *btop* for Brain — that shows
live runtime state: traces, turns, policy decisions, logs, host health,
and LLM activity.

It uses the same host-side virtualenv as the console. If you ran
`make deps` for the console, you're set; otherwise:
```sh
make deps
```

Launch it:
```sh
bin/dashboard
```

Panes populate from Brain Core within a few seconds of startup.

### Signal
Brain talks to Signal through a [signal-cli-rest-api] container in the
Compose stack. Brain is provisioned as a **standalone Signal account** —
it owns its own phone number, distinct from yours. The two accounts (yours
and Brain's) message each other directly.

Signal is fully optional. The `signal-api` container sits behind a Compose
profile (`signal`) and only starts when the install wizard recorded a
`signal.receive_e164` in `~/.config/brain/secrets.yaml`. If you declined
Signal during `make install`, `make up` skips the container entirely and
the relay's Signal callback registration is short-circuited at boot —
Brain still works fine over the local console.

To enable Signal later, re-run `make install RECONFIGURE=1` and answer yes
to the Signal prompt; the next `make up` will pick up the profile.

Prerequisites:
* A phone number for Brain that can receive an SMS (or a voice call).
  Throwaway numbers from services like Twilio or Google Voice work; the
  number doesn't have to be on a smartphone, but it must be reachable when
  the verification code is delivered.
* `profile.operator.signal_contact_e164` (your number) and
  `signal.receive_e164` (Brain's number) set in
  `~/.config/brain/secrets.yaml` — `make install` writes these for you.
  Both must be in E.164 form, including the leading `+`.
* `signal-api` healthy in `make ps` after `make up`.

Then run:
```sh
make signal-setup
```

The wizard walks you through the only two steps that genuinely need a
human:

1. **Captcha token.** Open the URL it prints
   (`https://signalcaptchas.org/registration/generate.html`), solve the
   captcha, and copy the token from the browser's developer console — the
   page silently tries to navigate to `signalcaptcha://<token>` and the
   console logs `Prevented navigation to "signalcaptcha://<token>"`. Paste
   that token (with or without the `signalcaptcha://` prefix) back into
   the wizard.
2. **Verification code.** Signal delivers a 6-digit code to Brain's number
   via SMS (or voice call, if you opted in). Type it in.

Everything else — health probing, registration, verification, and the
trust call that anchors first-message delivery — happens automatically via
signal-cli-rest-api. The account state is persisted to
`~/.local/state/brain/signal-cli/`, which is bind-mounted into the
container, so it survives stack restarts.

`make signal-setup` is re-runnable: if Brain's number is already
registered, it short-circuits to re-trusting the operator's identity (also
idempotent). Re-run it any time you need to refresh trust or recover from
a partial setup.

Send a message from your phone to Brain's number to confirm. Brain should
reply within a few seconds.

#### Manual fallback
If you'd rather drive the flow yourself, every step has a REST endpoint on
`signal-api`. Useful when you're scripting around it or debugging:

| Step | Method | Path |
|---|---|---|
| Health | `GET` | `/v1/health` |
| Already registered? | `GET` | `/v1/accounts` |
| Start registration | `POST` | `/v1/register/{brain_e164}` (body: `{"captcha":"…","use_voice":bool}`) |
| Verify code | `POST` | `/v1/register/{brain_e164}/verify/{code}` |
| Trust operator | `PUT` | `/v1/identities/{brain_e164}/trust/{operator_e164}` |

------------------------------------------------------------------------
## Optional Add-Ons
The base stack is fully functional without these. Each is opt-in:
* [Observability](observability.md) — local OTel, Langfuse, Grafana, Loki,
  and Prometheus overlay for traces, metrics, and logs.
* [Host MCP Gateway] — companion process that exposes localhost-only
  integrations (Apple Calendar, Reminders, etc.) to Brain over MCP.

------------------------------------------------------------------------
## Troubleshooting
A few situations a fresh install commonly hits.

*Brain Core is `unhealthy`.* Check Core's logs first:
```sh
docker compose logs brain-core
```
This is usually a missing or invalid runtime config key; cross-reference
with the [Configuration Reference](configuration.md).

*Console or dashboard can't connect to Core.* Both tools read `core.host`
and `core.port` from your runtime config. The defaults (`127.0.0.1:8898`)
match `BRAIN_CORE__PORT_BIND=8898:8898` from `.env.sample`; if you
changed one, change the other.

*Signal messages don't arrive.* Confirm the following in order:
1. `signal-api` is healthy in `make ps`.
2. Your number in `secrets.yaml` matches the sending number exactly,
   including the leading `+` and country code.
3. Re-run `make signal-setup` (idempotent) — this re-trusts your identity,
   which signal-cli requires before it releases held first-message
   payloads.
4. `~/.local/state/brain/signal-cli/` is non-empty, meaning registration
   succeeded.

*Obsidian writes fail.* The Local REST API plugin must be enabled in
Obsidian and `obsidian.api_key` must match the plugin's configured key.

------------------------------------------------------------------------
## Next
* [Configuration Reference](configuration.md) — every runtime key and how
  it resolves.
* [Boundaries & Responsibilities](boundaries-and-responsibilities.md) —
  conceptual model, service catalog, and shared infrastructure.
* [Manifesto](manifesto.md) — design philosophy and first principles.


[Host MCP Gateway]: https://github.com/cmtonkinson/host-mcp-gateway
[Local REST API]: https://github.com/coddingtonbear/obsidian-local-rest-api
[Obsidian]: https://obsidian.md
[Ollama]: https://ollama.com
[signal-cli-rest-api]: https://github.com/bbernhard/signal-cli-rest-api


------------------------------------------------------------------------
_End of Install Guide_
