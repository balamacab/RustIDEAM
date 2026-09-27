FROM nginx:1.27-alpine

COPY index.html /usr/share/nginx/html/index.html
COPY styles.css /usr/share/nginx/html/styles.css
COPY app.js /usr/share/nginx/html/app.js
COPY app-core.mjs /usr/share/nginx/html/app-core.mjs
COPY public-contract.json /usr/share/nginx/html/public-contract.json
COPY fixtures/ /usr/share/nginx/html/fixtures/
COPY nginx/case-console.conf.template /etc/nginx/case-console.conf.template
COPY nginx/20-configure-case-upstream.sh /docker-entrypoint.d/20-configure-case-upstream.sh

RUN chmod 0555 /docker-entrypoint.d/20-configure-case-upstream.sh

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=3s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz >/dev/null || exit 1
