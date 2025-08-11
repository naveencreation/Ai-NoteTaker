# main.py - Backend Server for Note Taker

import asyncio
import os
import uuid
import io
import wave
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Any, List, Optional, Dict

# --- OpenAI Integration for Transcription ---
try:
    from openai import OpenAI
    from dotenv import load_dotenv
    load_dotenv()
    # Initialize OpenAI client
    if os.getenv("OPENAI_API_KEY"):
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        HAS_OPENAI = True
        print("OpenAI client initialized for live transcription.")
    else:
        HAS_OPENAI = False
        print("Warning: OPENAI_API_KEY not found. Live transcription will be disabled.")
except ImportError:
    HAS_OPENAI = False
    print("Warning: 'openai' or 'python-dotenv' not installed. Live transcription disabled.")


# --- Import Local Modules (Analysis & Email) ---
try:
    from utils.analysis import main as analysis_main
    HAS_ANALYSIS = True
except ImportError:
    HAS_ANALYSIS = False
    print("Warning: analysis.py not found. Analysis features will be disabled.")
    async def analysis_main(audio_path: str, transcript_path: str):
        print(f"Analysis skipped: analysis.py module not found.")

try:
    from utils.email_service import EmailService
    HAS_EMAIL = True
except ImportError:
    HAS_EMAIL = False
    print("Warning: email_service.py not found. Email features will be disabled.")


# --- FastAPI Application Setup ---
app = FastAPI(
    title="Note Taker Web API",
    description="API for audio analysis with live transcription streaming.",
    version="2.1.6 (Auto-detect Language)"
)

# --- CORS Middleware ---
# origins = ["http://localhost", "http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static File Serving for Reports ---
os.makedirs("recordings", exist_ok=True)
app.mount("/recordings", StaticFiles(directory="recordings"), name="recordings")


# --- Application State & Pydantic Models ---
active_sessions: Dict[str, Dict[str, Any]] = {}
email_service = EmailService() if HAS_EMAIL else None

class EmailRequest(BaseModel):
    to_email: EmailStr
    subject: str = "Meeting Report from Notes Taker"
    message: str = "Please find your meeting report attached."
    pdf_path: str
    cc_emails: Optional[List[EmailStr]] = None
    bcc_emails: Optional[List[EmailStr]] = None

# --- Live Transcription Helper Function ---
async def transcribe_audio_chunk(audio_bytes: bytes, session_id_for_log: str) -> Optional[str]:
    if not HAS_OPENAI or not audio_bytes:
        return None
    try:
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "stream.webm"
        
        # Auto-detects language by not specifying the language parameter
        transcript = await asyncio.to_thread(
            client.audio.transcriptions.create,
            model="whisper-1",
            file=audio_file,
            response_format="text"
        )
        return transcript.strip() if transcript else None
    except Exception as e:
        print(f"[{session_id_for_log[:6]}] Error during transcription: {e}")
        return None

# --- API Endpoints ---

@app.get("/api/v1/")
async def get_root():
    return {"message": "Note Taker Web API", "version": "2.1.6"}

@app.post("/api/v1/sessions/start")
async def start_session():
    session_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_folder = Path("recordings") / f"session_{timestamp}_{session_id[:8]}"
    os.makedirs(session_folder, exist_ok=True)

    active_sessions[session_id] = {
        "folder_path": session_folder,
        "start_time": datetime.now(),
        "file_path": session_folder / "audio.wav",
        "transcript_path": session_folder / "transcript.txt"
    }
    print(f"Started new session: {session_id}")
    return {"session_id": session_id}

@app.post("/api/v1/sessions/upload-audio/{session_id}")
async def upload_audio(session_id: str, background_tasks: BackgroundTasks, audio_file: UploadFile = File(...)):
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found or already closed.")
    
    session = active_sessions[session_id]
    file_path = session["file_path"]
    try:
        with open(file_path, "wb") as f:
            while content := await audio_file.read(1024 * 1024): # Read in 1MB chunks
                f.write(content)
    except Exception as e:
        if session_id in active_sessions:
            del active_sessions[session_id]
        raise HTTPException(status_code=500, detail=f"Failed to save audio file: {e}")

    if HAS_ANALYSIS:
        background_tasks.add_task(analysis_main, str(file_path), str(session["transcript_path"]))
        analysis_message = "Analysis started in the background."
    else:
        analysis_message = "Analysis module not available."
    
    if session_id in active_sessions:
        del active_sessions[session_id]
        print(f"Session {session_id} closed and cleaned up after successful upload.")

    return {
        "status": "success", "message": f"Audio uploaded. {analysis_message}",
        "audio_url": f"/{file_path}", "transcript_url": f"/{session['transcript_path']}",
        "pdf_url": f"/{session['folder_path']}/meeting_report.pdf"
    }

@app.websocket("/ws/live/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    if session_id not in active_sessions or not HAS_OPENAI:
        reason = "Session not found or OpenAI not configured"
        await websocket.close(code=1008, reason=reason)
        return

    print(f"WebSocket client connected for session {session_id}.")
    
    frames = bytearray()
    last_full_transcription = ""

    try:
        while True:
            audio_data = await websocket.receive_bytes()
            frames.extend(audio_data)
            
            combined_audio = bytes(frames)
            transcript_text = await transcribe_audio_chunk(combined_audio, session_id)
            
            if transcript_text and transcript_text != last_full_transcription:
                new_text = transcript_text[len(last_full_transcription):].strip()

                if new_text:
                    print(f"[Live Transcript - {session_id[:6]}]: {new_text}")
                    await websocket.send_text(new_text)
                
                last_full_transcription = transcript_text

    except WebSocketDisconnect:
        print(f"WebSocket client for session {session_id} disconnected.")
    except Exception as e:
        print(f"An error occurred in the WebSocket for session {session_id}: {e}")
    finally:
        if session_id in active_sessions and last_full_transcription:
            transcript_path = active_sessions[session_id]["transcript_path"]
            with open(transcript_path, "w", encoding="utf-8") as f:
                f.write(last_full_transcription)
            print(f"Full live transcript saved for session {session_id}")
        
@app.get("/api/v1/status")
def get_status():
    return {"active_session_count": len(active_sessions)}

@app.post("/api/v1/email/send")
async def send_email(email_request: EmailRequest):
    if not HAS_EMAIL or not email_service:
        raise HTTPException(status_code=503, detail="Email service is not configured.")
    try:
        pdf_path = Path(email_request.pdf_path.strip("/")).resolve()
        if Path("recordings").resolve() not in pdf_path.parents:
            raise HTTPException(status_code=400, detail="Invalid file path.")
        result = email_service.send_email_with_attachment(email_request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {e}")

# Mount the static directory for the frontend LAST
os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")


# --- Main Startup ---
if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print(" Note Taker Web API Server (v2.1.6 - Auto-detect Language)")
    print(f" OpenAI for Live Transcription: {'✅ Available' if HAS_OPENAI else '❌ Not configured'}")
    print(f" Analysis Module: {'✅ Available' if HAS_ANALYSIS else '❌ Not found'}")
    print(f" Email Service:  {'✅ Available' if HAS_EMAIL else '❌ Not configured'}")
    print("=" * 60)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
