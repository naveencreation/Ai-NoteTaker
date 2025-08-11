import threading
import queue
import time
import os
import subprocess
import sys
from datetime import datetime
from dotenv import load_dotenv
import platform
import io
import wave
import re


load_dotenv(override=True)
# --- Attempt to import required libraries ---
try:
    from openai import OpenAI
    from dotenv import load_dotenv
except ImportError as e:
    raise ImportError(
        "A required dependency is missing. Please run: pip install openai python-dotenv. "
        f"Original error: {e}"
    )

# ——— Global Configuration ———
RECORDINGS_DIR = "recordings"
OPENAI_MODEL = os.getenv("OPENAI_MODEL")
SAMPLE_RATE = 16000
CHANNELS = 1
FFMPEG_PATH = os.getenv("FFMPEG_PATH")
print(FFMPEG_PATH)
# This format corresponds to 16-bit signed little-endian PCM, which is standard for WAV.
AUDIO_FORMAT = "s16le" 
# The number of bytes for one second of audio.
AUDIO_CHUNK_SIZE = SAMPLE_RATE * CHANNELS * 2  # (Sample Rate * Channels * Bytes per Sample)

# ——— Global State: Queues & Stop Event ———
# These are shared across threads to coordinate their work.
stop_event = threading.Event()
audio_save_q = queue.Queue()
audio_tx_q = queue.Queue() # tx stands for "transcription"
transcript_q = queue.Queue()
live_transcript_q = queue.Queue() # Queue for real-time WebSocket updates

# --- Helper Functions ---

def _run_command(command):
    """Internal helper to run a subprocess command."""
    return subprocess.run(command, capture_output=True, text=True, check=False)

def _clear_queues():
    """Empties all queues to ensure a clean state for a new recording."""
    for q in [audio_save_q, audio_tx_q, transcript_q, live_transcript_q]:
        while not q.empty():
            try:
                q.get_nowait()
            except queue.Empty:
                continue

# --- API-Callable Functions ---

def list_audio_devices():
    """
    Lists available audio input devices using ffmpeg. This is not interactive
    and is designed to be called by an API endpoint.
    Returns a list of device names or identifiers.
    """
    os_type = platform.system()
    if os_type == "Windows":
        command = ['ffmpeg', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy']
        regex = re.compile(r'\]\s*"([^"]+)"\s+\(audio\)')
        output = _run_command(command).stderr
        return regex.findall(output)
    
    if os_type == "Darwin": # macOS
        command = ['ffmpeg', '-f', 'avfoundation', '-list_devices', 'true', '-i', '""']
        # This regex captures both the index and the name, e.g., ['0', 'MacBook Pro Microphone']
        regex = re.compile(r'\[AVFoundation indev @ .*\] \[(\d+)\] (.+)')
        output = _run_command(command).stderr
        return regex.findall(output)
        
    if os_type == "Linux":
        command = ['arecord', '-l']
        # This regex captures card, device name, and device number
        regex = re.compile(r'card (\d+):.*?\[(.+?)\].*?device (\d+):')
        output = _run_command(command).stdout
        return regex.findall(output)
        
    return []

def build_ffmpeg_command(mic_device, sys_audio_device):
    """
    Constructs the platform-specific ffmpeg command for mixing audio sources.
    """
    os_type = platform.system()
    base_command = ['-hide_banner', '-loglevel', 'error']
    filter_command = ['-filter_complex', '[0:a][1:a]amix=inputs=2:duration=longest[aout]', '-map', '[aout]']
    output_format_command = ['-f', AUDIO_FORMAT, '-ar', str(SAMPLE_RATE), '-ac', str(CHANNELS), 'pipe:1']

    if os_type == "Windows":
        device_command = [
            '-f', 'dshow', '-i', f'audio={mic_device}',
            '-f', 'dshow', '-i', f'audio={sys_audio_device}',
        ]
    elif os_type == "Darwin":
        device_command = [
            '-f', 'avfoundation', '-i', f':{mic_device[0]}',
            '-f', 'avfoundation', '-i', f':{sys_audio_device[0]}',
        ]
    elif os_type == "Linux":
         device_command = [
            '-f', 'alsa', '-i', f'hw:{mic_device[0]},{mic_device[2]}',
            '-f', 'alsa', '-i', f'hw:{sys_audio_device[0]},{sys_audio_device[2]}',
        ]
    else:
        raise NotImplementedError(f"Recording is not supported on this OS: {os_type}")

    return [FFMPEG_PATH, *base_command, *device_command, *filter_command, *output_format_command]

# --- Core Worker Threads ---

def _audio_recorder_thread(ffmpeg_command):
    """
    Thread target function that runs ffmpeg to capture and mix audio.
    It reads the raw audio data from ffmpeg's stdout and puts it into two queues.
    """
    process = subprocess.Popen(ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while not stop_event.is_set():
        # Read one second of audio data at a time
        data = process.stdout.read(AUDIO_CHUNK_SIZE)
        if not data:
            break
        audio_save_q.put(data)
        audio_tx_q.put(data)
    
    process.terminate()
    try:
        # Wait for the process to terminate and capture any final output
        _, stderr = process.communicate(timeout=5)
        if stderr:
            print(f"ffmpeg stderr: {stderr.decode('utf-8', errors='ignore')}")
    except subprocess.TimeoutExpired:
        process.kill()
        print("ffmpeg process was killed due to timeout.")

def _transcriber_thread():
    """
    Thread target function that transcribes audio chunks in near real-time using OpenAI's Whisper API.
    """
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set. Transcription will not work.")
        return # Exit the thread if the key is not found
        
    client = OpenAI(api_key=api_key)
    
    buffer = bytearray()
    # Buffer audio for ~5 seconds before sending to transcription
    min_buffer_size = AUDIO_CHUNK_SIZE * 5

    while not stop_event.is_set() or not audio_tx_q.empty():
        try:
            # Wait for up to 1 second for new audio data
            chunk = audio_tx_q.get(timeout=1)
            buffer.extend(chunk)
            
            # If the buffer is smaller than our minimum, keep collecting
            if len(buffer) < min_buffer_size:
                continue

            # Prepare the audio data as a WAV file in memory
            wav_in_memory = io.BytesIO()
            with wave.open(wav_in_memory, 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2) # 2 bytes for 16-bit audio
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(buffer)
            
            wav_in_memory.seek(0)
            wav_in_memory.name = "transcript_chunk.wav" # The API needs a file name
            
            # Send to OpenAI for transcription
            transcript_text = client.audio.transcriptions.create(
                model=OPENAI_MODEL,
                file=wav_in_memory,
                response_format="text"
            )
            
            if transcript_text and transcript_text.strip():
                text = transcript_text.strip()
                print(f"[LIVE TRANSCRIPT] {text}")
                transcript_q.put(text)
                live_transcript_q.put(text)
            
            # Clear the buffer after successful transcription
            buffer.clear()

        except queue.Empty:
            # This is expected when the recording stops.
            continue
        except Exception as e:
            print(f"An error occurred in the transcriber thread: {e}")
            # Don't clear the buffer, try again with more data
            time.sleep(1)

# --- Main Control Functions for FastAPI ---

def start_recording(mic_device, sys_audio_device):
    """
    Sets up and starts audio recording and transcription threads.
    This is the main entry point to be called from the FastAPI start endpoint.
    Returns: folder_path, threads
    """
    # 1. Reset state from any previous recordings
    stop_event.clear()
    _clear_queues()

    # 2. Check for OpenAI API Key (fail early if not present)
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY environment variable not set.")

    # 3. Create a timestamped folder for the new recording
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder_path = os.path.join(RECORDINGS_DIR, timestamp)
    os.makedirs(folder_path, exist_ok=True)

    # 4. Build the platform-specific ffmpeg command for audio only
    ffmpeg_command = build_ffmpeg_command(mic_device, sys_audio_device)

    # 5. Create and configure threads (audio recording and transcription only)
    threads = [
        threading.Thread(target=_audio_recorder_thread, args=(ffmpeg_command,), daemon=True),
        threading.Thread(target=_transcriber_thread, daemon=True)
    ]

    # 6. Start all threads
    for t in threads:
        t.start()
        
    print("Audio recording and transcription threads started.")
    
    # 7. Return necessary info to the FastAPI app state 
    return folder_path, threads

def stop_recording():
    """
    Signals all running threads to stop by setting the global stop_event.
    """
    print("Signaling threads to stop...")
    stop_event.set()

def save_results(folder_path):
    """
    Saves the final audio and transcript files from their respective queues.
    This should be called after all threads have been joined.
    """
    # --- Save full mixed audio to a WAV file ---
    audio_path = os.path.join(folder_path, "audio.wav")
    print(f"Saving audio to {audio_path}...")
    with wave.open(audio_path, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2) # 2 bytes for 16-bit audio
        wf.setframerate(SAMPLE_RATE)
        
        # Drain the queue and write all frames
        while not audio_save_q.empty():
            wf.writeframes(audio_save_q.get())
    print("Audio saved.")

    # --- Save full transcript to a text file ---
    transcript_path = os.path.join(folder_path, "transcript.txt")
    print(f"Saving transcript to {transcript_path}...")
    all_transcripts = []
    while not transcript_q.empty():
        all_transcripts.append(transcript_q.get())
    
    if all_transcripts:
        with open(transcript_path, 'w', encoding='utf-8') as f:
            f.write(" ".join(all_transcripts))
        print("Transcript saved.")
    else:
        print("No transcript data was generated.")

    return audio_path, transcript_path