# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS web
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=secret,id=build_ca if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; npm ci --no-audit --no-fund
COPY index.html vite.config.js ./
COPY src ./src
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8000 GALLERY_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=secret,id=build_ca if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home gallery && mkdir /data && chown gallery:gallery /data
COPY --chown=gallery:gallery server ./server
COPY --from=web --chown=gallery:gallery /app/dist ./dist
COPY scripts/docker-entrypoint.sh /app/docker-entrypoint.sh
EXPOSE 8000
CMD ["sh", "/app/docker-entrypoint.sh"]
