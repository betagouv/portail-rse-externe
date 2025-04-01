FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app

COPY src pyproject.toml uv.lock Procfile .

RUN uv sync --frozen

EXPOSE 5000

ENV PYTHONPATH=.:src

CMD ["uv", "run", "honcho", "start"]
