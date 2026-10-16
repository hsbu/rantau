FROM python:3.12-slim AS contracts
COPY --from=ghcr.io/astral-sh/uv:0.11.27 /uv /bin/
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev
COPY backend ./backend
COPY scripts ./scripts
RUN uv run --no-sync python -m scripts.export_openapi

FROM node:22-alpine AS builder
WORKDIR /app/frontend
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
COPY --from=contracts /app/.generated /app/.generated
RUN npm run generate:contracts && npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0
COPY --from=builder /app/frontend/.next/standalone ./
COPY --from=builder /app/frontend/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
