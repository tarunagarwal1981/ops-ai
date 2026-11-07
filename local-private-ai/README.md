# Private AI on your laptop

Run an open-weight model on your own machine with [Ollama](https://ollama.com), call it from Python through its OpenAI-compatible endpoint, and ask questions about a folder of your own files. No API key, no cloud, no vector database.

Companion code for the post *Run a Private AI on Your Laptop in 15 Minutes*.

## What's here

- `ask_local.py`: ask the local model a question. `--json` forces the reply into a JSON schema.
- `chat_with_files.py`: "chat with a folder" of `.txt` / `.md` files. Local embeddings + cosine similarity in numpy.
- `local_ai.py`: shared settings, plus a guard that refuses non-local URLs and Ollama cloud models.
- `test_offline.py`: runs all of the above against a fake Ollama on 127.0.0.1. Needs no model.
- `sample_docs/`: three short fictional documents to try it on.

## 1. Install Ollama

From the [Ollama README](https://github.com/ollama/ollama):

- **macOS** (Sonoma 14 or newer): `curl -fsSL https://ollama.com/install.sh | sh`, or download the app from ollama.com/download
- **Windows** (10 22H2 or newer): in PowerShell, `irm https://ollama.com/install.ps1 | iex`, or run `OllamaSetup.exe`. No admin rights needed.
- **Linux**: `curl -fsSL https://ollama.com/install.sh | sh`

Check it's running: `ollama -v`. On Linux, start the server with `ollama serve` if it isn't already running as a service.

## 2. Make it local-only (do this before pulling anything)

Ollama can also run *cloud* models when you sign in. Turn that off:

- Set `OLLAMA_NO_CLOUD=1`, or put `{"disable_ollama_cloud": true}` in `~/.ollama/server.json`, then restart Ollama. The server log should show `Ollama cloud disabled: true`. ([FAQ](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features))
- In the desktop app, the same switch is **Settings → Cloud**.
- Leave `OLLAMA_HOST` alone. By default Ollama listens only on 127.0.0.1:11434, so nothing else on the network can reach it.

Then the real test: once your models are pulled, turn off Wi-Fi and run the scripts. If they still answer, the work is happening on your machine.

## 3. Pull a chat model and an embedding model

Pick one chat model that fits your memory. Download size is not the memory you need: context adds more on top, and your other apps need room too.

- 8-16 GB RAM, or no GPU: `qwen3.5:4b` (about 3.3-4 GB) or `gemma4:e2b` (about 7.2 GB; Ollama suggests 8 GB of free memory for it)
- 16 GB: `qwen3.5:9b` (about 6.6-7.6 GB). This is the default in the scripts.
- 32 GB Mac or a 24 GB GPU: `gpt-oss:20b` (14 GB), `gemma4:26b` (about 16-19 GB) or `qwen3.5:27b` (about 17-20 GB)

```bash
ollama pull qwen3.5:9b
ollama pull nomic-embed-text      # 274 MB embedding model
ollama run qwen3.5:9b "Say hello in one sentence."
ollama ps                          # what's loaded, and on GPU or CPU
```

Sizes are from the Ollama library pages and coverage checked in November 2026. They change; check `ollama.com/library/<model>` before you pull.

## 4. Run the scripts

```bash
pip install -r requirements.txt

export LOCAL_MODEL=qwen3.5:9b                 # Windows PowerShell: $env:LOCAL_MODEL="qwen3.5:9b"
python ask_local.py "Explain a limitation of liability clause in two sentences."
python ask_local.py --json "Extract parties, dates and risks: <paste text>"

python chat_with_files.py ./sample_docs "How much notice do we need to end the Acme agreement?"
```

`chat_with_files.py` prints the answer, then the files it used with their similarity scores. The answer comes from your model, so it will vary by model; no sample output is shown here because none was produced on a real model for this README.

Settings (env vars): `LOCAL_MODEL` (default `qwen3.5:9b`), `LOCAL_EMBED_MODEL` (default `nomic-embed-text`), `LOCAL_AI_URL` (default `http://localhost:11434`). The scripts refuse non-local URLs and model tags containing `cloud` unless you set `ALLOW_REMOTE=1`.

**LM Studio instead of Ollama?** Start its local server (port 1234 by default) and set `LOCAL_AI_URL=http://localhost:1234` and `LOCAL_MODEL` to the model name it shows. `ask_local.py` works as is. `chat_with_files.py` calls Ollama's native `/api/embed`, so it needs Ollama, or a small change to use `/v1/embeddings`.

## 5. Test without a model

```bash
python test_offline.py
```

Expected output:

```
PASS  test_ask_plain
PASS  test_ask_json_schema
PASS  test_guard_blocks_remote_and_cloud
PASS  test_chunking
PASS  test_retrieval_and_answer
PASS  test_every_request_stayed_local
ALL PASSED
```

The test starts a fake Ollama on 127.0.0.1, blocks every non-loopback connection, and checks requests, JSON-schema output, ranking and the privacy guard. It tests the plumbing, not answer quality.

## Known limits

- Ollama's default context is 4K tokens on machines with less than 24 GB of VRAM ([docs](https://docs.ollama.com/context-length)). The script sends 4 chunks of ~800 characters, well inside that. Raise it with `OLLAMA_CONTEXT_LENGTH` if you send more.
- Embeddings are recomputed on every run. Fine for a few hundred files; cache them (e.g. `np.save`) beyond that.
- Only `.txt` and `.md`. Convert PDFs and Word files first.

## Licences

The code here is MIT. Models have their own licences; check them before company use. At time of writing: Qwen3.5 small models, Gemma 4 and gpt-oss are Apache 2.0, and nomic-embed-text v1.5 is Apache 2.0. Ollama itself is MIT.
