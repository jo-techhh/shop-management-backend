FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY services/auth_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY services/auth_service/src /app/services/auth_service/src

EXPOSE 8001

CMD ["uvicorn", "services.auth_service.src.main:app", "--host", "0.0.0.0", "--port", "8001"]
