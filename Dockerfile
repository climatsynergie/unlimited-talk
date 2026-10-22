FROM python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4
ARG GIT_REVISION=development
LABEL org.opencontainers.image.source="https://github.com/climatsynergie/unlimited-talk" org.opencontainers.image.revision="$GIT_REVISION"
ENV APP_REVISION=$GIT_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock && addgroup -g 10001 staging && adduser -D -u 10001 -G staging staging
COPY backend/ /app/
USER 10001:10001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
