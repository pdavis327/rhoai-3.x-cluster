# Kueue GitOps (Unmanaged)

`DataScienceCluster` sets `spec.components.kueue.managementState: Unmanaged`. OpenShift AI does **not** manage ClusterQueue / ResourceFlavor / LocalQueue after first create. This directory is the source of truth.

Wave **5** — after the Kueue operator (wave 1) and DSC (wave 4).

## Topology

```
CPU workloads (workbenches, live-caption)
  → LocalQueue default
  → ClusterQueue default
  → ResourceFlavor default-flavor   (no node labels / taints)

Whisper / L40S models
  → LocalQueue large-gpu
  → ClusterQueue large-gpu-cq
  → ResourceFlavor large-gpu        (gpu-class=large, largegpu taint)

L4 models
  → LocalQueue small-gpu
  → ClusterQueue small-gpu-cq
  → ResourceFlavor small-gpu        (gpu-class=small, smallgpu taint)
```

`default` is **CPU-only**. Do not add `nvidia.com/gpu` or a GPU flavor to it — a missing flavor inactivates the entire queue and blocks CPU apps.

## Objects

| Kind | Name | Notes |
|------|------|--------|
| ResourceFlavor | `default-flavor` | Empty spec; any untainted CPU node |
| ResourceFlavor | `large-gpu` | L40S nodes |
| ResourceFlavor | `small-gpu` | L4 nodes |
| ClusterQueue | `default` | CPU/memory only; namespaceSelector `kueue.openshift.io/managed=true` |
| ClusterQueue | `large-gpu-cq` | cpu 80, memory 600Gi, gpu 10 |
| ClusterQueue | `small-gpu-cq` | cpu 40, memory 140Gi, gpu 5 |
| LocalQueue | `whisper-demo/default` | CPU apps in whisper-demo |
| LocalQueue | `whisper-demo/large-gpu` | Whisper ISVC |
| LocalQueue | `whisper-demo/small-gpu` | Optional L4 path |
| LocalQueue | `ray-workshop/default` | Ray workbench |
| LocalQueue | `ray-workshop/ray-workshop-queue` | Also points at ClusterQueue `default` |

LocalQueues require the namespace to exist. `whisper-demo` and `ray-workshop` are workshop projects, not created by this repo.

## Hardware profiles (must stay aligned)

| HardwareProfile | Scheduling | LocalQueue |
|-----------------|------------|------------|
| `nvidia-l40s-largegpu` | Queue | `large-gpu` |
| `nvidia-l4-smallgpu` | Queue | `small-gpu` |
| `cpu-local-queue` | Queue | `default` |
