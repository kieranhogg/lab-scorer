FROM python:3.15
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY app.py ./
COPY static/ ./static/
CMD ["uv", "run", "flask", "--app", "app", "run", "--host", "0.0.0.0", "--port", "8000"]