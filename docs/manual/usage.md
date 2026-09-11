# User manual

Roomlamp is a terminal UI for Kubernetes. This page describes the **current first-read path**: Pod list, Pod detail, and namespace switching.

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

If kubeconfig loads, the first screen is the Pod list for the context namespace (or `default`). If kubeconfig is missing or invalid, Roomlamp still starts and shows the error on the cluster screen.

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

The TUI does not display tokens, client keys, or certificate data.

## Keys

| Key | Action |
| --- | --- |
| `enter` | Open the selected Pod's detail |
| `n` | Switch namespace (includes All namespaces) |
| `c` | Show cluster / kubeconfig info |
| `p` | Return to the Pod list (from the cluster screen) |
| `r` | Reload the Pod list |
| `escape` | Back |
| `q` | Quit |

## What you see

The Pod table columns follow Headlamp's list and `kubectl get pods`: Namespace, Name, Ready, Status, Restarts, Node. Click a column header to sort ascending; click the same header again to sort descending. A different header starts over at ascending. The header subtitle is `context / namespace`. The list updates from the Kubernetes Watch API when the connection stays up.

Pod detail is read-only: metadata, phase, ready counts, node, pod IP, labels, and container lines.

## Current limitations

- No Deployment or other workload lists
- No logs, exec, YAML edit, apply, or delete
- No plugin system
- Cluster context is selected at launch (`--context` or `current-context`). Switching contexts inside the TUI is not implemented yet

When those features land, this manual should be updated in the same change.
