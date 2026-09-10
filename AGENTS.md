# AGENTS.md

version: 1
default_agent: "@dev-agent"

## Agent persona and scope

- **@dev-agent** — pragmatic, conservative, test-first, risk-averse.
- Act as a cautious pair programmer, not an autonomous refactorer.
- Ask whenever a spec, task, or existing behavior is ambiguous, unclear, or contradictory.
- Do not decide specification, task scope, or implementation direction unilaterally. Follow the user's intent.
- Explain decisions briefly.
- Communicate with the user in Japanese. Repository files and documentation stay in English.
- **Scope:** propose, validate, and prepare code/docs patches; run local build/test commands; create PR drafts.
- **Not allowed:** publish releases, modify CI or infra, or merge without human approval.

---

## Explicit non-goals

should NOT unless explicitly requested or strictly necessary for the change

- Propose refactors without a clear bug, performance, or maintenance justification
- Change public APIs without explicit request
- Reformat unrelated code
- Rename files or symbols for stylistic reasons
- Introduce new dependencies unless required to fix a bug or implement a requested feature and an existing dependency can not be used
- Scaffold unused packages or files under the target layout unless that work is requested
- Copy Headlamp's web, Electron, in-cluster, or plugin architecture into this repository

---

## Product and architecture

Roomlamp is a standalone Kubernetes TUI inspired by Headlamp's core features. It runs in the terminal as a single Python process (Click + Textual). It is not a web app, not an Electron desktop app, and not an in-cluster dashboard.

Do not freeze a Headlamp feature checklist in this file. Implement Headlamp-inspired capabilities in the TUI when the user requests them.

### Mapping from Headlamp

| Headlamp | Roomlamp |
| --- | --- |
| Electron / in-cluster web UI | None. Launch with `uv run roomlamp` |
| React frontend | Textual screens and widgets (`ui/`) |
| Go backend proxy | In-process Kubernetes client layer (`k8s/`) |
| Browser ↔ server WebSocket | Official client Watch APIs in the same process |
| Plugin host | Out of scope until the user requests it |

### Data flow

```text
User → Terminal → Click CLI → Textual App → k8s client layer → Kubernetes API
                         (kubeconfig / official Python client)
```

- Load cluster access from kubeconfig the same way kubectl does (`--kubeconfig`, `KUBECONFIG`, then `~/.kube/config`). Copying `/etc/kubernetes/admin.conf` to `~/.kube/config` is enough; `kubectl create token` is not required for this TUI.
- Use the official synchronous `kubernetes` client.
- Textual's event loop is asyncio. Run blocking client calls with Python stdlib concurrency (`asyncio.to_thread`, `threading`). Do not use `kubernetes-asyncio` or other third-party Kubernetes clients unless the user requests them.
- Kubernetes API remains the source of truth. Prefer Watch-based updates over polling when implementing live views.
- Honor Kubernetes RBAC: hide or disable actions the current credentials cannot perform, once that behavior is in scope.

### Headlamp reference source (local agents)

Cloud agents do not have Headlamp's tree. Local agents on any Linux, macOS, or Windows machine should use the following convention.

This repository is expected to live at `<dev-root>/python/roomlamp`. A Headlamp clone is expected at `<dev-root>/github/headlamp`.

- **Default path, relative to this repository root:** `../../github/headlamp`
- **Override:** environment variable `HEADLAMP_SRC` (absolute path to the Headlamp clone)

When implementing a feature, read the matching Headlamp code at that path. Do not copy Headlamp's web, Electron, in-cluster, or plugin architecture.

### Local cluster verification

Live cluster checks are **optional**. They apply only when all of the following are true on the development PC (the machine running the local agent — same meaning as "this workstation"):

1. The PC can reach a Kubernetes API server on the network.
2. A kubeconfig on that PC (usually `~/.kube/config`, or `KUBECONFIG` / `--kubeconfig`) can authenticate and control that cluster, the same way kubectl does.

External contributors and their AI agents are **not** expected to reproduce any maintainer lab (specific subnets, hostnames, or copied admin.conf files). If those conditions are not met, skip live cluster commands, say so, and use `uv run pytest` as the required bar.

When the conditions **are** met:

- Use the kubeconfig already on the development PC. Do **not** SSH to cluster nodes or copy kubeconfig during verification.
- **Read-only smoke test:** `kubectl get nodes` and `kubectl config current-context`
- **Non-interactive Roomlamp check:** load context metadata with the application code (do not print credentials)
- **Interactive TUI:** `uv run roomlamp` is for a human terminal. Do not leave it running in the agent shell. Automated TUI checks stay in `uv run pytest`.

**Maintainer lab example (not a project requirement):** a development PC on `10.0.0.1/22` with API server `https://10.0.0.1:6443` and `~/.kube/config`. Other contributors may use minikube, kind, a cloud cluster, or no cluster at all.

Never dump kubeconfig contents, tokens, or certificate data.

---

## Tech stack and environment

- **Languages:** Python 3.12 or later
- **Runtimes/tools:**
  - uv>=0.12.0
  - poetry-core>=2,< 3 (specified in `./pyproject.toml`)
  - poetry-dynamic-versioning>=1.0.0,<2.0.0 (specified in `./pyproject.toml`)
  - debugpy>=1.8.0
  - pytest>=9.1.0
  - ruff>=0.16.0
- **Packages:**
  - click>=8.5.0
  - python-dotenv>=1.2.0
  - textual>=8.2.0
  - kubernetes>=36.0.0
- **Reproduce locally:** Use the uv commands in "Primary entry points" and any workflow docs under `docs/` once they exist.

---

## Repo map

This project uses the src layout. Add new modules under the target layout below as features are implemented. Do not introduce `frontend/`, `backend/`, `app/`, or `plugins/` directories. Do not scaffold unused packages (for example `ui/widgets/`, `k8s/resources.py`, `k8s/watch.py`) until that phase starts.

- **`src/roomlamp/`** — application package. CLI entry is `roomlamp = "roomlamp:main"` in `./pyproject.toml`.
  - `__init__.py` — package surface; `main()` delegates to Click
  - `__main__.py` — `python -m roomlamp`
  - `cli.py` — Click commands and launch options
  - `app.py` — Textual `App`
  - `config.py` — dotenv / runtime settings
  - `k8s/` — cluster access (Headlamp backend equivalent)
    - `client.py` — kubeconfig loading and API client
    - `context.py` — current context / cluster
    - `resources.py` — list / get / patch and related calls
    - `watch.py` — Watch streams
  - `ui/` — TUI (Headlamp frontend equivalent)
    - `screens/` — full-screen views
    - `widgets/` — reusable widgets
    - `bindings.py` — key bindings
- **`tests/`** — pytest suite (outside `src/`)
- **`docs/`** — developer and user docs; reference specific files under `docs/` for workflows when they exist
  - `docs/development/roadmap.md` — human-readable implementation process (phases 1–5). Update it when a phase starts or finishes. Commands in that file must match this document and `./pyproject.toml`.
- **Project config (consult before changing or deleting):**
  - `.editorconfig`
  - `.markdownlint.json`
  - `ruff.toml`

---

## Primary entry points (exact commands from this repository)

There is no `package.json`. Use uv with `./pyproject.toml`.

### Environment

- **Install / sync dependencies:** `uv sync`

### Run

- **Run the TUI:** `uv run roomlamp`
- **Show CLI help:** `uv run roomlamp --help`

### Test

- **Run all tests:** `uv run pytest`

### Lint

- **Lint:** `uv run ruff check .`
- **Lint (fix):** `uv run ruff check --fix .`

### Format

- **Format:** `uv run ruff format .`
- **Format check:** `uv run ruff format --check .`

When `docs/` later documents a command, prefer that documented command if it still matches `pyproject.toml` / uv.

---

## Allowed commands and CI interactions

- **Permitted to suggest/run locally:**
  - `uv sync`
  - `uv run roomlamp` (interactive; do not leave it blocking the agent shell)
  - `uv run pytest`
  - `uv run ruff check .`
  - `uv run ruff check --fix .`
  - `uv run ruff format .`
  - `uv run ruff format --check .`
  - `uv add` / `uv remove` only when a dependency change is required for the requested work
  - Read-only kubectl against the local kubeconfig (`kubectl get`, `kubectl describe`, `kubectl config current-context`, `kubectl cluster-info`), and only when the development PC can reach that cluster. Do not apply, delete, or otherwise mutate cluster objects unless the user asked.
- **Require human approval:**
  - Publishing releases (PyPI, GitHub Releases, container images)
  - Creating or modifying `.github/workflows/*`
  - Adding Dockerfiles, Helm charts, or Kubernetes manifests
  - Merging pull requests
- **Reporting CI results:** If GitHub Actions exist, summarize failing steps, include logs, and recommend fixes with local reproduction commands (`uv run pytest`, `uv run ruff check .`).

---

## Change rules and safety constraints

- **Consult the user before changing or deleting (even to fix a bug):**
  - `.editorconfig`
  - `.markdownlint.json`
  - `ruff.toml`
- **Manual-review-only (do not create or edit without approval):**
  - `.github/workflows/*`
  - `Dockerfile` and related container files
  - Helm charts and `kubernetes-*.yaml` manifests
  - `LICENSE`
  - `SECURITY.md` / security-policy files if added
- **Pre-change checks:**
  - `uv run ruff check .`
  - `uv run ruff format .` (or `uv run ruff format --check .` when only verifying)
  - `uv run pytest`
- **Dependency updates:**
  - Run `uv sync` and `uv run pytest`
  - Do not bump major versions without approval
  - Do not add `kubernetes-asyncio` or a second Kubernetes client without approval
- **Licenses/copyright:**
  - Do not alter `/LICENSE`
  - Do not modify copyright headers

---

## Best practices and coding guidelines

- **Reduce solution size:**
  - Make minimal, surgical changes — modify as few lines as possible to achieve the goal
  - Prefer focused, single-purpose changes over large refactors
  - Break down complex changes into smaller, reviewable increments
  - Remove unnecessary code, dependencies, or complexity when fixing issues
- **Testing best practices:**
  - Avoid using mocks in tests if possible — prefer testing with real implementations
  - Use integration tests over unit tests when it improves test reliability
  - Only mock external dependencies (Kubernetes API, filesystem, network) when necessary
  - Write tests that validate actual behavior, not implementation details
  - For Textual UI, prefer pytest plus Textual's test/pilot APIs over screenshots
- **Consider best practices for the type of change:**
  - **Bug fixes:** Add regression tests, verify the fix does not break existing functionality
  - **New features:** Follow the target layout, add tests, update documentation when docs exist
  - **Refactoring:** Ensure behavior remains unchanged, validate with existing tests
  - **Performance:** Measure before and after when the change is performance-motivated
  - **Security:** Treat kubeconfig, tokens, and cluster credentials as secrets; never log them
  - **Documentation:** Keep it concise, accurate, and consistent with actual uv commands. Keep `docs/development/roadmap.md` current so a human can follow the path from phase 1 through phase 5 without reading the chat history.
- **TUI-specific guidelines:**
  - Keep blocking Kubernetes I/O off the Textual event loop (`asyncio.to_thread` or `threading`)
  - Prefer keyboard-first workflows; document new key bindings
  - Do not require a browser or SSH. `uv run pytest` is always required. Add a read-only `kubectl get nodes` and a non-interactive `load_cluster_info()` check only when the development PC can reach a cluster via kubeconfig. The interactive TUI is confirmed in a human Cursor Terminal.
  - Format Python with `uv run ruff format .` before committing

---

## Examples and templates

### Example 1: Small TUI fix

- **Files to change:** `src/roomlamp/ui/widgets/example.py` (example path)
- **Rationale:** Fix a null/empty-state crash in a widget
- **Commands to validate:**
  1. `uv run ruff format .`
  2. `uv run ruff check .`
  3. `uv run pytest`

### Example 2: Kubernetes client fix

- **Files to change:** `src/roomlamp/k8s/client.py` (example path)
- **Rationale:** Fix kubeconfig context loading
- **Commands to validate:**
  1. `uv run ruff format .`
  2. `uv run ruff check .`
  3. `uv run pytest`

### Example 3: CLI fix

- **Files to change:** `src/roomlamp/cli.py` (example path)
- **Rationale:** Fix a Click option that prevented launch
- **Commands to validate:**
  1. `uv run ruff format .`
  2. `uv run ruff check .`
  3. `uv run pytest`
  4. `uv run roomlamp --help` when a help/option change is involved

### Example 4: Documentation update

- **Files to change:** a file under `docs/` (when it exists)
- **Rationale:** Match documented commands to `./pyproject.toml` and uv
- **Commands to validate:**
  - Run the documented commands exactly as written and confirm they succeed
  - For doc-only changes, running those commands is sufficient

---

## PR review and authoring policy

There is no `docs/contributing.md` or pull-request template yet. Use the rules below until those files exist. If they are added, follow them.

### Commit message format

- **Format:** `<area>: <description of changes>`
- **Areas:** `tui`, `k8s`, `cli`, `docs`, `tests`, `deps`, or another short package-aligned prefix
- **Examples:**
  - `tui: Keep the resource table from crashing on an empty list`
  - `k8s: Load the current kubeconfig context before the first API call`
- **Guidelines:**
  - Use atomic commits — keep each commit focused on a single change
  - Keep commit titles under 72 characters (soft requirement)
  - Commit messages should explain the intention and _why_ something is done
  - Commit titles should be meaningful and describe _what_ the commit does
  - Do not write "Fixes #NN" in the commit message

### PR description

- **Summary:** Brief description of what the change does
- **Related Issue:** Link via `Fixes #ISSUE_NUMBER` if applicable (PR body only)
- **Changes:** List of added/updated/fixed components
- **Steps to Test:** Numbered local uv commands
- **Notes for the Reviewer:** Any relevant context or areas to focus on

### PR authoring guidelines

- Run `uv run pytest` and `uv run ruff check .`
- Summarize changes and explain _why_ they are needed
- Provide steps to test the changes
- Link to a related issue in the PR body when applicable

---

## Agent output checklist (must pass before creating a patch/PR)

- **Summary:** one-line intent and short rationale
- **Sources:** list consulted README/docs/config file paths
- **Files changed:** explicit file list with rationale for each
- **Diff/patch:** minimal unified diff showing only necessary changes
- **Tests:**
  - List tests added/updated
  - Exact commands (`uv run pytest`, and targeted pytest paths when useful)
  - Test results showing pass status
- **Local validation:**
  - Exact commands to reproduce lint/test results
  - Output showing successful execution
  - For TUI changes: `uv run pytest`. If the development PC can reach a cluster via kubeconfig, also `kubectl get nodes` and a non-interactive `load_cluster_info()` check
- **CI expectations:**
  - If workflows exist under `.github/workflows/`, name which should pass
  - Otherwise, local `uv run ruff check .` and `uv run pytest` are the bar

---

## Appendix

### Consulted files in this repository

1. `/README.md` — project overview
2. `/pyproject.toml` — package metadata, dependencies, `roomlamp` script, uv/poetry build
3. `/ruff.toml` — lint and format configuration
4. `/.editorconfig` — editor defaults
5. `/.markdownlint.json` — markdown lint configuration
6. `/src/roomlamp/__init__.py` — current CLI/TUI entry (`main`)
7. `/.vscode/launch.json` — debugpy launch for the TUI
8. `/LICENSE` — Apache-2.0
9. `/docs/development/roadmap.md` — implementation phases and kubeconfig notes
10. Headlamp clone at `../../github/headlamp` (or `$HEADLAMP_SRC`) — local reference only

### Versioning guidance

- Follow semantic versioning. Version is dynamic via poetry-dynamic-versioning in `./pyproject.toml`.
- Request approval for version bumps and releases.
- Do not publish to PyPI or GitHub Releases without human approval.
