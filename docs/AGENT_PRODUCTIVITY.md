# Agent productivity and setup

This update adds a usable skill catalog, real provider response testing, a
desktop restart action, and coordinated CPU/CUDA dependency installation.
Use a successful Windows installer build for the commit you are installing;
the Actions artifact contains the setup executable and its checksum.

## Connect and apply a provider

1. Open **Settings → AI Provider** and select your provider.
2. Paste its API key. Existing encrypted keys can be kept without retyping.
   For a custom compatible endpoint, also enter the base URL and model ID.
3. **Refresh models** retrieves available model IDs. Select a chat model from
   that list or enter an exact ID supplied by your provider.
4. **Test response & tools** sends a small request through the same adapter as
   production chat. It checks a harmless `redsight_probe` tool call and returns
   its result to the model. No file or system action is executed by this probe.
   Providers that only answer text are identified separately. The test can use
   API credit; access, billing, quotas, and model permissions belong to your account.
5. **Apply & Restart** saves the encrypted key and settings, closes the desktop,
   stops services verified as belonging to this installation, and uses the
   normal Windows launcher to reopen RedSight. Finish active chat/agent work
   first. Restarting expires pending approval runs; start a new task after
   checking any completed actions.

The UI stays responsive while the bounded provider test runs. Editing,
closing, or restarting Settings waits for that test to finish. Draft failures
do not overwrite saved settings. **Save & Apply** remains useful for immediate
provider changes without restarting. Runtime changes need a restart; changing
to container mode also requires the optional container components from setup.

Supported adapters are LM Studio, OpenAI, Anthropic, Gemini, xAI, OpenRouter,
Groq, Mistral, Together, DeepSeek, Cerebras, and custom OpenAI-compatible APIs.
Both OpenAI-style and native Anthropic/Gemini tool-result history are retained.
OpenAI chat requests use `max_completion_tokens` for reasoning-model support.

## Twelve bundled skills

Open **Settings → Skills**, search, select an example, replace its placeholders
with your task details, and press **Run skill in chat**. The same procedure can
be invoked with `/skill NAME | INSTRUCTION`.

| Skill | Task |
|---|---|
| `find-files` | Find files in a specified folder and inspect likely matches |
| `summarize-documents` | Extract supported document text and summarize with evidence |
| `compare-documents` | Compare two documents and identify material differences |
| `profile-data` | Inspect CSV, TSV, or XLSX columns, blanks, samples, and duplicates |
| `consolidate-csv` | Combine matching CSV/TSV exports into a new output |
| `business-report` | Turn supplied evidence into a report, optionally PDF |
| `research-brief` | Research primary web sources and produce a dated, cited brief |
| `build-knowledge-library` | Index an explicitly selected folder and verify retrieval |
| `windows-health` | Inspect system health and explain observed problems |
| `cuda-readiness` | Check NVIDIA, driver, Torch, and installed runtime readiness |
| `review-project` | Inspect project structure and source for concrete issues |
| `plan-workflow` | Break a task into executable steps with dependencies |

These are shipped inside the Python wheel and Windows payload; no skill
download is required. Skills use the registered RedSight tool catalog and
the same agent feedback loop as other tasks. A research search requires a
Brave Search credential; source URLs can be supplied when search is unavailable.
Local model inference requires a model loaded in LM Studio.

### Concrete document and data tools

- `documents.extract`: PDF, DOCX, and UTF-8 text extraction with page markers
  for PDFs and explicit truncation. Defaults: 30,000 characters and 25 PDF
  pages; maximums: 100,000 characters and 100 pages. Scanned PDFs need OCR.
- `data.profile`: CSV/TSV and read-only XLSX inspection. Defaults to 10,000
  rows, with a maximum of 100,000; counts explicitly describe scanned coverage.
  Formula text is preserved without recalculation. Samples are bounded.
- `data.merge`: matching CSV/TSV headers and column order, at most 100 files,
  optional exact-row deduplication, and a new CSV output. Defaults to 250,000
  rows, with a maximum of one million. The tool refuses existing outputs and
  never publishes a partial merge. Formula-like text is escaped for spreadsheet
  import, while signed numbers and text IDs are preserved in the CSV. Excel may
  infer types when opening a CSV; import identifier columns as Text to keep zeros.

Inputs are limited to 250 MB each and 500 columns for tabular operations.
Paths use the gateway's existing access rules. Mutations require approval of
the actual proposed action. The agent can recover from up to two failed reads
by choosing a new action from the error; it stops on uncertain write failures.

## CPU and CUDA dependencies

The installer upgrades dependencies within their supported project ranges and
runs `pip check`. It constrains the selected Torch and ONNX versions while
upgrading the rest, so a generic dependency resolution cannot replace the
chosen compute build. Profile changes remove the opposite ONNX distribution
and repair shared files. Actual `torch.version.cuda` is checked after installation.

| Detected profile | PyTorch index | ONNX Runtime |
|---|---|---|
| Laptop/API | CPU | CPU distribution only |
| Compute capability ≥ 7.5 and driver supports CUDA ≥ 13.0 | CUDA 13.0, Torch ≥ 2.12 | GPU ≥ 1.27, CUDA 13 |
| Pre-Blackwell GPU and driver supports CUDA ≥ 12.6 | CUDA 12.6 compatibility build | GPU ≥ 1.21, < 1.27 |
| Blackwell with an older/unknown driver capability | CUDA 12.8, Torch ≥ 2.7, < 2.12 | GPU ≥ 1.21, < 1.27 |
| Other older/unknown combinations | CUDA 12.4, Torch ≥ 2.5, < 2.7 | GPU ≥ 1.20, < 1.27 |

Fallback selection is followed by a real per-device allocation/kernel check;
it does not guarantee an old driver can run the selected wheel. Update the
NVIDIA driver if that check reports a mismatch. Mixed pre-Turing/Blackwell
machines require separate environments because one supported wheel cannot
cover those generations together. Other mixed machines retain CUDA 12 where needed.

The Windows workflow installs CPU packages and replaces them with CUDA packages
on a hosted runner, verifying imports, runtime versions, the ONNX CUDA provider,
and package consistency. Hosted runners have no physical NVIDIA GPU; the setup
check on the user's machine verifies actual device execution. Provider protocol
tests use loopback HTTP fixtures; use the Settings response test to verify your
real API key and model access.

## Verification and diagnostics

The quality workflow runs the full Python suite and maintained-source lint.
The Windows workflow builds and installs the real package under a path with
spaces, drives provider Settings with DPAPI, boots the backend and gateway,
performs dependent file actions with approval/resume, verifies owned-service
restart and a response from the saved provider afterward, then repairs and
uninstalls the application. It also verifies all twelve skills are discoverable.

Logs are under `%LOCALAPPDATA%\RedSight\logs`. Check `restart.log`,
`native-backend.err.log`, and `native-gateway.err.log` for startup failures.
Saved runtime ports are in `settings\native-runtime.json` under the same
RedSight data directory. Provider failures report the HTTP status and a useful
hint without echoing credentials or provider response bodies.

Compatibility references checked September 2026:

- [PyTorch releases and supported CUDA builds](https://github.com/pytorch/pytorch/releases)
- [ONNX Runtime CUDA compatibility](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
- [OpenAI Chat Completions parameters](https://developers.openai.com/api/reference/resources/chat)
- [Gemini thought signatures](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures)
