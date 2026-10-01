# RHOAI demo GitOps

This repository is the source of truth for **demo projects and cluster demo config** on a cluster that already has Red Hat OpenShift AI installed.

Platform install (operators, GPU stack, `DataScienceCluster`) lives in **[rhoai-argo](https://github.com/pdavis327/rhoai-argo)**.

This repo GitOps-deploys one MaaS model (`llama-3-2-1b-instruct` in `model-server`). Other InferenceServices and NIMs stay out of Git — create those from the OpenShift AI dashboard (or a dedicated demo repo) when you need them.

Dedicated demos that live elsewhere (not here):

- Credit card fraud
- Lemonade Stand

## What this deploys

| Layer | Path | Examples |
|-------|------|----------|
| Cluster demo config | `cluster-config/` | HardwareProfiles, Kueue flavors/ClusterQueues, EvalHub, MLflow, MCP catalog |
| Helm children | `argocd-applications/helm-charts.yaml` | model-registry, MinIO (in `country-of-origin-predictor`) |
| MCP | `argocd-applications/mcp.yaml` | kubernetes-mcp-server in `mcp-demo` |
| Demo projects | `projects/<namespace>/` | namespaces, workbenches, pipelines, MCP/OGX, apps |

## Prerequisites

1. OpenShift GitOps is running (installed by rhoai-argo).
2. OpenShift AI is healthy (`DataScienceCluster` Ready). Align DSC components in rhoai-argo with the demo set: AI Gateway / MaaS, MCP lifecycle, OGX, training operator, Kueue **Unmanaged**.
3. GPU nodes labeled/tainted to match HardwareProfiles (`gpu-type=smallgpu`, `gpu-class=large|small`, `largegpu` / `smallgpu` taints). MachineSet helpers stay in rhoai-argo `hardware-profile/`.
4. This repo is pushed to a URL Argo CD can fetch.

## Quick start (new cluster)

```bash
# After rhoai-argo is synced and RHOAI is Ready:
oc apply -f bootstrap/argocd-application.yaml

# Watch child apps
oc get applications -n openshift-gitops
```

Root Application: `rhoai-demo-workloads` (syncs `argocd-applications/`).

Then fill placeholder secrets (not synced by Argo):

```bash
# See secrets/placeholders/README.md
oc apply -f secrets/placeholders/country-of-origin-predictor/secrets.yaml
# edit CHANGE_ME values
```

## Repository layout

```
rhoai-3.x-cluster/
├── bootstrap/argocd-application.yaml   # apply once: demo root app
├── argocd-applications/                # child Applications
│   ├── cluster-config.yaml
│   ├── helm-charts.yaml
│   ├── mcp.yaml
│   └── projects/*.yaml
├── helm-values/kubernetes-mcp/values.yaml
├── cluster-config/
├── projects/<namespace>/
├── secrets/placeholders/
├── scripts/export-demo-resources.sh
└── README.md
```

Parent/child sync: change Application YAML → refresh **rhoai-demo-workloads**. Change project YAML → refresh the `demo-<namespace>` child.

## Demos included

| Namespace | Notes |
|-----------|--------|
| `country-of-origin-predictor` | Workbench, DSPA, MinIO via Helm (deploy models from the UI) |
| `whisper-demo` | Workbench, live-caption app, Kueue LocalQueues |
| `code-assistant` | code-server, NemoGuardrails, TrustyAI, OpenShift MCP, OGX playground |
| `ray-workshop` | Ray lab workbench + LocalQueues |
| `fine-tuning` / `gemma4` | Workbenches |
| `mcp-demo` | Kubernetes MCP server (Helm/OCI chart) |
| `models-as-a-service` / `ai-tenants` / `models-as-service-db` | MaaS tenant, subscription, and DB |
| `model-server` | MaaS `LLMInferenceService` + `MaaSModelRef` for llama-3.2-1b |
| `ticket-resolution` | Self-service agent + Zammad (rendered YAML) |
| `code-reviewer` | Pipeline listener |
| `rhoai-model-registries` | Helm chart only |

## Data that does **not** migrate with Git

YAML recreates objects, not disks. Notebook home directories, PVC contents, and MinIO objects are empty on a new cluster.

Strings still containing `APPS_DOMAIN` (ticket-resolution Zammad widget, code-reviewer `LLM_BASE_URL`, code-assistant llama-stack `base_url`) are the old cluster’s application route host. After sync, replace them with `apps.<your-cluster-domain>`.

## Re-export from a cluster

```bash
oc login ...   # cluster-admin
./scripts/export-demo-resources.sh
```

The exporter skips KServe InferenceServices, serving runtimes, GuardrailsOrchestrator (lemonade-stand), and dedicated fraud/lemonade namespaces. It does export the MaaS llama model in `model-server`. Review the diff before committing.

## Hardware profiles vs Kueue

Kueue is **Unmanaged** in the DSC. Flavors and ClusterQueues are in `cluster-config/kueue/`. LocalQueues are in `projects/whisper-demo` and `projects/ray-workshop`. HardwareProfiles are in `cluster-config/hardware-profiles/`.
