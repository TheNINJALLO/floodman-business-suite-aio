# Additive Office/portal update on the exact, tested shared Voice + Suite image.
# Voice binaries, models, telephony configuration and database schemas are unchanged.
FROM ghcr.io/theninjallo/floodman-operations:unified-portal-424e6305ca065baa3a70be1747f4ea57765fbedb@sha256:96ac8c7229ced9432cf02bfa93d8ad395f0a51598c674da7cfcfd7eeac8274d2
ARG SOURCE_REVISION
LABEL org.opencontainers.image.title="Floodman Operations - Voice and Business Suite" \
      org.opencontainers.image.version="4.7.3" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      com.floodman.patch="approved-call-portal" \
      org.opencontainers.image.authors="Josh Aldrich"
USER root
COPY --chown=container:container server/office-console/app/ /opt/floodman/office-console/app/
COPY --chown=container:container server/orchestrator/app/ /opt/floodman/orchestrator/app/
COPY --chown=container:container server/pwa/ /opt/floodman/pwa/
COPY --chown=container:container server/hub/ /opt/floodman/hub/
COPY containers/unified-portal/refresh_runtime.py /opt/floodman/unified/refresh-portal-runtime.py
RUN python3 /opt/floodman/unified/patch-office-runtime.py --office-root /opt/floodman/office-console \
    && python3 -m compileall -q /opt/floodman/office-console/app /opt/floodman/orchestrator/app \
    && python3 /opt/floodman/unified/refresh-portal-runtime.py \
    && printf '%s\n' "${SOURCE_REVISION}" > /opt/floodman/unified/portal-connection-revision
USER container
WORKDIR /home/container
