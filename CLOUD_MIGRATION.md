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

## Administrator access

`admin.html` uses the administrator's own GitHub fine-grained token, limited to this
repository, with Contents and Actions read/write permissions. It remains in page
memory only and is never written to browser storage. The provider token is a
GitHub encrypted secret named `IFIND_CLOUD_AUTH_TOKEN`; do not enter it in the UI.

The public page does not itself grant any privileges: GitHub verifies every read,
configuration write and workflow dispatch. Non-admin visitors cannot execute jobs.
The data-path registry links to the actual configuration, not arbitrary URLs.

## Production activation (not yet performed)

Only after acceptance: copy vetted staged changes into main, set config phase to
`production`, and add cloud-update.yml to the default gh-pages branch. The old
update-and-deploy workflow remains intact as a fallback. Keep the daily schedule
disabled initially; the administrator can enable it through the management page.
Scheduled gate runs hourly at :45 UTC and allows the selected Shanghai hour only.
GitHub scheduling may be delayed; this is not a guaranteed wall-clock scheduler.
Unattended runs use cloud Linux and never depend on the local Windows runner.

## Failure safety

All structural, freshness-regression and published-forecast checks precede data
commit and Pages publication. Requests have a per-run budget, exact-ID checks and
shared response cache. Model packages are pinned to the verified local versions.
Concurrent source edits abort persistence rather than overwrite newer work.
If deployment fails after data persistence, the existing deployed page remains
available; a publish-only retry uses no provider quota.
