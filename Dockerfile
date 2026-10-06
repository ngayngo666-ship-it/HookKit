FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# SQLite bền trên volume /data (gắn trên Railway)
ENV DATA_DIR=/data
ENV DB_PATH=/data/ket.db
CMD ["python", "main.py"]
