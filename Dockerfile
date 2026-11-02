# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir -r requirements.txt; else pip install --no-cache-dir -r requirements.txt; fi
COPY sellora sellora
COPY web web
COPY migrations migrations
RUN useradd -m -u 10001 sellora && mkdir data && chown sellora:sellora data && chmod -R a+rX sellora web migrations
USER sellora
ENV SELLORA_DB=/app/data/sellora.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s CMD python -c "import urllib.request,json; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health'))['database']=='سالم'"
CMD ["uvicorn","sellora.app:app","--host","0.0.0.0","--port","8000"]
