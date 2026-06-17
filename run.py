"""CLI entry point.

Examples:
    python run.py selftest                       # run pure-logic unit tests
    python run.py crawl --out ./wto_fish_out     # Tier 1 only
    python run.py crawl --out ./out --include-docs --max-depth 5
    python run.py crawl --out ./out --resume     # continue a previous run
    python run.py crawl --out ./out --pdf-backend pymupdf
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from pathlib import Path

from wto_fish import config
from wto_fish.pipeline import Crawler, load_visited


def _setup_logging(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(out / "crawl.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def cmd_crawl(args: argparse.Namespace) -> int:
    out = Path(args.out)
    _setup_logging(out)
    crawler = Crawler(
        out,
        max_depth=args.max_depth,
        concurrency=args.concurrency,
        delay_s=args.delay,
        include_docs=args.include_docs,
        max_pages=args.max_pages,
        pdf_backend=args.pdf_backend,
    )
    if args.resume:
        n, retry = load_visited(out, crawler)
        logging.getLogger("wto_fish").info(
            "resume: %d done URLs skipped, %d errored URLs will be retried", n, retry)
    seeds = config.SEEDS if not args.seed else args.seed
    asyncio.run(crawler.run(seeds))
    logging.getLogger("wto_fish").info("done. kept=%d", crawler.kept)
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
    return subprocess.call([sys.executable, "-m", "pytest", "tests/", "-q"])


def main() -> int:
    p = argparse.ArgumentParser(prog="wto-fish-crawler")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("crawl", help="run the crawl")
    c.add_argument("--out", required=True, help="output directory")
    c.add_argument("--max-depth", type=int, default=config.DEFAULT_MAX_DEPTH)
    c.add_argument("--concurrency", type=int, default=config.DEFAULT_CONCURRENCY)
    c.add_argument("--delay", type=float, default=config.DEFAULT_DELAY_S,
                   help="seconds between requests (politeness)")
    c.add_argument("--include-docs", action="store_true",
                   help="also crawl Tier-2 docs.wto.org whitelisted documents")
    c.add_argument("--max-pages", type=int, default=None,
                   help="stop after keeping this many docs (smoke test)")
    c.add_argument("--pdf-backend", choices=["mineru", "pymupdf"], default="mineru")
    c.add_argument("--resume", action="store_true",
                   help="skip URLs already in the existing manifest")
    c.add_argument("--seed", action="append",
                   help="override seeds (repeatable); default = config.SEEDS")
    c.set_defaults(func=cmd_crawl)

    s = sub.add_parser("selftest", help="run pure-logic unit tests")
    s.set_defaults(func=cmd_selftest)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
