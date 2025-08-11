FROM python:3.11-slim-bullseye

# Set the working directory
WORKDIR /opt/app

# Install system packages required by ffmpeg, audio, and pyaudio
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    portaudio19-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install uv (fast dependency installer)
RUN pip install --upgrade pip && pip install uv

# Copy requirements.txt and install dependencies
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# Copy the rest of the app
COPY . .

# Command to run the FastAPI app
CMD ["python", "main.py"]
