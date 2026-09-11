# Roomlamp

Roomlamp is a Kubernetes TUI inspired by the core features of [Headlamp](https://headlamp.dev/).

It is in early development. The current build lists Pods and common workloads (Deployments, ReplicaSets, StatefulSets, DaemonSets, Jobs, CronJobs) with Watch-backed tables, read-only detail views, namespace switching, YAML view, and Pod logs. It does not edit cluster objects yet.

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

Roomlamp uses the same kubeconfig as kubectl (`~/.kube/config` by default). Press `q` to quit.

See the [user manual](docs/manual/usage.md) for prerequisites, kubeconfig setup, CLI flags, and what this release can do.
