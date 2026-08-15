FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/data \
    APP_ENV=production

COPY app.py /app/app.py
COPY web /app/web

VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "app.py"]
