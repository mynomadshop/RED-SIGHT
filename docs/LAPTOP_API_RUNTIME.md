# Laptop CPU/API installation and agent runtime

Choose the **Laptop / API** profile with the recommended **native** runtime.
Setup provisions the bundled Python runtime, CPU PyTorch, CPU ONNX Runtime,
the desktop/backend environment, the action gateway environment, and Playwright
Chromium. Docker, WSL2, CUDA, and a running LM Studio server are unnecessary for
this profile. Existing CUDA and container profiles remain available.

## Startup and resource allocation

The generated `START-REDSIGHT-NATIVE.ps1` launcher performs a quick CPU affinity
and available-memory check without loading models or scanning files. It reserves
capacity for foreground applications, limits numerical worker threads to 1–8,
and limits simultaneous agent work to 1–4 jobs according to available resources.
The backend uses a single process and persistent embedded Qdrant.

The launcher prefers the last selected ports, then 8000 for the backend and 8765
for the gateway. It checks occupied ports and chooses distinct free alternatives.
It reuses a running service only when its health response identifies the correct
service and installation. Services bind to `127.0.0.1`; this does not change the
network router or Windows default gateway. A port captured by another program
between allocation and process startup is reported as a startup failure.

Selected ports and resource budgets are recorded in
`%LOCALAPPDATA%\RedSight\settings\native-runtime.json`. The desktop, memory,
agent bridge, and gateway use the same recorded endpoints. Explicit launcher
`-Port` and `-GatewayPort` values express preferred ports, with conflict handling.

## Connect a provider

1. Open **Settings → AI Provider**.
2. Select OpenAI, Anthropic Claude, Google Gemini, xAI, OpenRouter, Groq,
   Mistral, Together, DeepSeek, Cerebras, or a custom OpenAI-compatible endpoint.
3. Enter the key and use **Refresh models** to populate the editable model list.
   Select a chat model that supports tool calling; model access depends on the
   provider account. A custom endpoint also needs its base URL and model ID.
4. Use **Test response & tools**. This tests an actual completion and, when
   supported, a harmless tool-call/result exchange with the selected model.
5. Use **Apply & Restart** to save the selection and restart the installed
   desktop and its services. **Save & Apply** also remains available; provider
   changes are read by the backend on the next request.

The UI opens before any provider is configured. Keys remain protected with
Windows CurrentUser DPAPI. Refreshing the model list does not verify inference.
The response test uses a small amount of provider inference and may incur an
API charge. Success verifies connectivity and the selected model's response,
not the quality of every future task. Failed draft tests never save credentials.

## Agent and skill execution

Use `/agent GOAL`, an action request in chat, or `/skill SKILL NAME | INSTRUCTION`.
Agents send actual results back to the selected model before choosing dependent
actions. Native OpenAI-style, Anthropic, and Gemini tool calls are supported;
provider response blocks and Gemini thought signatures survive subsequent turns.
Models without native tool support can use the existing JSON-plan fallback.

Agents discover and read installed `SKILL.md` guidance with `skills.list` and
`skills.read`, then carry out the procedure through registered tools. Direct
skill execution uses the same bounded feedback loop. Configured MCP servers can
be enumerated, their tool definitions inspected, and their tools called through
the existing approval policy. An API key alone does not configure an MCP server,
its required local executable, or a separate search-service credential.

Twelve ready-to-use skills ship inside the application package. Find them in
**Settings → Skills**, edit an example request, and run it in chat. See the
[catalog and tool limits](AGENT_PRODUCTIVITY.md).

The default action budget is 16 steps, with a 540-second execution window per
resume, including time waiting for an execution slot. `REDSIGHT_AGENT_MAX_STEPS`
supports up to 50. A failed read can trigger up to two recovery attempts based
on its observed error; remaining actions from the failed batch are skipped.
Failed writes and exhausted recovery budgets stop the run. New state-changing steps
require review under the existing tool policy. Approval is tied to the exact
pending actions; the server retains a run ID and resumes without replaying
completed changes. Pending runs expire after 30 minutes or a gateway restart.
After expiration, inspect completed results before beginning a new task.

Specialized multi-agent tasks now execute through the authenticated gateway.
Use unique `task_id` values and reference them in `dependencies`. Downstream
agents receive successful dependency results and are blocked on failed
dependencies. A second orchestration does not re-execute the first one's tasks.

## Checks and troubleshooting

- Setup runs `pip check` in each environment and treats a missing action gateway
  as an installation failure. APScheduler stays on its supported 3.x API, and
  `psutil` is explicitly installed for hardware-aware sizing.
- The Python quality workflow runs the full suite, including provider round trips,
  exact-plan approval/resume, failure propagation, and task dependency tests.
- The Windows build installs the actual generated package, checks CPU-only Torch,
  constructs Settings with no provider, and runs `Test-NativeRuntime.py`.
  That smoke test occupies the default ports, starts both installed services,
  checks memory, saves an encrypted test provider key while services are running,
  and performs a real find/read/write sequence through a loopback API fixture.
  It also verifies repeat-launch reuse, owned-service restart, provider response
  after restart, bundled skill discovery, setup repair, and uninstall.
- A second Windows job installs CPU packages, switches that environment to
  CUDA packages, and verifies the actual Torch runtime, ONNX provider, package
  exclusivity, and dependency consistency. Physical GPU execution is verified
  by setup on the user's NVIDIA machine, not by a hosted runner without a GPU.

If startup fails, inspect `%LOCALAPPDATA%\RedSight\logs\native-backend.err.log`
and `native-gateway.err.log`; restart failures also appear in `restart.log`.
If a provider rejects a model, refresh the list, choose an available tool-capable
model, and test its response. Live billing, provider credentials,
remote MCP programs, and NVIDIA hardware are not simulated into successful tests.

Protocol references checked during this change:
- [Anthropic tool results](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)
- [Gemini thought signatures](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures)
- [APScheduler 3.11.3](https://pypi.org/project/APScheduler/)
