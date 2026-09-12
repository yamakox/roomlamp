# User manual

Roomlamp is a terminal UI for Kubernetes. This page describes the **cluster home** (CPU / memory / Pod / Node overview and a Node list), **workload lists** (Pods, Deployment, ReplicaSet, StatefulSet, DaemonSet, Job, CronJob), and **Storage** (PersistentVolumeClaim, PersistentVolume, StorageClass). Open kinds from the main menu. From a detail view you can edit YAML and apply it, open Pod logs, exec into a Pod, or delete the object. Keys for actions the current kubeconfig user cannot perform are hidden.

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

If kubeconfig loads, the first screen is the cluster home (context / cluster / user, usage overview, and a Node list). Press `m` to open the main menu, then Workloads or Storage for those lists. If kubeconfig is missing or invalid, Roomlamp still starts and shows the error on the home screen.

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
| `m` | Open the main menu (groups, then kinds) |
| `h` | Return to the home screen (hidden on home) |
| `enter` | Open the selected item's detail (not used on the home Node table) |
| `n` | Switch namespace (includes All namespaces; hidden on cluster-scoped lists) |
| `c` | Pick a container (on Pod logs) |
| `y` | Edit YAML (from a detail screen) |
| `l` | View Pod logs (from Pod detail) |
| `e` | Exec into a Pod (from Pod detail) |
| `d` | Delete the selected item (list or detail). Confirm, then Delete / Force delete / Evict (Pods) |
| `f2` | Pick a container (on Pod exec) |
| `ctrl+]` | Detach from Pod exec |
| `r` | Reload the home overview, current list, or logs |
| `ctrl+s` | Apply the YAML editor buffer |
| `f8` | Dry-run the YAML editor buffer |
| `ctrl+r` | Reload YAML from the API |
| `escape` | Back (on exec, this key goes to the remote shell) |
| `q` | Quit (on exec, this key goes to the remote shell) |

## What you see

The home screen shows Context, Cluster, User, and the kubeconfig path, then htop-style bars for CPU, Memory, Pods, and Nodes, then a Node table. CPU and Memory come from Metrics Server (`metrics.k8s.io`); if it is missing, those bars show unavailable. If metrics are forbidden, those bars are hidden. The home view refreshes every 60 seconds and with `r`. List columns follow Headlamp and `kubectl get` for that kind:

**Home**

| Kind | Columns |
| --- | --- |
| Nodes | Name, CPU, Memory, Ready, Roles, Internal IP, Version, Age |

**Workloads**

| Kind | Columns |
| --- | --- |
| Pods | Namespace, Name, Ready, Status, Restarts, Node |
| Deployments | Namespace, Name, Ready, Up-to-date, Available, Age |
| ReplicaSets | Namespace, Name, Desired, Current, Ready, Age |
| StatefulSets | Namespace, Name, Ready, Replicas, Age |
| DaemonSets | Namespace, Name, Desired, Current, Ready, Up-to-date, Available, Age |
| Jobs | Namespace, Name, Completions, Conditions, Duration, Age |
| CronJobs | Namespace, Name, Schedule, Suspend, Active, Last Schedule, Age |

**Storage**

| Kind | Columns |
| --- | --- |
| PersistentVolumeClaims | Namespace, Name, Status, Volume, Capacity, Access Modes, Storage Class, Age |
| PersistentVolumes | Name, Capacity, Access Modes, Reclaim Policy, Status, Claim, Storage Class, Age |
| StorageClasses | Name, Provisioner, Default, Reclaim Policy, Volume Binding Mode, Allow Volume Expansion, Age |

Click a column header to sort ascending; click the same header again to sort descending. A different header starts over at ascending. The header subtitle is `context / namespace` (lists also show the kind). PersistentVolumes and StorageClasses are cluster-scoped, so the subtitle omits a namespace. Resource lists update from the Kubernetes Watch API when the connection stays up. API errors show the HTTP Reason first, then the response body (JSON Status objects as YAML).

Detail views summarize metadata, kind-specific status fields, and labels. Workload details also list container image lines from the pod template. Storage details include Headlamp extra fields that fit a TUI (requested size, volume mode, PV source, StorageClass parameters). From a detail screen, `y` opens the live object as YAML (`managedFields` hidden). If you can `update` the object, that YAML is an editor: `ctrl+s` applies (POST, then PUT if the object already exists, matching Headlamp); `f8` dry-runs; `ctrl+r` reloads from the API. Without `update`, the YAML stays read-only. From a Pod, `l` opens logs for the default container (a running main container if there is one, matching Headlamp) when you can `get` the `log` subresource. The log view tails 100 lines with timestamps and follows the stream while the screen is open. `e` opens an interactive exec session in that same default container when you can `create` on `exec`. Roomlamp tries `bash`, then `/bin/bash`, then `sh`, then `/bin/sh` (Headlamp's linux list; windows pods get `powershell.exe` / `cmd.exe`). `f2` switches container; `ctrl+]` detaches. `escape` and `q` are sent to the shell, not used to leave the screen. `d` on a list or detail screen asks for confirmation, then deletes the object (Jobs use Background deletion; Force delete sets a zero grace period) when you have `delete`. On Pods, Evict is also offered (`pods/eviction`, verb `create`) when that subresource is allowed.

## Current limitations

- No Node detail, YAML, or delete (the home Node table is list-only)
- No VolumeAttributesClass lists
- No JobSet or LeaderWorkerSet lists
- No attach or debug / ephemeral containers
- Exec is a TTY text log (ANSI stripped), not a full terminal emulator; tools such as vim or top may not render correctly
- No aggregated logs from a Deployment or other workload detail
- No plugin system
- Cluster context is selected at launch (`--context` or `current-context`). Switching contexts inside the TUI is not implemented yet

When those features land, this manual should be updated in the same change.
