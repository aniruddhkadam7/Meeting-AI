FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Cloud config (SUPABASE_*, OPENAI_API_KEY, CORS_ALLOW_ORIGINS, ...) is
# supplied at deploy time via the host's env var mechanism (Fly.io secrets,
# Render env vars, etc.) — never baked into the image.
ENV BACKEND_HOST=0.0.0.0
ENV BACKEND_PORT=8000
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
