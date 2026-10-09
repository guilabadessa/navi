# ---- Frontend (Vite/React) ----
FROM node:20-alpine AS fe
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ .
RUN npm run build

# ---- Backend + worker (mesma imagem) ----
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=America/Sao_Paulo HOME=/tmp/navi-home XDG_CACHE_HOME=/tmp/navi-home/.cache MPLCONFIGDIR=/tmp/navi-home/mpl
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 libffi8 shared-mime-info fonts-dejavu-core \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app
COPY --from=fe /fe/dist /app/static
RUN useradd -r -u 10001 navi && mkdir -p /data/storage /data/backups && chown -R navi /data /app
RUN mkdir -p /tmp/navi-home && chown -R navi /tmp/navi-home
USER navi
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["api"]
