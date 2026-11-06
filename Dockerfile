# ComfySweep — the ComfyUI Cleaner Agent
FROM python:3.12-slim

LABEL org.opencontainers.image.title="ComfySweep" \
      org.opencontainers.image.description="The ComfyUI Cleaner Agent: scheduled, safe cleanup of ComfyUI outputs and uploads with a web dashboard" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COMFYSWEEP_DATA_DIR=/data \
    COMFYSWEEP_HOST_ROOT=/host \
    COMFYSWEEP_PORT=8191

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web

EXPOSE 8191
VOLUME ["/data"]

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8191/api/ping', timeout=3).status == 200 else 1)"

# ONE worker, always: the scheduler and the "one cleanup at a time" lock live
# in-process. More workers would mean more schedulers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8191", "--workers", "1", "--no-server-header"]
