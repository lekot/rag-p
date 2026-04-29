FROM postgres:16-alpine

# pg_dump comes from the base image. We add awscli for S3 uploads,
# jq for JSON parsing of list-objects output, plus bash and coreutils
# so the entrypoint scripts can rely on a predictable userland.
RUN apk add --no-cache \
        aws-cli \
        bash \
        coreutils \
        gzip \
        jq \
        tzdata

COPY backup.sh /usr/local/bin/backup.sh
COPY restore.sh /usr/local/bin/restore.sh
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/restore.sh

ENV TZ=UTC

# Default: run the daemon loop. Operators can override with
#   docker compose run --rm postgres-backup bash /usr/local/bin/backup.sh once
# or invoke restore.sh directly.
ENTRYPOINT ["/usr/local/bin/backup.sh"]
CMD ["loop"]
