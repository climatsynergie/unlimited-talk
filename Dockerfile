FROM node:22-alpine@sha256:0e1754758c2df4cfa3e68d59e2e1b7374bb7fd9ea6328eaaacf15cc934af8202 AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-alpine@sha256:e064671ca452259bab50e8e2c7bd896e39e9a343bb06ca25234adf6fe18d0fc7
ARG GIT_REVISION=development
LABEL org.opencontainers.image.source="https://github.com/climatsynergie/unlimited-talk" org.opencontainers.image.revision="$GIT_REVISION" io.unlimitedtalk.schema="0012_incoming_runtime"
LABEL io.unlimitedtalk.voice-runtime="1"
LABEL io.unlimitedtalk.voice-archive="1"
LABEL io.unlimitedtalk.voice-browser="1"
LABEL io.unlimitedtalk.inbound-compatible="1"
LABEL io.unlimitedtalk.inbound-config="1"
LABEL io.unlimitedtalk.voice-manual="1"
LABEL io.unlimitedtalk.dialer-compatible="1"
LABEL io.unlimitedtalk.dialer="1"
LABEL io.unlimitedtalk.schema11-compatible="1"
LABEL io.unlimitedtalk.long-recordings="1"
LABEL io.unlimitedtalk.schema12-compatible="1"
LABEL io.unlimitedtalk.incoming-runtime="1"
LABEL io.unlimitedtalk.incoming-recovery="1"
ENV APP_REVISION=$GIT_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.lock /app/requirements.lock
RUN python -m pip install --no-cache-dir --upgrade --only-binary=:all: pip==26.3 \
    && python -m pip --version \
    && python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip check \
    && python -m pip uninstall --yes pip \
    && python -c "import ensurepip, shutil, sysconfig; from pathlib import Path; target=Path(ensurepip.__file__).resolve().parent; assert target==Path(sysconfig.get_path('stdlib'))/'ensurepip'; shutil.rmtree(target)" \
    && addgroup -g 10001 staging && adduser -D -u 10001 -G staging staging
RUN mkdir -p /var/spool/unlimited-talk-recordings && chown 10001:10001 /var/spool/unlimited-talk-recordings && chmod 700 /var/spool/unlimited-talk-recordings
COPY backend/ /app/
COPY --from=web /web/dist /app/web
USER 10001:10001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log"]
