#!/usr/bin/env python3
"""
Compress a PDF by selectively rasterising its heavy (vector-graphics-laden)
pages while leaving lighter, text-bearing pages as native, searchable vector.

Strategy
--------
Figure-heavy scientific PDFs are often dominated by a handful of pages that
contain huge *vector* scatter / UMAP / spatial plots (hundreds of thousands of
points, each drawn as Bezier curves). Those pages are enormous as vector but
collapse to a small raster image with no visible quality loss at normal print
or screen sizes. This script:

  1. Detects the heavy pages automatically (by serialised byte weight),
     or uses an explicit list you pass in.
  2. Renders ONLY those pages to a JPEG at a chosen DPI and rebuilds them as a
     single image; every other page is copied through untouched (vector text
     stays selectable / searchable).
  3. Searches DPI to maximise quality under a size budget:
       - Tries --min-dpi first (your minimum acceptable quality, default 300).
         If the file is STILL over the target at that DPI, it gives up
         (exit code 2) rather than ship something blurrier than you allow.
       - Otherwise it probes progressively higher DPIs (binary search) and
         keeps the HIGHEST DPI whose output is still under the target.

Usage
-----
    python compress_pdf.py INPUT.pdf [OUTPUT.pdf] [options]

Examples
--------
    # Defaults: target 30 MB, min 300 dpi, auto-detect heavy pages
    python compress_pdf.py paper.pdf

    # Custom target and explicit pages
    python compress_pdf.py paper.pdf small.pdf --target-mb 25 --pages 5,9,13,18

See README.md for venv setup.
"""

import argparse
import os
import shutil
import sys
import tempfile

import fitz  # PyMuPDF


def human_mb(n_bytes: int) -> str:
    return f"{n_bytes / 1048576:.1f} MB"


def page_weight(doc: "fitz.Document", pno: int) -> int:
    """Real on-disk byte weight of a page: serialise it as a standalone
    one-page PDF (garbage-collected so only the resources this page actually
    references survive) and measure the result. This correctly captures heavy
    vector plots wrapped in Form XObjects, which a content-stream-only count
    would miss."""
    one = fitz.open()
    try:
        one.insert_pdf(doc, from_page=pno, to_page=pno)
        return len(one.tobytes(garbage=4, deflate=True))
    finally:
        one.close()


def detect_heavy_pages(doc: "fitz.Document", threshold_bytes: int) -> list:
    """Return 0-based page indices whose byte weight exceeds the threshold."""
    return [i for i in range(doc.page_count)
            if page_weight(doc, i) >= threshold_bytes]


def build_at_dpi(src_path: str, out_path: str, heavy: set, dpi: int,
                 jpeg_quality: int) -> int:
    """Render the heavy pages at `dpi` as JPEGs, copy the rest verbatim,
    save to out_path, and return the resulting file size in bytes."""
    src = fitz.open(src_path)
    out = fitz.open()
    try:
        for i in range(src.page_count):
            if i in heavy:
                page = src[i]
                rect = page.rect
                pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
                jpg = pix.tobytes("jpeg", jpg_quality=jpeg_quality)
                npage = out.new_page(width=rect.width, height=rect.height)
                npage.insert_image(npage.rect, stream=jpg)
            else:
                out.insert_pdf(src, from_page=i, to_page=i)
        toc = src.get_toc(simple=True)
        if toc:
            out.set_toc(toc)
        out.set_metadata(src.metadata)
        out.save(out_path, garbage=4, deflate=True, clean=True)
    finally:
        out.close()
        src.close()
    return os.path.getsize(out_path)


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="Compress a PDF by rasterising heavy vector pages, "
                    "maximising DPI under a size budget.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", help="input PDF path")
    p.add_argument("output", nargs="?", default=None,
                   help="output PDF path (default: <input>_compressed.pdf)")
    p.add_argument("--target-mb", type=float, default=30.0,
                   help="maximum output size in MB")
    p.add_argument("--min-dpi", type=int, default=300,
                   help="minimum acceptable DPI; if the output is still over "
                        "target at this DPI the script aborts")
    p.add_argument("--max-dpi", type=int, default=600,
                   help="never go above this DPI even if budget allows")
    p.add_argument("--dpi-step", type=int, default=25,
                   help="DPI search granularity")
    p.add_argument("--jpeg-quality", type=int, default=85,
                   help="JPEG quality (1-100) for rasterised pages")
    p.add_argument("--heavy-threshold-mb", type=float, default=1.0,
                   help="a page is rasterised if its byte weight exceeds this")
    p.add_argument("--pages", default=None,
                   help="explicit comma-separated 1-based pages to rasterise, "
                        "e.g. '5,9,13'; overrides auto-detection")
    return p.parse_args(argv)


def main(argv):
    args = parse_args(argv)

    if not os.path.isfile(args.input):
        sys.exit(f"error: input not found: {args.input}")
    if args.min_dpi > args.max_dpi:
        sys.exit("error: --min-dpi must be <= --max-dpi")
    if args.dpi_step < 1:
        sys.exit("error: --dpi-step must be >= 1")
    if not 1 <= args.jpeg_quality <= 100:
        sys.exit("error: --jpeg-quality must be in 1-100")

    out_path = args.output
    if out_path is None:
        base, ext = os.path.splitext(args.input)
        out_path = f"{base}_compressed{ext or '.pdf'}"

    target_bytes = int(args.target_mb * 1048576)

    doc = fitz.open(args.input)
    n = doc.page_count
    orig = os.path.getsize(args.input)

    # --- choose which pages to rasterise -------------------------------------
    if args.pages:
        try:
            heavy = sorted({int(x) - 1 for x in args.pages.split(",") if x.strip()})
        except ValueError:
            sys.exit("error: --pages must be comma-separated integers")
        bad = [i + 1 for i in heavy if i < 0 or i >= n]
        if bad:
            sys.exit(f"error: pages out of range (1-{n}): {bad}")
    else:
        thr = int(args.heavy_threshold_mb * 1048576)
        heavy = detect_heavy_pages(doc, thr)
    doc.close()

    print(f"input : {args.input}  ({human_mb(orig)}, {n} pages)")
    print(f"target: <= {args.target_mb:.0f} MB")
    if not heavy:
        sys.exit("error: no pages selected for rasterisation — nothing to do. "
                 "Lower --heavy-threshold-mb or pass --pages.")
    print(f"rasterising {len(heavy)} page(s): "
          f"{', '.join(str(i + 1) for i in heavy)}")
    print(f"leaving {n - len(heavy)} page(s) as native vector\n")

    heavy_set = set(heavy)
    tmpdir = tempfile.mkdtemp(prefix="pdfcompress_")
    cache = {}  # dpi -> (path, size)

    def render(dpi: int):
        if dpi not in cache:
            path = os.path.join(tmpdir, f"cand_{dpi}.pdf")
            size = build_at_dpi(args.input, path, heavy_set, dpi, args.jpeg_quality)
            cache[dpi] = (path, size)
            status = "OK   " if size <= target_bytes else "OVER "
            print(f"  {status} {dpi:>4} dpi -> {human_mb(size)}")
        return cache[dpi][1]

    try:
        # 1) Minimum acceptable DPI must pass, or we abort.
        print("probing DPI:")
        if render(args.min_dpi) > target_bytes:
            print(f"\nFAILED: even at the minimum {args.min_dpi} dpi the output "
                  f"exceeds {args.target_mb:.0f} MB.\n"
                  f"Options: raise --target-mb, lower --jpeg-quality, lower "
                  f"--min-dpi, or rasterise more pages (lower --heavy-threshold-mb).")
            return 2

        best_dpi = args.min_dpi

        # 2) Probe higher DPIs (binary search) for the highest that still fits.
        candidates = list(range(args.min_dpi + args.dpi_step,
                                 args.max_dpi + 1, args.dpi_step))
        lo, hi = 0, len(candidates) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            dpi = candidates[mid]
            if render(dpi) <= target_bytes:
                best_dpi = dpi
                lo = mid + 1
            else:
                hi = mid - 1

        best_path, best_size = cache[best_dpi]
        shutil.move(best_path, out_path)
        print(f"\nDONE: chose {best_dpi} dpi -> {out_path}  "
              f"({human_mb(best_size)}, was {human_mb(orig)}, "
              f"{orig / best_size:.1f}x smaller)")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
