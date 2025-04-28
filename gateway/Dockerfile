FROM python:3.12-slim

WORKDIR /app
COPY gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway/ /app/gateway/

ENV PYTHONUNBUFFERED=1; PYTHONPATH=/app/gateway
EXPOSE 8000
CMD ["uvicorn", "gateway:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
