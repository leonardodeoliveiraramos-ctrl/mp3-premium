import os
import sys
import socket
import json
import uuid
import asyncio
import io
import base64
from typing import Dict, Any, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import qrcode
import imageio_ffmpeg
import yt_dlp

app = FastAPI(title="MP3 PREMIUM - Mobile App")

# Permitir CORS para requisições na rede local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Obter caminho do executável ffmpeg
try:
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception as e:
    FFMPEG_PATH = "ffmpeg"

completed_downloads: Dict[str, Dict[str, Any]] = {}

def get_media_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".mp3"):
        return "audio/mpeg"
    elif lower.endswith(".mp4"):
        return "video/mp4"
    elif lower.endswith(".m4a"):
        return "audio/mp4"
    elif lower.endswith(".webm"):
        return "video/webm"
    return "application/octet-stream"


def get_local_ip() -> str:
    """Descobre o IP local na rede Wi-Fi/Ethernet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def generate_qr_code_base64(text: str) -> str:
    """Gera um QR Code em imagem PNG codificada em base64."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{img_str}"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {"theme_mode": "System"}

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Erro ao salvar config: {e}")

@app.get("/api/system-info")
async def system_info():
    ip = get_local_ip()
    port = 8080
    mobile_url = f"http://{ip}:{port}"
    qr_data = generate_qr_code_base64(mobile_url)
    config = load_config()
    return {
        "ip": ip,
        "port": port,
        "mobile_url": mobile_url,
        "qr_code": qr_data,
        "config": config,
    }

@app.post("/api/save-config")
async def save_config_endpoint(cfg: dict):
    save_config(cfg)
    return {"status": "ok"}

@app.get("/api/video-info")
async def get_video_info(url: str):
    """Obtém rapidamente informações do vídeo (título, autor, miniatura, duração)."""
    if not url:
        raise HTTPException(status_code=400, detail="URL inválida")

    ydl_opts = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["visionos", "android"]
            }
        }
    }

    loop = asyncio.get_event_loop()
    def _extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await loop.run_in_executor(None, _extract)
        if not info:
            raise HTTPException(status_code=404, detail="Vídeo não encontrado")

        is_playlist = "entries" in info and bool(info.get("entries"))
        title = info.get("title", "Sem título")
        uploader = info.get("uploader", info.get("channel", "YouTube"))
        duration = info.get("duration", 0)
        thumbnail = info.get("thumbnail")

        # Se for playlist, pega informações do primeiro item ou da playlist
        if is_playlist:
            entries = list(info.get("entries", []))
            count = len(entries)
            if entries and isinstance(entries[0], dict):
                first = entries[0]
                if not thumbnail:
                    thumbnail = first.get("thumbnail")
            return {
                "title": title,
                "uploader": uploader,
                "is_playlist": True,
                "count": count,
                "thumbnail": thumbnail,
                "duration": duration,
            }

        return {
            "title": title,
            "uploader": uploader,
            "is_playlist": False,
            "thumbnail": thumbnail,
            "duration": duration,
        }
    except Exception as e:
        return {"error": str(e)}

@app.websocket("/ws/download")
async def websocket_download(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        url = data.get("url")
        mode = data.get("mode", "video") # 'audio' ou 'video'
        is_playlist = data.get("is_playlist", False)
        download_id = str(uuid.uuid4())[:8]

        if not url:
            await websocket.send_json({"type": "error", "message": "Por favor, insira um link válido."})
            await websocket.close()
            return

        await websocket.send_json({
            "type": "status",
            "percentage": 0,
            "status_text": "Iniciando download..."
        })

        out_template = os.path.join(DOWNLOAD_DIR, f"{download_id}_%(title)s.%(ext)s")

        last_percent = [0]
        downloaded_files = []

        def progress_hook(d):
            status = d.get("status")
            if status == "downloading":
                try:
                    p_str = d.get("_percent_str", "0%").replace("%", "").strip()
                    percentage = float(p_str) / 100.0
                    last_percent[0] = percentage
                    eta = d.get("_eta_str", "?")
                    speed = d.get("_speed_str", "")
                    status_text = f"Baixando: {int(percentage * 100)}% | ETA: {eta}"
                    if speed:
                        status_text += f" ({speed})"

                    asyncio.run_coroutine_threadsafe(
                        websocket.send_json({
                            "type": "progress",
                            "percentage": percentage,
                            "status_text": status_text,
                            "eta": eta,
                            "speed": speed
                        }),
                        loop
                    )
                except Exception:
                    pass
            elif status == "finished":
                filename = d.get("filename")
                if filename:
                    downloaded_files.append(filename)
                asyncio.run_coroutine_threadsafe(
                    websocket.send_json({
                        "type": "progress",
                        "percentage": 1.0,
                        "status_text": "Processando/Convertendo..."
                    }),
                    loop
                )

        ydl_opts = {
            "outtmpl": out_template,
            "progress_hooks": [progress_hook],
            "noplaylist": not is_playlist,
            "ffmpeg_location": FFMPEG_PATH,
            "quiet": True,
            "no_warnings": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["visionos", "android"]
                }
            }
        }

        if mode == "audio":
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            ydl_opts.update({
                "format": "bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
            })

        loop = asyncio.get_event_loop()

        def _run_ydl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return info

        try:
            info = await loop.run_in_executor(None, _run_ydl)

            # Localiza o arquivo baixado recursivamente
            found_file = None
            for root, dirs, files in os.walk(DOWNLOAD_DIR):
                for fname in files:
                    if fname.startswith(f"{download_id}_"):
                        found_file = os.path.join(root, fname)
                        break
                if found_file:
                    break

            if found_file and os.path.exists(found_file):
                final_filename = os.path.basename(found_file)[len(download_id) + 1:]
                completed_downloads[download_id] = {
                    "path": found_file,
                    "filename": final_filename,
                    "mode": mode,
                    "title": info.get("title", final_filename) if info else final_filename
                }
                file_size_mb = round(os.path.getsize(found_file) / (1024 * 1024), 2)
                import urllib.parse
                safe_url_name = urllib.parse.quote(final_filename)

                await websocket.send_json({
                    "type": "complete",
                    "download_id": download_id,
                    "filename": final_filename,
                    "title": info.get("title", final_filename) if info else final_filename,
                    "size_mb": file_size_mb,
                    "download_url": f"/api/download-file/{download_id}/{safe_url_name}",
                    "status_text": "Download Concluído!"
                })
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": "Download finalizado, mas o arquivo não pôde ser localizado."
                })

        except Exception as dl_err:
            await websocket.send_json({
                "type": "error",
                "message": f"Falha no download: {str(dl_err)}"
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": f"Erro de conexão: {str(e)}"})
        except Exception:
            pass

@app.get("/api/download-file/{download_id}/{filename}")
@app.get("/api/download-file/{download_id}")
async def download_file_endpoint(download_id: str, filename: Optional[str] = None):
    """Entrega o arquivo final convertido diretamente para o download do celular com nome e tipo corretos."""
    item = completed_downloads.get(download_id)
    fpath = None
    final_name = None

    if item and os.path.exists(item["path"]):
        fpath = item["path"]
        final_name = item["filename"]
    else:
        for fname in os.listdir(DOWNLOAD_DIR):
            if fname.startswith(f"{download_id}_"):
                fpath = os.path.join(DOWNLOAD_DIR, fname)
                final_name = fname[len(download_id) + 1:]
                break

    if not fpath or not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado ou expirado.")

    media_type = get_media_type(final_name)
    import urllib.parse
    safe_ascii = "".join(c for c in final_name if c.isalnum() or c in " ._-()")
    if not safe_ascii or not (safe_ascii.endswith(".mp3") or safe_ascii.endswith(".mp4")):
        ext = ".mp3" if final_name.endswith(".mp3") else ".mp4"
        safe_ascii = f"download_{download_id}{ext}"

    headers = {
        "Content-Type": media_type,
        "Content-Disposition": f'attachment; filename="{safe_ascii}"; filename*=UTF-8\'\'{urllib.parse.quote(final_name)}'
    }

    return FileResponse(
        path=fpath,
        filename=final_name,
        media_type=media_type,
        headers=headers
    )

@app.get("/api/stream-file/{download_id}")
async def stream_file_endpoint(download_id: str):
    """Permite tocar o áudio ou vídeo diretamente no player do celular."""
    item = completed_downloads.get(download_id)
    if not item or not os.path.exists(item["path"]):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")

    media_type = get_media_type(item["filename"])
    return FileResponse(path=item["path"], media_type=media_type)

# Servir arquivos estáticos (HTML, CSS, JS, Ícones)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    ip = get_local_ip()
    port = int(os.environ.get("PORT", 8080))
    print("\n" + "="*50)
    print("   MP3 PREMIUM - SERVIDOR INICIADO")
    print("="*50)
    print(f"-> Acesso local: http://localhost:{port}")
    print(f"-> Acesso na rede: http://{ip}:{port}")
    print("="*50)
    print("Escaneie o QR Code abaixo com seu celular:")
    try:
        qr = qrcode.QRCode()
        qr.add_data(f"http://{ip}:{port}")
        qr.print_ascii(invert=True)
    except Exception:
        pass
    print("="*50 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=port)
