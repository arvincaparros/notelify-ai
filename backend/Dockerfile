FROM python:3.12-slim

WORKDIR /app

# No apt build deps needed: psycopg[binary] and asyncpg both ship prebuilt wheels.
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
