ARG NGINX_BASE_IMAGE=nginx:1.27-alpine
FROM ${NGINX_BASE_IMAGE}

RUN apk add --no-cache gettext

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY hub.js /usr/share/nginx/html/floodman-hub.js
COPY hub.css /usr/share/nginx/html/floodman-hub.css
COPY hub-config.js.template /opt/floodman/hub-config.js.template
COPY starting.html /usr/share/nginx/html/floodman-starting.html
COPY brand /usr/share/nginx/html/floodman-brand
COPY docker-entrypoint.sh /usr/local/bin/floodman-hub-entrypoint
RUN chmod 0755 /usr/local/bin/floodman-hub-entrypoint

EXPOSE 9000
ENTRYPOINT ["/usr/local/bin/floodman-hub-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
