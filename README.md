# pdf-compress

Shrink a large PDF to fit a size budget by **selectively rasterising only the
heavy pages** — typically figure pages built from enormous *vector* plots — while leaving text pages as native, searchable vector.

It then **maximises quality under the budget**: it renders the heavy pages at
the highest DPI whose output still fits under your target size.

## Why this works

In figure-heavy scientific PDFs, a few pages can each be tens of MB because a
plot of hundreds of points is stored as vector geometry (millions
of Bezier curves). Flattening those pages to a 300+ DPI raster collapses them
dramatically with no visible quality loss at normal viewing/print sizes. Pages
that are mostly text stay untouched, so their text remains selectable and crisp.

## Setup (use a virtual environment)

You are advised to install the dependency into a dedicated virtual environment
rather than your system Python:

```bash
cd pdf-compress
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

The only dependency is [PyMuPDF](https://pymupdf.readthedocs.io/).

## Usage

```bash
python compress_pdf.py INPUT.pdf [OUTPUT.pdf] [options]
```

If `OUTPUT.pdf` is omitted it writes `INPUT_compressed.pdf` next to the input.

### Examples

```bash
# Defaults: target 30 MB, min 300 DPI, auto-detect heavy pages
python compress_pdf.py paper.pdf

# Tighter budget, explicit output name
python compress_pdf.py paper.pdf small.pdf --target-mb 25

# Rasterise a specific set of pages instead of auto-detecting
python compress_pdf.py paper.pdf --pages 5,9,13,18,23,32,35,36,39,42,49,50
```

## How the DPI search works

1. **300 DPI first** (`--min-dpi`, your minimum acceptable quality).
   If the output is *still* over the target at this DPI, the script **aborts**
   (exit code `2`) rather than produce something blurrier than you allow.
2. Otherwise it probes **progressively higher DPIs** (binary search up to
   `--max-dpi`) and keeps the **highest DPI whose output is still under target**.

Each probe is logged, e.g.:

```
probing DPI:
  OK    300 dpi -> 13.0 MB
  OK    450 dpi -> 22.8 MB
  OVER  525 dpi -> 31.4 MB
  OK    475 dpi -> 25.1 MB
DONE: chose 475 dpi -> paper_compressed.pdf (25.1 MB, was 170.0 MB, 6.8x smaller)
```

## Options

| Option | Default | Meaning |
|---|---|---|
| `--target-mb` | `30` | Maximum output size in MB. |
| `--min-dpi` | `300` | Minimum acceptable DPI; abort if still over target here. |
| `--max-dpi` | `600` | Never exceed this DPI even if budget allows. |
| `--dpi-step` | `25` | DPI search granularity. |
| `--jpeg-quality` | `85` | JPEG quality (1–100) for rasterised pages. |
| `--heavy-threshold-mb` | `1.0` | A page is rasterised if its byte weight exceeds this. |
| `--pages` | _(auto)_ | Explicit 1-based pages to rasterise, e.g. `5,9,13`. Overrides auto-detection. |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success — output written under target. |
| `2` | Could not fit under target even at `--min-dpi`. Raise `--target-mb`, lower `--jpeg-quality`/`--min-dpi`, or rasterise more pages. |

## Caveats

- Text *inside* rasterised figure pages (axis labels, gene names baked into a
  plot) becomes pixels and is no longer selectable/searchable. All body text and
  non-figure pages remain native vector.
- Auto-detection targets pages whose serialised byte weight exceeds
  `--heavy-threshold-mb`. If it picks the wrong pages, pass `--pages` explicitly.
- Bookmarks (table of contents) and document metadata are preserved in the
  output.
