import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from core.config import SIZE_PRESETS  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Multi-agent research assistant")
    p.add_argument("--topic", help="What to research")
    p.add_argument("--size", choices=list(SIZE_PRESETS), default="medium")
    p.add_argument("--pdf", action="store_true", help="Also produce a PDF (needs the Docker worker)")
    p.add_argument("--tier", type=int, choices=[0, 1, 2, 3], default=None, help="Force a search depth")
    p.add_argument("--check", action="store_true", help="Check keys, models and the worker, then exit (costs nothing)")
    p.add_argument("--live", action="store_true", help="With --check: also send one tiny prompt to each model")
    args = p.parse_args(argv)
    if not args.check and not args.topic:
        p.error("--topic is required (or use --check to test your setup)")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    # Notes and captions carry model text (non-breaking hyphens, CJK brackets); a cp1252 console
    # cannot print them, and a crash here would hide where the finished report was saved.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if args.check:
        import os

        from tools import setup_check
        from tools.worker_client import WorkerClient

        worker = WorkerClient(os.getenv("WORKER_URL", "http://localhost:8000"))
        checks = setup_check.run_checks(os.environ, worker, live=args.live)
        print(setup_check.format_checks(checks))
        return 1 if any(c.status == "fail" for c in checks) else 0
    from flows.research_flow import ResearchFlow

    flow = ResearchFlow(
        args.topic, pdf=args.pdf, size=args.size, forced_tier=args.tier,
        on_stage=lambda s, st: print(f"[{s}] {st}", flush=True),
    )
    result = flow.run()
    print(f"\nReport: {result.markdown_path} ({result.words} words)")
    if result.pdf_path:
        print(f"PDF: {result.pdf_path}")
    for note in result.notes:
        print(f"Note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
