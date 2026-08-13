# Builds the current Floodman custom source on the existing AIO foundation.
# Tag retained for human traceability; OCI index digest is the immutable input.
ARG FLOODMAN_BASE_IMAGE=ghcr.io/theninjallo/floodman-business-suite-aio:3.2.2@sha256:3c2d611d64980589a0680bf6c467af73ea8a2a519a51252be577ea78150c37e5
FROM ${FLOODMAN_BASE_IMAGE}

LABEL org.opencontainers.image.title="Floodman Operations"
LABEL org.opencontainers.image.description="Floodman Operations v4.6.8 derivative AIO runtime."
LABEL org.opencontainers.image.version="4.6.8"
LABEL org.opencontainers.image.authors="Josh Aldrich"

USER root
WORKDIR /opt/floodman

COPY server/requirements/ /tmp/floodman-requirements/
RUN set -eux;     for service in orchestrator messaging-ai competitor-intel office-console local-lab; do       rm -rf "/opt/pydeps/${service}";       python3 -m pip install --no-cache-dir --break-system-packages         --target "/opt/pydeps/${service}"         -r "/tmp/floodman-requirements/${service}.txt"         -c "/tmp/floodman-requirements/constraints/${service}.txt";     done;     rm -rf /tmp/floodman-requirements

COPY --chown=container:container server/ /opt/floodman/
RUN chmod 0755 /opt/floodman/aio/*.sh

# The pinned upstream image declares development credential defaults. Floodman's
# start-suite generates persistent random values before the ERP starts; clear the
# inherited placeholders so no known credential remains usable from image config.
ENV FLOODMAN_RELEASE=pterodactyl-mobile-v4.6.8 \
    TZ=America/Detroit \
    EXPRESS_SESSION_SECRET= \
    JWT_SECRET= \
    JWT_REFRESH_TOKEN_SECRET=

WORKDIR /home/container
USER container
EXPOSE 9000 9001 9002 9003 9004
ENTRYPOINT ["/opt/floodman/aio/pterodactyl-entrypoint.sh"]
CMD ["/opt/floodman/aio/start-suite.sh"]
