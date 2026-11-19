FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    MERMAID_JS=/opt/mermaid/mermaid.min.js

RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs npm curl ca-certificates libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# Bundle mermaid so diagrams render offline inside Chromium.
RUN mkdir -p /opt/mermaid /tmp/mm && cd /tmp/mm && npm install mermaid@11 \
    && cp node_modules/mermaid/dist/mermaid.min.js /opt/mermaid/mermaid.min.js \
    && rm -rf /tmp/mm

WORKDIR /srv
COPY worker/requirements.txt /srv/requirements.txt
# CPU-only PyTorch for Docling: the default Linux wheel bundles several GB of CUDA libraries the worker never uses.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && crawl4ai-setup

# Bake Docling's layout and table models (~500 MB) into the image, so the first PDF does not
# download them and recreating the container does not lose them.
RUN python -c "from docling.document_converter import DocumentConverter; from docling.datamodel.base_models import InputFormat; DocumentConverter().initialize_pipeline(InputFormat.PDF)"
ENV CRAWL4AI_NO_CLOUD_NOTICE=1

COPY worker /srv/worker
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["uvicorn", "worker.app:app", "--host", "0.0.0.0", "--port", "8000"]
