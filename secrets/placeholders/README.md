# Secret placeholders

These YAML files list **key names only**. Values are `CHANGE_ME`.

They are **not** synced by Argo CD. After the demo Applications are healthy, apply the ones you need:

```bash
oc apply -f secrets/placeholders/country-of-origin-predictor/secrets.yaml
# Then edit the live secrets with real credentials:
oc edit secret minio -n country-of-origin-predictor
```

`model-server/llama-3-2-1b-instruct` is a dashboard URI connection. On the target cluster set `URI` to the same modelcar URI as the `LLMInferenceService` (`oci://quay.io/redhat-ai-services/modelcar-catalog:llama-3.2-1b-instruct`).

Never commit live credentials. `security/` remains gitignored for htpasswd and similar files.
