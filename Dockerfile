FROM python:3.11-slim

# Install system dependencies (ffmpeg, libsndfile for audio processing, git for git dependencies)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libsndfile1 \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces runs as user with UID 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=7860

WORKDIR $HOME/app

# Install Python requirements
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY --chown=user:user . .

# Install chatterbox package in editable mode
RUN pip install --no-cache-dir -e .

# Expose default Hugging Face Spaces port
EXPOSE 7860

# Start Voice Studio web server and Telegram bot
CMD ["python", "server.py"]
