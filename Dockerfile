FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /models && \
    curl -sSL -o /models/msd-musicnn-1.pb \
      "https://essentia.upf.edu/models/feature-extractors/musicnn/msd-musicnn-1.pb" && \
    curl -sSL -o /models/mood_happy-msd-musicnn-1.pb \
      "https://essentia.upf.edu/models/classification-heads/mood_happy/mood_happy-msd-musicnn-1.pb" && \
    curl -sSL -o /models/mood_aggressive-msd-musicnn-1.pb \
      "https://essentia.upf.edu/models/classification-heads/mood_aggressive/mood_aggressive-msd-musicnn-1.pb" && \
    curl -sSL -o /models/mood_relaxed-msd-musicnn-1.pb \
      "https://essentia.upf.edu/models/classification-heads/mood_relaxed/mood_relaxed-msd-musicnn-1.pb" && \
    curl -sSL -o /models/mood_party-msd-musicnn-1.pb \
      "https://essentia.upf.edu/models/classification-heads/mood_party/mood_party-msd-musicnn-1.pb" && \
    curl -sSL -o /models/danceability-msd-musicnn-1.pb \
      "https://essentia.upf.edu/models/classification-heads/danceability/danceability-msd-musicnn-1.pb"

ENV MODELS_DIR=/models
ENV MUSIC_DIR=/music
ENV DB_PATH=/data/library.db
ENV SCAN_INTERVAL_SECONDS=1800

COPY crate_mind/ ./crate_mind/

CMD ["python", "-m", "crate_mind.analysis.main"]
