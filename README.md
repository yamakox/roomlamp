# Roomlamp

Roomlamp is a Kubernetes TUI inspired by the core features of [Headlamp](https://headlamp.dev/).

It is in early development. This release starts on a cluster home and opens kinds from a main menu.

**Home**

- Usage overview (CPU, memory, Pods, Nodes)
- Node list (open Node detail from `Cluster` → `Nodes`)

**Main menu**

- Cluster: Namespaces, Nodes
- Workloads: Pods, Deployments, ReplicaSets, StatefulSets, DaemonSets, Jobs, CronJobs
- Storage: PersistentVolumeClaims, PersistentVolumes, StorageClasses
- Network: Services, Endpoints, EndpointSlices, Ingresses
- Gateway: Gateways, GatewayClasses, HTTPRoutes (only when the cluster serves those CRDs)
- Security: ServiceAccounts, Roles (including ClusterRoles), RoleBindings (including ClusterRoleBindings)
- Configuration: ConfigMaps, Secrets

**Also in this release**

- Watch-backed tables and detail views
- Namespace switching on namespaced kinds
- kubeconfig context switching in this process only (does not rewrite the file)
- YAML edit/apply, Pod logs, Pod exec, and delete
- Actions the current kubeconfig user cannot perform are hidden

## How to Use

The easiest way to run Roomlamp is with [uvx](https://docs.astral.sh/uv/guides/tools/):

```bash
uvx roomlamp
```

You can install it from the GitHub repository:

```bash
uv tool install --from https://github.com/yamakox/roomlamp.git roomlamp

# Run roomlamp
roomlamp
```

Use `roomlamp --help` for more information about options.

Roomlamp uses the same kubeconfig as kubectl (`~/.kube/config` by default). Press `q` to quit.

See the [user manual](https://github.com/yamakox/roomlamp/blob/main/docs/manual/usage.md) for prerequisites, kubeconfig setup, CLI flags, and what this release can do.
