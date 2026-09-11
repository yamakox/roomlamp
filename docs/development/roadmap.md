# Implementation roadmap

Roomlamp is a standalone Kubernetes TUI. It is inspired by [Headlamp](https://headlamp.dev/) but it is not a port of Headlamp's web, Electron, in-cluster, or plugin architecture.

This document is the human-readable record of how that TUI is built. Agents and contributors update it when a phase starts or finishes. Commands here must match `./pyproject.toml` and `AGENTS.md`.

## Cluster access (same as kubectl)

Roomlamp reads the same kubeconfig file kubectl uses. It does **not** need `kubectl create token`.

**On the control plane**, kubeadm prints this after a successful `kubeadm init`:

```bash
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

**On the development PC**, kubectl must be installed first. Then pull `admin.conf` over SSH (replace `user@control-plane` with your SSH login):

```bash
install -d -m 700 ~/.kube
umask 077
ssh -t user@control-plane 'sudo cat /etc/kubernetes/admin.conf' > ~/.kube/config
```

`ssh -t` gives remote `sudo` a TTY so it can prompt for a password. `umask 077` creates `~/.kube/config` as mode `600`. Confirm the copy with `kubectl get nodes`.

The resulting kubeconfig already holds the API server URL and credentials (usually a client certificate). kubectl and Roomlamp both honor:

1. `--kubeconfig` when the CLI flag is passed
2. the `KUBECONFIG` environment variable
3. `$HOME/.kube/config`

Headlamp's "create a ServiceAccount token" steps apply to its **in-cluster web UI**, where a browser often authenticates with a bearer token. Roomlamp is a local process, so it uses kubeconfig the way kubectl and Headlamp's desktop mode do.

Do not print or log tokens, client keys, or certificate data from that file.

Live cluster checks are optional. Use them only when the development PC can reach a Kubernetes API server **and** kubeconfig on that PC can control the cluster. External contributors do not need the maintainer lab (`10.0.0.1/22`, `https://10.0.0.1:6443`). If there is no reachable cluster, skip kubectl smoke tests and rely on `uv run pytest`.

When those conditions are met, verify **without SSH**:

```bash
kubectl get nodes
kubectl config current-context
```

Do not start `uv run roomlamp` in a way that blocks the agent. Humans run the TUI in the Cursor Terminal and quit with `q`.

## Headlamp source (local agents)

From this repository root, the default clone is `../../github/headlamp` (that is, `<dev-root>/github/headlamp` next to `<dev-root>/python/roomlamp`). Override with `HEADLAMP_SRC` if the clone lives somewhere else. Cloud agents do not have this tree.

Useful Headlamp files when adding features:

- Sidebar and navigation: `frontend/src/components/Sidebar/useSidebarItems.tsx`
- Resource models: `frontend/src/lib/k8s/`
- kubeconfig handling: `backend/pkg/kubeconfig/` (replace with the official Python client)

## Commands

```bash
uv sync
uv run roomlamp
uv run roomlamp --help
uv run pytest
uv run ruff check .
uv run ruff format .
```

Quit the TUI with `q`.

## Phases

### 1. Launch skeleton — done

**Goal:** start a Textual app, load kubeconfig, show the current context. No cluster API calls yet.

**Why this first:** prove that Roomlamp can use the same credentials as kubectl before listing resources.

**What shipped:**

- Click entry (`uv run roomlamp`, `--kubeconfig`, `--context`)
- Textual home screen with kubeconfig path, context, cluster, user, namespace, and context list
- Official `kubernetes` client used only to read context metadata (`list_kube_config_contexts`). `load_kube_config` is not called yet, so Roomlamp does not rewrite kubeconfig
- Blocking cluster I/O is not on the event loop in this phase because there is no live API traffic

**Layout:**

```text
src/roomlamp/
  cli.py
  app.py
  config.py
  k8s/client.py      # path resolution
  k8s/context.py     # context metadata
  ui/screens/home.py
tests/
docs/development/roadmap.md
```

**Not in this phase:** resource lists, Watch, logs, exec, YAML edit, RBAC gating, widgets package, `resources.py`, `watch.py`.

### 2. First read path — planned

**Goal:** namespace switch plus one resource type (Pod is the likely first choice) with list and detail views. Prefer Watch over polling.

**Depends on:** phase 1. Introduce `k8s/resources.py` and `k8s/watch.py` when this starts. Run Kubernetes calls with `asyncio.to_thread` or `threading`.

### 3. Common workloads — planned

**Goal:** reuse the list/detail pattern for Deployment, ReplicaSet, StatefulSet, Job, and similar workload objects (see Headlamp `frontend/src/components/workload/`).

### 4. Operator actions — planned

**Goal:** logs and YAML view first; then exec / apply / delete. Hide or disable actions the current kubeconfig user cannot perform (RBAC).

### 5. Wider catalog — planned

**Goal:** Services, ConfigMaps, Ingress, and other objects as requested. Multi-cluster via kubeconfig context switching. Plugins, charts, and in-cluster OIDC web login stay out of scope unless requested.

## Status

| Phase | Status |
| --- | --- |
| 1. Launch skeleton | Done |
| 2. First read path | Planned |
| 3. Common workloads | Planned |
| 4. Operator actions | Planned |
| 5. Wider catalog | Planned |
