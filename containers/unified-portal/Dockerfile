# Additive Office/portal update on the exact, tested shared Voice + Suite image.
# Voice binaries, models, telephony configuration and database schemas are unchanged.
FROM ghcr.io/theninjallo/floodman-operations-voice-aio:gpu-appliance-candidate-62353445d5201afeb14cb784164148ac89436c44@sha256:44b610b48b3219b1eca1362bbfe1293cd762714837ba5cdcc1802acf2d8c585a
ARG SOURCE_REVISION
LABEL org.opencontainers.image.title="Floodman Operations - Voice and Business Suite" \
      org.opencontainers.image.version="4.7.3" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      com.floodman.patch="approved-call-portal" \
      org.opencontainers.image.authors="Josh Aldrich"
USER root
COPY --chown=container:container server/office-console/app/ /opt/floodman/office-console/app/
COPY --chown=container:container server/orchestrator/app/ /opt/floodman/orchestrator/app/
COPY containers/unified-portal/refresh_runtime.py /opt/floodman/unified/refresh-portal-runtime.py
RUN python3 /opt/floodman/unified/patch-office-runtime.py --office-root /opt/floodman/office-console \
    && python3 -m compileall -q /opt/floodman/office-console/app /opt/floodman/orchestrator/app \
    && python3 /opt/floodman/unified/refresh-portal-runtime.py \
    && printf '%s\n' "${SOURCE_REVISION}" > /opt/floodman/unified/portal-connection-revision
USER container
WORKDIR /home/container
