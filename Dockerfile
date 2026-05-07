FROM node:24-bookworm-slim

RUN npm install -g openclaw@latest

WORKDIR /app

COPY entrypoint.sh /app/entrypoint.sh
COPY openclaw.json /app/openclaw.json

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
