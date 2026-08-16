# Complete AIO build. This composes upstream Gauzy, Documenso and Mailpit
# runtimes with the original Floodman integration source in this repository.
# Tags are retained for human traceability; digests are the immutable inputs
# resolved for the Floodman v4.6.10 readiness gate on 2026-08-13.
ARG GAUZY_API_IMAGE=ghcr.io/ever-co/gauzy-api:latest@sha256:b99003e2c3f575b615a693af6d94887ae6a9de31c5a488f5dcc64800ec14a33e
ARG GAUZY_WEB_IMAGE=ghcr.io/ever-co/gauzy-webapp:latest@sha256:dfe1ae5e057c12ebaff562310c9b670d9fde71fae481f1891194454da1bd57b4
ARG DOCUMENSO_IMAGE=documenso/documenso:v2.11.0@sha256:d9b9a21841e28ebf08d747706e15319a485aa19afea09ab1c926b025c2ce4a18
ARG MAILPIT_IMAGE=axllent/mailpit:latest@sha256:d5ecbb067db3705fa953d79e1b7f81ef84038df67aba6c52825d8c02a1ea748a

FROM ${GAUZY_WEB_IMAGE} AS gauzy_web
FROM ${DOCUMENSO_IMAGE} AS documenso
FROM ${MAILPIT_IMAGE} AS mailpit
FROM ${GAUZY_API_IMAGE} AS runtime

LABEL org.opencontainers.image.title="Floodman Business Suite AIO"
LABEL org.opencontainers.image.description="Floodman Operations, Gauzy, Documenso, messaging, receivables, RoomFlow and mobile gateway."
LABEL org.opencontainers.image.version="4.6.10"
LABEL org.opencontainers.image.authors="Josh Aldrich"

USER root
RUN apk add --no-cache       bash ca-certificates coreutils curl gettext jq netcat-openbsd nginx openssl       postgresql17 postgresql17-client postgresql17-contrib       python3 py3-pip supervisor tzdata font-freefont       libstdc++ libc6-compat gcompat     && apk add --no-cache --virtual .python-build-deps       build-base cargo libffi-dev linux-headers openssl-dev python3-dev     && if id node >/dev/null 2>&1; then          sed -i 's/^node:/container:/' /etc/passwd;          sed -i 's#:/home/node:#:/home/container:#' /etc/passwd;          sed -i 's/^node:/container:/' /etc/group;        else          addgroup -g 1000 container && adduser -D -u 1000 -G container -h /home/container -s /bin/sh container;        fi     && mkdir -p /home/container /opt/floodman /opt/pydeps     && chown -R 1000:1000 /home/container

COPY --from=gauzy_web --chown=container:container /srv/gauzy/ /opt/gauzy-web-pristine/
COPY --from=documenso --chown=container:container /app/ /opt/documenso/
COPY --from=documenso --chown=container:container /usr/local/ /opt/documenso-runtime/usr/local/
COPY --from=mailpit /mailpit /usr/local/bin/mailpit

COPY server/requirements/ /tmp/floodman-requirements/
RUN set -eux;     for service in orchestrator messaging-ai competitor-intel office-console local-lab; do       rm -rf "/opt/pydeps/${service}";       python3 -m pip install --no-cache-dir --break-system-packages         --target "/opt/pydeps/${service}"         -r "/tmp/floodman-requirements/${service}.txt"         -c "/tmp/floodman-requirements/constraints/${service}.txt";     done;     rm -rf /tmp/floodman-requirements;     apk del .python-build-deps

COPY --chown=container:container server/ /opt/floodman/

RUN mkdir -p /opt/floodman/gauzy-public-seed     && if [ -d /srv/gauzy/apps/api/public ]; then cp -a /srv/gauzy/apps/api/public/. /opt/floodman/gauzy-public-seed/; fi     && rm -rf /srv/gauzy/apps/api/public /import     && ln -s /home/container/data/gauzy-files /srv/gauzy/apps/api/public     && ln -s /home/container/data/gauzy-import /import     && chmod 0755 /usr/local/bin/mailpit /opt/floodman/aio/*.sh     && chown -R 1000:1000 /opt/floodman /opt/pydeps /srv/gauzy /home/container

ENV USER=container     HOME=/home/container     FM_HOME=/home/container     FLOODMAN_RELEASE=pterodactyl-mobile-v4.6.10     TZ=America/Detroit     PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1

WORKDIR /home/container
USER container
EXPOSE 9000 9001 9002 9003 9004
ENTRYPOINT ["/opt/floodman/aio/pterodactyl-entrypoint.sh"]
CMD ["/opt/floodman/aio/start-suite.sh"]
