"""Deterministic chart rendering with matplotlib (SVG). Data always comes from a validated CSV."""
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from core.models import FigureSpec  # noqa: E402

_COLOR = "#1f4e79"


def render_chart(spec: FigureSpec, data_dir: Path, out: Path) -> Path:
    with open(Path(data_dir) / spec.data_ref, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    xs = [r[spec.x] for r in rows]
    ys = [float(r[spec.y].replace(",", "")) for r in rows]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    if spec.kind == "bar":
        ax.bar(xs, ys, color=_COLOR)
    elif spec.kind == "line":
        ax.plot(xs, ys, marker="o", color=_COLOR)
    else:
        ax.pie(ys, labels=xs, autopct="%1.0f%%")
    if spec.kind != "pie":
        ax.set_xlabel(spec.x)
        ax.set_ylabel(spec.y)
        ax.spines[["top", "right"]].set_visible(False)
        if len(xs) > 8:
            ax.tick_params(axis="x", rotation=45)
    ax.set_title(spec.title)
    fig.tight_layout()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="svg")
    plt.close(fig)
    return out
