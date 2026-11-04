"""Run one eval experiment and write its section into a results file.

    cd server && uv run python ../eval/run.py chunks
    cd server && uv run python ../eval/run.py transcribe --reader noisy:0.1

Exit 2 when the Gemini privacy gate refuses (see evalkit/readers.py).
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evalkit import report
from evalkit.arms import IMAGE_SCALE, STROKE_TOKEN_BUDGET, STROKE_WIDTH
from evalkit.dataset import load_dataset
from evalkit.experiments import EXPERIMENTS
from evalkit.readers import GateError, load_reader

NEEDS_READER = {"transcribe", "diagram", "input_repr"}


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else REPO / path


def main(argv: list[str] | None = None, today: str | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("experiment", choices=sorted(EXPERIMENTS))
    ap.add_argument("--data", default="eval/data/synthetic-v1")
    ap.add_argument("--reader", default=None, help="oracle | noisy:RATE | gemini | module:attr")
    ap.add_argument("--allow-model", action="store_true", help="permit the gemini reader")
    ap.add_argument("--out", default="eval/results.md")
    ap.add_argument("--label", default=None, help="section name (default: the experiment)")
    args = ap.parse_args(argv)

    dataset = load_dataset(_resolve(args.data))
    reader = None
    reader_name = "none"
    spec = args.reader or ("oracle" if args.experiment in NEEDS_READER else None)
    if spec:
        try:
            reader = load_reader(spec, dataset, allow_model=args.allow_model)
        except GateError as e:
            print(f"refused: {e}", file=sys.stderr)
            return 2
        reader_name = getattr(reader, "name", spec)

    result = EXPERIMENTS[args.experiment](dataset, reader)
    table = report.render_table(result.headers, result.rows)
    note = f"\n\n{result.summary['skipped']}" if "skipped" in result.summary else ""
    body = report.section_header(dataset.name, dataset.synthetic, reader_name, today)
    body += f"\n\n{table}{note}"
    if args.experiment == "input_repr":
        body += (
            f"\n\nfixed across arms: image scale {IMAGE_SCALE:.1f}, stroke width {STROKE_WIDTH}, "
            f"stroke budget {STROKE_TOKEN_BUDGET} tokens"
        )
    print(body)
    report.write_section(_resolve(args.out), args.label or args.experiment, body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
