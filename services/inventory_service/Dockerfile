FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY services/inventory_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY services/inventory_service/src /app/services/inventory_service/src

EXPOSE 8002

CMD ["uvicorn", "services.inventory_service.src.main:app", "--host", "0.0.0.0", "--port", "8002"]
