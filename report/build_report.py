"""
Assemble the project report: embeds the screenshots (report/img/*.jpg) into
report_template.html and writes
  report/Lambert_Studio_Report.html   stand-alone page (open in any browser)
  <out>/lambert_studio_report.html    same content without the outer html
                                       wrapper, for publishing as a web page
usage: python report/build_report.py [out-dir]
"""
import base64, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
tpl = (HERE / "report_template.html").read_text(encoding="utf-8")

def embed(m):
    img = HERE / "img" / f"{m.group(1)}.jpg"
    return "data:image/jpeg;base64," + base64.b64encode(img.read_bytes()).decode()

body = re.sub(r"\{\{IMG:([\w]+)\}\}", embed, tpl)
page = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        + body.split("<div class=\"wrap\">")[0] + "</head><body>\n<div class=\"wrap\">"
        + body.split("<div class=\"wrap\">", 1)[1] + "\n</body></html>\n")
(HERE / "Lambert_Studio_Report.html").write_text(page, encoding="utf-8")
if len(sys.argv) > 1:
    out = pathlib.Path(sys.argv[1]) / "lambert_studio_report.html"
    out.write_text(body, encoding="utf-8")
    print("publish copy:", out, f"{out.stat().st_size / 1e6:.2f} MB")
print("stand-alone:", HERE / "Lambert_Studio_Report.html")
