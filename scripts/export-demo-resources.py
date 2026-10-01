#!/usr/bin/env python3
"""Export sanitized demo resources from the current OpenShift context.

Writes GitOps YAML under projects/, cluster-config/, and secrets/placeholders/.
Does not dump live secret values.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CLUSTER_HOST_RE = re.compile(
    r"[a-z0-9.-]+\.(sandbox[0-9]+|dyn)\.[a-z0-9.-]+",
    re.IGNORECASE,
)

PROJECT_NS = [
    "country-of-origin-predictor",
    "whisper-demo",
    "code-assistant",
    "ray-workshop",
    "fine-tuning",
    "gemma4",
    "mcp-demo",
    "model-server",
    "models-as-a-service",
    "models-as-service-db",
    "ai-tenants",
    "ticket-resolution",
    "code-reviewer",
]

# Helm Applications in this repo own these; skip helm-managed objects there.
HELM_OWNED_NS = {
    "rhoai-model-registries",
    "mcp-demo",
}

# Include helm-rendered YAML (strip helm ownership labels).
HELM_RENDER_NS = {
    "ticket-resolution",
    "code-reviewer",
}

NAMESPACED_KINDS = [
    "notebooks.kubeflow.org",
    "dspa",
    "pipeline.pipelines.kubeflow.org",
    "pipelineversion.pipelines.kubeflow.org",
    "nemoguardrails.trustyai.opendatahub.io",
    "trustyaiservices.trustyai.opendatahub.io",
    "mcpservers.mcp.x-k8s.io",
    "ogxservers.ogx.io",
    "aitenants.maas.opendatahub.io",
    "tenants.maas.opendatahub.io",
    "maassubscriptions.maas.opendatahub.io",
    "maasmodelrefs.maas.opendatahub.io",
    "llminferenceservices.serving.kserve.io",
    "localqueues.kueue.x-k8s.io",
    "deployments.apps",
    "statefulsets.apps",
    "cronjobs.batch",
    "services",
    "routes.route.openshift.io",
    "configmaps",
    "persistentvolumeclaims",
    "serviceaccounts",
    "roles.rbac.authorization.k8s.io",
    "rolebindings.rbac.authorization.k8s.io",
]

SKIP_CM_EXACT = {
    "kube-root-ca.crt",
    "openshift-service-ca.crt",
    "odh-trusted-ca-bundle",
    "odh-kserve-custom-ca-bundle",
    "workbench-trusted-ca-bundle",
    "pipeline-runtime-images",
}

SKIP_CM_SUBSTR = (
    "kube-rbac-proxy",
    "metrics-dashboard",
    "trusted-ca",
    "service-ca",
    "-sar-config",
    "ca-bundle",
)

SKIP_SA = {"builder", "default", "deployer", "pipeline"}

SAMPLE_PIPELINES = (
    "autogluon-tabular-training-pipeline",
    "autogluon-timeseries-training-pipeline",
    "documents-indexing-pipeline",
    "documents-rag-optimization-pipeline",
)

KEEP_SECRET_NAMES = {
    "minio",
    "minio-secret",
    "mlflow-artifact-s3",
    "minio-data-connection-detector-models",
    "dashboard-dspa-secret",
    "ds-pipeline-db-dspa",
    "storage-config",
    "genai-pgvector-credentials",
    "whisper-live-caption",
    "api-keys",
    "llama-stack-env",
    "pgvector",
    "code-reviewer-pipeline-secrets",
}

PLACEHOLDER = "CHANGE_ME"


class LiteralStr(str):
    pass


def literal_str_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(LiteralStr, literal_str_representer)


def oc_json(args: list[str]) -> dict | None:
    try:
        r = subprocess.run(
            ["oc", *args, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=45,
        )
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT: oc {' '.join(args)}", file=sys.stderr, flush=True)
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def oc_items(kind: str, namespace: str | None = None) -> list[dict]:
    args = ["get", kind]
    if namespace:
        args += ["-n", namespace]
    else:
        args += ["-A"]
    data = oc_json(args)
    if not data:
        return []
    if data.get("kind") == "List":
        return data.get("items") or []
    return [data]


def drop_empty(obj):
    if isinstance(obj, dict):
        return {
            k: drop_empty(v)
            for k, v in obj.items()
            if v is not None and v != {} and v != []
        }
    if isinstance(obj, list):
        return [drop_empty(v) for v in obj]
    return obj


def sanitize(obj: dict) -> dict:
    obj = deepcopy(obj)
    obj.pop("status", None)
    md = obj.get("metadata") or {}
    for k in (
        "uid",
        "resourceVersion",
        "generation",
        "creationTimestamp",
        "managedFields",
        "selfLink",
        "finalizers",
        "ownerReferences",
        "deletionTimestamp",
        "deletionGracePeriodSeconds",
    ):
        md.pop(k, None)
    anns = md.get("annotations") or {}
    drop_ann = []
    for key in list(anns):
        if key.startswith("kubectl.kubernetes.io/"):
            drop_ann.append(key)
        elif key in {
            "deployment.kubernetes.io/revision",
            "argocd.argoproj.io/tracking-id",
            "internal.config.kubernetes.io/previousKinds",
            "internal.config.kubernetes.io/previousNames",
            "internal.config.kubernetes.io/previousNamespaces",
        }:
            drop_ann.append(key)
        elif key.startswith("meta.helm.sh/"):
            drop_ann.append(key)
        elif key.startswith("openshift.io/sa.scc."):
            drop_ann.append(key)
        elif key in {
            "ovn.kubernetes.io/hybrid-overlay-external-gw",
            "k8s.ovn.org/pod-networks",
        }:
            drop_ann.append(key)
    for key in drop_ann:
        anns.pop(key, None)
    if not anns:
        md.pop("annotations", None)
    else:
        md["annotations"] = anns
    labels = md.get("labels") or {}
    for key in (
        "app.kubernetes.io/instance",
        "helm.sh/chart",
        "app.kubernetes.io/managed-by",
        "app.kubernetes.io/version",
    ):
        if obj.get("kind") in {"Deployment", "StatefulSet", "Service", "Route", "ConfigMap", "Secret", "ServiceAccount", "CronJob"}:
            if md.get("namespace") in HELM_RENDER_NS:
                labels.pop(key, None)
    if not labels:
        md.pop("labels", None)
    else:
        md["labels"] = labels
    obj["metadata"] = md
    spec = obj.get("spec")
    if isinstance(spec, dict):
        spec.pop("clusterIP", None)
        spec.pop("clusterIPs", None)
        spec.pop("ipFamilies", None)
        spec.pop("ipFamilyPolicy", None)
        spec.pop("internalTrafficPolicy", None)
        spec.pop("sessionAffinity", None)
        if spec.get("sessionAffinityConfig") == {}:
            spec.pop("sessionAffinityConfig", None)
        spec.pop("volumeName", None)
        spec.pop("volumeMode", None)
        if obj.get("kind") == "Route":
            spec.pop("host", None)
            spec.pop("wildcardPolicy", None)
        if obj.get("kind") == "PersistentVolumeClaim":
            spec.pop("volumeName", None)
            spec.pop("storageClassName", None)
        obj["spec"] = spec
    if obj.get("kind") == "Service" and "spec" in obj:
        ports = obj["spec"].get("ports") or []
        for p in ports:
            p.pop("nodePort", None)
    return replace_cluster_hosts(obj)


def replace_cluster_hosts(obj):
    raw = json.dumps(obj)
    raw = CLUSTER_HOST_RE.sub("APPS_DOMAIN", raw)
    return json.loads(raw)


def is_helm_owned(obj: dict) -> bool:
    labels = (obj.get("metadata") or {}).get("labels") or {}
    anns = (obj.get("metadata") or {}).get("annotations") or {}
    if labels.get("app.kubernetes.io/managed-by") == "Helm":
        return True
    if "meta.helm.sh/release-name" in anns:
        return True
    return False


def skip_workload(obj: dict) -> bool:
    name = obj["metadata"]["name"]
    ns = obj["metadata"].get("namespace", "")
    kind = obj.get("kind")
    labels = obj["metadata"].get("labels") or {}

    if ns in HELM_OWNED_NS:
        return True
    if ns == "country-of-origin-predictor" and name.startswith("minio"):
        return True
    if ns == "country-of-origin-predictor" and kind in {"Deployment", "Service", "Route", "PersistentVolumeClaim"} and "minio" in name:
        return True

    if "lemonade" in name:
        return True
    if kind == "GuardrailsOrchestrator":
        return True
    if labels.get("serving.kserve.io/inferenceservice"):
        return True
    if labels.get("app.kubernetes.io/part-of") == "llminferenceservice":
        return True
    if labels.get("app.kubernetes.io/component") == "llminferenceservice-workload":
        return True
    if labels.get("app.kubernetes.io/managed-by") in {
        "odh-model-controller",
        "ogx-operator",
        "mcp-lifecycle-operator",
        "opendatahub.io-notebook-controller",
        "notebook-controller.kubeflow.org",
    }:
        return True
    if labels.get("app.opendatahub.io/notebook-controller") == "true":
        return True
    if labels.get("notebook-name"):
        return True
    if name.endswith("-predictor") or "-predictor-" in name:
        return True
    if name.startswith("ds-pipeline") or name.startswith("mariadb-dspa"):
        return True
    if "workflow-controller" in name or "persistenceagent" in name:
        return True
    if kind == "StatefulSet" and name in {
        "code-server",
        "country-of-origin-wb",
        "credit-card-fraud-wb",
        "fine-tuning",
        "model-testing",
        "ray-lab",
        "whisper-lab",
    }:
        return True
    if kind == "PersistentVolumeClaim" and (
        name.endswith("-storage")
        or name in {"mariadb-dspa", "model-registry-mysql", "claim-devworkspace"}
    ):
        # Keep demo app disks that are not notebook/operator PVCs
        if name in {
            "genai-pgvector-storage",
            "trustyai-service-pvc",
            "minio-pvc",
            "minio-storage-guardrail-detectors-claim",
            "maas-postgresql-data",
        } or name.startswith("data-self-service") or name.startswith("pg-data") or name.startswith("nim-pvc"):
            return False
        return True
    if kind == "ServiceAccount":
        if name in {"mcp-viewer", "ocp-mcp", "mlflow-sa", "whisper-live-caption"}:
            return False
        if name in SKIP_SA or "-dockercfg" in name or "predictor" in name:
            return True
        if name.endswith("-sa"):
            return True
    if kind == "Pipeline" and name in SAMPLE_PIPELINES:
        return True
    if kind == "PipelineVersion" and any(name.startswith(p) for p in SAMPLE_PIPELINES):
        return True
    if kind == "ConfigMap":
        if name in SKIP_CM_EXACT:
            return True
        if any(s in name for s in SKIP_CM_SUBSTR):
            return True
    if kind in {"Deployment", "StatefulSet", "Service", "Route", "ConfigMap", "PersistentVolumeClaim", "CronJob", "ServiceAccount"}:
        if ns not in HELM_RENDER_NS and is_helm_owned(obj) and ns != "code-assistant":
            # Skip helm objects that a remaining Helm Application owns
            if ns in {"country-of-origin-predictor"} and "minio" in name:
                return True
            if name in {"bge-large-embedding-model"} or "model-registry" in name:
                return True
    return False


def strip_isvc_injected(obj: dict) -> dict:
    spec = obj.get("spec") or {}
    pred = spec.get("predictor") or {}
    model = pred.get("model") or {}
    anns = (obj.get("metadata") or {}).get("annotations") or {}
    if "opendatahub.io/hardware-profile-name" in anns or "opendatahub.io/hardware-profile-namespace" in anns:
        model.pop("resources", None)
        pred.pop("tolerations", None)
        pred.pop("nodeSelector", None)
        if model:
            pred["model"] = model
        spec["predictor"] = pred
        obj["spec"] = spec
    return obj


def fix_dspa(obj: dict) -> dict:
    spec = obj.get("spec") or {}
    storage = ((spec.get("objectStorage") or {}).get("externalStorage") or {})
    host = storage.get("host") or ""
    if "minio" in host or host == "APPS_DOMAIN" or "APPS_DOMAIN" in host:
        storage["host"] = "minio-service.country-of-origin-predictor.svc"
        storage["port"] = "9000"
        storage["scheme"] = "http"
        spec.setdefault("objectStorage", {}).setdefault("externalStorage", {}).update(storage)
        obj["spec"] = spec
    return obj


def keep_secret(obj: dict) -> bool:
    name = obj["metadata"]["name"]
    typ = obj.get("type") or "Opaque"
    labels = obj["metadata"].get("labels") or {}
    if name.startswith("sh.helm.release"):
        return False
    if "-dockercfg-" in name or name.endswith("-token"):
        return False
    if typ in {
        "kubernetes.io/tls",
        "kubernetes.io/service-account-token",
        "helm.sh/release.v1",
        "kubernetes.io/dockercfg",
    }:
        return False
    if typ == "kubernetes.io/dockerconfigjson" and name not in {"ngc-secret"}:
        return False
    if labels.get("opendatahub.io/dashboard") == "true":
        return True
    if name in KEEP_SECRET_NAMES or name.startswith("secret-"):
        return True
    if "webhook" in name or name.startswith("kserve-"):
        return False
    if "credentials" in name or name.endswith("-secret") or "token" in name.lower():
        if typ == "Opaque":
            return True
    return False


def placeholder_secret(obj: dict) -> dict:
    obj = sanitize(obj)
    data = obj.get("data") or {}
    string_data = {}
    for key in data:
        if obj.get("type") == "kubernetes.io/dockerconfigjson" and key == ".dockerconfigjson":
            string_data[key] = '{"auths":{"CHANGE_ME_REGISTRY":{"auth":"CHANGE_ME"}}}'
        else:
            string_data[key] = PLACEHOLDER
    obj.pop("data", None)
    obj["stringData"] = string_data
    md = obj.setdefault("metadata", {})
    anns = md.setdefault("annotations", {})
    anns["rhoai-demo/placeholder"] = "true"
    anns["rhoai-demo/note"] = "Replace CHANGE_ME values on the target cluster. Do not commit live credentials."
    return obj


def kind_filename(kind: str) -> str:
    mapping = {
        "Namespace": "00-namespace",
        "Notebook": "notebooks",
        "InferenceService": "inferenceservices",
        "ServingRuntime": "servingruntimes",
        "LLMInferenceService": "llminferenceservices",
        "DataSciencePipelinesApplication": "dspa",
        "Pipeline": "pipelines",
        "PipelineVersion": "pipelineversions",
        "FeatureStore": "featurestore",
        "GuardrailsOrchestrator": "guardrails-orchestrator",
        "NemoGuardrails": "nemoguardrails",
        "TrustyAIService": "trustyai",
        "MCPServer": "mcpserver",
        "OGXServer": "ogxserver",
        "AITenant": "aitenant",
        "Tenant": "maas-tenant",
        "MaaSSubscription": "maas-subscription",
        "MaaSModelRef": "maas-modelref",
        "LocalQueue": "localqueues",
        "Grafana": "grafana",
        "GrafanaDashboard": "grafana-dashboards",
        "GrafanaDatasource": "grafana-datasources",
        "Deployment": "deployments",
        "StatefulSet": "statefulsets",
        "CronJob": "cronjobs",
        "Service": "services",
        "Route": "routes",
        "ConfigMap": "configmaps",
        "PersistentVolumeClaim": "pvcs",
        "ServiceAccount": "serviceaccounts",
        "Role": "roles",
        "RoleBinding": "rolebindings",
        "HardwareProfile": "hardware-profiles",
        "EvalHub": "evalhub",
        "MLflow": "mlflow",
        "ClusterRoleBinding": "clusterrolebindings",
        "Config": "maas-config",
    }
    return mapping.get(kind, kind.lower())


def dump_docs(path: Path, docs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = []
    for d in docs:
        d = sanitize(d)
        if d.get("kind") == "InferenceService":
            d = strip_isvc_injected(d)
        if d.get("kind") == "DataSciencePipelinesApplication":
            d = fix_dspa(d)
        # Restore multiline strings
        d = stringify_cm_data(d)
        cleaned.append(d)
    with path.open("w") as f:
        yaml.dump_all(
            cleaned,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )


def stringify_cm_data(obj: dict) -> dict:
    if obj.get("kind") == "ConfigMap" and "data" in obj:
        data = obj["data"]
        for k, v in list(data.items()):
            if isinstance(v, str) and "\n" in v:
                data[k] = LiteralStr(v)
    return obj


def export_namespaces() -> None:
    items = oc_items("namespace")
    by_name = {i["metadata"]["name"]: i for i in items}
    for ns in PROJECT_NS:
        obj = by_name.get(ns)
        if not obj:
            print(f"WARN: namespace {ns} not found", file=sys.stderr)
            continue
        md = obj.get("metadata") or {}
        keep_labels = {}
        labels = md.get("labels") or {}
        for k in (
            "opendatahub.io/dashboard",
            "kueue.openshift.io/managed",
            "modelmesh-enabled",
            "argocd.argoproj.io/managed-by",
            "maas.opendatahub.io/gateway-access",
            "maas-gateway-access",
        ):
            if k in labels:
                keep_labels[k] = labels[k]
        keep_ann = {}
        anns = md.get("annotations") or {}
        for k in ("openshift.io/display-name", "openshift.io/description"):
            if k in anns:
                keep_ann[k] = anns[k]
        ns_obj = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": ns,
            },
        }
        if keep_labels:
            ns_obj["metadata"]["labels"] = keep_labels
        if keep_ann:
            ns_obj["metadata"]["annotations"] = keep_ann
        dump_docs(ROOT / "projects" / ns / "00-namespace.yaml", [ns_obj])


def export_namespaced() -> None:
    for ns in PROJECT_NS:
        print(f"  scanning {ns}...", flush=True)
        grouped: dict[str, list[dict]] = {}
        kinds = list(NAMESPACED_KINDS)
        if ns != "country-of-origin-predictor":
            kinds = [
                k
                for k in kinds
                if k
                not in {
                    "pipelines.pipelines.kubeflow.org",
                    "pipelineversions.pipelines.kubeflow.org",
                    "datasciencepipelinesapplications.opendatahub.io",
                }
            ]
        if ns not in {"models-as-a-service", "ai-tenants", "model-server"}:
            kinds = [k for k in kinds if not k.endswith(".maas.opendatahub.io")]
        if ns != "model-server":
            kinds = [k for k in kinds if not k.startswith("llminferenceservices")]
        for kind in kinds:
            for obj in oc_items(kind, ns):
                if skip_workload(obj):
                    continue
                if ns in HELM_OWNED_NS:
                    continue
                grouped.setdefault(obj.get("kind") or kind, []).append(obj)
        for kind, docs in grouped.items():
            fname = kind_filename(kind) + ".yaml"
            dump_docs(ROOT / "projects" / ns / fname, docs)
            print(f"  {ns}/{fname}: {len(docs)}", flush=True)


def export_cluster_config() -> None:
    # Hardware profiles
    profiles = oc_items("hardwareprofiles.infrastructure.opendatahub.io", "redhat-ods-applications")
    if profiles:
        dump_docs(
            ROOT / "cluster-config" / "hardware-profiles" / "hardware-profiles.yaml",
            profiles,
        )
        print(f"  hardware-profiles: {len(profiles)}", flush=True)

    evalhub = oc_items("evalhubs.trustyai.opendatahub.io", "redhat-ods-applications")
    if evalhub:
        dump_docs(ROOT / "cluster-config" / "evalhub.yaml", evalhub)
        print(f"  evalhub: {len(evalhub)}", flush=True)

    mlflow = oc_items("mlflows.mlflow.opendatahub.io")
    if mlflow:
        # Ensure namespace
        for m in mlflow:
            m.setdefault("metadata", {}).setdefault("namespace", "redhat-ods-applications")
        dump_docs(ROOT / "cluster-config" / "mlflow.yaml", mlflow)
        print(f"  mlflow: {len(mlflow)}", flush=True)

    maas_cfg = oc_items("configs.maas.opendatahub.io")
    if maas_cfg:
        dump_docs(ROOT / "cluster-config" / "maas-config.yaml", maas_cfg)
        print(f"  maas-config: {len(maas_cfg)}", flush=True)

    mcp_cm = oc_json(["get", "configmap", "gen-ai-aa-mcp-servers", "-n", "redhat-ods-applications"])
    if mcp_cm and mcp_cm.get("kind") == "ConfigMap":
        dump_docs(ROOT / "cluster-config" / "mcp-catalog" / "gen-ai-aa-mcp-servers.yaml", [mcp_cm])

    keep_crb = []
    for name in ("ocp-mcp-cluster-view", "code-assistant-mcp-viewer"):
        obj = oc_json(["get", "clusterrolebinding", name])
        if obj and obj.get("kind") == "ClusterRoleBinding":
            keep_crb.append(obj)
    if keep_crb:
        dump_docs(
            ROOT / "cluster-config" / "mcp-catalog" / "clusterrolebindings.yaml",
            keep_crb,
        )


def export_secret_placeholders() -> None:
    ns_list = PROJECT_NS + ["redhat-ods-applications"]
    for ns in ns_list:
        secrets = oc_items("secrets", ns)
        kept = []
        for obj in secrets:
            if keep_secret(obj):
                kept.append(placeholder_secret(obj))
        if not kept:
            continue
        path = ROOT / "secrets" / "placeholders" / ns / "secrets.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            yaml.dump_all(
                kept,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=120,
            )
        print(f"  placeholders {ns}: {len(kept)}", flush=True)


def main() -> int:
    who = subprocess.run(["oc", "whoami"], capture_output=True, text=True, timeout=20)
    if who.returncode != 0:
        print("ERROR: not logged in to a cluster", file=sys.stderr)
        return 1
    print(f"Exporting as {who.stdout.strip()}", flush=True)
    print("== namespaces ==", flush=True)
    export_namespaces()
    print("== namespaced resources ==", flush=True)
    export_namespaced()
    print("== cluster-config ==", flush=True)
    export_cluster_config()
    print("== secret placeholders ==", flush=True)
    export_secret_placeholders()
    print("Done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
