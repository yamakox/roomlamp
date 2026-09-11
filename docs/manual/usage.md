# User manual

Roomlamp is a terminal UI for Kubernetes. This page describes how to use the **current skeleton**. Later phases will add resource lists and cluster actions; this document should stay in step with what the TUI actually does.

## Prerequisites

- A development PC (or any machine where you run Roomlamp) with [uv](https://docs.astral.sh/uv/)
- **kubectl** installed on that machine, so you can confirm the kubeconfig before starting the TUI
- Network access to a Kubernetes API server
- A kubeconfig that can authenticate to that cluster (the same file kubectl uses)

You do not need `kubectl create token`. A normal kubeadm `admin.conf` copied to `~/.kube/config` is enough. Control-plane and SSH copy steps are in [the implementation roadmap](../development/roadmap.md#cluster-access-same-as-kubectl).

Confirm the file works:

```bash
kubectl get nodes
kubectl config current-context
```

## Install and run

After Roomlamp is published to PyPI as `roomlamp`, the fastest way to try it is:

```bash
uvx roomlamp
```

From GitHub:

```bash
uv tool install --from https://github.com/yamakox/roomlamp.git roomlamp
roomlamp
```

From a source checkout (developers):

```bash
uv sync
uv run roomlamp
```

## Kubeconfig

Roomlamp follows the same lookup order as kubectl:

1. `--kubeconfig` on the command line
2. the `KUBECONFIG` environment variable
3. `~/.kube/config`

Examples:

```bash
roomlamp --kubeconfig ~/.kube/config
roomlamp --context kubernetes-admin@kubernetes
```

The TUI shows the kubeconfig path, current context, cluster name, user, namespace, and the list of contexts. It does not display tokens, client keys, or certificate data.

If the file is missing or invalid, Roomlamp still starts and shows the error on the home screen.

## Keys

| Key | Action |
| --- | --- |
| `q` | Quit |

## Current limitations

- No Pod, Deployment, or other resource lists
- No Watch, logs, exec, YAML edit, apply, or delete
- No plugin system
- Context is selected at launch (`--context` or `current-context`). Switching contexts inside the TUI is not implemented yet

When those features land, this manual should be updated in the same change.
