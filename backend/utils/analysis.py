# analysis.py - Full Analysis Workflow for Note Taker
import os
import re
import io
import base64
import asyncio
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional

# ReportLab imports for PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.units import inch


# Third-party libraries
try:
    from dotenv import load_dotenv
    from openai import OpenAI
    from pydantic import BaseModel
    from PIL import Image
except ImportError as e:
    raise ImportError(
        "A required dependency is missing. "
        "Please run: pip install python-dotenv openai pydantic Pillow reportlab. "
        f"Original error: {e}"
    )

# ==============================================================================
# CONFIGURATION & CLIENT INITIALIZATION
# ==============================================================================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("WARNING: OPENAI_API_KEY is not set. Analysis using OpenAI will fail.")
client = OpenAI(api_key=OPENAI_API_KEY)

# ==============================================================================
# HELPER FUNCTIONS & CLASSES
# ==============================================================================

class TranscriptionOutput(BaseModel):
    """Pydantic model for the output of the transcription agent."""
    transcription: str
    raw_translation: str
    refined_translation: str

async def convert_to_standard_wav(input_path: str, output_path: str) -> bool:
    """Converts any audio file to a standard PCM WAV format."""
    print(f"🔹 Converting {os.path.basename(input_path)} to standard WAV format...")
    command = [
        "ffmpeg", "-i", input_path, "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1", "-y", output_path
    ]
    process = await asyncio.to_thread(
        subprocess.run, command, capture_output=True, text=True, check=False
    )
    if process.returncode != 0:
        print(f"❌ Error during audio conversion: {process.stderr}")
        return False
    print(f"✅ Conversion successful. Standard WAV saved to: {os.path.basename(output_path)}")
    return True

async def split_audio(audio_path: str, output_dir: str, chunk_duration: int = 600) -> List[str]:
    """Splits an audio file into smaller chunks."""
    print("🔹 Splitting audio into chunks...")
    os.makedirs(output_dir, exist_ok=True)
    
    get_duration_cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_path
    ]
    
    process = await asyncio.to_thread(
        subprocess.run, get_duration_cmd, capture_output=True, text=True, check=False
    )
    if process.returncode != 0:
        print(f"❌ Error getting audio duration: {process.stderr}")
        return []
    
    try:
        total_duration = float(process.stdout.strip())
    except (ValueError, TypeError):
        print(f"❌ Error: ffprobe could not determine audio duration. Output was: '{process.stdout.strip()}'")
        return []

    output_files = []
    tasks = []

    for i in range(int(total_duration // chunk_duration) + 1):
        start_time = i * chunk_duration
        output_file = os.path.join(output_dir, f"chunk_{i:02d}.mp3")
        command = [
            "ffmpeg", "-i", audio_path, "-ss", str(start_time), "-t", str(chunk_duration),
            "-c:a", "libmp3lame", "-q:a", "2", output_file, "-y"
        ]
        task = asyncio.to_thread(subprocess.run, command, capture_output=True)
        tasks.append((task, output_file))

    await asyncio.gather(*[t for t, _ in tasks])

    for _, output_file in tasks:
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            output_files.append(output_file)

    print(f"✅ Audio split into {len(output_files)} chunks.")
    return output_files

async def run_transcription_agent(input_audio_path: str) -> TranscriptionOutput:
    """Transcribes, translates, and formats an audio file using Whisper and GPT."""
    print(f"🔹 Transcribing and refining: {os.path.basename(input_audio_path)}")
    
    try:
        with open(input_audio_path, "rb") as f:
            audio_data = f.read()

        with open(input_audio_path, "rb") as f:
            transcription = client.audio.transcriptions.create(model="whisper-1", file=f)

        audio_io = io.BytesIO(audio_data)
        audio_io.name = "audio.mp3"
        translation = client.audio.translations.create(model="whisper-1", file=audio_io)

        system_prompt = (
            "You are a professional meeting transcript formatter.\n"
            "You will receive a raw English transcript from a team meeting.\n\n"
            "Your task is to format it into a clean, readable conversation with each line starting with the speaker's name.\n\n"
            "Follow these rules strictly:\n"
            "1. Detect speaker names from context (e.g., 'I'm John').\n"
            "2. If you cannot determine a name, use placeholders like 'Speaker 1' consistently.\n"
            "3. Do NOT make up random proper names.\n"
            "4. Format the output with each speaker's name followed by a colon and their line.\n"
            "5. Ensure proper punctuation and readability.\n"
            "6. Output only the final cleaned-up transcript."
        )
        
        chat_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": translation.text}
            ]
        )
        refined_conversation = chat_response.choices[0].message.content.strip()

        print(f"✅ Transcription complete for {os.path.basename(input_audio_path)}.")
        return TranscriptionOutput(
            transcription=transcription.text.strip(),
            raw_translation=translation.text.strip(),
            refined_translation=refined_conversation
        )
    except Exception as e:
        print(f"❌ Error during transcription for {input_audio_path}: {e}")
        return TranscriptionOutput(transcription="", raw_translation="", refined_translation="")

def save_text_to_file(text: str, path: str):
    """Saves text content to a file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"✅ Content saved to: {path}")

async def analyze_sentiment_from_text(transcript_chunk: str, time_label: str) -> str:
    """Analyzes sentiment from a transcript chunk using GPT-4o."""
    print(f"🔹 Analyzing text sentiment for {time_label}...")
    try:
        system_prompt = (
            f"You are an expert sentiment analyst. Analyze the following transcript segment from a meeting ({time_label}).\n\n"
            "Focus on:\n"
            "- The emotional tone of the dialogue.\n"
            "- The level of engagement or disengagement.\n"
            "- The overall atmosphere (e.g., collaborative, tense, productive).\n\n"
            "Format your response as:\n"
            "**Time:** {time_label}\n"
            "**Overall Emotion:** <A single dominant emotion like: Positive, Negative, Neutral, Collaborative, Tense>\n"
            "**Key Insights:** <One or two bullet points on specific observations>"
        )

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript_chunk}
            ],
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Error analyzing text sentiment for {time_label}: {e}")
        return f"**Time:** {time_label}\n**Error:** Sentiment analysis could not be performed for this segment."

def generate_summary_and_insights(transcript: str, sentiment_analysis: str, output_dir: str) -> str:
    """Generates a detailed summary, action items, and insights."""
    print("\n🔹 Generating detailed meeting report...")
    if not transcript:
        return "No transcript available to generate a report."

    summary_prompt = (
        "You are a meeting assistant. Based on the full transcript provided, extract the following using Markdown formatting:\n\n"
        "## Executive Summary\nA concise, one-paragraph overview of the meeting.\n\n"
        "## Key Discussion Points\nA bulleted list of the main topics discussed.\n\n"
        "## Action Items\nA bulleted list of tasks assigned with assignees (e.g., - **John:** Finalize the Q3 budget report.)"
    )
    
    insights_prompt = (
        "You are a senior analyst. Based on the transcript and sentiment summary, extract deep insights into team dynamics using Markdown formatting:\n\n"
        "## Meeting Insights\n"
        "- **Emotional Tone:** Describe the overall emotional atmosphere.\n"
        "- **Engagement Level:** Comment on the participation and engagement of the team.\n"
        "- **Potential Conflicts:** Note any areas of disagreement or tension.\n"
        "- **Leadership Behavior:** Comment on leadership style observed."
    )

    try:
        summary_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": summary_prompt},
                {"role": "user", "content": transcript}
            ], max_tokens=1000, temperature=0.4
        )
        summary_content = summary_response.choices[0].message.content.strip()

        insights_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": insights_prompt},
                {"role": "user", "content": f"Transcript:\n{transcript}\n\nSentiment Summary:\n{sentiment_analysis}"}
            ], max_tokens=1000, temperature=0.5
        )
        insights_content = insights_response.choices[0].message.content.strip()

        combined_report = f"{summary_content}\n\n{insights_content}"
        
        output_path = os.path.join(output_dir, "meeting_report.txt")
        save_text_to_file(combined_report, output_path)
        print("✅ Detailed meeting report generated.")
        return combined_report
    except Exception as e:
        print(f"❌ Error generating detailed report: {e}")
        return "Could not generate report due to an error."

def create_beautiful_pdf(text_content: str, output_path: str):
    """Generates a clean PDF from Markdown-like text content."""
    print(f"\n🔹 Creating PDF report at {output_path}...")
    try:
        doc = SimpleDocTemplate(output_path, pagesize=letter, topMargin=inch, bottomMargin=inch)
        styles = getSampleStyleSheet()
        
        h1_style = styles['h1']
        h2_style = styles['h2']
        body_style = styles['BodyText']
        bullet_style = styles['Bullet']
        bullet_style.leftIndent = 20
        
        story = [Paragraph("Meeting Report", styles['Title'])]
        story.append(Spacer(1, 0.2 * inch))
        
        for line in text_content.split('\n'):
            line = line.strip()
            if not line: continue
            
            if line.startswith('## '):
                story.append(Paragraph(line.replace('## ', ''), h2_style))
            elif line.startswith('# '):
                story.append(Paragraph(line.replace('# ', ''), h1_style))
            elif line.startswith(('* ', '- ')):
                line_content = line[2:]
                parts = re.split(r'(\*\*.*?\*\*)', line_content)
                p_text = ''.join([f'<b>{p.replace("**", "")}</b>' if p.startswith('**') else p for p in parts])
                story.append(Paragraph(p_text, bullet_style))
            else:
                story.append(Paragraph(line, body_style))
        
        doc.build(story)
        print(f"✅ PDF saved to: {output_path}")
    except Exception as e:
        print(f"❌ Error creating PDF: {e}")

# --- Main analysis workflow ---
async def main(audio_path: str, transcript_path: str):
    """Main analysis function called by FastAPI as a background task."""
    print(f"\n🚀 STARTING AUDIO MEETING ANALYSIS WORKFLOW 🚀")
    print(f"   Audio Input: {audio_path}")
    print(f"   Transcript Input: {transcript_path}")
    
    try:
        recording_folder = os.path.dirname(audio_path)
        audio_chunks_dir = os.path.join(recording_folder, "audio_chunks")
        os.makedirs(audio_chunks_dir, exist_ok=True)

        if not os.path.exists(audio_path):
            print(f"❌ Audio file does not exist: {audio_path}")
            return

        standard_wav_path = os.path.join(recording_folder, "audio_standard.wav")
        if not await convert_to_standard_wav(audio_path, standard_wav_path):
            print("❌ Halting analysis due to audio conversion failure.")
            return

        chunk_paths = await split_audio(standard_wav_path, output_dir=audio_chunks_dir)
        if not chunk_paths:
            print("❌ Failed to create audio chunks. Using full audio for analysis.")
            chunk_paths = [standard_wav_path]

        print("\n🔹 Running transcription on audio chunks...")
        transcription_tasks = [run_transcription_agent(chunk) for chunk in chunk_paths]
        transcription_results = await asyncio.gather(*transcription_tasks)
        
        full_refined_transcript = "\n\n".join(
            [res.refined_translation for res in transcription_results if res.refined_translation]
        )
        
        if not full_refined_transcript:
            print("❌ Post-transcription failed. Using live transcript as fallback.")
            if os.path.exists(transcript_path) and os.path.getsize(transcript_path) > 0:
                with open(transcript_path, 'r', encoding='utf-8') as f:
                    full_refined_transcript = f.read()
            else:
                print("❌ No transcript available. Cannot generate report.")
                return
        save_text_to_file(full_refined_transcript, transcript_path)

        print("\n🔹 Running sentiment analysis on text chunks...")
        transcript_lines = full_refined_transcript.splitlines()
        num_lines = len(transcript_lines)
        num_chunks = len(chunk_paths)
        lines_per_chunk = (num_lines + num_chunks - 1) // num_chunks
        
        transcript_chunks = [
            "\n".join(transcript_lines[i:i + lines_per_chunk])
            for i in range(0, num_lines, lines_per_chunk)
        ]

        sentiment_tasks = [
            analyze_sentiment_from_text(transcript_chunks[i], f"Segment {i+1}")
            for i in range(min(len(chunk_paths), len(transcript_chunks)))
        ]
        sentiment_results = await asyncio.gather(*sentiment_tasks)
        combined_sentiment = "\n\n".join(sentiment_results)
        
        report_content = generate_summary_and_insights(full_refined_transcript, combined_sentiment, recording_folder)

        if report_content:
            pdf_path = os.path.join(recording_folder, "meeting_report.pdf")
            create_beautiful_pdf(report_content, pdf_path)
        
        print(f"\n✅ AUDIO ANALYSIS WORKFLOW COMPLETED SUCCESSFULLY! ✅")
        print(f"   Check the '{recording_folder}' directory for all generated files.")

    except Exception as e:
        print(f"❌ An error occurred in the main analysis workflow: {e}")
        import traceback
        traceback.print_exc()

# ==============================================================================
# STANDALONE EXECUTION (FOR TESTING)
# ==============================================================================
if __name__ == "__main__":
    async def standalone_main():
        test_audio_path = "recordings/test_audio.wav"
        if not os.path.exists(test_audio_path):
             os.makedirs("recordings", exist_ok=True)
             subprocess.run([
                 "ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                 "-t", "5", "-q:a", "9", "-acodec", "pcm_s16le", test_audio_path
             ])
        
        test_transcript_path = "recordings/test_transcript.txt"
        with open(test_transcript_path, "w") as f:
            f.write("This is a test transcript.")
            
        await main(test_audio_path, test_transcript_path)
    
    asyncio.run(standalone_main())
