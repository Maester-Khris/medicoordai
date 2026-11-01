# Image for the local horizontal-scaling harness: the API replicas and the provider mock.
# Only the dependencies are baked in; the code is mounted read-only by docker-compose.yml, so no
# file from backend/ (the untracked .env files included) ends up in an image layer.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
