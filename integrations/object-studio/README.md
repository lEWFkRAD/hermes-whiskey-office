# Object Studio integration

This is the source of the adapted [Camera to Blender](https://github.com/ahujasid/camera-to-blender) local server, durable job store, streamed checkpoint worker, web UI and Blender add-on used by the office podium. Upstream baseline: `3de881fb3aa5a7a2bfd243e34ba4190c88c803de`; preserve [its MIT notice](LICENSE). Local adaptations supply persistent jobs, explicit Fast/Detailed presets, SSH generation, recovery and import acknowledgements.

## Install

Use Python 3.12 on the computer hosting the local API:

```bash
cd integrations/object-studio
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
```

The GPU machine needs Linux, a compatible NVIDIA driver, Python/NumPy and the pinned [trellis.cpp](https://github.com/pwilkin/trellis.cpp) v0.6.0 runtime. `install_forge_runtime.py` downloads the checksum-verified CUDA release and separately pinned GGUF weights into `~/camera-to-blender-runtime`. It is an explicit, large download; inspect upstream model/component licenses first. Model weights and GPU libraries are **not** covered by this repository's MIT license or bundled here. The GGUF model card delegates licensing to its source components; do not assume all models share one license.

Run that installer on your chosen GPU host, then set these on the API computer (example paths must be replaced):

```bash
export GENERATION_BACKEND=forge
export FORGE_SSH_HOST=office-gpu
export FORGE_TRELLIS_BIN=/home/your-user/camera-to-blender-runtime/runtime/trellis-cli
export FORGE_TRELLIS_MODELS=/home/your-user/camera-to-blender-runtime/models
uvicorn relay_server:app --host 127.0.0.1 --port 8000
```

`forge` is the inherited API backend identifier. It does not require any particular machine. There are no host/key defaults; setup fails until configured. SSH requires batch authentication and strict known-host verification. `FORGE_SUDO` is off by default; install into your own directory. Verify your alias and host fingerprint independently.

The API is local and unauthenticated: keep loopback binding. If the office runs elsewhere, create an authenticated SSH tunnel, e.g. `ssh -N -L 8000:127.0.0.1:8000 office-api`, then use `HERMES_OBJECT_STUDIO_URL=http://127.0.0.1:8000`. Do not make a public tunnel to this API. Opening the server does not run inference; generation requires explicit submission.

Visit the local URL for the optional browser studio. Its preview currently loads Google model-viewer 4.1.0 from a public CDN; see `dependencies.json`. The office's native podium does not need this CDN. Install `blender_addon/__init__.py` using Blender's add-on installer for optional auto-import on the API computer. See its source configuration for the local WebSocket address.

## API and recovery

- `GET /health`: backend identifier and readiness; this is not proof SSH works.
- `GET /api/jobs`, `GET /api/jobs/{id}`: durable status, presets and artifact metadata.
- `POST /generate3d`: multipart image, name, request_key and explicit fast/detailed preset. The office writes an attempt before submission and does not retry an ambiguous POST.
- `GET /local-models/{id}.glb`: completed binary; client validates byte count, embedded resources and mesh.
- `GET /api/jobs/{id}/checkpoints/{kind}`: optional live cutout/mesh/wire checkpoints.

Jobs and images are private local state under `generated/` and ignored by Git. Known jobs can be collected after reconnect. Uncertain submissions need reconciliation; do not blindly resubmit. One GPU generation runs at a time. Closing the room stops its worker but does not cancel already accepted GPU work.

Run `python -m unittest test_forge_backend test_live_build test_stop test_studio`. These tests fake remote generation and use synthetic data. They do not validate a new driver's CUDA compatibility or model license. Real image-to-object acceptance requires an operator-controlled GPU run.

Inherited optional Gemini isolation/Tripo routes remain in the upstream server but are unused by the default local renderer. No cloud keys are supplied and there is no automatic cloud fallback.
