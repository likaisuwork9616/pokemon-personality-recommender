# Cost controls and active alerts

Application rate limits and Prometheus alerts are the first safety layer. They
do not replace account-level hard spend limits because a distributed attack,
another application using the same key, or delayed billing data can bypass
application-local assumptions.

## Runtime alerts

Prometheus evaluates `ops/prometheus/alerts.yml` every 15 seconds and forwards
firing alerts to Alertmanager. Rules cover API availability, live PostgreSQL
readiness, HTTP 5xx ratio, p95 latency, repeated 429 responses, external model
failures, model traffic spikes and an unhealthy personality snapshot.

For production, copy `ops/alertmanager/alertmanager.example.yml` to
`/etc/pokemon-recommender/alertmanager.yml`, replace the placeholder with a
secret operator-owned webhook, set owner/group `root:65534` and mode `0640`,
and keep `ALERTMANAGER_CONFIG_FILE` pointed at that file. Prometheus, Grafana and
Alertmanager remain loopback-only on the host; never publish ports 9090, 3000
or 9093 to a public interface.

```bash
sudo install -d -m 0750 -o root -g 65534 /etc/pokemon-recommender
sudo install -m 0640 -o root -g 65534 ops/alertmanager/alertmanager.example.yml \
  /etc/pokemon-recommender/alertmanager.yml
```

The pinned Alertmanager image runs as UID/GID `65534:65534`; the group-readable
mode above lets that non-root process read the bind mount while keeping it
unreadable to other host users. Reapply the same owner and mode after editing.

After replacing the webhook URL, validate the file before deployment:

```bash
docker run --rm \
  --user 65534:65534 \
  --entrypoint amtool \
  -v /etc/pokemon-recommender/alertmanager.yml:/etc/alertmanager.yml:ro \
  prom/alertmanager:v0.28.1 \
  check-config /etc/alertmanager.yml
```

## AWS artwork budget

`ops/aws/artwork-budget.yml` creates an account-level monthly CloudFront/S3
cost budget. Its default is USD 5 and sends forecasted 50%, actual 80%, and
actual 100% alerts. AWS Budgets is an alert, not an automatic service shutoff.
Deploy it only after choosing the recipient and budget amount:

```bash
aws sts get-caller-identity
aws cloudformation deploy \
  --region us-east-1 \
  --stack-name pokemon-artwork-budget \
  --template-file ops/aws/artwork-budget.yml \
  --parameter-overrides AlertEmail=operator@example.com MonthlyBudgetUsd=5
```

The email recipient must confirm or allow the budget notifications as required
by the AWS account. Confirm the budget in Billing and Cost Management and check
CloudFront `Requests` plus `BytesDownloaded` in the `us-east-1` CloudWatch
metrics view.

## OpenAI and Gemini

- OpenAI: use a dedicated project key and configure a low project monthly
  budget plus alerts. Treat that project budget as soft unless the account's
  Limits page explicitly offers a separately labelled hard spend limit; spend
  alerts do not stop API traffic. Keep the application global request
  guardrail even when an account-level limit is available.
- Gemini: use a dedicated AI Studio project and set its monthly project spend
  cap. The feature is experimental, is unavailable for some invoiced accounts,
  and billing enforcement can lag by roughly ten minutes, so retain the
  application global request guardrail and allow for small overages.
- Keep both keys blank during public tunnel tests unless an intentionally small
  paid-provider canary is being performed.

Record the chosen project names, monthly amounts, recipient and the date each
control was verified in the private operator runbook; do not commit account
IDs, API keys, billing emails or secret webhook URLs.
