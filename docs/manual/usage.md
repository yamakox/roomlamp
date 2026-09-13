# User manual

Roomlamp is a terminal UI for Kubernetes. This page describes the **cluster home** (CPU / memory / Pod / Node overview and a Node list), **Cluster** (Namespace, Node), **workload lists** (Pods, Deployment, ReplicaSet, StatefulSet, DaemonSet, Job, CronJob), **Storage** (PersistentVolumeClaim, PersistentVolume, StorageClass), **Network** (Service, Endpoints, EndpointSlice, Ingress), **Gateway** (Gateway, GatewayClass, HTTPRoute when those CRDs are installed), **Security** (ServiceAccount, Role, RoleBinding), and **Configuration** (ConfigMap, Secret). Open kinds from the main menu. Press `c` to switch kubeconfig context without rewriting the file. From a detail view you can edit YAML and apply it, open Pod logs, exec into a Pod, or delete the object. Keys for actions the current kubeconfig user cannot perform are hidden.

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

If kubeconfig loads, the first screen is the cluster home (context / cluster / user, usage overview, and a Node list). Press `m` to open the main menu, then Cluster, Workloads, Storage, Network, Gateway, Security, or Configuration for those lists. Press `c` to pick another kubeconfig context; that change stays in this process and does not rewrite kubeconfig. Gateway kinds are hidden when the API does not serve them (no Gateway CRDs). If kubeconfig is missing or invalid, Roomlamp still starts and shows the error on the home screen.

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
| `m` | Open the main menu (groups, then kinds). Each list ends with Back: kinds return to groups, groups close the menu |
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

The home screen shows Context, Cluster, User, and the kubeconfig path, then htop-style bars for CPU, Memory, Pods, and Nodes, then a Node table. The home view scrolls as a whole when the terminal is short. CPU and Memory come from Metrics Server (`metrics.k8s.io`); if it is missing, those bars show unavailable. If metrics are forbidden, those bars are hidden. The home view refreshes every 60 seconds and with `r`. List columns follow Headlamp and `kubectl get` for that kind:

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

Click a column header to sort ascending; click the same header again to sort descending. A different header starts over at ascending. The header subtitle is `context / namespace` (lists also show the kind). PersistentVolumes, StorageClasses, GatewayClasses, Namespaces, and Nodes are cluster-scoped, so the subtitle omits a namespace. Resource lists update from the Kubernetes Watch API when the connection stays up. API errors show the HTTP Reason first, then the response body (JSON Status objects as YAML). Switching context with `c` always opens the picker (even when the file has one context). Choosing the current context shows `No changes to apply`. A successful switch returns to home and rebuilds the API client; a failed switch stays on the previous context and screen. YAML edit and Pod exec omit `c`.

Detail views summarize metadata, kind-specific status fields, and labels. Workload details also list container image lines from the pod template. Storage details include Headlamp extra fields that fit a TUI (requested size, volume mode, PV source, StorageClass parameters). Network details include Service traffic policy and ports, Endpoints subsets, EndpointSlice conditions, and Ingress rules and TLS. Gateway details include listener protocol/port/hostname, addresses, conditions, and HTTPRoute parent refs, matches, and backends. Security details include ServiceAccount secrets and automount, Role / ClusterRole rules, and RoleBinding / ClusterRoleBinding roleRef and subjects. The Roles list also shows ClusterRoles, and the Role Bindings list also shows ClusterRoleBindings (Headlamp's mixed tables). Configuration details include ConfigMap data and binaryData keys, and Secret type plus data key names with byte sizes (values are not decoded in the detail view). Cluster details include Namespace status and conditions, and Node roles, taints, addresses, capacity, allocatable, and system info. Open Node detail from Cluster → Nodes, not from the home Node table. From a detail screen, `y` opens the live object as YAML (`managedFields` hidden). If you can `update` the object, that YAML is an editor: `ctrl+s` applies (POST, then PUT if the object already exists, matching Headlamp); `f8` dry-runs; `ctrl+r` reloads from the API. Without `update`, the YAML stays read-only. From a Pod, `l` opens logs for the default container (a running main container if there is one, matching Headlamp) when you can `get` the `log` subresource. The log view tails 100 lines with timestamps and follows the stream while the screen is open. `e` opens an interactive exec session in that same default container when you can `create` on `exec`. Roomlamp tries `bash`, then `/bin/bash`, then `sh`, then `/bin/sh` (Headlamp's linux list; windows pods get `powershell.exe` / `cmd.exe`). `f2` switches container; `ctrl+]` detaches. `escape` and `q` are sent to the shell, not used to leave the screen. `d` on a list or detail screen asks for confirmation, then deletes the object (Jobs use Background deletion; Force delete sets a zero grace period) when you have `delete`. System Namespaces require typing the name before Delete. On Pods, Evict is also offered (`pods/eviction`, verb `create`) when that subresource is allowed.

## Current limitations

- No VolumeAttributesClass lists
- No IngressClass or NetworkPolicy lists
- No GRPCRoute, TCPRoute, UDPRoute, ReferenceGrant, BackendTLSPolicy, or BackendTrafficPolicy lists
- No ServiceAccount token create or show UI
- No HPA, VPA, PodDisruptionBudget, ResourceQuota, LimitRange, PriorityClass, RuntimeClass, Lease, or admission webhook lists
- Secret detail does not decode or copy data values (YAML still shows the live API object)
- No Port Forwarding
- No JobSet or LeaderWorkerSet lists
- No attach or debug / ephemeral containers
- Exec is a TTY text log (ANSI stripped), not a full terminal emulator; tools such as vim or top may not render correctly
- No aggregated logs from a Deployment or other workload detail
- No plugin system

When those features land, this manual should be updated in the same change.
