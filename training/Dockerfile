FROM python:3.11-slim AS trainer
WORKDIR /repo
COPY services/prediction/requirements.txt /tmp/requirements.txt
COPY training/requirements.txt /tmp/training-requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/training-requirements.txt
COPY backend /repo/backend
COPY services/prediction /repo/services/prediction
COPY services/clustering /repo/services/clustering
COPY training /repo/training
ENV PYTHONPATH=/repo/backend:/repo/services/prediction PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
ENTRYPOINT ["python", "training/train_models.py"]
CMD ["--out-dir", "/app/models"]

FROM trainer AS tests
RUN pip install --no-cache-dir pytest~=8.3.0 ruff~=0.11.0
ENTRYPOINT []
CMD ["sh", "-c", "ruff check training/train_models.py training/evaluate_models.py training/tests services/prediction services/clustering && python -m pytest training/tests -q && python -m pytest services/prediction/tests -q && python -m pytest services/clustering/tests -q"]
