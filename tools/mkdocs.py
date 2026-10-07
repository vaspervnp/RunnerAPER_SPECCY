"""Player's manuals -> PDF.

    python3 tools/mkdocs.py            (make docs)

docs/manual_en.md, docs/manual_el.md -> build/docs/manual_*.html -> docs/manual_*.pdf

The Markdown is the small subset the manuals use (headings, paragraphs,
lists, tables, images, quotes, code blocks, **bold**, *italic*, `code`,
links). The PDFs are printed by a headless Chromium browser: EDGE (default:
Microsoft Edge of Windows, reached from WSL) or any chrome/chromium binary.
"""

import html
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DOCS = os.path.join(ROOT, "docs")
BUILD = os.path.join(ROOT, "build", "docs")
EDGE = os.environ.get("EDGE", "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
WSL = EDGE.startswith("/mnt/")
FONTS = ("https://fonts.googleapis.com/css2?family=Play:wght@400;700"
         "&family=Noto+Sans:ital,wght@0,400;0,700;1,400&family=Fira+Mono&display=swap")


# --- Markdown subset -> HTML ---------------------------------------------------

def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)


def markdown(source):
    out, para, lines, i = [], [], source.splitlines(), 0

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("```"):
            flush()
            block = []
            i += 1
            while not lines[i].startswith("```"):
                block.append(html.escape(lines[i]))
                i += 1
            out.append("<pre>" + "\n".join(block) + "</pre>")
        elif not line:
            flush()
        elif m := re.match(r"(#{1,3}) (.*)", line):
            flush()
            n = len(m[1])
            out.append(f"<h{n}>{inline(m[2])}</h{n}>")
        elif line == "---":
            flush()
            out.append('<div class="stripes"></div>')
        elif m := re.match(r"!\[([^\]]*)\]\(([^)]+)\)$", line):
            flush()
            out.append(f'<figure><img src="{m[2]}" alt="{html.escape(m[1])}">'
                       f"<figcaption>{inline(m[1])}</figcaption></figure>")
        elif line.startswith("> "):
            flush()
            quote = []
            while i < len(lines) and lines[i].startswith("> "):
                quote.append(lines[i][2:])
                i += 1
            out.append(f"<blockquote>{inline(' '.join(quote))}</blockquote>")
            continue
        elif line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], rows[2:]
            out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
                       + "</table>")
            continue
        elif m := re.match(r"(- |\d+\. )(.*)", line):
            flush()
            tag = "ul" if m[1] == "- " else "ol"
            items = []
            while i < len(lines) and (m := re.match(r"(- |\d+\. )(.*)", lines[i])):
                items.append(m[2])
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        else:
            para.append(line.strip())
        i += 1
    flush()
    return "\n".join(out)


MANUAL_CSS = """
@page { size: A5; margin: 14mm 13mm 16mm 13mm;
        @bottom-center { content: counter(page); font: 700 9pt Play, sans-serif; color: #800000; } }
@page :first { @bottom-center { content: none; } }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font: 9.5pt/1.45 'Noto Sans', 'Segoe UI', sans-serif; color: #111; background: #fffdf3; margin: 0; }
h1 { font: 700 30pt/1 Play, sans-serif; margin: 0 0 2mm; letter-spacing: 1px; text-align: center;
     background: linear-gradient(#ffff00 0 35%, #ff8000 35% 60%, #ff0000 60%); -webkit-background-clip: text;
     color: transparent; -webkit-text-stroke: 0.6pt #000; }
h1 + h2 { text-align: center; border: 0; background: none; color: #000080; margin-top: 0; padding: 0; }
h2 { font: 700 14pt Play, sans-serif; color: #fff; background: #000080; padding: 1.2mm 3mm; margin: 5mm 0 3mm;
     border-left: 3mm solid #ff0000; break-after: avoid; }
h3 { font: 700 11pt Play, sans-serif; color: #800000; margin: 4mm 0 2mm; break-after: avoid; }
h1 + h2 + p { text-align: center; }
p { margin: 0 0 2.5mm; }
.stripes { height: 2.4mm; margin: 5mm 0; background: linear-gradient(#ff0000 0 33%, #00c000 33% 66%, #0000ff 66%); }
figure { margin: 3mm 0; text-align: center; break-inside: avoid; }
figure img { width: 88%; image-rendering: pixelated; border: 1.5mm solid #000; box-shadow: 1.5mm 1.5mm 0 #ff8000; }
figcaption { font: italic 8pt 'Noto Sans', sans-serif; color: #555; margin-top: 1mm; }
table { border-collapse: collapse; width: 100%; margin: 2mm 0 3mm; font-size: 8.8pt; break-inside: avoid; }
th { font: 700 9pt Play, sans-serif; background: #ffff80; text-align: left; border-bottom: 0.6mm solid #000; }
th, td { padding: 1mm 1.6mm; vertical-align: top; }
tr:nth-child(odd) td { background: #f2eedc; }
code, pre { font-family: 'Fira Mono', Consolas, monospace; font-size: 8.6pt; }
code { background: #000; color: #ffff00; padding: 0 1mm; border-radius: 0.6mm; }
pre { background: #000080; color: #ffff80; padding: 2.5mm 3mm; border-left: 3mm solid #ff8000; white-space: pre-wrap; }
blockquote { margin: 3mm 0; padding: 2mm 3mm; border: 0.6mm dashed #800000; background: #fff3d0; }
ul, ol { margin: 0 0 2.5mm; padding-left: 6mm; }
strong { color: #800000; }
"""


def manual(lang):
    with open(os.path.join(DOCS, f"manual_{lang}.md"), encoding="utf-8") as f:
        body = markdown(f.read())
    body = body.replace('src="screenshots/', f'src="{file_url(os.path.join(DOCS, "screenshots"))}/')
    page = (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<link href="{FONTS}" rel="stylesheet"><style>{MANUAL_CSS}</style></head>'
            f"<body>{body}</body></html>")
    os.makedirs(BUILD, exist_ok=True)
    path = os.path.join(BUILD, f"manual_{lang}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path


# --- headless browser ------------------------------------------------------------

def native(path):
    if not WSL:
        return path
    return subprocess.run(["wslpath", "-w", path], capture_output=True, text=True, check=True).stdout.strip()


def file_url(path):
    return "file:" + native(path).replace("\\", "/") if WSL else "file://" + path


def browser(*args):
    if not os.path.exists(EDGE) and not shutil.which(EDGE):
        raise SystemExit(f"mkdocs: no browser at {EDGE} (set EDGE=chromium binary)")
    subprocess.run([EDGE, "--headless", "--disable-gpu", "--hide-scrollbars", "--no-pdf-header-footer",
                    "--virtual-time-budget=5000", *args], check=True, capture_output=True, timeout=120)


def pdf(html_path, out):
    browser(f"--print-to-pdf={native(out)}", file_url(html_path))
    print(f"docs       {os.path.relpath(out, ROOT)}")


def main():
    for lang in ("en", "el"):
        pdf(manual(lang), os.path.join(DOCS, f"manual_{lang}.pdf"))


if __name__ == "__main__":
    main()
