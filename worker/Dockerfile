FROM python:3.12-slim

# WITH_DOCLING=1 (default): full image that also parses open-access PDFs (~6.2 GB, ~6-10 min first build).
# WITH_DOCLING=0: lean image for page reading, diagrams and PDF output only; papers fall back to abstracts.
ARG WITH_DOCLING=1

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    MERMAID_JS=/opt/mermaid/mermaid.min.js \
    CRAWL4AI_NO_CLOUD_NOTICE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs npm curl ca-certificates libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# Bundle mermaid so diagrams render offline inside Chromium.
RUN mkdir -p /opt/mermaid /tmp/mm && cd /tmp/mm && npm install mermaid@11 \
    && cp node_modules/mermaid/dist/mermaid.min.js /opt/mermaid/mermaid.min.js \
    && rm -rf /tmp/mm

WORKDIR /srv
# Shared by both images: scraping, Chromium for rendering, the HTTP app.
# Playwright (PDF rendering) and Patchright (Crawl4AI's fork) each install their own Chromium build.
# Both only ever run headless, which uses the smaller headless shell, so the two full builds (~800 MB)
# are removed.
COPY worker/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps --only-shell chromium \
    && crawl4ai-setup \
    && rm -rf /ms-playwright/chromium-[0-9]*

# Full image only. CPU-only PyTorch: the default Linux wheel bundles several GB of CUDA libraries the
# worker never uses. Docling's layout and table models (~500 MB) are baked in, so the first PDF does not
# download them and recreating the container does not lose them.
COPY worker/requirements-docling.txt /srv/requirements-docling.txt
RUN if [ "$WITH_DOCLING" = "1" ]; then \
        pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
        && pip install --no-cache-dir -r requirements-docling.txt \
        && python -c "from docling.document_converter import DocumentConverter; from docling.datamodel.base_models import InputFormat; DocumentConverter().initialize_pipeline(InputFormat.PDF)"; \
    fi

COPY worker /srv/worker
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["uvicorn", "worker.app:app", "--host", "0.0.0.0", "--port", "8000"]
