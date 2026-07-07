FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY brain.py cli.py scheduler.py state.py telegram_bot.py vault.py ./
CMD ["uv", "run", "python", "scheduler.py"]
