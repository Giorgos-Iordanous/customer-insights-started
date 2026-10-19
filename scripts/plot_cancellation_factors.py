"""Plot reviewed numeric aggregates only; never query customer data or post reports."""
import argparse
import json
import math
import os
from pathlib import Path
import tempfile

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.ticker import PercentFormatter


ROOT = Path(__file__).resolve().parents[1]
INK, MUTED, GRID = "#172c43", "#53677b", "#e1e8ee"
BLUE, TEAL, ORANGE = "#3266ae", "#128278", "#c76b32"


def _count(value):
    if type(value) is not int or value < 0:
        raise ValueError("Counts must be nonnegative integers")
    return value


def _pair(cancelled, total):
    cancelled, total = _count(cancelled), _count(total)
    if cancelled > total:
        raise ValueError("A numerator exceeds its denominator")
    return cancelled, total


def _groups(rows, expected, scope):
    groups = {}
    if not isinstance(rows, list):
        raise ValueError("Expected aggregate groups")
    for row in rows:
        key = row["group"]
        if not isinstance(key, str) or key not in expected or key in groups:
            raise ValueError("Missing, duplicate, or unexpected aggregate group")
        groups[key] = _pair(row["cancelled"], row["total"])
    if set(groups) != set(expected):
        raise ValueError("Missing aggregate group")
    if tuple(sum(pair[i] for pair in groups.values()) for i in (0, 1)) != scope:
        raise ValueError("Group counts disagree with the overall snapshot")
    return groups


def _percentage(numerator, denominator, places=2):
    return f"{numerator / denominator:.{places}%}" if denominator else "N/A"


def _bars(ax, labels, pairs, color, title, subtitle, places=2):
    rates = [n / d if d else 0 for n, d in pairs]
    limit = min(1.3, max(0.5, math.ceil(max(rates, default=0) * 125) / 100))
    ax.barh(range(len(labels)), rates, color=color, height=0.54, zorder=3)
    ax.set_yticks(range(len(labels)), labels, fontsize=11, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, limit)
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.tick_params(axis="both", length=0, labelcolor=MUTED, pad=8)
    ax.grid(axis="x", color=GRID, zorder=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_facecolor("#ffffff")
    ax.set_title(title, loc="left", fontsize=14, fontweight="bold", color=INK, pad=35)
    ax.text(0, 1.08, subtitle, transform=ax.transAxes, fontsize=10, color=MUTED)
    for i, ((n, d), rate) in enumerate(zip(pairs, rates)):
        ax.text(rate + limit * 0.025, i,
                f"{_percentage(n, d, places)}  ({n:,}/{d:,})",
                va="center", fontsize=11, fontweight="bold", color=INK)


def build_figure(data):
    """Return a figure with fixed text and validated, recomputed numeric values."""
    scope = _pair(data["scope"]["cancelled"], data["scope"]["customers"])
    payment = _groups(data["factor_groups"]["payment"], ("paid", "late", "failed"), scope)
    tickets = _groups(data["factor_groups"]["tickets"], ("0", "1-2", "3-5", "6+"), scope)
    high = tuple(tickets["3-5"][i] + tickets["6+"][i] for i in (0, 1))
    low = tuple(tickets["0"][i] + tickets["1-2"][i] for i in (0, 1))
    coverage = data["comment_coverage"]
    eligible = _count(coverage["eligible_prior_customers"])
    comments = _count(coverage["eligible_prior_comments"])
    if eligible > scope[0] or comments < eligible or (eligible == 0 and comments != 0):
        raise ValueError("Earlier-comment coverage is inconsistent")
    themes = data["prior_comment_themes"]
    theme_pairs = [
        _pair(themes["technical_unique_customers"], eligible),
        _pair(themes["arabic_audio"]["customers"], eligible),
        _pair(themes["payment_failure"]["customers"], eligible),
        _pair(themes["poor_value"]["customers"], eligible),
    ]

    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 11}):
        fig = plt.figure(figsize=(14.4, 10.4), facecolor="#f5f8fb")
        fig.text(0.06, 0.945, "What accompanies customer cancellation?", fontsize=24,
                 fontweight="bold", color=INK)
        fig.text(0.06, 0.902,
                 f"Full customer snapshot  |  {_percentage(*scope)} cancelled  "
                 f"({scope[0]:,} of {scope[1]:,} customers)", fontsize=13, color=MUTED)
        _bars(fig.add_axes((0.12, 0.58, 0.32, 0.22)),
              ["Failed", "Late", "Paid"], [payment[k] for k in ("failed", "late", "paid")],
              BLUE, "Payment status", "Cancellation proportion within each group")
        _bars(fig.add_axes((0.66, 0.58, 0.29, 0.22)),
              ["3+ tickets", "0-2 tickets"], [high, low],
              TEAL, "Support-ticket count", "Cancellation proportion within each group")
        _bars(fig.add_axes((0.25, 0.235, 0.66, 0.225)),
              ["Technical problems*", "Missing Arabic audio", "Payment failure", "Poor perceived value"],
              theme_pairs, ORANGE, "Issues mentioned before cancellation",
              f"Share of {eligible:,} eligible cancelled commenters; {comments:,} earlier comments", places=1)
        fig.text(0.06, 0.155,
                 "* Technical problems include login/access, buffering, and subtitle-sync issues.",
                 fontsize=10.5, color=MUTED)
        fig.text(0.06, 0.117,
                 f"Comment coverage: {eligible:,}/{scope[0]:,} cancelled customers "
                 f"({_percentage(eligible, scope[0], 1)}). Signup date <= comment date < cancellation date.",
                 fontsize=10.5, color=MUTED)
        fig.text(0.06, 0.083,
                 "Customers count once per theme; themes overlap. Limited coverage and phrase rules restrict interpretation.",
                 fontsize=10.5, color=MUTED)
        fig.text(0.06, 0.045,
                 "Associations and reported issues, not proven causes. Snapshot proportions are not weekly churn rates.\n"
                 "Latest payment status and ticket counts may postdate cancellation.",
                 fontsize=10.5, color=INK, linespacing=1.5)
    return fig


def _check_output(source, output):
    protected = [source, ROOT / "data/customers.db"]
    if os.environ.get("DB_PATH"):
        protected.append(Path(os.environ["DB_PATH"]))
    for path in protected:
        if output.resolve() == path.resolve() or (
            output.exists() and path.exists() and output.samefile(path)
        ):
            raise ValueError("Chart output must not overwrite input data")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "outbox/cancellation_factors.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outbox/cancellation_factors.png")
    args = parser.parse_args()
    fig, temporary = None, None
    try:
        if args.input.suffix.lower() != ".json" or args.output.suffix.lower() != ".png":
            raise ValueError("Input must be JSON and output must be PNG")
        _check_output(args.input, args.output)
        data = json.loads(args.input.read_text(encoding="utf-8"))
        fig = build_figure(data)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=args.output.parent, prefix=".cancellation_chart_",
                                         suffix=".png", delete=False) as handle:
            temporary = Path(handle.name)
        fig.savefig(temporary, dpi=170, facecolor=fig.get_facecolor(), metadata={"Software": "Matplotlib"})
        _check_output(args.input, args.output)
        os.replace(temporary, args.output)
        temporary = None
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        parser.exit(1, "Chart generation failed: check aggregate counts and input/output paths.\n")
    finally:
        if fig is not None:
            plt.close(fig)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print("Cancellation-factor chart created from aggregate counts.")


if __name__ == "__main__":
    main()
