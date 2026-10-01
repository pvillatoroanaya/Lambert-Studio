"""
Assemble the project report: embeds the screenshots and charts (report/img)
into report_template.html (or report_template_es.html with --es) and writes
  report/Lambert_Studio_Report.html      stand-alone page (open in any browser)
  report/Lambert_Studio_Report_ES.html   the Spanish version (--es)
  <out>/lambert_studio_report[_es].html  same content without the outer html
                                          wrapper, for publishing as a web page
usage: python report/build_report.py [--es] [out-dir]
"""
import base64, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
args = [a for a in sys.argv[1:] if a != "--es"]
es = "--es" in sys.argv[1:]
suffix = "_es" if es else ""
tpl = (HERE / f"report_template{suffix}.html").read_text(encoding="utf-8")

def embed(m):
    img = next(q for q in ((HERE / "img" / f"{m.group(1)}{e}") for e in (".jpg", ".png")) if q.exists())
    return "data:image/" + ("png" if img.suffix == ".png" else "jpeg") + ";base64," + base64.b64encode(img.read_bytes()).decode()

body = re.sub(r"\{\{IMG:([\w]+)\}\}", embed, tpl)
page = (f'<!DOCTYPE html>\n<html lang="{"es" if es else "en"}"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        + body.split("<div class=\"wrap\">")[0] + "</head><body>\n<div class=\"wrap\">"
        + body.split("<div class=\"wrap\">", 1)[1] + "\n</body></html>\n")
page_file = HERE / f"Lambert_Studio_Report{suffix.upper()}.html"
page_file.write_text(page, encoding="utf-8")
if args:
    out = pathlib.Path(args[0]) / f"lambert_studio_report{suffix}.html"
    out.write_text(body, encoding="utf-8")
    print("publish copy:", out, f"{out.stat().st_size / 1e6:.2f} MB")
print("stand-alone:", page_file)
