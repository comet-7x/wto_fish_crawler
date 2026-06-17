"""PDF -> Markdown.

Default backend: MinerU (you already run it). We shell out to the `mineru`
CLI so this works regardless of which magic_pdf/mineru Python API version you
have pinned. Adjust MINERU_CMD below to match your install.

MinerU 2.x typical layout:
    mineru -p input.pdf -o OUTDIR -m auto
produces  OUTDIR/<stem>/auto/<stem>.md

Fallback backend: pymupdf4llm (fast, text-only; loses scanned content).
Switch with `--pdf-backend pymupdf` on the CLI.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

# Edit to your MinerU invocation if it differs.
MINERU_CMD = ["mineru", "-p", "{pdf}", "-o", "{outdir}", "-m", "auto"]


def pdf_to_markdown(pdf_bytes: bytes, stem: str, backend: str = "mineru") -> str | None:
    if backend == "mineru":
        return _via_mineru(pdf_bytes, stem)
    if backend == "pymupdf":
        return _via_pymupdf(pdf_bytes)
    raise ValueError(f"unknown pdf backend: {backend}")


def _via_mineru(pdf_bytes: bytes, stem: str) -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pdf_path = tmp_path / f"{stem}.pdf"
        pdf_path.write_bytes(pdf_bytes)
        outdir = tmp_path / "out"
        outdir.mkdir()

        cmd = [c.format(pdf=str(pdf_path), outdir=str(outdir)) for c in MINERU_CMD]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=900)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            # Surface the reason so the pipeline can log it and fall back.
            raise RuntimeError(f"mineru failed for {stem}: {e}") from e

        # Find the produced markdown (layout varies slightly by version).
        md_files = sorted(outdir.rglob("*.md"))
        if not md_files:
            return None
        # Prefer the one matching the stem; else the largest.
        for m in md_files:
            if stem in m.stem:
                return m.read_text(encoding="utf-8", errors="replace")
        return max(md_files, key=lambda p: p.stat().st_size).read_text(
            encoding="utf-8", errors="replace"
        )


def _via_pymupdf(pdf_bytes: bytes) -> str | None:
    import pymupdf  # noqa: PLC0415
    import pymupdf4llm  # noqa: PLC0415

    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf_bytes)
        f.flush()
        doc = pymupdf.open(f.name)
        return pymupdf4llm.to_markdown(doc)
