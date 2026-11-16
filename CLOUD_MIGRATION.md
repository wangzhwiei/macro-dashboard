# Cloud migration — isolated staging

Production is not switched. Baseline source: `93773d061454ed958b1c392e7e405d625b5700be`.

Rollback snapshots: `backup/pre-cloud-main-20261116` and `backup/pre-cloud-pages-20261116`.
These are snapshot branches, not branch-protection rules.

The `cloud-admin-staging` branch has a separate read-only GitHub-hosted workflow.
It has no Pages deployment permission, no production commit step and no schedule.
Its first gate checks provider TLS with no credentials. Never bypass a failed TLS check.

Remaining acceptance gates before production cutover:

1. Trusted HTTPS connectivity from GitHub-hosted runner.
2. Secret-backed get_edb_data query with exact provider identity validation.
3. Incremental data and all monthly-model execution; cache and quota limits.
4. Authenticated management UI, allowlisted data-source configuration, status and logs.
5. Scheduling with explicit enable/disable and no overlapping runs.
6. Preview build, forecast-vintage checks, production snapshot and rollback verification.

Until all gates pass, existing production source, data, page and manual workflow remain intact.
