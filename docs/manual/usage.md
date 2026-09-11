# User manual

Roomlamp is a terminal UI for Kubernetes. This page describes the **current workload lists**: Pods plus Deployment, ReplicaSet, StatefulSet, DaemonSet, Job, and CronJob. You can switch namespaces and workload types. From a detail view you can edit YAML and apply it, or open Pod logs.

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
| `c` | Show cluster / kubeconfig info (on a list). Pick a container (on Pod logs) |
| `p` | Open the Pod list |
| `y` | Edit YAML (from a detail screen) |
| `l` | View Pod logs (from Pod detail) |
| `r` | Reload the current list or logs |
| `ctrl+s` | Apply the YAML editor buffer |
| `f8` | Dry-run the YAML editor buffer |
| `ctrl+r` | Reload YAML from the API |
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

Detail views summarize metadata, kind-specific status fields, labels, and container image lines from the pod template. From a detail screen, `y` opens the live object as YAML (`managedFields` hidden) in an editor. `ctrl+s` applies (POST, then PUT if the object already exists, matching Headlamp); `f8` dry-runs; `ctrl+r` reloads from the API. From a Pod, `l` opens logs for the default container (a running main container if there is one, matching Headlamp). The log view tails 100 lines with timestamps and follows the stream while the screen is open.

## Current limitations

- No JobSet or LeaderWorkerSet lists
- No exec, delete, or RBAC gating of actions
- No aggregated logs from a Deployment or other workload detail
- No plugin system
- Cluster context is selected at launch (`--context` or `current-context`). Switching contexts inside the TUI is not implemented yet

When those features land, this manual should be updated in the same change.
