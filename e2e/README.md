# Lifecycle end-to-end fixtures

These fixtures exercise environment deployment, service development, agent setup, Jobs, CronJobs, and completion webhooks. Select the fixture services through Lifecycle.

Use a dedicated test environment. Record the fixture commit and the API, UI, CLI, and chart revisions for each run. A passing local run does not certify a production installation.

## Fixture services

The root [`lifecycle.yaml`](../lifecycle.yaml) defines the service selection and expected behavior.

| Service | Expected result |
| --- | --- |
| `lc-test-4` | Default HTTP service. `/` contains `E2E_HTTP_OK lc-test-4`. `/health` contains `E2E_HTTP_HEALTHY`. |
| `e2e-job` | Default Job reaches `Complete`. Its output includes `E2E_JOB_OK`. |
| `e2e-cron` | Default CronJob schedules once per minute. A scheduled child Job reaches `Complete` and prints `E2E_CRON_OK`. |
| `e2e-attach` | Optional HTTP service without a setup command. Use it to check service connection and workspace exclusivity. |
| `e2e-agent-sandbox` | Optional sandbox fixture. `/` contains `E2E_SANDBOX_BASELINE`. `/health` contains `E2E_SANDBOX_HEALTHY`. |
| `e2e-job-fail` | Negative fixture. The Job prints `E2E_JOB_EXPECTED_FAILURE`, exits with code 23, and fails deployment. |
| `e2e-unsafe` | Negative fixture. The chart requests a ClusterRole. The deployment must reject it without creating that resource. |
| `e2e-symlink` | Negative fixture. The selected chart path is a symbolic link. The deployment must reject that chart input. |

Do not select negative fixtures for a successful deployment test. Rejection of a selected chart link does not imply rejection of unrelated repository links.

A successful deployment also runs command and Docker completion webhooks. Check both `E2E_COMMAND_WEBHOOK_DONE` and `E2E_DOCKER_WEBHOOK_DONE`. An error deployment runs the command webhook with `E2E_ERROR_WEBHOOK_OK`. Verify Lifecycle webhook history as well as marker output.

The observer below does not read logs or webhook history. Capture only these known markers through an approved log interface. Keep raw logs and credentials out of evidence.

## Setup and approval

1. Confirm that the selected workspace backend supports environment sessions and service development.
2. Deploy the fixture and capture the baseline before opening an agent session.
3. Open the intended environment session or sandbox fork through Lifecycle.
4. Check the complete setup command in the approval request before approval.
5. Confirm that setup has not run before approval.
6. Approve setup and wait for the workspace and selected service to become ready.

For `lc-test-4`, setup appends one line to `.lifecycle-e2e/setup/runs`. Successful setup writes `E2E_SETUP_APPROVED_SUFFIX run=<count>` to `.lifecycle-e2e/setup/success`.

The optional `.lifecycle-e2e/setup/pause` file makes setup wait for 20 seconds. The optional `.lifecycle-e2e/setup/fail` file makes setup exit with code 23. Create these files only inside the task-owned workspace when the test requires them. Remove the failure file before an explicitly approved retry. Verify the counter after each attempt.

For `e2e-agent-sandbox`, approved setup writes `E2E_SANDBOX_SETUP_OK` to `.lifecycle-e2e/agent-sandbox/setup`.

An environment session modifies the selected environment service during development. A sandbox fork creates a separate environment. For a fork, also verify that the original service, namespace, and HTTP content remain unchanged.

If setup or service connection requires recovery, preserve the workspace and its PVC. Use the supported operator procedure. Do not clear database locks, strip finalizers, or delete resources to make a check pass. An uncertain service connection can require administrator review without an automatic recovery path.

## Capture deployment evidence

[`tools/observe_environment.py`](tools/observe_environment.py) uses Python's standard library and `kubectl`. It issues Kubernetes `get` requests and optional HTTP `GET` requests. It does not execute commands in containers or read the database, Secrets, logs, browser, or GitHub.

Supply the exact context, namespace, selected Deployment, and a new output file. The directory must exist. Existing files are never overwritten. Obtain resource names from the intended environment, rather than guessing from display names.

```sh
KUBE_CONTEXT='your-test-context'
ENV_NAMESPACE='your-environment-namespace'
SERVICE_DEPLOYMENT='your-service-deployment'
SERVICE_URL='https://your-test-service.example'
EVIDENCE_DIR="$(mktemp -d)"

python3 e2e/tools/observe_environment.py \
  --context "$KUBE_CONTEXT" \
  --namespace "$ENV_NAMESPACE" \
  --deployment "$SERVICE_DEPLOYMENT" \
  --output "$EVIDENCE_DIR/baseline.json" \
  --ignore-restarted-at \
  --require-ready --expect-no-pvc \
  --http "$SERVICE_URL/" 'E2E_HTTP_OK lc-test-4' \
  --http "$SERVICE_URL/health" 'E2E_HTTP_HEALTHY'
```

Use the sandbox markers for `e2e-agent-sandbox`. The HTTP check requires the expected marker and status 200 by default. `--expected-status` changes that status. It reads at most 64 KiB and retains no response body. It does not follow redirects or supply credentials. HTTPS uses certificate verification. DNS and routing errors remain failures. The helper does not rewrite hostnames or redirect traffic to loopback. Supply only public test URLs and nonsecret markers. URLs cannot contain credentials, a query, or a fragment.

Each snapshot includes:

- Namespace and selected Deployment identities, owners, replicas, and readiness.
- Namespace Services, Ingresses, Pods, Jobs, CronJobs, horizontal pod autoscalers (HPAs), and PVCs.
- PVs referenced by those PVCs, plus PVs recorded in an optional baseline.
- Container images, working directories, ports, volume references, and service accounts.
- Command and argument counts and hashes. Raw commands can contain credentials and are not saved.
- Configuration hashes for each object's full `spec`, metadata labels, and annotations, with the exclusions described below. Environment values and raw annotations are not saved.
- HTTP status and whether each expected marker was found.

Treat snapshots as private operational evidence. Resource names, paths, images, and hashes can still reveal configuration. The helper reads resource specifications in memory to calculate hashes.

Only the selected Deployment is captured. Other listed resources come from the explicit namespace. PV reads use exact names from current or baseline PVC evidence. No cluster-wide PV list is used.

## Verify development and restoration

Capture a baseline with `--ignore-restarted-at` when archive is expected to restart the Deployment. This option excludes only `kubectl.kubernetes.io/restartedAt` from configuration hashes. The output records this rule. Both snapshots must use the same rule.

The top-level Deployment annotation `deployment.kubernetes.io/revision` is controller bookkeeping. Its numeric value is recorded separately and always excluded from configuration hashes. Other annotations remain in the hashes. Object status and server metadata, such as resource version, are not configuration fields. HPA replica status is recorded separately and does not change its configuration hash. Deployment `spec.replicas` remains a configuration field, so autoscaler changes can require review during a restore comparison.

After approved setup and service connection, capture the selected PVC and service readiness:

```sh
WORKSPACE_PVC='your-workspace-pvc'
python3 e2e/tools/observe_environment.py \
  --context "$KUBE_CONTEXT" --namespace "$ENV_NAMESPACE" \
  --deployment "$SERVICE_DEPLOYMENT" \
  --output "$EVIDENCE_DIR/attached.json" \
  --baseline "$EVIDENCE_DIR/baseline.json" --verify identity \
  --ignore-restarted-at --require-ready --require-pvc "$WORKSPACE_PVC" \
  --http "$SERVICE_URL/" 'E2E_HTTP_OK lc-test-4'
```

Use the actual editor to replace the fixture's index marker with a unique test marker. Save the file. Confirm the exact workspace file change and unchanged health file through the supported workspace interface. Then repeat the observer with a new output file and the edited HTTP marker. A saved editor buffer alone does not prove that the service serves the change.

Archive the task-owned session through Lifecycle. Wait for its workspace cleanup and service rollout. Then compare the restored deployment with the original baseline:

```sh
python3 e2e/tools/observe_environment.py \
  --context "$KUBE_CONTEXT" --namespace "$ENV_NAMESPACE" \
  --deployment "$SERVICE_DEPLOYMENT" \
  --output "$EVIDENCE_DIR/restored.json" \
  --baseline "$EVIDENCE_DIR/baseline.json" --verify restored \
  --ignore-restarted-at --require-ready --expect-no-pvc \
  --http "$SERVICE_URL/" 'E2E_HTTP_OK lc-test-4' \
  --http "$SERVICE_URL/health" 'E2E_HTTP_HEALTHY'
```

`--verify identity` requires the same namespace UID and preserves each baseline Deployment, Service, Ingress, CronJob, and HPA UID. It permits additional resources, such as the agent workspace Service, and records them in `comparison`. Removed or replaced baseline resources fail.

`--verify restored` requires the exact baseline set of those resources and matching configuration hashes. Additional workspace Services must disappear before this check passes. Neither mode checks database dev-mode flags or session state. Verify those through Lifecycle separately.

With `--baseline` alone, `comparison` reports added, removed, and changed resource identities or configuration hashes. Differences do not fail this informational mode. Scheduled Jobs and replacement Pods can change during a valid run. Readiness and HTTP checks fail only when explicitly requested.

The helper takes a snapshot through separate reads. It is not an atomic cluster snapshot. Each Kubernetes request has a timeout. Each HTTP probe has a total deadline, including DNS and response reading. It does not wait for rollout or retry failures. Read the failed checks, wait through the normal deployment workflow, and capture a new file. Kubernetes error states remain distinct from confirmed absence. Exit code 1 retains failed evidence. Exit code 2 means invalid arguments or an unavailable output destination.

## Cleanup and test boundaries

Use Lifecycle to archive task-owned sessions and remove task-owned environments. Preserve preexisting environments and user-owned servers. For a PR test, closing the authorized test PR should drive teardown. Marking an environment static does not remove its API lease or prevent PR-close teardown.

For a task-owned API fixture, archive the session and verify service restoration before unpinning or deleting the environment. Use supported Lifecycle actions. Leave preexisting static environments unchanged.

Use the attached snapshot to track the former workspace PV during cleanup:

```sh
python3 e2e/tools/observe_environment.py \
  --context "$KUBE_CONTEXT" --namespace "$ENV_NAMESPACE" \
  --deployment "$SERVICE_DEPLOYMENT" \
  --output "$EVIDENCE_DIR/removed.json" \
  --baseline "$EVIDENCE_DIR/attached.json" \
  --ignore-restarted-at --expect-absent
```

This checks the namespace and baseline PVs are absent. A storage class with a `Retain` policy can intentionally retain a PV. Record that policy and handle retained storage through the approved operator process. Do not remove storage to force a passing result.

Verify associated job namespaces separately with their exact names and recorded UIDs. Also verify environment state, archived sessions, ended runtimes, and any temporary settings through Lifecycle. The observer cannot prove those application states.

PR reopen tests must preserve the environment record while creating new namespace and workload UIDs after teardown. Record each cycle separately. A webhook delivery failure before application ingress is different from an application deployment failure.

Restore temporary settings to their exact original state, including absent versus explicit values. Remove only task-owned authentication caches and evidence exports. Do not revoke unrelated sessions or stop user-owned servers.

Keep failed evidence with the final results. Separate local fixture results from AWS identity, networking, admission, storage, and production fleet checks. These fixtures do not replace those checks.
