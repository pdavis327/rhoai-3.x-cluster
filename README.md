# RHOAI 3.3 Cluster Configuration — ArgoCD GitOps

This repository uses **OpenShift GitOps (ArgoCD)** to declaratively deploy and configure **Red Hat OpenShift AI (RHOAI) 3.3** and all of its operator dependencies on a blank OpenShift cluster.

A separate **Helm charts repo** ([openshiftai-helmcharts](https://github.com/pdavis327/openshiftai-helmcharts)) contains reusable charts for workloads (model deployment, model registry, MinIO, hardware profiles). This repo references those charts via ArgoCD Applications defined in `manifests/argocd-applications/helm-charts-repo.yaml`.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  rhoai-3.3-cluster (this repo)                                   │
│                                                                  │
│  bootstrap/          One-time setup (apply manually)             │
│    ├── openshift-gitops-subscription.yaml                        │
│    ├── argocd-cluster-admin.yaml                                 │
│    ├── argocd-rbac.yaml                                          │
│    └── argocd-application.yaml  ← root Application               │
│                                                                  │
│  manifests/          Managed by ArgoCD (root app syncs this)     │
│    ├── operators/              Wave 0-2: Operator installs       │
│    ├── gpu-config/             Wave 3: NFD + GPU config          │
│    ├── rhoai-config/           Wave 4: DataScienceCluster        │
│    └── argocd-applications/    Child ArgoCD Applications         │
│        └── helm-charts-repo.yaml                                 │
│            ├── model-registry    → Helm chart                    │
│            ├── minio             → Helm chart                    │
│            ├── modeldeploy       → Helm chart                    │
│            ├── hardware-profile  → Helm chart                    │
│            └── hardware-profile-small → Helm chart               │
│                                                                  │
└────────────────────────┬─────────────────────────────────────────┘
                         │ source.repoURL
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  openshiftai-helmcharts (separate repo)                          │
│    ├── model-registry/    ModelRegistry CR + MySQL               │
│    ├── minio/             MinIO object storage                   │
│    ├── models/modeldeploy/  InferenceService + ServingRuntime    │
│    └── hardware-profile/  HardwareProfile for GPU scheduling     │
└──────────────────────────────────────────────────────────────────┘
```

## What Gets Deployed

### Operators (via sync waves)

| Sync Wave | Resources | Description |
|-----------|-----------|-------------|
| 0 | Namespaces | All operator namespaces |
| 1 | OperatorGroups + Subscriptions | NFD, NVIDIA GPU, KMM, and all RHOAI dependency operators |
| 2 | RHOAI Operator | OperatorGroup + Subscription (waits for dependency operators) |
| 3 | NFD Instance, ClusterPolicy | GPU operator configuration |
| 4 | DataScienceCluster, Telemetry ConfigMap | RHOAI operator configuration |

### Helm Chart Applications

| Application | Chart | Namespace | Description |
|-------------|-------|-----------|-------------|
| model-registry | `model-registry` | `rhoai-model-registries` | ModelRegistry CR + MySQL database |
| minio | `minio` | `minio` | MinIO object storage for model artifacts |
| modeldeploy | `models/modeldeploy` | `country-of-origin-predictor` | InferenceService + vLLM ServingRuntime |
| hardware-profile | `hardware-profile` | `redhat-ods-applications` | GPU HardwareProfile (nvidia-l40s) |
| hardware-profile-small | `hardware-profile` | `redhat-ods-applications` | Small GPU HardwareProfile (nvidia-l4-small) |

### Operators Installed

- Node Feature Discovery (NFD)
- NVIDIA GPU Operator
- Kernel Module Management (KMM)
- Red Hat OpenShift AI (RHOAI)
- JobSet Operator
- Custom Metrics Autoscaler (KEDA)
- Leader Worker Set
- Red Hat Connectivity Link (Kuadrant)
- Kueue
- SR-IOV Network Operator
- Red Hat OpenTelemetry
- Tempo Operator
- Cluster Observability Operator

## Prerequisites

- OpenShift Container Platform 4.19+
- `oc` CLI installed and logged in as `cluster-admin`
- A GPU-capable node (or MachineSet) available in your cluster
- This repository pushed to a Git server reachable by the cluster

## Quick Start

1. **Clone and push to your Git server**

   ```bash
   git clone <this-repo>
   cd rhoai-3.3-cluster
   ```

2. **Update the ArgoCD Application repo URL**

   Edit `bootstrap/argocd-application.yaml` and replace the `repoURL` with your actual Git repository URL.

3. **Run the bootstrap script**

   ```bash
   ./scripts/bootstrap.sh
   ```

   This installs OpenShift GitOps, grants it cluster-admin, and creates the root ArgoCD Application (`rhoai-cluster-config`).

4. **Monitor progress**

   ```bash
   # Get the ArgoCD URL
   oc get route openshift-gitops-server -n openshift-gitops -o jsonpath='{.spec.host}'

   # Watch the Application status
   oc get application rhoai-cluster-config -n openshift-gitops -w

   # List all ArgoCD Applications
   oc get applications -n openshift-gitops
   ```

## How It Works

### Two-repo pattern

- **This repo** (rhoai-3.3-cluster) is the GitOps repo. It contains cluster config, operator subscriptions, and ArgoCD Application definitions. The root Application `rhoai-cluster-config` syncs everything under `manifests/`.
- **openshiftai-helmcharts** is the Helm charts repo. It contains reusable charts. The ArgoCD Applications in `helm-charts-repo.yaml` point at this repo and pass values inline so all configuration lives in the GitOps repo.

### Parent-child relationship

```
rhoai-cluster-config (root app, syncs manifests/)
  ├── operators, gpu-config, rhoai-config (direct manifests)
  └── helm-charts-repo.yaml (creates child Applications)
        ├── model-registry (syncs from Helm charts repo)
        ├── minio
        ├── modeldeploy
        ├── hardware-profile
        └── hardware-profile-small
```

Changes to `helm-charts-repo.yaml` are picked up by the **parent** app. Changes to the Helm charts are picked up by the **child** apps. Refresh the parent to update Application definitions; refresh a child to pick up chart changes.

### Key design decisions

- **HardwareProfile drives resources and tolerations.** The modeldeploy chart does not set `resources` or `tolerations` on the InferenceService. The ODH controller fills these from the HardwareProfile referenced in the `opendatahub.io/hardware-profile-name` annotation.
- **ignoreDifferences** on the modeldeploy app suppresses diffs for fields the controller injects (`resources`, `tolerations`, `minReplicas`, `maxReplicas`).
- **Replace=true** on the model-registry app avoids merge conflicts with operator-managed fields (e.g. `kubeRBACProxy` defaults injected by the model-registry-operator).
- **Replicas are not managed in Git.** The InferenceService doesn't set `minReplicas`/`maxReplicas`; the API defaults to 1. Scaling is done outside Git (e.g. via the UI or `kubectl`), and `ignoreDifferences` prevents Argo from reverting manual scale changes.

## Adding a New Model

1. Add a new Application block in `manifests/argocd-applications/helm-charts-repo.yaml`:

   ```yaml
   ---
   apiVersion: argoproj.io/v1alpha1
   kind: Application
   metadata:
     name: my-new-model
     namespace: openshift-gitops
   spec:
     project: default
     source:
       repoURL: https://github.com/pdavis327/openshiftai-helmcharts.git
       targetRevision: main
       path: models/modeldeploy
       helm:
         releaseName: my-new-model
         values: |
           modelname: my-new-model
           namespace: my-namespace
           uri: "oci://quay.io/myorg/my-model:1.0"
           runtime: my-new-model
           hardwareProfileName: nvidia-l4-small
     destination:
       server: https://kubernetes.default.svc
       namespace: my-namespace
     ignoreDifferences:
       - group: serving.kserve.io
         kind: InferenceService
         jsonPointers:
           - /spec/predictor/model/resources
           - /spec/predictor/tolerations
           - /spec/predictor/minReplicas
           - /spec/predictor/maxReplicas
     syncPolicy:
       automated:
         prune: true
         selfHeal: true
   ```

2. Commit and push. The parent app will create the new child Application on its next sync.

## Manual Steps After Sync

Some steps are cluster-specific and cannot be fully automated via GitOps:

1. **GPU MachineSet** — Create a GPU worker MachineSet for your cloud provider. See [RHOAI Installation Workshop Step 2](https://github.com/redhat-ai-americas/rhoai-installation-workshop/blob/main/docs/02-enable-gpu-support.md).

2. **GPU Node Taints** (optional) — Prevent non-GPU workloads from scheduling on GPU nodes. See [RHOAI Installation Workshop Step 5](https://github.com/redhat-ai-americas/rhoai-installation-workshop/blob/main/docs/05-configure-gpu-sharing-method.md).

## Repository Structure

```
rhoai-3.3-cluster/
├── bootstrap/                              One-time setup (not managed by ArgoCD)
│   ├── openshift-gitops-subscription.yaml    Install OpenShift GitOps operator
│   ├── argocd-cluster-admin.yaml             Grant ArgoCD cluster-admin
│   ├── argocd-rbac.yaml                      ArgoCD RBAC config
│   └── argocd-application.yaml               Root Application (rhoai-cluster-config)
├── manifests/                              Managed by ArgoCD
│   ├── operators/                            Wave 0-2: Operator installs
│   │   ├── nfd.yaml
│   │   ├── nvidia-gpu.yaml
│   │   ├── kmm.yaml
│   │   ├── rhoai.yaml
│   │   ├── jobset.yaml
│   │   ├── custom-metrics-autoscaler.yaml
│   │   ├── leader-worker-set.yaml
│   │   ├── connectivity-link.yaml
│   │   ├── kueue.yaml
│   │   ├── sriov.yaml
│   │   ├── opentelemetry.yaml
│   │   ├── tempo.yaml
│   │   └── cluster-observability.yaml
│   ├── gpu-config/                           Wave 3: GPU operator config
│   │   ├── nfd-instance.yaml
│   │   └── clusterpolicy.yaml
│   ├── rhoai-config/                         Wave 4: RHOAI config
│   │   ├── dsc.yaml
│   │   └── telemetry-cm.yaml
│   └── argocd-applications/                  Child ArgoCD Applications
│       └── helm-charts-repo.yaml               model-registry, minio, modeldeploy, hardware-profiles
├── scripts/
│   ├── bootstrap.sh                          Bootstrap script
│   └── create-gpu-machineset.sh              GPU MachineSet helper
├── security/
│   └── htpass/
│       └── htpasscr.yaml                     HTPasswd identity provider
└── README.md
```

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Child app shows OutOfSync for resources/tolerations | Controller injects fields from HardwareProfile | Add `ignoreDifferences` for those jsonPointers |
| "Cannot use both oauthProxy and kubeRBACProxy" | Operator defaults inject `kubeRBACProxy`; chart had `oauthProxy` | Use `kubeRBACProxy` in chart to match operator defaults |
| "already exists" on sync | Manually-created resources conflict with chart resources | Delete existing resources first, or use `Replace=true` syncOption |
| Child app not picking up changes to helm-charts-repo.yaml | Changes are in the parent repo, not the charts repo | Refresh/sync the **parent** app (rhoai-cluster-config) |
| `syncOptions: null` validation error | `syncOptions:` key with no list value | Use `syncOptions: []` or remove the key entirely |
