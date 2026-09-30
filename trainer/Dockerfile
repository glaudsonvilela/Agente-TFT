FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY remote_trainer /app/remote_trainer

RUN python -m pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
ENV TRAINER_HOST=0.0.0.0
ENV TRAINER_PORT=8801

EXPOSE 8801

CMD ["sh", "-c", "uvicorn remote_trainer.app:app --host ${TRAINER_HOST} --port ${TRAINER_PORT}"]
