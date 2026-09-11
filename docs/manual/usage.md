# User manual

Roomlamp is a terminal UI for Kubernetes. This page describes the **current workload lists**: Pods plus Deployment, ReplicaSet, StatefulSet, DaemonSet, Job, and CronJob. Detail views are read-only. You can switch namespaces and workload types.

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

If kubeconfig loads, the first screen is the Pod list for the context namespace (or `default`). Press `w` to open Deployments and the other workload lists. If kubeconfig is missing or invalid, Roomlamp still starts and shows the error on the cluster screen.

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
| `enter` | Open the selected item's detail |
| `n` | Switch namespace (includes All namespaces) |
| `w` | Switch workload type |
| `c` | Show cluster / kubeconfig info |
| `p` | Open the Pod list |
| `r` | Reload the current list |
| `escape` | Back |
| `q` | Quit |

## What you see

List columns follow Headlamp and `kubectl get` for that kind. Click a column header to sort ascending; click the same header again to sort descending. A different header starts over at ascending. The header subtitle is `context / namespace` (workload lists also show the kind). The list updates from the Kubernetes Watch API when the connection stays up.

| Kind | Columns |
| --- | --- |
| Pods | Namespace, Name, Ready, Status, Restarts, Node |
| Deployments | Namespace, Name, Ready, Up-to-date, Available, Age |
| ReplicaSets | Namespace, Name, Desired, Current, Ready, Age |
| StatefulSets | Namespace, Name, Ready, Replicas, Age |
| DaemonSets | Namespace, Name, Desired, Current, Ready, Up-to-date, Available, Age |
| Jobs | Namespace, Name, Completions, Conditions, Duration, Age |
| CronJobs | Namespace, Name, Schedule, Suspend, Active, Last Schedule, Age |

Detail views are read-only: metadata, kind-specific status fields, labels, and container image lines from the pod template.

## Current limitations

- No JobSet or LeaderWorkerSet lists
- No logs, exec, YAML edit, apply, or delete
- No plugin system
- Cluster context is selected at launch (`--context` or `current-context`). Switching contexts inside the TUI is not implemented yet

When those features land, this manual should be updated in the same change.
