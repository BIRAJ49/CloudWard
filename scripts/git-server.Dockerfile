FROM alpine:3.22

RUN apk add --no-cache git-daemon \
    && addgroup -g 10001 cloudward \
    && adduser -D -H -u 10001 -G cloudward cloudward \
    && mkdir -p /srv/git /opt/cloudward-git-seed \
    && chown cloudward:cloudward /srv/git /opt/cloudward-git-seed

COPY --chown=cloudward:cloudward cloudward-gitops.git /opt/cloudward-git-seed/cloudward-gitops.git

USER 10001:10001
EXPOSE 9418 9419

ENTRYPOINT ["git", "daemon", "--reuseaddr", "--verbose", "--export-all", "--port=9418", "--base-path=/srv/git", "/srv/git"]
