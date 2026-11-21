FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/tripmate \
    UV_CACHE_DIR=/home/tripmate/.cache/uv

WORKDIR /app

RUN groupadd --system --gid 10001 tripmate \
    && useradd --system --uid 10001 --gid tripmate \
        --home-dir /home/tripmate --create-home \
        --shell /usr/sbin/nologin tripmate \
    && mkdir -p /home/tripmate/.cache/uv \
    && chown -R tripmate:tripmate /home/tripmate

COPY requirements.txt .

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY --chown=tripmate:tripmate . .

USER tripmate

EXPOSE 8014

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8014/health', timeout=3)"]

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8014"]
