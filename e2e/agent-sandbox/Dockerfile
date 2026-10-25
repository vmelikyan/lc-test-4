FROM busybox:1.37.0-musl@sha256:5cec3fc171c87218698e85a52af7087de727372aae264a787b8112901a5b0092
COPY e2e/agent-sandbox/public/ /srv/
USER 10001:10001
EXPOSE 8080
CMD ["/bin/sh", "-c", "printf 'E2E_SANDBOX_HTTP_STARTED port=8080\\n'; exec busybox httpd -f -v -p 8080 -h /srv"]
