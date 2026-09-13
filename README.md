# Roomlamp

Roomlamp is a Kubernetes TUI inspired by the core features of [Headlamp](https://headlamp.dev/).

It is in early development. The current build starts on a cluster home (usage overview and a Node list), opens kinds from a main menu (Cluster, Workloads, Storage, Network, Gateway, Security, and Configuration), and lists Namespaces, Nodes, Pods, common workloads, PersistentVolumeClaims, PersistentVolumes, StorageClasses, Services, Endpoints, EndpointSlices, Ingresses, Gateways, GatewayClasses, HTTPRoutes, ServiceAccounts, Roles (including ClusterRoles), RoleBindings (including ClusterRoleBindings), ConfigMaps, and Secrets with Watch-backed tables, detail views, namespace switching (namespaced kinds), YAML edit/apply, Pod logs, Pod exec, and delete. Gateway kinds appear only when the cluster serves those CRDs. Actions the current kubeconfig user cannot perform are hidden.

## How to Use

The easiest way to run Roomlamp is with [uvx](https://docs.astral.sh/uv/guides/tools/) (after the `roomlamp` package is on PyPI):

```bash
uvx roomlamp
```

You can install it from the GitHub repository:

```bash
uv tool install --from https://github.com/yamakox/roomlamp.git roomlamp

# Run roomlamp
roomlamp
```

Use "roomlamp --help" for more information about options.

Roomlamp uses the same kubeconfig as kubectl (`~/.kube/config` by default). Press `q` to quit.

See the [user manual](docs/manual/usage.md) for prerequisites, kubeconfig setup, CLI flags, and what this release can do.
