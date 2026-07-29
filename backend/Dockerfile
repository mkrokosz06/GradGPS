# 3.12 (not 3.13): the pinned pandas 2.2.2 has no cp313 wheels
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Prod config comes from real env vars (App Runner service config), not .env:
# no DYNAMODB_ENDPOINT/S3_ENDPOINT -> db.py talks to real AWS via the task role.
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
