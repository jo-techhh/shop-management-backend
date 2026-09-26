FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY services/api_gateway/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY services/api_gateway/src /app/services/api_gateway/src

EXPOSE 8000

CMD ["uvicorn", "services.api_gateway.src.main:app", "--host", "0.0.0.0", "--port", "8000"]
