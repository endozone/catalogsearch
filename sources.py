"""Search backends: NYU Primo VE catalog, NYU Special Collections portal, Wikidata name variants."""

import re
import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
)
VID = "01NYU_INST:NYU"

# ── NYU catalog (Primo VE) ────────────────────────────────────────

PRIMO_URL = "https://search.library.nyu.edu/primaws/rest/pub/pnxs"
PRIMO_PARAMS = {
    "acTriggered": "false", "blendFacetsSeparately": "false",
    "citationTrailFilterByAvailability": "true", "disableCache": "false",
    "getMore": "0", "inst": "01NYU_INST", "isCDSearch": "false", "lang": "en",
    "newspapersActive": "false", "newspapersSearch": "false", "otbRanking": "false",
    "pcAvailability": "false", "qExclude": "", "rapido": "false",
    "refEntryActive": "true", "rtaLinks": "true", "scope": "CI_NYU_CONSORTIA",
    "searchInFulltextUserSelection": "false", "skipDelivery": "Y", "sort": "rank",
    "tab": "Unified_Slot", "vid": VID,
}
PRIMO_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": UA,
    "Referer": f"https://search.library.nyu.edu/discovery/search?vid={VID}",
}

BOILERPLATE = [
    r"This title is part of UC Press's Voices Revived program.*?(?=This title was originally|$)",
    r"This title was originally published in \d{4}\.?",
    r"[—–-]+\s*(Back|Front) cover\.?\s*$",
    r"[—–-]+\s*(Provided by|Source:) publisher\.?\s*$",
    r"Drawing on a backlist dating to \d{4}.*?technology\.",
]


def clean_description(text: str) -> str:
    for pat in BOILERPLATE:
        text = re.sub(pat, "", text, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) > 40 else ""


def _first(d: dict, k: str) -> str:
    v = d.get(k) or []
    return v[0] if v else ""


def _strip(s: str) -> str:
    return s.split("$$Q")[0].strip().rstrip(".,;:/ ")


def primo_query(q: str, rtype: str | None, limit: int) -> list[dict]:
    """q is a full Primo query string, e.g. 'any,contains,Manchukuo'."""
    params = {
        **PRIMO_PARAMS, "q": q, "limit": str(limit), "offset": "0",
        "qInclude": f"facet_rtype,exact,{rtype}" if rtype else "",
    }
    r = requests.get(PRIMO_URL, params=params, headers=PRIMO_HEADERS, timeout=30)
    r.raise_for_status()
    out = []
    for doc in r.json().get("docs", []):
        pnx = doc.get("pnx", {})
        disp, ad, ctl = pnx.get("display", {}), pnx.get("addata", {}), pnx.get("control", {})
        rid = _first(ctl, "recordid")
        if not rid:
            continue
        # Primo sometimes stores the original-script title in a parallel field
        vernacular = ""
        for k in ("vertitle", "lds10"):
            if disp.get(k):
                vernacular = _strip(disp[k][0])
                break
        subjects = []
        for s in disp.get("subject", []):
            s = _strip(s)
            if s and s not in subjects:
                subjects.append(s)
        out.append({
            "id": rid,
            "source": "catalog",
            "title": _strip(_first(disp, "title")),
            "vernacular": vernacular,
            "author": _strip(_first(disp, "creator")) or _strip(_first(ad, "au")),
            "year": _first(disp, "creationdate") or _first(ad, "date"),
            "type": _first(disp, "type").replace("_", " "),
            "publisher": _first(disp, "publisher"),
            "language": _first(disp, "language"),
            "isbn": _first(ad, "isbn"),
            "description": clean_description(_first(disp, "description") or _first(ad, "abstract")),
            "contents": _first(disp, "contents"),
            "subjects": subjects,
            "link": f"https://search.library.nyu.edu/discovery/fulldisplay?docid={rid}&context={doc.get('context', 'L')}&vid={VID}",
        })
    return out


def term_query(term: str) -> str:
    return f"any,contains,{term}"


def heading_query(heading: str, core: str) -> str:
    # subject heading AND keyword, in Primo's advanced-search syntax
    q = f"sub,contains,{heading}"
    return f"{q},AND;any,contains,{core}" if core else q


# ── Special Collections portal (Blacklight, server-rendered HTML) ─

ARCHIVES_URL = "https://specialcollections.library.nyu.edu/search/"


def archives_query(term: str, per_page: int = 50) -> list[dict]:
    r = requests.get(
        ARCHIVES_URL,
        params={"utf8": "✓", "q": term, "per_page": per_page},
        headers={"User-Agent": UA},
        timeout=30,
    )
    r.raise_for_status()
    return parse_archives_html(r.text)


def parse_archives_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for d in soup.select("div.document"):
        a = d.select_one("h2 a")
        if not a:
            continue
        meta = {}
        for dt, dd in zip(d.select("dt"), d.select("dd")):
            meta[dt.get_text(" ", strip=True).rstrip(":")] = dd
        path = ""
        if "Contained in" in meta:
            path = re.sub(r"\s*>>\s*", " › ", meta["Contained in"].get_text(" ", strip=True))
        text = lambda k: meta[k].get_text(" ", strip=True) if k in meta else ""
        kind = next((c for c in d.get("class", []) if c.startswith("blacklight-")), "")
        out.append({
            "id": a.get("href", ""),
            "source": "archives",
            "title": a.get_text(" ", strip=True),
            "kind": kind.replace("blacklight-", "").replace("archival-", "").replace("-", " "),
            "path": path,
            "collection": path.split(" › ")[0] if path else "",
            "library": text("Library"),
            "call_no": text("Collection call no"),
            "location": text("Location"),
            "dates": text("Date range"),
            "link": a.get("href", ""),
        })
    return out


# ── Wikidata: suggest name variants for a concept ────────────────

WD_API = "https://www.wikidata.org/w/api.php"
WD_LANGS = ["en", "zh", "zh-hans", "zh-hant", "zh-tw", "zh-cn", "ja", "ru"]


def wikidata_variants(name: str) -> tuple[str, list[str]]:
    """Return (matched item label, list of labels + aliases across WD_LANGS)."""
    h = {"User-Agent": "nyu-concept-search/0.2 (research tool)"}
    s = requests.get(WD_API, params={
        "action": "wbsearchentities", "search": name, "language": "en",
        "format": "json", "limit": 1,
    }, headers=h, timeout=15).json()
    hits = s.get("search") or []
    if not hits:
        return "", []
    qid = hits[0]["id"]
    e = requests.get(WD_API, params={
        "action": "wbgetentities", "ids": qid, "props": "labels|aliases",
        "languages": "|".join(WD_LANGS), "format": "json",
    }, headers=h, timeout=15).json()["entities"][qid]
    names = [v["value"] for v in e.get("labels", {}).values()]
    for lst in e.get("aliases", {}).values():
        names += [v["value"] for v in lst]
    seen, out = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return f"{hits[0].get('label', name)} ({qid})", out
