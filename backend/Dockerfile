# Backend image: used by the Celery worker and Celery Beat (docker-dev-compose.yaml).
# The same image can run the API: `fastapi run src/main.py --port 8000`.
FROM python:3.11-slim-bookworm

# Tesseract reads scanned pages (eng = English text, osd = page orientation).
# libglib2.0-0 is needed by OpenCV even in its headless build.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-osd libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.13.7

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    # tiktoken downloads its token table on first use; bake it into the image instead.
    TIKTOKEN_CACHE_DIR=/opt/tiktoken

WORKDIR /app

# Dependencies first, in their own layer: rebuilt only when pyproject/uv.lock change.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY src ./src

# Celery refuses to be comfortable as root; run as an unprivileged user.
RUN useradd --create-home --uid 1000 app && chown -R app /opt/tiktoken
USER app

CMD ["celery", "-A", "src.workers.celery_app:celery_app", "worker", "--loglevel=INFO"]
