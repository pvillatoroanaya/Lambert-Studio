"""
Build the project report: one self-contained HTML page (screenshots embedded)
and, with Edge installed, a PDF of it.

    python report/build_project_report.py [--fragment PATH]

Reads   report/project_report_template.html  and  report/img/project/*.jpg
Writes  report/Lambert_Studio_Project_Report.html  (+ .pdf)
--fragment also writes the page body without the <html>/<head>/<body> wrapper
(the form a hosted-page publisher wants).
"""
import argparse
import base64
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE / "project_report_template.html"
IMAGES = HERE / "img" / "project"
OUT = HERE / "Lambert_Studio_Project_Report.html"


def embed(match):
    path = IMAGES / f"{match.group(1)}.jpg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{data}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fragment")
    args = ap.parse_args()
    body = re.sub(r"\{\{img:(\w+)\}\}", embed, TEMPLATE.read_text(encoding="utf-8"))
    page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            + body.replace("<main", "</head>\n<body>\n<main", 1) + "\n</body>\n</html>\n")
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.name} ({OUT.stat().st_size / 1e6:.1f} MB)")
    if args.fragment:
        pathlib.Path(args.fragment).write_text(body, encoding="utf-8")
        print(f"wrote fragment {args.fragment}")

    edge = shutil.which("msedge") or r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if pathlib.Path(edge).exists():
        pdf = OUT.with_suffix(".pdf")
        subprocess.run([edge, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", "--virtual-time-budget=15000", OUT.as_uri()],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"wrote {pdf.name}" if pdf.exists() else "PDF not written")
    else:
        print("Edge not found: open the HTML in a browser and print it to PDF.")


if __name__ == "__main__":
    sys.exit(main())
