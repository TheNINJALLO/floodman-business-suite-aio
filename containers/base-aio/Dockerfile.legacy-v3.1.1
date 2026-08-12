ARG GAUZY_API_IMAGE=ghcr.io/ever-co/gauzy-api:latest
ARG GAUZY_WEB_IMAGE=ghcr.io/ever-co/gauzy-webapp:latest
ARG DOCUMENSO_IMAGE=documenso/documenso:v2.11.0
ARG MAILPIT_IMAGE=axllent/mailpit:latest

FROM ${GAUZY_WEB_IMAGE} AS gauzy_web
FROM ${DOCUMENSO_IMAGE} AS documenso
FROM ${MAILPIT_IMAGE} AS mailpit
FROM ${GAUZY_API_IMAGE} AS runtime

LABEL org.opencontainers.image.title="Floodman Business Suite - Pterodactyl AIO Test"
LABEL org.opencontainers.image.description="Single-container test edition of Floodman Operations, Gauzy, Documenso, AI, messaging and receivables for Pterodactyl."
LABEL org.opencontainers.image.version="3.1.1-pterodactyl-aio-test"
LABEL org.opencontainers.image.source="https://github.com/TheNINJALLO/floodman-business-suite-aio"

USER root

RUN apk add --no-cache \
      bash ca-certificates coreutils curl gettext jq netcat-openbsd nginx openssl \
      postgresql17 postgresql17-client postgresql17-contrib \
      python3 py3-pip supervisor tzdata font-freefont \
      libstdc++ libc6-compat gcompat \
    && apk add --no-cache --virtual .python-build-deps \
      build-base cargo libffi-dev linux-headers openssl-dev python3-dev \
    && if id node >/dev/null 2>&1; then \
         sed -i 's/^node:/container:/' /etc/passwd; \
         sed -i 's#:/home/node:#:/home/container:#' /etc/passwd; \
         sed -i 's/^node:/container:/' /etc/group; \
       else \
         addgroup -g 1000 container && adduser -D -u 1000 -G container -h /home/container -s /bin/sh container; \
       fi \
    && mkdir -p /home/container /opt/floodman /opt/pydeps \
    && chown -R 1000:1000 /home/container

# Preserve the exact upstream browser and signing runtimes. Gauzy API remains the
# primary Node 24 runtime from the final base image. Documenso carries its own Node
# 22 runtime so native modules are not crossed between Node ABI versions.
COPY --from=gauzy_web --chown=container:container /srv/gauzy/ /opt/gauzy-web-pristine/
COPY --from=documenso --chown=container:container /app/ /opt/documenso/
COPY --from=documenso --chown=container:container /usr/local/ /opt/documenso-runtime/usr/local/
COPY --from=mailpit /mailpit /usr/local/bin/mailpit

COPY orchestrator/requirements.txt /tmp/requirements-orchestrator.txt
COPY messaging-ai/requirements.txt /tmp/requirements-messaging-ai.txt
COPY competitor-intel/requirements.txt /tmp/requirements-competitor-intel.txt
COPY office-console/requirements.txt /tmp/requirements-office-console.txt
COPY local-lab/requirements.txt /tmp/requirements-local-lab.txt

RUN python3 -m pip install --no-cache-dir --break-system-packages --target /opt/pydeps/orchestrator -r /tmp/requirements-orchestrator.txt \
    && python3 -m pip install --no-cache-dir --break-system-packages --target /opt/pydeps/messaging-ai -r /tmp/requirements-messaging-ai.txt \
    && python3 -m pip install --no-cache-dir --break-system-packages --target /opt/pydeps/competitor-intel -r /tmp/requirements-competitor-intel.txt \
    && python3 -m pip install --no-cache-dir --break-system-packages --target /opt/pydeps/office-console -r /tmp/requirements-office-console.txt \
    && python3 -m pip install --no-cache-dir --break-system-packages --target /opt/pydeps/local-lab -r /tmp/requirements-local-lab.txt \
    && rm -f /tmp/requirements-*.txt \
    && apk del .python-build-deps

COPY --chown=container:container orchestrator/app/ /opt/floodman/orchestrator/app/
COPY --chown=container:container messaging-ai/app/ /opt/floodman/messaging-ai/app/
COPY --chown=container:container messaging-ai/knowledge/ /opt/floodman/messaging-ai/knowledge/
COPY --chown=container:container competitor-intel/app/ /opt/floodman/competitor-intel/app/
COPY --chown=container:container office-console/app/ /opt/floodman/office-console/app/
COPY --chown=container:container local-lab/app/ /opt/floodman/local-lab/app/
COPY --chown=container:container database/ /opt/floodman/database/
COPY --chown=container:container roomflow-integration/ /opt/floodman/resources/roomflow-integration/
COPY --chown=container:container import-templates/ /opt/floodman/resources/import-templates/
COPY --chown=container:container examples/ /opt/floodman/resources/examples/
COPY --chown=container:container gauzy-hub/hub.js /opt/floodman/hub/hub.js
COPY --chown=container:container gauzy-hub/hub.css /opt/floodman/hub/hub.css
COPY --chown=container:container gauzy-hub/hub-config.js.template /opt/floodman/hub/hub-config.js.template
COPY --chown=container:container gauzy-hub/starting.html /opt/floodman/hub/starting.html
COPY --chown=container:container gauzy-hub/brand/ /opt/floodman/hub/brand/
COPY --chown=container:container aio/ /opt/floodman/aio/

# Gauzy local file storage must survive Pterodactyl restarts and image upgrades.
RUN mkdir -p /opt/floodman/gauzy-public-seed \
    && if [ -d /srv/gauzy/apps/api/public ]; then cp -a /srv/gauzy/apps/api/public/. /opt/floodman/gauzy-public-seed/; fi \
    && rm -rf /srv/gauzy/apps/api/public /import \
    && ln -s /home/container/data/gauzy-files /srv/gauzy/apps/api/public \
    && ln -s /home/container/data/gauzy-import /import \
    && chmod 0755 /usr/local/bin/mailpit /opt/floodman/aio/*.sh \
    && chown -R 1000:1000 /opt/floodman /opt/pydeps /srv/gauzy /home/container

ENV USER=container \
    HOME=/home/container \
    FM_HOME=/home/container \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /home/container
USER container

EXPOSE 9000 9001 9002 9003 9004

ENTRYPOINT ["/opt/floodman/aio/pterodactyl-entrypoint.sh"]
CMD ["/opt/floodman/aio/start-suite.sh"]
