# CodeWalk Agent reverse proxy (Module 15): nginx, unprivileged (uid 101), listening on 8080/8443.
#   docker build -t codewalk-proxy deploy/nginx
# Configuration only; certificates are mounted at run time (see docs/deployment/reverse-proxy.md).
FROM nginxinc/nginx-unprivileged:1.28-alpine

COPY --chown=root:root codewalk/ /etc/nginx/codewalk/
COPY --chown=root:root --chmod=0755 40-codewalk-site.sh /docker-entrypoint.d/40-codewalk-site.sh

EXPOSE 8080 8443
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/nginx-health"]
