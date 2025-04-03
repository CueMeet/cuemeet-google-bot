FROM --platform=linux/amd64 public.ecr.aws/docker/library/python:3.10-slim-bullseye

WORKDIR /app

# Set Python to run in unbuffered mode
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update --fix-missing && apt-get install -y \
    openssl \
    libglib2.0-0 \
    build-essential \
    tzdata \
    wget \
    ffmpeg \
    gnupg \
    pulseaudio \
    pulseaudio-utils \
    alsa-utils \
    ca-certificates \
    fonts-liberation \
    libnss3 \
    libgbm1 \
    libasound2 \
    && ln -fs /usr/share/zoneinfo/UTC /etc/localtime \
    && dpkg-reconfigure --frontend noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

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

# Set up PulseAudio configuration
RUN mkdir -p /etc/pulse
COPY pulse-client.conf /etc/pulse/client.conf
COPY pulse-daemon.conf /etc/pulse/daemon.conf

# Ensure ffmpeg has executable permissions
RUN chmod 755 /usr/bin/ffmpeg

# Set up entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Use the entrypoint script
ENTRYPOINT ["/entrypoint.sh"]