# Additive Office/portal update on the exact, tested shared Voice + Suite image.
# Voice binaries, models, telephony configuration and database schemas are unchanged.
FROM ghcr.io/theninjallo/floodman-operations:unified-portal-837d13b89b01c336ee4c3cc97ef4cce1dffb6291@sha256:fbf8194e2935f1239b6743d1fd9e1d86cda44fc3c89f3dd5d5d29635ce426fbc
ENV CUSTOMER_SMS_CONSENT_CHECK_ENABLED=true
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
COPY --chown=container:container server/office-console/app/sms_policy.py /opt/voice/app/sms_policy.py
COPY containers/unified-portal/patch_sms_policy.py /opt/floodman/unified/patch-sms-policy.py
RUN python3 /opt/floodman/unified/patch-office-runtime.py --office-root /opt/floodman/office-console \
    && python3 /opt/floodman/unified/patch-sms-policy.py \
    && python3 -m compileall -q /opt/floodman/office-console/app /opt/floodman/orchestrator/app \
    && python3 /opt/floodman/unified/refresh-portal-runtime.py \
    && printf '%s\n' "${SOURCE_REVISION}" > /opt/floodman/unified/portal-connection-revision
USER container
WORKDIR /home/container
