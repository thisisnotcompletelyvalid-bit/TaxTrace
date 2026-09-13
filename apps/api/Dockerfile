FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY apps ./apps
COPY data ./data
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "apps.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
