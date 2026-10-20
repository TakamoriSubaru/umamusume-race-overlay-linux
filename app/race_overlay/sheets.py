"""Reads a score table from a Google Sheet (link), a .csv file or a .xlsx file.

No account and no extra packages: a Google Sheet must be shared as "Anyone with the link can view"
(or published to the web); the program then downloads it as CSV."""

import csv
import io
import os
import re
import zipfile
import xml.etree.ElementTree as ET

from .scoring import rank_rows
from .util import http_get


def col_index(letter):
    """'A' -> 0, 'B' -> 1, 'AA' -> 26. Returns None for anything that is not a column letter."""
    s = str(letter or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,3}", s):
        return None
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def google_csv_url(link):
    """Turn a normal Google Sheets link into its CSV download link. Returns None if it is not one."""
    m = re.search(r"docs\.google\.com/spreadsheets/d/(?:e/)?([A-Za-z0-9_-]+)", link or "")
    if not m:
        return None
    sid = m.group(1)
    g = re.search(r"[?#&]gid=(\d+)", link)
    if "/d/e/" in link:                       # "publish to the web" link
        url = "https://docs.google.com/spreadsheets/d/e/%s/pub?output=csv" % sid
        return url + ("&gid=" + g.group(1) if g else "")
    return "https://docs.google.com/spreadsheets/d/%s/export?format=csv%s" % (sid, "&gid=" + g.group(1) if g else "")


def parse_csv(text):
    return [row for row in csv.reader(io.StringIO(text))]


def _xlsx_rows(path, sheet=""):
    """Tiny .xlsx reader (values only, no formulas)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels}
        sheets = [(s.get("name"), targets.get(s.get(rel))) for s in wb.find("m:sheets", ns)]
        if not sheets:
            return []
        pick = next((s for s in sheets if sheet and s[0].strip().lower() == sheet.strip().lower()), sheets[0])
        t = pick[1].lstrip("/")
        t = t if t.startswith("xl/") else "xl/" + t
        rows = []
        for row in ET.fromstring(z.read(t)).iter("{%s}row" % ns["m"]):
            cells = {}
            for c in row.findall("m:c", ns):
                ci = col_index(re.sub(r"\d+", "", c.get("r", "")))
                if ci is None:
                    continue
                v = c.find("m:v", ns)
                if c.get("t") == "s" and v is not None:
                    val = shared[int(v.text)]
                elif c.get("t") == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
                else:
                    val = v.text if v is not None and v.text is not None else ""
                cells[ci] = val
            r_no = int(row.get("r", len(rows) + 1))
            while len(rows) < r_no - 1:
                rows.append([])
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
        return rows


def load_rows(source, sheet=""):
    """source = Google Sheets link, other web link to a CSV, or a path to .csv / .xlsx. Returns rows of text."""
    source = (source or "").strip().strip('"')
    if not source:
        raise ValueError("No sheet chosen yet.")
    if re.match(r"https?://", source):
        url = google_csv_url(source) or source
        data = http_get(url, timeout=20)
        text = data.decode("utf-8-sig", "replace") if isinstance(data, bytes) else str(data)
        if text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
            raise ValueError("Google wants a sign-in. Share the sheet as \"Anyone with the link can view\".")
        return parse_csv(text)
    path = os.path.expanduser(source)
    if not os.path.isfile(path):
        raise ValueError("File not found: " + path)
    if path.lower().endswith((".xlsx", ".xlsm")):
        return _xlsx_rows(path, sheet)
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        return parse_csv(f.read())


def to_number(text):
    t = str(text or "").strip().replace(",", ".").replace(" ", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return int(v) if v == int(v) else v


def read_standings(rows, name_col="B", score_col="D", uma_col="C", first_row=4):
    """Pick the player / score columns out of the table. Rows without a name or without a number are skipped
    (headers, empty lines, notes). Reading stops at the first fully empty row after the list started."""
    ni, si, ui = col_index(name_col), col_index(score_col), col_index(uma_col)
    if ni is None or si is None:
        raise ValueError("Column letters must look like B or D.")
    out, started = [], False
    for r in rows[max(0, int(first_row) - 1):]:
        get = lambda i: (r[i].strip() if i is not None and i < len(r) else "")
        name, score = get(ni), to_number(get(si))
        if not name and score is None:
            if started:
                break
            continue
        if not name or score is None:
            continue
        started = True
        out.append({"name": name, "uma": get(ui), "score": score, "races": 0, "last": 0})
    return rank_rows(out)
