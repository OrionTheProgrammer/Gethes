# Syster Core Runtime Bundle

This project supports packaging the local Syster AI runtime and model inside the game build.

## Goal

Ship a distributable where players run Syster locally (no extra manual Ollama install).

## Bundle layout

- `gethes/vendor/syster_core/ollama/ollama.exe`
- `gethes/vendor/syster_core/ollama/lib/*`
- `gethes/vendor/syster_core/models/manifests/*`
- `gethes/vendor/syster_core/models/blobs/*`

## Prepare bundle on developer machine

```powershell
.\packaging\prepare_syster_core_bundle.ps1 -Model mistral
```

This script:
- copies local runtime from `%LOCALAPPDATA%\Programs\Ollama`
- pulls the selected model into `gethes/vendor/syster_core/models`

## Build

`build_exe.ps1` and `Gethes.spec` already include `gethes/vendor` in packaged data.

```powershell
.\build_exe.ps1
```

## Important

- A bundled runtime + `mistral` model can add around 8-12 GB to local build artifacts.
- `.gitignore` excludes `gethes/vendor/syster_core/ollama` and `gethes/vendor/syster_core/models` by default to avoid pushing large binaries to Git.

## Runtime resolution order in game

Syster checks runtime paths in this order:
1. explicit configured path
2. bundled `gethes/vendor/syster_core/ollama/ollama.exe`
3. bundled `gethes/vendor/ollama/ollama.exe`
4. local install `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`
5. PATH lookup

## Continuous training and eval loop

Use the local evaluator to measure response quality/latency and store automatic feedback in Syster training DB:

```powershell
python tools/syster_eval.py --profile balanced --runs 1 --store-feedback --json-out build/syster_eval_balanced.json
```

The script:
- runs prompt cases against local Syster + bundled model
- scores each response for immersion, brevity, and command safety
- writes optional JSON report
- can append feedback into `%APPDATA%/Gethes/syster/syster_training.db`

For personality/lore/commands curriculum injection (equivalent long-session training):

```powershell
python tools/syster_train_curriculum.py --minutes 30 --profile balanced
```
