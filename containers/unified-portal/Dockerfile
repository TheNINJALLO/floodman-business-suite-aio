# Additive Office/portal update on the exact, tested shared Voice + Suite image.
# The base carries the Tel-Agent voice runtime; this layer preserves the current
# Business Suite sources and does not alter persistent customer/database data.
FROM ghcr.io/theninjallo/floodman-operations-voice-aio:gpu-appliance-candidate-ba00c0b51ae228023b5ebf20bf362f8b64d4fc55@sha256:5e65885391015d744a2da93f958236f391a2ce908292148bd5c6aa579afd31a9
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
