# Builds the whole tool into one image: the Angular dashboard is compiled and
# then served by the FastAPI app, so everything lives behind a single port.

# ----------------------------------------------------------------- frontend
FROM node:22-alpine AS frontend
WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ------------------------------------------------------------------ runtime
FROM python:3.11-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DVT_STATIC_DIR=/app/frontend/dist/frontend/browser \
    DVT_STORAGE_DIR=/app/data

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY sample-data/ ./sample-data/
COPY --from=frontend /build/dist/frontend/browser ./frontend/dist/frontend/browser

RUN mkdir -p /app/data

EXPOSE 8000

# Hosts such as Render and Railway inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "cd /app/backend && python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
