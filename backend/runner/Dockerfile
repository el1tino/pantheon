# Runner image for the Integrate phase: checks a generated static site with jsdom.
# Containers from this image run with no network, a read-only filesystem and no secrets.
FROM node:22-alpine
WORKDIR /runner
RUN npm init -y >/dev/null && npm install --omit=dev --no-audit --no-fund jsdom@25 && npm cache clean --force
COPY check-site.mjs /runner/check-site.mjs
USER node
ENTRYPOINT ["node", "/runner/check-site.mjs"]
