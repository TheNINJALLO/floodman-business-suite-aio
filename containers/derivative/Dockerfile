# Builds the current Floodman custom source on the existing AIO foundation.
# Pin the base image digest before a production release.
ARG FLOODMAN_BASE_IMAGE=ghcr.io/theninjallo/floodman-business-suite-aio:3.2.2
FROM ${FLOODMAN_BASE_IMAGE}

USER root
WORKDIR /opt/floodman

COPY server/requirements/ /tmp/floodman-requirements/
RUN set -eux;     for service in orchestrator messaging-ai competitor-intel office-console local-lab; do       python3 -m pip install --no-cache-dir --break-system-packages         --target "/opt/pydeps/${service}"         -r "/tmp/floodman-requirements/${service}.txt";     done;     rm -rf /tmp/floodman-requirements

COPY --chown=container:container server/ /opt/floodman/
RUN chmod 0755 /opt/floodman/aio/*.sh     && chown -R container:container /opt/floodman /opt/pydeps

ENV FLOODMAN_RELEASE=pterodactyl-mobile-v4.6.7     TZ=America/Detroit

WORKDIR /home/container
USER container
EXPOSE 9000 9001 9002 9003 9004
ENTRYPOINT ["/opt/floodman/aio/pterodactyl-entrypoint.sh"]
CMD ["/opt/floodman/aio/start-suite.sh"]
