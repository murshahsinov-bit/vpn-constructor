# docker build -f billing_bot/Dockerfile .
# docker run --env-file billing_bot/.env shieldvpn-bot
FROM python:3.12-slim

WORKDIR /app
COPY billing_bot/ /app/

ENV PYTHONUNBUFFERED=1

CMD ["python", "handler.py"]
