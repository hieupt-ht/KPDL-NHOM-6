FROM python:3.11-slim
WORKDIR /app
COPY services/clustering/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY backend/common /app/common
COPY services/clustering /app
COPY services/prediction/features.py /app/features.py
ENV PYTHONPATH=/app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
