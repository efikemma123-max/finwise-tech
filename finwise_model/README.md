# Finwise Model Workspace

This folder is the serious starting point for building Finwise-owned model intelligence.

## What this workspace does

- Generates **synthetic Finwise trading contexts** shaped like the real copilot context.
- Builds a **domain corpus** for language-model pretraining style experiments.
- Builds an **instruction/SFT dataset** for Finwise Copilot chat behavior.
- Defines a **foundation-model research manifest** so the model effort has a clean structure.

## Important reality check

Training a true foundation model from scratch is not something this repo can finish by itself.

You would still need:

- very large datasets
- a real training stack
- substantial GPU infrastructure
- evaluation and safety loops

So this workspace is designed to move Finwise from:

`no model ownership`

to:

`Finwise-owned data pipeline + Finwise-owned training format + Finwise-ready local deployment path`

## Files

- `sample_contexts.py`
  Generates synthetic broker, market, route, and execution contexts that match Finwise Copilot's runtime shape.

- `scripts/build_datasets.py`
  Builds:
  - `datasets/finwise_domain_corpus.jsonl`
  - `datasets/finwise_copilot_sft.jsonl`
  - `datasets/dataset_manifest.json`

- `scripts/export_live_data.py`
  Exports real Finwise data from:
  - `trade_history`
  - `broker_connections`
  - `model_event_log`
  - `copilot_chat_turns`

  into:
  - `datasets/finwise_live_domain_corpus.jsonl`
  - `datasets/finwise_live_sft.jsonl`
  - `datasets/live_export_manifest.json`

- `scripts/validate_datasets.py`
  Validates the generated JSONL outputs.

- `scripts/evaluate_copilot.py`
  Runs fixed Finwise Copilot eval scenarios against the live turn engine so you can score action selection, reasoning, and memory updates.

- `configs/foundation_manifest.json`
  High-level model project plan.

- `configs/copilot_eval_cases.json`
  Starter evaluation cases for route explanations, safe tool actions, and memory behavior.

## Recommended path

### Phase 1

Use the generated SFT dataset to train a Finwise Copilot instruction model on top of an open base model.

### Phase 2

Expand the domain corpus with:

- real market commentary
- your trade journal language
- route explanations
- broker diagnostics
- alert and execution narratives

### Phase 3

If you still want "foundation-like" ownership later, use a larger accumulated Finwise corpus for continued pretraining on an existing open model family before instruction tuning.

## Commands

Build the datasets:

```powershell
python finwise_model/scripts/build_datasets.py --limit 180
```

Validate them:

```powershell
python finwise_model/scripts/validate_datasets.py
```

Export live Finwise data:

```powershell
python finwise_model/scripts/export_live_data.py
```

Run the copilot evaluations:

```powershell
python finwise_model/scripts/evaluate_copilot.py
```

Run the Finwise-owned local runtime:

```powershell
python -m uvicorn finwise_model.local_runtime:app --host 127.0.0.1 --port 11435
```

Or from the repo root:

```powershell
.\start_finwise_runtime.ps1
```

Create and inspect Finwise-owned model descriptors:

```powershell
python -m finwise_model.runtime_cli create finwise-scratch:0.1 -f finwise_model/FinwiseModelfile
python -m finwise_model.runtime_cli list
python -m finwise_model.runtime_cli show finwise-scratch:0.1 --full
python -m finwise_model.runtime_cli engine finwise-scratch:0.1
python -m finwise_model.runtime_cli copy finwise-scratch:0.1 finwise-scratch:dev
python -m finwise_model.runtime_cli delete finwise-scratch:dev
```

Create a descriptor for a real local GGUF model:

```powershell
python -m pip install -r finwise_model/requirements-local-runtime.txt
Copy-Item finwise_model/FinwiseGGUFModelfile.example finwise_model/FinwiseGGUFModelfile
# Edit WEIGHTS to your local .gguf path first.
python -m finwise_model.runtime_cli create finwise-gguf:local -f finwise_model/FinwiseGGUFModelfile
```

Then point the app at it:

```env
FINWISE_COPILOT_PROVIDER=ollama
FINWISE_COPILOT_MODEL=finwise-scratch:0.1
FINWISE_COPILOT_BASE_URL=http://127.0.0.1:11435
```

This is intentionally an Ollama-compatible first step, not a full Ollama replacement yet. It gives Finwise its own `/api/tags`, `/api/show`, `/api/chat`, `/api/generate`, `/api/create`, `/api/copy`, `/api/delete`, and `/api/ps` runtime so the app can talk to a local service you control. It also includes a small registry and CLI for Finwise model descriptors.

The next deeper layer is replacing the current rules-plus-context responder with:

- tokenizer loading
- model weight loading
- transformer inference
- sampling controls
- quantized model support
- model pull/import commands

The runtime can already select a local inference backend when available:

- `ENGINE rules` uses the built-in Finwise context responder.
- `ENGINE llama-cpp` uses a local `.gguf` file through `llama-cpp-python`.
- `ENGINE transformers` uses a local Hugging Face model folder through `transformers`.
- `ENGINE auto` chooses from the `WEIGHTS` path when possible and falls back to rules.

For full independence, keep your active model on:

```text
ENGINE rules
```

That path uses only Finwise code and the live context packet. It does not require Ollama, OpenAI, llama.cpp, Transformers, or model weights.

The built-in rules engine is designed to answer in three layers:

- direct read
- why it matters
- suggestions

This keeps the local runtime helpful instead of only returning strict one-line answers.

## Output formats

### SFT dataset

Each row contains:

- `id`
- `messages`
- `metadata`

This is suitable for chat-style supervised fine-tuning pipelines.

### Domain corpus

Each row contains:

- `id`
- `text`
- `metadata`

This is suitable for corpus-building and domain-adaptation experiments.

## Copilot memory

Finwise Copilot now supports a small durable user-memory layer stored in the app database.

That memory keeps track of things like:

- preferred symbols and timeframes
- common broker context
- preferred reply style
- recent topics and actions

This memory is for continuity and personalization, not hidden autonomous trading decisions.

## Best next steps

1. Generate the starter datasets.
2. Add real Finwise examples from live sessions and trade history.
3. Choose a base open model.
4. Fine-tune locally.
5. Swap the trained artifact back into `broker_ai_copilot.py`.

That is the realistic path toward a truly Finwise-owned model.
