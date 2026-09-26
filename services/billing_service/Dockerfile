FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY services/billing_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY services/billing_service/src /app/services/billing_service/src

EXPOSE 8003

CMD ["uvicorn", "services.billing_service.src.main:app", "--host", "0.0.0.0", "--port", "8003"]
