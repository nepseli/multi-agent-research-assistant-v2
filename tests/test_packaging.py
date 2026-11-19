"""Guards for the Docker packaging: cheap to break, slow to notice (a 10-minute build)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_build_context_is_only_the_worker():
    lines = [l.strip() for l in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()]
    assert "*" in lines and "!worker/" in lines  # otherwise .venv (~1.3 GB) is uploaded on every build


def test_lean_image_does_not_install_docling():
    base = (ROOT / "worker" / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "docling" not in base and "torch" not in base
    assert "docling" in (ROOT / "worker" / "requirements-docling.txt").read_text(encoding="utf-8").lower()


def test_compose_and_dockerfile_share_the_docling_switch():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "worker" / "Dockerfile").read_text(encoding="utf-8")
    assert "WITH_DOCLING: ${WORKER_DOCLING:-1}" in compose
    assert "ARG WITH_DOCLING=1" in dockerfile and '"$WITH_DOCLING" = "1"' in dockerfile


def test_only_headless_chromium_is_kept():
    dockerfile = (ROOT / "worker" / "Dockerfile").read_text(encoding="utf-8")
    assert "--only-shell" in dockerfile and "rm -rf /ms-playwright/chromium-[0-9]*" in dockerfile
