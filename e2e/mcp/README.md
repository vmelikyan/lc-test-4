# Workspace MCP isolation fixture

This dependency-free Node stdio server preserves the fixture used for Lifecycle's
25 October 2026 MCP admission, session isolation and discovery-recovery checks.
It is not enabled by `lifecycle.yaml`. Use only task-owned disposable sessions and
an explicitly scoped MCP connection.

[`e2e-mcp-server.mjs`](e2e-mcp-server.mjs) is byte-for-byte the observed workspace
fixture, SHA-256
`9308f059a6b684874e0df216f61aa772cd4b9d7757189d782a50ca1ca25c03f9`.
Those historical managed passes used API `7856eadb` and retained `7ac03a7e`
workspace gateways. They do not qualify a later candidate or fixture revision.

## Protocol and state

The server reads one JSON-RPC request per stdin line and writes one response per
stdout line. `initialize` echoes the requested protocol version, or defaults to
`2024-11-05`; the recorded gateway handshake requested `2025-03-26`. It also
supports `ping`, `tools/list` and `tools/call` for `e2e_probe`. Notifications and
invalid JSON lines receive no response. Unsupported methods return error -32603.

Copy [`mcp-state.example.json`](mcp-state.example.json) to `mcp-state.json` beside
the server in each workspace. The path is relative to the server file, not the
process working directory. The server rereads state for each list and call.

| Field | Behavior |
| --- | --- |
| `label` | One to 48 lowercase letters, digits or hyphens. Appears in the discovered tool description, stderr `E2E_MCP_DISCOVERY <label>`, and tool result `E2E_MCP_RESULT <label>`. Use a different label for each session/run. |
| `failDiscovery` | Set the JSON boolean to true to make `tools/list` return error -32603 with `E2E_DISCOVERY_EXPECTED_FAILURE`. Restore false for recovery. This flag affects discovery only; it does not block direct `tools/call`. |

The tool advertises `readOnlyHint: true` deliberately. Workspace-owned metadata
must not select the read authorization policy. Lifecycle must classify the tool
as an external MCP write and apply the configured write/tool policy. The default
requires approval; an administrator's configured allow or deny remains effective.
The fixture itself provides neither authorization nor an approval gate.

## Connected rerun

1. Record the API/UI/CLI and fixture revisions, actual gateway image/source,
   backend, MCP connection scope, policy, session owners and starting catalog
   state. Use two fresh, independent workspaces. Do not reuse old session IDs.
2. Through the runtime owner's supported preparation path, copy the server and
   state into each exact workspace. The historical connection used stdio command
   `node` with argument `/workspace/e2e-mcp-server.mjs`, so its state was
   `/workspace/mcp-state.json`. Set A to `session-a-run-1` and B to
   `session-b-run-1`, both with `failDiscovery: false`. Verify the copied hash.
   Operator copies, syntax checks and direct protocol probes are preparation;
   they are not proof of managed model execution.
3. Configure an enabled repository-scoped stdio connection for this command.
   Use default Develop selection for A and explicit saved connection selection
   for B. Confirm the distinction in saved controls and actual run-plan snapshots;
   a selected UI checkbox alone does not prove admission.
4. Start a separate managed run in each session asking the model to call the MCP
   `e2e_probe` tool. Capture tool identity, policy/approval events and actual result
   markers. Under the default policy, require the write approval before the call.
   A shell command named `e2e_probe`, direct gateway call, model claim or outer
   completed status cannot substitute for the MCP result. Keep failed attempts.
5. After A's first run ends, change only its label to `session-a-run-2`. Start a
   new run and require fresh discovery plus the new marker without B's marker.
   Preserve discovery evidence, such as the fixture's stderr discovery marker
   correlated to the run or its discovered tool description. A changed call
   result alone does not prove fresh discovery because calls also reread state.
6. Set A's `failDiscovery` to true and start another new run. Require discovery
   failure and no successful call of an unavailable MCP tool; do not use a shell
   fallback. Then restore false, set `label` to `session-a-recovered`, and start
   another run. Require fresh discovery and a policy-authorized MCP result.
   Change only fixture state for recovery; do not clear persisted configuration
   to make it pass.
7. Compare read-only shared and user catalog/error snapshots before and after
   successful calls, failure and recovery. Require no persisted workspace tool
   catalog or transient validation error. Save counts and relevant timestamps,
   not credentials, raw connection configuration or encrypted user state.
8. Two sessions owned by one user prove only session isolation. A live cross-user
   claim requires a second authenticated owner, separate workspace and corresponding
   catalog/result assertions. Record that limit when only one owner is available.
9. Archive owned sessions through Lifecycle, verify restoration and exact owned
   workspace storage removal, then remove only the owned MCP configuration and
   temporary settings. Follow the [fixture cleanup rules](../README.md#cleanup-and-test-boundaries).

Record local protocol checks separately from the connected run. Preserve provider
errors even if the run's stored status says completed; require actual tool results
and approval evidence. Neither these checks nor this fixture establish production
rollout, HTTP/SSE MCP parity or cross-user behavior that was not exercised.
