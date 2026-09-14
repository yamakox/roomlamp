# User manual

Roomlamp is a terminal UI for Kubernetes. Open kinds from the main menu. Press `c` to switch kubeconfig context without rewriting the file. Keys for actions the current kubeconfig user cannot perform are hidden.

This page describes what this release can do.

## This release

**Home**

- Context, cluster, user, and kubeconfig path
- CPU / memory / Pod / Node usage overview
- Node list (list only; open Node detail from `Cluster` → `Nodes`)

**Cluster**

- Namespaces
- Nodes

**Workloads**

- Pods, Deployments, ReplicaSets, StatefulSets, DaemonSets, Jobs, CronJobs

**Storage**

- PersistentVolumeClaims, PersistentVolumes, StorageClasses

**Network**

- Services, Endpoints, EndpointSlices, Ingresses

**Gateway** (when the cluster serves those CRDs)

- Gateways, GatewayClasses, HTTPRoutes

**Security**

- ServiceAccounts
- Roles (including ClusterRoles)
- RoleBindings (including ClusterRoleBindings)

**Configuration**

- ConfigMaps, Secrets

**Operator actions**

- Watch-backed tables and detail views
- Namespace switching on namespaced kinds
- kubeconfig context switching in this process only (does not rewrite the file)
- YAML edit/apply, Pod logs, Pod exec, and delete
- Actions the current kubeconfig user cannot perform are hidden

## Prerequisites

- A machine with [uv](https://docs.astral.sh/uv/)
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

The fastest way to try it is:

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

## First screen

If kubeconfig loads, the first screen is the cluster home.

- Identity: context / cluster / user, and the kubeconfig path
- Usage overview and a Node list
- `m` opens the main menu (`Cluster`, `Workloads`, `Storage`, `Network`, `Gateway`, `Security`, `Configuration`)
- `c` opens the kubeconfig context picker; the change stays in this process and does not rewrite kubeconfig
- Gateway kinds are hidden when the API does not serve them (no Gateway CRDs)
- If kubeconfig is missing or invalid, Roomlamp still starts and shows the error on the home screen

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

The TUI does not display tokens, client keys, or certificate data. Switching context with `c` uses the same file in this process only (`persist_config=False`); it does not run `kubectl config use-context` or change `current-context` on disk.

## Keys

| Key | Action |
| --- | --- |
| `m` | Open the main menu (groups, then kinds). Each list ends with `Back`: kinds return to groups, groups close the menu |
| `c` | Switch kubeconfig context (home, lists, and details). On Pod logs, pick a container |
| `h` | Return to the home screen (hidden on home) |
| `enter` | Open the selected item's detail (not used on the home Node table) |
| `n` | Switch namespace (includes All namespaces; hidden on cluster-scoped lists) |
| `y` | Edit YAML (from a detail screen) |
| `l` | View Pod logs (from Pod detail) |
| `e` | Exec into a Pod (from Pod detail) |
| `d` | Delete the selected item (list or detail). Confirm, then Delete / Force delete / Evict (Pods). System namespaces (`default`, `kube-public`, `kube-node-lease`, `kube-system`) require typing the name first |
| `f2` | Pick a container (on Pod exec) |
| `ctrl+]` | Detach from Pod exec |
| `r` | Reload the home overview, current list, detail, or logs |
| `ctrl+s` | Apply the YAML editor buffer |
| `f8` | Dry-run the YAML editor buffer |
| `ctrl+r` | Reload YAML from the API |
| `escape` | Back (on exec, this key goes to the remote shell) |
| `q` | Quit (on exec, this key goes to the remote shell) |

## What you see

The home screen shows Context, Cluster, User, and the kubeconfig path, then htop-style bars for CPU, Memory, Pods, and Nodes, then a Node table.

- The home view scrolls as a whole when the terminal is short
- CPU and Memory come from Metrics Server (`metrics.k8s.io`); if it is missing, those bars show unavailable
- If metrics are forbidden, those bars are hidden
- The home view refreshes every 60 seconds and with `r`

List columns follow Headlamp and `kubectl get` for that kind:

**Home**

| Kind | Columns |
| --- | --- |
| Nodes | Name, CPU, Memory, Ready, Roles, Internal IP, Version, Age |

**Cluster**

| Kind | Columns |
| --- | --- |
| Namespaces | Name, Status, Age |
| Nodes | Name, Ready, Taints, Roles, Internal IP, External IP, Version, Age |

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

**Network**

| Kind | Columns |
| --- | --- |
| Services | Namespace, Name, Type, Cluster IP, External IP, Ports, Selector, Age |
| Endpoints | Namespace, Name, Addresses, Age |
| EndpointSlices | Namespace, Name, Endpoints, Ports, Address Type, Age |
| Ingresses | Namespace, Name, Class, Hosts, Address, Ports, Age |

**Gateway**

| Kind | Columns |
| --- | --- |
| Gateways | Namespace, Name, Class, Addresses, Listeners, Conditions, Age |
| GatewayClasses | Name, Controller, Conditions, Age |
| HTTPRoutes | Namespace, Name, Hostnames, Parents, Rules, Age |

**Security**

| Kind | Columns |
| --- | --- |
| Service Accounts | Namespace, Name, Secrets, Age |
| Roles | Kind, Name, Namespace, Age |
| Role Bindings | Kind, Name, Namespace, Role, Users, Groups, Service Accounts, Age |

**Configuration**

| Kind | Columns |
| --- | --- |
| Config Maps | Namespace, Name, Data, Age |
| Secrets | Namespace, Name, Type, Data, Age |

## Lists

- Click a column header to sort ascending; click the same header again to sort descending. A different header starts over at ascending.
- The header subtitle is `context / namespace` (lists also show the kind).
- PersistentVolumes, StorageClasses, GatewayClasses, Namespaces, and Nodes are cluster-scoped, so the subtitle omits a namespace.
- Resource lists update from the Kubernetes Watch API when the connection stays up.
- API errors show the HTTP Reason first, then the response body (JSON Status objects as YAML).
- Switching context with `c` always opens the picker (even when the file has one context).
- Choosing the current context shows `No changes to apply`.
- A successful switch returns to home and rebuilds the API client; a failed switch stays on the previous context and screen.
- YAML edit and Pod exec omit `c`.

## Details

Every detail view summarizes metadata, kind-specific status fields, and labels. Open Node detail from `Cluster` → `Nodes`, not from the home Node table.

### Cluster

- Namespace status and conditions
- Node roles, taints, addresses, capacity, allocatable, and system info

### Workloads

- Container image lines from the pod template

### Storage

- Requested size, volume mode, PV source, and StorageClass parameters (Headlamp extra fields that fit a TUI)

### Network

- Service traffic policy and ports
- Endpoints subsets
- EndpointSlice conditions
- Ingress rules and TLS

### Gateway

- Listener protocol, port, and hostname
- Addresses and conditions
- HTTPRoute parent refs, matches, and backends

### Security

- ServiceAccount secrets and automount
- Role / ClusterRole rules
- RoleBinding / ClusterRoleBinding roleRef and subjects
- The `Roles` list also shows ClusterRoles, and the `Role Bindings` list also shows ClusterRoleBindings (Headlamp's mixed tables)

### Configuration

- ConfigMap data and binaryData keys
- Secret type plus data key names with byte sizes (values are not decoded in the detail view)

## Actions

### YAML

From a detail screen, `y` opens the live object as YAML (`managedFields` hidden).

- If you can `update` the object, that YAML is an editor: `ctrl+s` applies (POST, then PUT if the object already exists, matching Headlamp); `f8` dry-runs; `ctrl+r` reloads from the API
- Without `update`, the YAML stays read-only

### Pod logs

From a Pod, `l` opens logs for the default container (a running main container if there is one, matching Headlamp) when you can `get` the `log` subresource.

- The log view tails 100 lines with timestamps and follows the stream while the screen is open

### Pod exec

`e` opens an interactive exec session in that same default container when you can `create` on `exec`.

- Linux: `bash`, then `/bin/bash`, then `sh`, then `/bin/sh` (Headlamp's linux list)
- Windows: `powershell.exe` / `cmd.exe`
- `f2` switches container; `ctrl+]` detaches
- `escape` and `q` are sent to the shell, not used to leave the screen

### Delete

`d` on a list or detail screen asks for confirmation, then deletes the object when you have `delete`.

- Jobs use Background deletion
- Force delete sets a zero grace period
- System Namespaces (`default`, `kube-public`, `kube-node-lease`, `kube-system`) require typing the name before Delete
- On Pods, Evict is also offered (`pods/eviction`, verb `create`) when that subresource is allowed

## Compared with Headlamp

Roomlamp is inspired by Headlamp's core features. It is not a port of Headlamp's web, Electron, in-cluster, or plugin architecture.

- Single Python process TUI (`uvx roomlamp` / `uv run roomlamp`). Not a browser UI, Electron desktop app, or in-cluster dashboard
- Authentication uses the same kubeconfig as kubectl. There is no in-cluster ServiceAccount token create or show UI
- Context switching is in-process only (`persist_config=False`). It does not rewrite `current-context` on disk
- Main menu groups follow Headlamp's sidebar order. Kinds that are not implemented are omitted. Gateway kinds appear only when the API serves those CRDs
- The home Node table is a list only. Node detail is `Cluster` → `Nodes`
- `Roles` / `Role Bindings` mix ClusterRole(s) the same way Headlamp's tables do
- Exec is a TTY text log (ANSI stripped), not a full terminal emulator; tools such as vim or top may not render correctly
- No plugin system

## Current limitations

**Workloads**

- No JobSet or LeaderWorkerSet lists
- No aggregated logs from a Deployment or other workload detail

**Storage**

- No VolumeAttributesClass lists

**Network**

- No IngressClass or NetworkPolicy lists
- No Port Forwarding

**Gateway**

- No GRPCRoute, TCPRoute, UDPRoute, ReferenceGrant, BackendTLSPolicy, or BackendTrafficPolicy lists

**Security**

- No ServiceAccount token create or show UI

**Configuration**

- No HPA, VPA, PodDisruptionBudget, ResourceQuota, LimitRange, PriorityClass, RuntimeClass, Lease, or admission webhook lists
- Secret detail does not decode or copy data values (YAML still shows the live API object)

**Actions**

- No attach or debug / ephemeral containers
