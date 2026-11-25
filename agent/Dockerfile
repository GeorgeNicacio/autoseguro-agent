# Multi-stage: dependências resolvidas pelo uv.lock no build; imagem final só com o venv.
FROM python:3.12-slim AS build
RUN pip install --no-cache-dir uv==0.13.10
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    AGENT_DB_PATH=/data/autoseguro.db \
    AGENT_CHECKPOINT_DB_PATH=/data/checkpoints.db
RUN useradd --create-home agent && mkdir /data && chown agent /data
USER agent
EXPOSE 8080
CMD ["uvicorn", "autoseguro_agent.api:app", "--host", "0.0.0.0", "--port", "8080"]
