FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.27 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev
COPY backend ./backend
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
