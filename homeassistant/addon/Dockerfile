ARG BUILD_FROM=python:3.13-slim-bookworm
FROM ${BUILD_FROM}

ARG BUILD_VERSION=dev
ARG BUILD_ARCH=unknown
LABEL io.hass.name="WebClock" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="${BUILD_ARCH}"

WORKDIR /app
ENV HOST=0.0.0.0 \
    PORT=8099 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Taipei \
    WEBCLOCK_INGRESS=1 \
    WEBCLOCK_STATE_DIR=/data \
    NOTES_FILE=/data/manual_notes.json

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py sw.js ./
COPY webclock ./webclock
COPY templates ./templates
COPY static ./static

EXPOSE 8099
CMD ["python", "app.py"]
