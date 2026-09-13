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
- Workload overview: `frontend/src/components/workload/`
- Workload lists: `frontend/src/components/deployments/List.tsx`, `replicaset/List.tsx`, `statefulset/List.tsx`, `daemonset/List.tsx`, `job/List.tsx`, `cronjob/List.tsx`
- Resource models: `frontend/src/lib/k8s/`
- Pod logs: `frontend/src/lib/k8s/pod.ts`, `frontend/src/components/pod/Details.tsx`
- YAML view: `frontend/src/components/common/Resource/ViewButton.tsx`
- YAML edit / apply: `frontend/src/components/common/Resource/EditorDialog.tsx`, `frontend/src/lib/k8s/api/v1/apply.ts`
- Pod exec: `frontend/src/lib/k8s/pod.ts`, `frontend/src/components/common/Terminal.tsx`, `frontend/src/components/pod/Details.tsx`
- Delete / evict: `frontend/src/components/common/Resource/DeleteButton.tsx`, `frontend/src/lib/k8s/KubeObject.ts`, `frontend/src/lib/k8s/pod.ts`
- RBAC gating: `frontend/src/components/common/Resource/AuthVisible.tsx`, `frontend/src/lib/k8s/KubeObject.ts` (`getAuthorization`)
- kubeconfig handling: `backend/pkg/kubeconfig/` (replace with the official Python client)
- Storage lists: `frontend/src/components/storage/ClaimList.tsx`, `VolumeList.tsx`, `ClassList.tsx`
- Storage details: `frontend/src/components/storage/ClaimDetails.tsx`, `VolumeDetails.tsx`, `ClassDetails.tsx`
- Storage models: `frontend/src/lib/k8s/persistentVolumeClaim.ts`, `persistentVolume.ts`, `storageClass.ts`
- Network lists: `frontend/src/components/service/List.tsx`, `endpoints/List.tsx`, `endpointSlices/List.tsx`, `ingress/List.tsx`
- Network details: `frontend/src/components/service/Details.tsx`, `endpoints/Details.tsx`, `endpointSlices/Details.tsx`, `ingress/Details.tsx`
- Network models: `frontend/src/lib/k8s/service.ts`, `endpoints.ts`, `endpointSlices.ts`, `ingress.ts`

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

### 2. First read path — done

**Goal:** namespace switch plus Pod list and detail views. Prefer Watch over polling.

**What shipped:**

- Official client with `persist_config=False` (`k8s/client.py`, `k8s/cluster.py`)
- Namespace list and Pod list/get (`k8s/resources.py`)
- Pod Watch in a background thread (`k8s/watch.py`); list/get use `asyncio.to_thread`
- TUI: Pod table (Name / Ready / Status / Restarts / Node), detail screen, namespace picker including All namespaces
- Default screen is the Pod list when kubeconfig loads; `c` opens the cluster summary from phase 1
- Columns follow Headlamp `frontend/src/components/pod/List.tsx` and `kubectl get pods`

**Keys:** `enter` detail, `n` namespace, `c` cluster, `p` pods, `r` refresh, `escape` back, `q` quit.

**Not in this phase:** other workload types, logs, exec, YAML edit, apply/delete, in-TUI context switch.

### 3. Common workloads — done

**Goal:** reuse the list/detail pattern for Deployment, ReplicaSet, StatefulSet, Job, and similar workload objects (see Headlamp `frontend/src/components/workload/` and the Workloads sidebar).

**What shipped:**

- Apps and batch reads through the official client (`k8s/workloads.py`); Watch shares the Pod watch loop (`k8s/watch.py`)
- TUI: `w` picks Pods, Deployments, ReplicaSets, StatefulSets, DaemonSets, Jobs, or CronJobs
- List columns follow Headlamp plus `kubectl get` (Ready / replica counts, Job completions, CronJob schedule)
- Read-only detail with kind-specific fields (selector, strategy, Headlamp extraInfo where it maps cleanly)
- Default screen is still the Pod list from phase 2

**Keys:** `w` workload type, `p` pods, plus `enter` / `n` / `c` / `r` / `escape` / `q` from phase 2.

**Layout:**

```text
src/roomlamp/k8s/workloads.py
src/roomlamp/ui/screens/workloads.py
src/roomlamp/ui/screens/kinds.py
tests/test_k8s_workloads.py
tests/test_workloads.py
```

**Not in this phase:** JobSet, LeaderWorkerSet, logs, exec, YAML edit, apply/delete, in-TUI context switch.

### 4. Operator actions — done

**Goal:** logs and YAML view first; then exec / apply / delete. Hide or disable actions the current kubeconfig user cannot perform (RBAC).

**What shipped:**

- Read-only YAML dump from Pod and workload detail (`y`), with `managedFields` hidden (Headlamp's default)
- Pod logs from Pod detail (`l`). Last 100 lines with timestamps; follows the stream when Watch is enabled. `c` picks a container (main, init, then ephemeral, same order as Headlamp)
- YAML from Pod and workload detail (`y`) is an editor. `ctrl+s` applies; `f8` dry-runs; `ctrl+r` reloads from the API; unchanged buffers are not sent
- Apply matches Headlamp `apply.ts`: POST, then PUT on 409 Conflict or 403 Forbidden. `resourceVersion` is dropped for create and restored for replace. Namespaced objects without a namespace use the object's namespace (or `default`)
- YAML and JSON (including multi-document YAML) go through the official client's `DynamicClient`. Blocking apply I/O stays off the Textual event loop (`asyncio.to_thread`)
- Exec from Pod detail (`e`) opens an interactive TTY via the official client's `kubernetes.stream` (`connect_get_namespaced_pod_exec`)
- Default exec container matches logs (running main, then running init, then the first spec name)
- Shell fallback matches Headlamp `Terminal.tsx`: `bash`, `/bin/bash`, `sh`, `/bin/sh` on linux; `powershell.exe`, `cmd.exe` on windows; all of those when the OS is unknown (`kubernetes.io/os` / `beta.kubernetes.io/os` on the pod node selector)
- `f2` picks a container on exec (not `c`, so typing `c` in the shell still works). `ctrl+]` detaches; `escape` and `q` go to the remote TTY. A successful process exit closes the screen. After every shell fails, Enter reconnects
- Exec output is shown as a text log (ANSI stripped); this is not xterm.js, so full-screen tools such as vim are out of scope here
- Delete from Pod and workload detail (`d`) and from the selected list row. Confirm, then DELETE via `DynamicClient`
- Jobs use `propagationPolicy=Background` (Headlamp `KubeObject.delete`). Force delete sets `gracePeriodSeconds=0`
- Pods also offer Evict (`POST pods/eviction`, Headlamp `pod.evict`). After a successful delete from a detail screen, Roomlamp returns to the list
- RBAC gating via `SelfSubjectAccessReview`, matching Headlamp AuthVisible. Unauthorized keys are hidden (fail closed if the review itself errors). YAML without `update` stays a read-only view

**This increment (RBAC):**

- Delete uses verb `delete`; Pod evict uses verb `create` + subresource `eviction`
- Logs use `get` + `log`; exec uses `create` + `exec`; YAML apply uses `update`
- Blocking SSAR I/O stays off the Textual event loop (`asyncio.to_thread`)

**Keys:** `y` YAML, `ctrl+s` Apply, `f8` Dry Run, `ctrl+r` refresh YAML, `l` logs (Pods), `c` container on the log screen, `e` exec (Pods), `f2` container on the exec screen, `ctrl+]` detach exec, `d` delete (list or detail), `escape` back (not on the exec TTY).

**Layout:**

```text
src/roomlamp/k8s/dump.py
src/roomlamp/k8s/logs.py
src/roomlamp/k8s/apply.py
src/roomlamp/k8s/errors.py
src/roomlamp/k8s/exec.py
src/roomlamp/k8s/delete.py
src/roomlamp/k8s/auth.py
src/roomlamp/ui/screens/yaml_view.py
src/roomlamp/ui/screens/logs.py
src/roomlamp/ui/screens/exec.py
src/roomlamp/ui/screens/containers.py
src/roomlamp/ui/screens/delete.py
tests/test_k8s_dump.py
tests/test_k8s_logs.py
tests/test_k8s_apply.py
tests/test_k8s_errors.py
tests/test_k8s_exec.py
tests/test_k8s_delete.py
tests/test_k8s_auth.py
tests/test_yaml_view.py
tests/test_exec.py
tests/test_delete.py
tests/test_auth.py
```

**Not in this phase:** attach, debug / ephemeral containers, JSON Patch (Headlamp EditButton), server-side apply, create-from-empty YAML, live conflict watch in the editor, JSON log prettify, workload-aggregated logs, previous-container logs, a full VT/xterm emulator, multi-select delete, Namespace type-to-confirm (Namespaces are not in the catalog yet).

## Later phases

Phases 1–7 covered the **Workloads** sidebar (Pods and common controllers), operator actions, a cluster home with metrics, a two-level group menu, **Storage**, and **Network**. From here, one Headlamp in-cluster sidebar group is one phase.

Do not copy Headlamp's web, Electron, in-cluster, or plugin architecture. Reuse the list / detail / Watch / YAML / delete / RBAC path already shipped.

### 5. Home, metrics, and navigation — done

**Goal:** start on a cluster home, show CPU / memory / Pod / Node overview plus a Node list, and open kinds from a group menu (`m`) instead of workload-only footer keys.

**What shipped:**

- Default screen is always the home screen (kubeconfig errors stay here; no cluster API on that path)
- Identity strip: Context, Cluster, User, kubeconfig path. No token / key / cert data. No in-TUI context switch (phase 12)
- Overview bars (htop-style text, not circular charts), matching Headlamp `frontend/src/components/cluster/Overview.tsx`:
  - CPU and Memory: node `metrics.k8s.io/v1beta1` usage totals over `status.capacity` (not allocatable)
  - Pods: Ready (Succeeded or Ready=True) / total
  - Nodes: Ready condition True / total
- Node table under the overview (Headlamp `frontend/src/components/node/List.tsx` columns that fit a TUI): Name, CPU, Memory, Ready, Roles, Internal IP, Version, Age. Enter does **not** open Node detail
- Metrics 404 (no Metrics Server): CPU / Memory unavailable; Pods / Nodes still from the core API. Metrics 403: hide metric bars and show a short error (fail closed)
- Refresh: 60s poll + `r` (Headlamp overview does not Watch; the metrics API has no useful Watch)
- Main menu (`m`): Cluster, Workloads, Storage, Network, Gateway, Security, Configuration. Submenu lists **implemented kinds only**. A group with no kinds is visible but not selectable (notify, stay on the menu). Both lists end with Back (kinds return to groups; groups close the menu). Escape still closes the menu. Workloads kinds are the current `PICKER_KINDS` (no JobSet / LeaderWorkerSet)
- Footer leftmost: `m` Menu, `h` Home (`h` hidden on home). Drop `w` / `p` / `c` from lists. Keep `n` on lists. YAML / logs / exec / delete keys stay as they are. Do not add `m` / `h` on exec
- Screen stack: Home → list → detail → modals. Opening a kind pops back to Home then pushes the list. `h` pops until Home; it does not push another Home

**Keys:** `m` menu, `h` home (not on home), `n` namespace (lists), `r` refresh, plus phase 4 operator keys on the screens that already have them.

**Layout:**

```text
src/roomlamp/k8s/nodes.py
src/roomlamp/k8s/metrics.py
src/roomlamp/ui/nav.py
src/roomlamp/ui/bindings.py
src/roomlamp/ui/usage.py
src/roomlamp/ui/screens/home.py
src/roomlamp/ui/screens/menu.py
src/roomlamp/ui/screens/kinds.py
src/roomlamp/k8s/cluster.py
tests/test_k8s_nodes.py
tests/test_k8s_metrics.py
tests/test_home.py
tests/test_menu.py
```

**Not in this phase:** Node detail / YAML / delete, Namespace catalog objects, Events, Storage or other group screens, in-TUI context switch, Watch on the home screen, a `ui/widgets/` package.

### Sidebar groups (phases 6+)

**How to run a later phase** (same rules as Headlamp and Roomlamp `AGENTS.md`):

- Small increments. If a group is large, ship the most-used kinds first (the way phase 2 shipped Pods before phase 3 shipped the other workloads).
- Read the matching Headlamp list/detail under `frontend/src/components/` and the model under `frontend/src/lib/k8s/`. Do not import React, plugins, or the Go proxy.
- Prefer Watch over polling. Keep blocking API calls off the Textual event loop.
- Hide or disable actions the current kubeconfig cannot perform (phase 4 SSAR).
- Do not add kinds, screens, or packages until that increment starts. Do not freeze this list as a product checklist; skip or split a group when the user asks.
- Add each shipped kind to `ui/nav.py` so it appears under its group in the phase 5 menu.
- Plugins, Helm charts, the resource map, Electron-only port-forward, Advanced Search, Scheduling (alpha), and in-cluster OIDC stay out of scope unless requested.

Headlamp sidebar order after Workloads (`frontend/src/components/Sidebar/useSidebarItems.tsx`): Storage, Network, Gateway, Security, Configuration, then Custom Resources. Cluster sits above Workloads in Headlamp. Phase 5 already shows a Node **list** on home; Namespace/Node **objects** (detail, YAML, delete) wait until the cluster-catalog phase. The existing `n` namespace picker stays. JobSet and LeaderWorkerSet stay out of Workloads until requested.

**Priority:**

- **Normal** — ship in that phase (first increment, then the rest of the group's Normal kinds).
- **Low** — skip unless the user asks. Do not start a Low kind while Normal work in the same phase is unfinished.

Low kinds (do not implement unless requested):

- Storage: VolumeAttributesClass
- Network: IngressClass, NetworkPolicy (Port Forwarding stays out of scope)
- Gateway: GRPCRoute, TCPRoute, UDPRoute, ReferenceGrant, BackendTLSPolicy, BackendTrafficPolicy
- Configuration: HPA, VPA, PodDisruptionBudget, ResourceQuota, LimitRange, PriorityClass, RuntimeClass, Lease, MutatingWebhookConfiguration, ValidatingWebhookConfiguration
- Custom Resources (the Headlamp CRD sidebar)

Ingress stays **Normal**: it is still the common HTTP front for Service / Endpoints, and it was in the old wider-catalog goal. Listener TLS for Gateway API lives on Gateway / HTTPRoute, not on BackendTLSPolicy.

### 6. Storage — done

**Goal:** PersistentVolumeClaim, PersistentVolume, and StorageClass lists and details (Headlamp Storage).

**What shipped:**

- Core and storage.k8s.io reads through the official client (`k8s/storage.py`); Watch shares the existing watch loop (`k8s/watch.py`)
- TUI: Storage group in the phase 5 menu opens PVC, PV, and StorageClass. No new footer keys
- PVC is namespaced (`n` still switches namespace, including All namespaces). PV and StorageClass are cluster-scoped (`n` hidden)
- List columns follow Headlamp plus `kubectl get` (phase, volume/claim, capacity, access modes, storage class, reclaim policy, provisioner, default, binding mode)
- Read-only detail with Headlamp extraInfo that maps cleanly (requested size, volume mode, PV source, reason/message, SC parameters and mount options)
- YAML / delete / RBAC reuse the phase 4 path. StorageClass SSAR uses `storage.k8s.io/storageclasses`

**Keys:** `m` menu, `h` home, `n` namespace (PVC lists only), `r` refresh, `y` YAML and `d` delete from detail (and `d` from the list).

**Layout:**

```text
src/roomlamp/k8s/storage.py
src/roomlamp/ui/screens/storage.py
src/roomlamp/ui/nav.py
src/roomlamp/k8s/watch.py
src/roomlamp/k8s/cluster.py
src/roomlamp/k8s/auth.py
src/roomlamp/k8s/delete.py
tests/test_k8s_storage.py
tests/test_storage.py
```

**Low:** VolumeAttributesClass.

**Not in this phase:** CSI extras beyond Headlamp's Storage subList, snapshots, other sidebar groups.

### 7. Network — done

**Goal:** Headlamp Network kinds. Start with Service. Then Endpoints and EndpointSlices (already used in this lab). Then Ingress.

**What shipped:**

- Core, discovery.k8s.io, and networking.k8s.io reads through the official client (`k8s/network.py`); Watch shares the existing watch loop (`k8s/watch.py`)
- TUI: Network group in the phase 5 menu opens Service, Endpoints, EndpointSlice, and Ingress. No new footer keys
- All four kinds are namespaced (`n` still switches namespace, including All namespaces)
- List columns follow Headlamp plus `kubectl get` (type, cluster/external IP, ports, selector, addresses, address type, class, hosts)
- Read-only detail with Headlamp extraInfo that maps cleanly (traffic policy, session affinity, subsets, slice conditions, Ingress rules/TLS). No Port Forwarding and no related-object tables on Service detail
- YAML / delete / RBAC reuse the phase 4 path. EndpointSlice SSAR uses `discovery.k8s.io/endpointslices`; Ingress uses `networking.k8s.io/ingresses`

**Keys:** `m` menu, `h` home, `n` namespace, `r` refresh, `y` YAML and `d` delete from detail (and `d` from the list).

**Layout:**

```text
src/roomlamp/k8s/network.py
src/roomlamp/ui/screens/network.py
src/roomlamp/ui/nav.py
src/roomlamp/k8s/watch.py
src/roomlamp/k8s/cluster.py
src/roomlamp/k8s/auth.py
src/roomlamp/k8s/delete.py
tests/test_k8s_network.py
tests/test_network.py
```

**Low:** IngressClass, NetworkPolicy.

**Not in this phase:** Port Forwarding (Headlamp hides it except in Electron). Gateway API belongs in phase 8.

### 8. Gateway — planned

**Goal:** Gateway API objects from Headlamp's Gateway (beta) group, when the cluster has those CRDs.

**First increment:** Gateway, GatewayClass, and HTTPRoute. Hide kinds the API does not serve.

**Low:** GRPCRoute, TCPRoute, UDPRoute, ReferenceGrant, BackendTLSPolicy, BackendTrafficPolicy.

**Not in this phase:** installing Gateway CRDs.

### 9. Security — planned

**Goal:** ServiceAccount, Role, and RoleBinding (Headlamp Security subList).

**Not in this phase:** ClusterRole / ClusterRoleBinding unless requested (they are not on Headlamp's Security subList). Token create/show UI.

### 10. Configuration — planned

**Goal:** ConfigMap first, then Secret.

**Low:** HPA, VPA, PodDisruptionBudget, ResourceQuota, LimitRange, PriorityClass, RuntimeClass, Lease, MutatingWebhookConfiguration, ValidatingWebhookConfiguration.

**Not in this phase:** decoding or copying Secret data into logs. Keep Secret bytes off the status line.

### 11. Cluster catalog — planned

**Goal:** Namespace as a catalog object, and Node **detail** / YAML / delete (Headlamp Cluster subList). The home screen already lists Nodes (phase 5). Include Namespace type-to-confirm delete if delete stays in scope.

**Not in this phase:** Advanced Search, the resource map, replacing the existing namespace picker, replacing the home Node table.

### 12. Kubeconfig contexts — planned

**Goal:** switch cluster context inside the TUI from kubeconfig, the same way kubectl uses contexts. This is not a Headlamp sidebar group; it replaces Headlamp's multi-cluster chooser for a local process.

**Not in this phase:** plugins, charts, in-cluster OIDC web login.

Custom Resources stay **Low** and have no phase until requested.

## Status

| Phase | Status |
| --- | --- |
| 1. Launch skeleton | Done |
| 2. First read path | Done |
| 3. Common workloads | Done |
| 4. Operator actions | Done |
| 5. Home, metrics, and navigation | Done |
| 6. Storage | Done |
| 7. Network | Done |
| 8. Gateway | Planned |
| 9. Security | Planned |
| 10. Configuration | Planned |
| 11. Cluster catalog | Planned |
| 12. Kubeconfig contexts | Planned |
