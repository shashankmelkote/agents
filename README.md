# Jarvis Ingress (AWS CDK v2)

## Prerequisites
- Python 3.11
- AWS CDK v2 (`npm install -g aws-cdk`)
- AWS credentials configured for `us-east-1`

## Deploy
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cdk deploy -c sharedSecretName=jarvis/webhook/shared_secret
```

The `sharedSecretName` context value defaults to `jarvis/webhook/shared_secret` if omitted. Override it with `-c sharedSecretName=...` to point at a different secret name.

## Test
```bash
pip install -r requirements-dev.txt
pytest
```

## Curl Example
```bash
SECRET_VALUE="your-shared-secret"
TIMESTAMP=$(date +%s)
BODY='{"hello":"world"}'
SIGNATURE=$(python3 - <<'PY'
import hmac, hashlib, os
payload = f"{os.environ['TIMESTAMP']}.{os.environ['BODY']}".encode()
print(hmac.new(os.environ['SECRET_VALUE'].encode(), payload, hashlib.sha256).hexdigest())
PY
)

curl -X POST "$(cdk output JarvisIngressStack.IngressUrl)" \
  -H "x-jarvis-timestamp: $TIMESTAMP" \
  -H "x-jarvis-signature: $SIGNATURE" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

## Acceptance Test
- Without headers: `POST /ingress` should return 401/403 (missing/invalid signature).
- With correct headers: `POST /ingress` should return 200 and the Router Lambda should be invoked.
- The request should succeed with only the HMAC headers (no AWS credentials required).
