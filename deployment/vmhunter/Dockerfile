# Independent media worker, on the exact application/dependency image already tested.
FROM ghcr.io/climatsynergie/unlimited-talk-api@sha256:65bc7e7750006552d129a2466f13cfb7e589bd3f43f202b48f8414b03a6b825c
ARG GIT_REVISION
ENV APP_REVISION=$GIT_REVISION
LABEL io.unlimitedtalk.component="vmhunter-worker"
LABEL org.opencontainers.image.revision="$GIT_REVISION"
LABEL io.unlimitedtalk.vmhunter.api-base="36a451a4e974dc0a8ff80bbe5540806f57fa3c6f"
LABEL io.unlimitedtalk.vmhunter.protocol="1"
# Keep the shared bounded factory in sync; the observer retains its default
# two-connection pool. The explicit API/serial-worker allocation is elsewhere.
COPY backend/app/database.py /app/app/database.py
COPY backend/app/telephony/vmhunter.py /app/app/telephony/vmhunter.py
COPY backend/app/telephony/vmhunter_observer.py /app/app/telephony/vmhunter_observer.py
CMD ["python", "-m", "app.telephony.vmhunter_observer"]
