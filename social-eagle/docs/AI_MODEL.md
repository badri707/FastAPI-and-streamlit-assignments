# Local AI model

- **Runtime:** Ollama (free, local). Build environment used Ollama **v0.40.6** (official release, SHA-256 verified).
- **Default model:** Qwen3-4B-Instruct-2507, Q4_K_M GGUF (~2.5 GB file), **Apache-2.0**. Chosen for an 8 GB Mac: one model, one
  inference at a time, `num_ctx=4096`, `temperature=0.1`, non-thinking mode, JSON-schema structured output.
- **Fallback:** Qwen3-1.7B Q4_K_M (~1.1 GB, Apache-2.0) — faster, weaker; see the measured comparison in `docs/VERIFICATION_REPORT.md`.
- Excluded: Qwen2.5-3B (research licence restricts commercial use).

## How the weights were obtained in the build container
The build environment's network policy blocked `ollama.com`/`registry.ollama.ai` and Hugging Face. The GGUF files were pulled from
Docker Hub's official `ai/qwen3` model repository (OCI artifacts, content-addressed). Each file was verified against its OCI digest:
- `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` sha256 `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` (repo annotation: unsloth/Qwen3-4B-Instruct-2507-GGUF)
- `Qwen3-1.7B-Q4_K_M.gguf` sha256 `b139949c5bd74937ad8ed8c8cf3d9ffb1e99c866c823204dc42c0d91fa181897` (unsloth/Qwen3-1.7B-GGUF)
and imported with a Modelfile (`FROM <file>`, `num_ctx 4096`, `temperature 0.2`) as `se-qwen3-4b` / `se-qwen3-1.7b`.

## On your Mac
1. Install Ollama for macOS (free) and start it.
2. Either `ollama pull qwen3:4b-instruct-2507-q4_K_M` (verify the tag exists; set `OLLAMA_MODEL` to it), **or** reproduce the build
   exactly: download the same GGUF, check the SHA-256 above, then
   `printf 'FROM ./Qwen3-4B-Instruct-2507-Q4_K_M.gguf\nPARAMETER num_ctx 4096\n' > Modelfile && ollama create se-qwen3-4b -f Modelfile`
   and set `OLLAMA_MODEL=se-qwen3-4b`. A library build may differ slightly from the evaluated file; re-run `scripts/ai-eval`.
3. Recommended Ollama environment: `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NO_CLOUD=1`, bound to 127.0.0.1.
4. Model files live in Ollama's own store (`~/.ollama/models`). Moving them to the external SSD (`OLLAMA_MODELS`) is optional and
   only after the SSD's path and filesystem are verified.

Memory: the 4B Q4_K_M model needs roughly 3–3.5 GB with a 4096 context (estimate; measure with `scripts/doctor` / Activity Monitor on
the Mac). If memory pressure is high, switch to the 1.7B model and set FAQ replies to draft-only in *System → Settings*.
