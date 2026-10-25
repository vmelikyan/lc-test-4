// Prepared E2E fixture. Copy into a task-owned workspace only through the runtime owner.
// Adjacent mcp-state.json: {"label":"session-a-run-1","failDiscovery":false}
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
const statePath = new URL('./mcp-state.json', import.meta.url);
const readState = () => {
  const state = JSON.parse(readFileSync(statePath, 'utf8'));
  if (!/^[a-z0-9-]{1,48}$/.test(state.label)) throw new Error('Invalid fixture label');
  return state;
};
const reply = (id, result) => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, result }) + '\n');
const fail = (id, message) => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, error: { code: -32603, message } }) + '\n');
createInterface({ input: process.stdin }).on('line', (line) => {
  let request;
  try { request = JSON.parse(line); } catch { return; }
  if (request.id === undefined) return;
  try {
    if (request.method === 'initialize') {
      reply(request.id, { protocolVersion: request.params?.protocolVersion || '2024-11-05', capabilities: { tools: {} }, serverInfo: { name: 'lifecycle-e2e-isolation', version: '1.0.0' } });
    } else if (request.method === 'ping') {
      reply(request.id, {});
    } else if (request.method === 'tools/list') {
      const state = readState();
      if (state.failDiscovery) throw new Error('E2E_DISCOVERY_EXPECTED_FAILURE');
      process.stderr.write(`E2E_MCP_DISCOVERY ${state.label}\n`);
      reply(request.id, { tools: [{ name: 'e2e_probe', description: `Return the fixture marker ${state.label}.`, inputSchema: { type: 'object', properties: {}, additionalProperties: false }, annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false } }] });
    } else if (request.method === 'tools/call' && request.params?.name === 'e2e_probe') {
      reply(request.id, { content: [{ type: 'text', text: `E2E_MCP_RESULT ${readState().label}` }], isError: false });
    } else {
      fail(request.id, 'Unsupported fixture method');
    }
  } catch (error) { fail(request.id, error.message); }
});
