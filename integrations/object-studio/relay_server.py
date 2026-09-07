"""
Photo → 3D → Blender relay server.

Endpoints:
  POST /isolate     - Remove background from image (Gemini API)
  POST /generate3d  - Generate 3D model from image (Tripo API)
  POST /relay       - Forward model URL to WebSocket clients (Blender)
  WS   /ws?client=X - WebSocket connection for clients

Usage:
  cp .env.example .env  # fill in API keys
  pip install -r requirements.txt
  uvicorn relay_server:app --host 127.0.0.1 --port 8000
"""
import asyncio
import json
import os
import time
import uuid
import httpx
from typing import Dict, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
from forge_backend import forge
GENERATION_BACKEND = os.getenv("GENERATION_BACKEND", "forge")

# Config
TRIPO_API_KEY = os.getenv("TRIPO_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

TRIPO_BASE_URL = "https://api.tripo3d.ai/v2/openapi"


class RelayPayload(BaseModel):
    target: str
    url: str
    type: str = "model"


app = FastAPI(title="Photo → 3D → Blender")

# CORS for webapp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connections
connections: Dict[str, Set[WebSocket]] = {}
lock = asyncio.Lock()
imports = {}
import_sockets = {}
blender_caps = set()


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket endpoint
# ─────────────────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, client: str):
    await websocket.accept()
    async with lock:
        connections.setdefault(client, set()).add(websocket)
    print(f"[WS] Client '{client}' connected. Total: {sum(len(v) for v in connections.values())}")
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
                if client == 'blender' and message.get('type') == 'hello' and message.get('import_ack') is True:
                    blender_caps.add(websocket)
                token = message.get('request_id')
                if message.get('type') == 'import_result' and token in imports and websocket is import_sockets.get(token):
                    imports[token].update(status='success' if message.get('success') else 'failed',
                        error=str(message.get('error', ''))[:500], meshes=message.get('meshes', 0),
                        materials=message.get('materials', 0))
            except (ValueError, AttributeError):
                pass
    except WebSocketDisconnect:
        blender_caps.discard(websocket)
        async with lock:
            connections.get(client, set()).discard(websocket)
            if connections.get(client) == set():
                connections.pop(client, None)
        print(f"[WS] Client '{client}' disconnected.")


# ─────────────────────────────────────────────────────────────────────────────
# Relay endpoint
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/relay")
async def relay(payload: RelayPayload):
    async with lock:
        targets = list(connections.get(payload.target, set()))
    if not targets:
        raise HTTPException(status_code=404, detail="No target clients connected")

    data = payload.model_dump()
    dead: Set[WebSocket] = set()
    for ws in targets:
        try:
            await ws.send_json(data)
        except Exception:
            dead.add(ws)
    if dead:
        async with lock:
            for ws in dead:
                connections.get(payload.target, set()).discard(ws)
    return JSONResponse({"delivered": len(targets) - len(dead)})


# ─────────────────────────────────────────────────────────────────────────────
# Isolate object (background removal via Gemini, or pass-through)
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/isolate")
async def isolate_object(image: UploadFile = File(...)):
    """Remove background from image using Gemini."""
    image_bytes = await image.read()

    # If no API key, return image as-is (skip isolation)
    if not GEMINI_API_KEY:
        print("[Isolate] No GEMINI_API_KEY set, returning original image")
        return Response(content=image_bytes, media_type="image/png")

    try:
        import base64
        import google.generativeai as genai

        def run_gemini_isolate():
            """Run Gemini background removal in sync context."""
            # Configure Gemini
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-2.5-flash-image")

            # Convert image to base64
            base64_image = base64.b64encode(image_bytes).decode("utf-8")

            # Create prompt for background removal - be very specific
            prompt = [
                "Extract the single MAIN object from this image. You can only pick the most prominent object. Do not pick secondary objects. Give it a white background in an isometric view, perfectly centered. The output must be a clean PNG image showing just the hero object on white.",
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": base64_image
                    }
                }
            ]

            print("[Isolate] Calling Gemini for background removal...")
            response = model.generate_content(prompt)

            if not response.candidates:
                print("[Isolate] No candidates in response, returning original image")
                return image_bytes

            for part in response.candidates[0].content.parts:
                inline_data = getattr(part, "inline_data", None)
                if not inline_data or not getattr(inline_data, "data", None):
                    continue

                # Gemini returns raw bytes here, not base64
                isolated_image_bytes = inline_data.data
                if len(isolated_image_bytes) > 1000:  # Guard against truncated/invalid output
                    print(f"[Isolate] ✓ Background removed ({len(isolated_image_bytes)} bytes)")
                    return isolated_image_bytes

                print(f"[Isolate] ⚠ Image too small ({len(isolated_image_bytes)} bytes), likely invalid")

            # If no valid image in response, return original
            print("[Isolate] ⚠ No valid image in response, returning original image")
            return image_bytes

        # Run sync Gemini call in thread pool
        isolated_image_bytes = await asyncio.to_thread(run_gemini_isolate)
        return Response(content=isolated_image_bytes, media_type="image/png")

    except ImportError:
        raise HTTPException(status_code=500, detail="google-generativeai package not installed. Run: pip install google-generativeai")
    except Exception as e:
        error_msg = str(e)
        print(f"[Isolate] Error: {error_msg}")

        # Check if it's a quota/rate limit error
        if "quota" in error_msg.lower() or "429" in error_msg or "rate limit" in error_msg.lower():
            raise HTTPException(
                status_code=429,
                detail=f"Gemini API quota exceeded. Please check your API key limits. Error: {error_msg[:200]}"
            )
        elif "API key" in error_msg or "401" in error_msg or "403" in error_msg:
            raise HTTPException(
                status_code=401,
                detail=f"Gemini API authentication failed. Please check your API key. Error: {error_msg[:200]}"
            )
        else:
            # For other errors, still raise an exception so frontend knows it failed
            raise HTTPException(
                status_code=500,
                detail=f"Background removal failed: {error_msg[:200]}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Generate 3D model (Tripo API)
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/generate3d")
async def generate_3d(image: UploadFile = File(...), request_key: str = Form(''), preset: str = Form('detailed'), name: str = Form('Untitled object')):
    """
    Generate a 3D model from an image using the Tripo API.

    Two tasks run in parallel:
    - Preview: untextured low-poly mesh, used to drive the point-cloud assembly
      animation as soon as a shape is available (~20-40s).
    - Final: textured PBR model that replaces the preview once ready (~30-50s).
    """
    if GENERATION_BACKEND == "forge":
        return await forge.generate(await image.read(20 * 1024 * 1024 + 1), request_key or None, preset, name)
    if not TRIPO_API_KEY:
        raise HTTPException(status_code=500, detail="TRIPO_API_KEY not configured")

    image_bytes = await image.read()

    headers = {"Authorization": f"Bearer {TRIPO_API_KEY}"}

    async with httpx.AsyncClient(timeout=300.0) as client:
        # Step 1: Upload image to get a token
        print("[Tripo] Uploading image...")
        upload_resp = await client.post(
            f"{TRIPO_BASE_URL}/upload/sts",
            headers=headers,
            files={"file": ("image.png", image_bytes, "image/png")}
        )
        if upload_resp.status_code != 200:
            error_data = upload_resp.json() if upload_resp.headers.get("content-type", "").startswith("application/json") else {}
            raise HTTPException(
                status_code=upload_resp.status_code,
                detail=f"Tripo upload failed: {error_data.get('message', upload_resp.text)}"
            )

        upload_data = upload_resp.json()
        if upload_data.get("code") != 0:
            raise HTTPException(status_code=500, detail=f"Tripo upload error: {upload_data.get('message', 'Unknown error')}")

        image_token = upload_data.get("data", {}).get("image_token")
        if not image_token:
            raise HTTPException(status_code=500, detail=f"No image_token in response: {upload_data}")
        print(f"[Tripo] Image uploaded, token: {image_token[:20]}...")

        # Step 2: Create both tasks in parallel
        print("[Tripo] Creating preview task (Turbo)...")
        preview_task_request = client.post(
            f"{TRIPO_BASE_URL}/task",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "type": "image_to_model",
                "file": {"type": "png", "file_token": image_token},
                "model_version": "Turbo-v1.0-20250506",
                "texture": False,
                "pbr": False,
                "export_uv": False,  # Skipping UVs is significantly faster
                "face_limit": 10000
            }
        )

        print("[Tripo] Creating final task (v2.5)...")
        final_task_request = client.post(
            f"{TRIPO_BASE_URL}/task",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "type": "image_to_model",
                "file": {"type": "png", "file_token": image_token},
                "model_version": "v2.5-20250123",  # Balanced quality/speed
                "texture": True,
                "pbr": True
                # Use default settings for standard quality
            }
        )

        # Execute both in parallel
        preview_resp, final_resp = await asyncio.gather(preview_task_request, final_task_request)

        # Check preview task response
        if preview_resp.status_code != 200:
            error_data = preview_resp.json() if preview_resp.headers.get("content-type", "").startswith("application/json") else {}
            print(f"[Tripo] Preview task failed with status {preview_resp.status_code}")
            print(f"[Tripo] Preview error data: {error_data}")
            raise HTTPException(
                status_code=preview_resp.status_code,
                detail=f"Tripo preview task failed: {error_data.get('message', preview_resp.text)}"
            )

        preview_data = preview_resp.json()
        if preview_data.get("code") != 0:
            raise HTTPException(status_code=500, detail=f"Tripo preview error: {preview_data.get('message')}")

        preview_task_id = preview_data.get("data", {}).get("task_id")
        if not preview_task_id:
            raise HTTPException(status_code=500, detail=f"No preview task_id: {preview_data}")
        print(f"[Tripo] Preview task created: {preview_task_id}")

        # Check final task response
        if final_resp.status_code != 200:
            error_data = final_resp.json() if final_resp.headers.get("content-type", "").startswith("application/json") else {}
            print(f"[Tripo] Final task failed with status {final_resp.status_code}")
            print(f"[Tripo] Final error data: {error_data}")
            raise HTTPException(
                status_code=final_resp.status_code,
                detail=f"Tripo final task failed: {error_data.get('message', final_resp.text)}"
            )

        final_data = final_resp.json()
        if final_data.get("code") != 0:
            raise HTTPException(status_code=500, detail=f"Tripo final error: {final_data.get('message')}")

        final_task_id = final_data.get("data", {}).get("task_id")
        if not final_task_id:
            raise HTTPException(status_code=500, detail=f"No final task_id: {final_data}")
        print(f"[Tripo] Final task created: {final_task_id}")

        return JSONResponse({
            "preview_task_id": preview_task_id,
            "final_task_id": final_task_id
        })


@app.get("/generate3d/{task_id}/stream")
async def stream_3d_progress(task_id: str):
    """Stream real-time updates for a single Tripo task via SSE."""
    if GENERATION_BACKEND == "forge":
        return forge.stream(task_id)
    if not TRIPO_API_KEY:
        raise HTTPException(status_code=500, detail="TRIPO_API_KEY not configured")

    async def event_generator():
        """Poll Tripo task status until complete."""
        headers = {"Authorization": f"Bearer {TRIPO_API_KEY}"}

        print(f"[Tripo Stream] Starting polling for task: {task_id}")

        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                max_attempts = 120  # Max 10 minutes (5s intervals)

                for attempt in range(max_attempts):
                    await asyncio.sleep(5)

                    try:
                        status_resp = await client.get(
                            f"{TRIPO_BASE_URL}/task/{task_id}",
                            headers=headers,
                            timeout=10.0
                        )

                        if status_resp.status_code != 200:
                            print(f"[Tripo Stream] Status check failed: HTTP {status_resp.status_code}")
                            continue

                        status_data = status_resp.json()

                        # Check for API-level errors
                        if status_data.get("code") != 0:
                            error_msg = status_data.get("message", "Unknown error")
                            print(f"[Tripo Stream] API error: {error_msg}")
                            yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                            return

                        data = status_data.get("data", {})
                        if not data:
                            print(f"[Tripo Stream] No data in response")
                            continue

                        status = data.get("status")
                        progress = data.get("progress", 0)

                        print(f"[Tripo Stream] Attempt {attempt + 1}: status={status}, progress={progress}%")

                        # Send progress updates
                        yield f"event: progress\ndata: {json.dumps({'progress': progress, 'status': status})}\n\n"

                        # Check for completion
                        if status == "success":
                            output = data.get("output", {})
                            if not output:
                                error_msg = "Task succeeded but no output available"
                                print(f"[Tripo Stream] ERROR: {error_msg}")
                                yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                                return

                            model_url = output.get("model") or output.get("pbr_model") or output.get("base_model")

                            if not model_url:
                                error_msg = "Task succeeded but no model URL found"
                                print(f"[Tripo Stream] ERROR: {error_msg}")
                                yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                                return

                            print(f"[Tripo Stream] ✓ Task complete: {model_url[:100]}...")

                            # Send completion event with model URL
                            yield f"event: complete\ndata: {json.dumps({'status': 'success', 'model_url': model_url})}\n\n"
                            return

                        elif status in ("failed", "banned", "expired", "cancelled"):
                            error_msg = data.get("message", f"Task {status}")
                            print(f"[Tripo Stream] Task {status}: {error_msg}")
                            yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                            return

                    except httpx.TimeoutException:
                        print(f"[Tripo Stream] Timeout checking status")
                        continue

                error_msg = "Task generation timed out"
                print(f"[Tripo Stream] ERROR: {error_msg}")
                yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"

            except Exception as e:
                error_msg = f"Stream error: {str(e)}"
                print(f"[Tripo Stream] ERROR: {error_msg}")
                yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Health check & connection info
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "generation_backend": GENERATION_BACKEND,
        "tripo_configured": bool(TRIPO_API_KEY),
        "gemini_configured": bool(GEMINI_API_KEY),
        "connected_clients": {k: len(v) for k, v in connections.items()}
    }



@app.get("/proxy-model")
async def proxy_model(url: str):
    """Proxy 3D models to avoid CORS issues with remote CDNs."""
    print(f"[Proxy] Fetching model from: {url[:100]}...")

    # Forge backend hands back relative URLs (/local-models/x.glb) for locally
    # generated models. httpx rejects those with "missing protocol" -> 500.
    # They are same-origin on this very server, so serve them directly.
    # forge.model() returns a FileResponse (streamed by starlette) or raises
    # HTTPException(404); pass both through untouched.
    if url.startswith("/"):
        return forge.model(url.split("/")[-1])

    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Proxy url must be a local path or http(s) URL")

    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=f"Failed to fetch model: {resp.status_code}")

            # Return the model with proper CORS headers
            return Response(
                content=resp.content,
                media_type="model/gltf-binary",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Disposition": "inline"
                }
            )
        except Exception as e:
            print(f"[Proxy] Error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")


@app.get("/connection-info")
async def connection_info():
    """Returns WebSocket URL info for Blender connection."""
    # Try to detect ngrok URL
    ngrok_url = None
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://127.0.0.1:4040/api/tunnels")
            if resp.status_code == 200:
                data = resp.json()
                tunnels = data.get("tunnels", [])
                for tunnel in tunnels:
                    if tunnel.get("proto") == "https":
                        ngrok_url = tunnel.get("public_url", "").replace("https://", "wss://")
                        break
    except Exception:
        pass

    # Determine WebSocket URL
    if ngrok_url:
        ws_url = f"{ngrok_url}/ws?client=blender"
        connection_type = "ngrok"
    else:
        # Use current request host or default to localhost
        ws_url = "ws://localhost:8000/ws?client=blender"
        connection_type = "local"

    return {
        "ws_url": ws_url,
        "connection_type": connection_type,
        "ngrok_detected": bool(ngrok_url)
    }


# ─────────────────────────────────────────────────────────────────────────────
# Serve static files
# ─────────────────────────────────────────────────────────────────────────────
import pathlib

@app.get("/local-models/{filename}")
async def local_model(filename: str):
    return forge.model(filename)

@app.get('/api/jobs')
async def list_jobs():
    return {'jobs': forge.listing(), 'blender_connected': bool(blender_caps)}

@app.get('/api/jobs/{key}')
async def job_status(key: str):
    return forge.status(key)

@app.get('/api/jobs/{key}/photo')
async def job_photo(key: str):
    return forge.photo(key)

@app.get('/api/jobs/{key}/checkpoints/{name}')
async def job_checkpoint(key: str, name: str):
    return forge.preview(key, name)

@app.post('/api/jobs/{key}/retry')
async def retry_job(key: str, request_key: str = Form(''), preset: str = Form('')):
    return await forge.retry(key, request_key or None, preset or None)

@app.post('/api/jobs/{key}/stop')
async def stop_job(key: str):
    return forge.stop(key)

@app.delete('/api/jobs/{key}')
async def delete_job(key: str):
    return forge.remove(key)

@app.post('/api/jobs/{key}/restore')
async def restore_job(key: str):
    return forge.restore(key)

@app.post('/api/jobs/{key}/import')
async def import_job(key: str):
    record = forge.status(key)
    if record['status'] != 'success':
        raise HTTPException(409, 'This model is not ready yet.')
    async with lock:
        targets = [socket for socket in connections.get('blender', set()) if socket in blender_caps]
    if not targets:
        raise HTTPException(409, 'Open the Camera to Blender desktop shortcut to connect the updated Blender add-on.')
    now = time.time()
    for token, state in list(imports.items()):
        if now - state['created_at'] > 600:
            imports.pop(token, None)
            import_sockets.pop(token, None)
        elif state['job_id'] == key and state['status'] == 'pending' and now-state['created_at'] < 90:
            return {'request_id': token}
    token = uuid.uuid4().hex
    imports[token] = {'job_id': key, 'status': 'pending', 'created_at': now}
    target = targets[0]
    import_sockets[token] = target
    # The optional Blender add-on runs on the API computer.
    url = 'http://127.0.0.1:8000/local-models/' + key + '.glb'
    try:
        await target.send_json({'type': 'model', 'url': url, 'request_id': token})
    except Exception:
        imports[token].update(status='failed', error='Blender disconnected. Reconnect it and try again.')
    return {'request_id': token}

@app.get('/api/imports/{token}')
async def import_status(token: str):
    if token not in imports:
        raise HTTPException(404, 'Import confirmation unavailable. Check Blender before sending again.')
    state = imports[token]
    if state['status'] == 'pending' and time.time()-state['created_at'] > 90:
        state.update(status='unconfirmed', error='Blender has not confirmed the import. Check its window before sending again.')
    return state

webapp_dir = pathlib.Path(__file__).parent / "webapp"
if webapp_dir.exists():
    app.mount("/", StaticFiles(directory=str(webapp_dir), html=True), name="webapp")
