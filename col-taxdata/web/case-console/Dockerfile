FROM nginx:1.27-alpine

COPY index.html /usr/share/nginx/html/index.html
COPY styles.css /usr/share/nginx/html/styles.css
COPY app.js /usr/share/nginx/html/app.js
COPY app-core.mjs /usr/share/nginx/html/app-core.mjs
COPY coverage-renderer.mjs /usr/share/nginx/html/coverage-renderer.mjs
COPY public-contract.json /usr/share/nginx/html/public-contract.json
COPY fixtures/ /usr/share/nginx/html/fixtures/
COPY nginx/case-console.conf.template /etc/nginx/case-console.conf.template
COPY nginx/20-configure-case-upstream.sh /docker-entrypoint.d/20-configure-case-upstream.sh
COPY nginx/healthcheck.sh /usr/local/bin/case-console-healthcheck

# nginx:alpine maps .js but does not currently map .mjs. ES modules are subject
# to strict browser MIME checks, so keep both extensions on the same explicit
# JavaScript type and fail the image build if the base-file shape ever drifts.
RUN sed -i -E \
      's#application/javascript([[:space:]]+)js;#application/javascript\1js mjs;#' \
      /etc/nginx/mime.types \
    && grep -Eq \
      '^[[:space:]]*application/javascript[[:space:]]+js[[:space:]]+mjs;' \
      /etc/nginx/mime.types \
    && chmod 0555 \
      /docker-entrypoint.d/20-configure-case-upstream.sh \
      /usr/local/bin/case-console-healthcheck

EXPOSE 8080

# Readiness covers the browser boot chain, not only the nginx process. In
# particular, an .mjs MIME regression must make the container unhealthy.
HEALTHCHECK --interval=10s --timeout=3s --start-period=3s --retries=3 \
  CMD ["/usr/local/bin/case-console-healthcheck"]
