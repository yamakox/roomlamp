# Roomlamp

Roomlamp is a Kubernetes TUI inspired by the core features of [Headlamp](https://headlamp.dev/).

It is in early development. The current build lists Pods and common workloads (Deployments, ReplicaSets, StatefulSets, DaemonSets, Jobs, CronJobs) with Watch-backed tables, detail views, namespace switching, YAML edit/apply, Pod logs, Pod exec, and delete. Actions the current kubeconfig user cannot perform are hidden.

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
