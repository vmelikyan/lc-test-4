# Lifecycle release fixtures

Use branch `platform-maintenance-e2e` through Lifecycle. `main` retains the earlier application fixtures.

The default environment builds the `lc-test-4` HTTP image with BuildKit and deploys `e2e-job` and `e2e-cron` through native Helm. The services share one local chart, with separate values so Job and CronJob pod discovery can be checked independently. `E2E-NOTES.md` is an unrelated symlink that must not block Helm deployment.

| Service | Expected result |
| --- | --- |
| `lc-test-4` | HTTP `/` contains `E2E_HTTP_OK`; `/health` contains `E2E_HTTP_HEALTHY`; logs contain `E2E_HTTP_STARTED`. |
| `e2e-job` | Job completes and logs `E2E_JOB_OK`. |
| `e2e-cron` | CronJob runs once per minute and logs `E2E_CRON_OK`. |
| `e2e-job-fail` (optional) | Job exits 23 and logs `E2E_JOB_EXPECTED_FAILURE`; Lifecycle reports failure. |
| `e2e-unsafe` (optional) | Helm is denied access to a cluster-scoped ClusterRole; no ClusterRole is created. Its empty rules grant no permissions if the check fails. |

Two completion webhooks print `E2E_COMMAND_WEBHOOK_OK` and `E2E_DOCKER_WEBHOOK_OK`. The error webhook prints `E2E_ERROR_WEBHOOK_OK`. Each webhook has a 60-second deadline and performs no network calls or credential inspection.

Public BusyBox (HTTP/dev) and Alpine (batch/webhooks) images are pinned to multi-platform digests. The HTTP build copies static files and installs no dependencies. Jobs have a 30-second deadline, no retries, and one-hour finished TTL. CronJob history is bounded to one success and one failure. Teardown through Lifecycle removes the environment and stops future ticks.

## Workspace setup

The HTTP service has a `dev` configuration. Its setup command is longer than 160 characters; the approval must show the final `E2E_SETUP_APPROVED_SUFFIX` command. Setup writes only `.lifecycle-e2e/setup/` inside the workspace and runs no package installation.

- `runs` has one line per attempt.
- `success` records the completion marker and run count.
- Create `pause` in that directory before approval to hold execution for 20 seconds for interruption testing.
- Create `fail` before approval to return exit 23 after recording the attempt.
- Remove those control files for the normal success scenario. A failed or interrupted attempt must not silently execute again.

Start, approve, retry, inspect logs, and tear down through Lifecycle's normal UI/API/CLI paths. Rendering this chart locally checks syntax only; it does not prove Kubernetes policy enforcement or a successful Lifecycle deployment.
