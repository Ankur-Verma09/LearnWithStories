FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY web ./web
COPY config/settings.example.json ./config/settings.example.json
EXPOSE 8766
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8766/api/config', timeout=3)"
CMD ["python", "-m", "story_tutor.web_server", "--config", "config/settings.json", "--static", "web", "--host", "0.0.0.0", "--port", "8766"]
