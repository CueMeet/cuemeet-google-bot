# Use Python 3.10 slim-bookworm image
FROM --platform=linux/amd64 public.ecr.aws/docker/library/python:3.10-slim-bullseye

WORKDIR /app

# Set Python to run in unbuffered mode
ENV PYTHONUNBUFFERED=1

# Install system dependencies (minimized for headless operation)
RUN apt-get update && apt-get install -y \
    openssl \
    libglib2.0-0 \
    build-essential \
    tzdata \
    wget \
    ffmpeg \
    gnupg \
    pulseaudio \
    ca-certificates \
    fonts-liberation \
    libnss3 \
    libgbm1 \
    && ln -fs /usr/share/zoneinfo/UTC /etc/localtime \
    && dpkg-reconfigure --frontend noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

# Ensure ffmpeg has executable permissions
RUN chmod 755 /usr/bin/ffmpeg

# Install Google Chrome
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add -
RUN echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list
RUN apt-get update && apt-get install -y google-chrome-stable && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry

# Copy your project files
COPY pyproject.toml poetry.lock* ./

# Install project dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi

COPY . .

# Default command (can be overridden)
CMD ["pulseaudio", "--start", "&&", "python", "-u", "app.py"]