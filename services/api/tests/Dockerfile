FROM python:3.11-slim
WORKDIR /app
COPY services/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY services/api/requirements-dev.txt /tmp/requirements-dev.txt
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt
COPY backend/common /app/common
COPY services/api /app
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 SCHEDULER_ENABLED=false
CMD ["python", "-m", "pytest", "-c", "pytest.ini", "tests", "-q", "-p", "no:cacheprovider"]
