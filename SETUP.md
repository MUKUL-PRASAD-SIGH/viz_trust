# Setting up viz_trust

This gets a new machine ready to work on viz_trust. Run the steps in order. Expect about
20 minutes, most of it spent downloading the Gemma 4 model.

## What you need

| Tool | Version | Used for |
| --- | --- | --- |
| Git | any recent | the repo |
| [Ollama](https://ollama.com) | **0.40 or newer** | runs Gemma 4 locally |
| Python | **3.12** (3.11 also works; avoid 3.13+, the pinned numpy/scikit-learn have no wheels for it) | engine and score service |
| [uv](https://docs.astral.sh/uv/) | any recent | Python environment (recommended; plain `venv` + `pip` also works) |
| Node.js | **20 or newer** | web UI |
| [Foundry](https://getfoundry.sh) | optional | only if you work on `contracts/` |

Hardware: 16 GB RAM is comfortable. A GPU helps but isn't required. See
[Pick a model size](#3-pick-a-gemma-4-model-size) for which model fits your machine.

## 1. Clone the repo

```bash
git clone git@github.com:charithra754-boop/viz_trust.git
cd viz_trust
```

## 2. Install Ollama

**macOS / Windows:** download the installer from <https://ollama.com/download> and run it. It
starts Ollama in the background for you.

**Linux, with sudo:**

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Don't use your distro's package (e.g. Fedora's `dnf install ollama`). It is usually too old to
run Gemma 4.

**Linux, without sudo** (installs into your home folder):

```bash
mkdir -p ~/.local/opt/ollama ~/.local/bin
curl -fsSL https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tar.zst \
  | zstd -d | tar -x -C ~/.local/opt/ollama
ln -sf ~/.local/opt/ollama/bin/ollama ~/.local/bin/ollama
```

Then run it as a user service so it starts on login:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/ollama.service <<'EOF'
[Unit]
Description=Ollama (user)

[Service]
ExecStart=%h/.local/bin/ollama serve
Restart=on-failure

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now ollama
```

Check it's running:

```bash
ollama --version
curl http://127.0.0.1:11434/api/version
```

## 3. Pick a Gemma 4 model size

Pick by your GPU memory (VRAM). With no GPU, Ollama runs on the CPU. That works but is slow, so
use `e2b`.

| Your machine | Model | Download |
| --- | --- | --- |
| No GPU, or under 6 GB VRAM | `gemma4:e2b` | ~4.6 GB |
| 6–8 GB VRAM (**team default**) | `gemma4:e4b` | ~6.6 GB |
| 12 GB+ VRAM | `gemma4:12b` | ~8 GB |

On a 6 GB GPU, `e4b` doesn't fully fit. Ollama puts the rest in system RAM, which works but is
slower. Switch to `e2b` if reviews are too slow.

```bash
ollama pull gemma4:e4b
ollama run gemma4:e4b "Reply with OK"
```

If you use a different size, set `VIZ_TRUST_MODEL` in your `.env` (see step 6) so the engine uses
it. Everyone's code must work with `e4b`, since that is what the demo machine runs.

## 4. Python environment

From the repo root:

```bash
uv venv --python 3.12 .venv
uv pip install -p .venv -r score/requirements.txt -r oracle/requirements.txt -r agents/requirements.txt
```

Activate it in each new terminal:

```bash
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows
```

Without uv: `python3.12 -m venv .venv`, activate it, then `pip install -r ...` with the same three files.

## 5. Web UI

```bash
cd web
npm ci
cd ..
```

## 6. Environment files

`.env` files hold secrets and are gitignored. Copy the examples and only fill in what you need:

```bash
cp oracle/.env.example oracle/.env
cp contracts/.env.example contracts/.env    # only if you deploy contracts
```

**Never commit a `.env` file, a private key or an API key.** viz_trust's own checks look for
exactly this, so it would be an embarrassing way to fail the demo.

## 7. Train the score model and run the tests

The trained model files aren't in git, so generate them once:

```bash
cd score
python generate_data.py
python train.py
pytest
cd ..
```

## 8. Run it

In separate terminals, with the venv active:

```bash
# score service: http://127.0.0.1:8000
cd score && uvicorn app:app --reload

# web UI: http://127.0.0.1:5173
cd web && npm run dev
```

Ollama runs in the background on `http://127.0.0.1:11434`.

> The review engine, call graph and agent hooks are being ported in now. This section will grow
> as they land. Check the Status table in the [README](README.md).

## Optional: contracts

Only needed if you touch `contracts/`.

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
cd contracts && forge test
```

## Working together

- Branch from `main` and open a pull request. Don't push straight to `main`.
- Pull before you start: `git pull --rebase`.
- Never commit `.env`, keys, `node_modules/`, `.venv/`, or model files. `.gitignore` covers
  these, so if `git status` shows one, stop and check.
- When you add a dependency, add it to the right `requirements.txt` or `package.json` and note it
  here if it needs a manual step.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `pull model manifest: file does not exist` | Your Ollama is too old. Reinstall from step 2 |
| Model is very slow | It's running on the CPU. Try a smaller size, and check `ollama ps` shows `GPU` |
| `connection refused` on port 11434 | Ollama isn't running: `systemctl --user start ollama`, or open the Ollama app |
| `pip` fails building numpy or scikit-learn | You're on Python 3.13+. Recreate the venv with `--python 3.12` |
| Score service fails to start, missing `models/` | Run step 7 |
| Port 8000 or 5173 already in use | Stop the other process, or pass `--port` |
