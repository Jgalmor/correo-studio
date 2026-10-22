FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --chown=10001:10001 campaign.py server.py index.html ./

USER 10001:10001
EXPOSE 8765

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8765"]
