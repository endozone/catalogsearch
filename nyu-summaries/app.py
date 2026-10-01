"""
NYU Catalog Summaries
Search NYU Libraries and read what each book is about without clicking into every record.

Run locally:   streamlit run app.py
"""

import time
import requests
import pandas as pd
import streamlit as st

PRIMO_BASE = "https://search.library.nyu.edu/primaws/rest/pub/pnxs"
VID = "01NYU_INST:NYU"

BASE_PARAMS = {
    "acTriggered": "false",
    "blendFacetsSeparately": "false",
    "citationTrailFilterByAvailability": "true",
    "disableCache": "false",
    "getMore": "0",
    "inst": "01NYU_INST",
    "isCDSearch": "false",
    "lang": "en",
    "newspapersActive": "false",
    "newspapersSearch": "false",
    "otbRanking": "false",
    "pcAvailability": "false",
    "qExclude": "",
    "rapido": "false",
    "refEntryActive": "true",
    "rtaLinks": "true",
    "scope": "CI_NYU_CONSORTIA",
    "searchInFulltextUserSelection": "false",
    "skipDelivery": "Y",
    "sort": "rank",
    "tab": "Unified_Slot",
    "vid": VID,
}

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    ),
    "Referer": f"https://search.library.nyu.edu/discovery/search?vid={VID}",
}

TYPE_FACETS = {
    "Books": "books",
    "Articles": "articles",
    "Book chapters": "book_chapters",
    "Dissertations": "dissertations",
    "Everything": None,
}


# ── Catalog search ────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def search_nyu(query: str, rtype: str | None, limit: int, offset: int) -> dict:
    params = {
        **BASE_PARAMS,
        "q": f"any,contains,{query}",
        "qInclude": f"facet_rtype,exact,{rtype}" if rtype else "",
        "limit": str(limit),
        "offset": str(offset),
    }
    r = requests.get(PRIMO_BASE, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def _first(section: dict, key: str, default: str = "") -> str:
    vals = section.get(key) or []
    return vals[0] if vals else default


def _clean(s: str) -> str:
    # Primo stuffs facet keys after "$$Q"; drop them
    return s.split("$$Q")[0].strip().rstrip(".,;:")


def parse_records(data: dict) -> list[dict]:
    out = []
    for doc in data.get("docs", []):
        pnx = doc.get("pnx", {})
        display, addata, control = (
            pnx.get("display", {}),
            pnx.get("addata", {}),
            pnx.get("control", {}),
        )
        record_id = _first(control, "recordid")
        context = doc.get("context", "L")
        desc = _first(display, "description") or _first(addata, "abstract")

        subjects = []
        for s in display.get("subject", []):
            s = _clean(s)
            if s and s not in subjects:
                subjects.append(s)

        out.append({
            "title": _clean(_first(display, "title")),
            "author": _clean(_first(display, "creator")) or _clean(_first(addata, "au")),
            "year": _first(display, "creationdate") or _first(addata, "date"),
            "type": _first(display, "type").replace("_", " "),
            "publisher": _first(display, "publisher"),
            "description": desc.strip(),
            "source": "NYU catalog" if desc else "",
            "isbn": _first(addata, "isbn"),
            "subjects": "; ".join(subjects),
            "link": (
                f"https://search.library.nyu.edu/discovery/fulldisplay"
                f"?docid={record_id}&context={context}&vid={VID}"
                if record_id else ""
            ),
        })
    return out


# ── Fallbacks for records with no catalog summary ─────────────────

@st.cache_data(ttl=86400, show_spinner=False)
def openlibrary_description(isbn: str) -> str:
    def unwrap(d):
        return d.get("value", "") if isinstance(d, dict) else (d or "")
    try:
        r = requests.get(f"https://openlibrary.org/isbn/{isbn}.json", timeout=10)
        if r.status_code != 200:
            return ""
        edition = r.json()
        if desc := unwrap(edition.get("description")):
            return desc
        works = edition.get("works") or []
        if works and works[0].get("key"):
            w = requests.get(f"https://openlibrary.org{works[0]['key']}.json", timeout=10)
            if w.status_code == 200:
                return unwrap(w.json().get("description"))
    except (requests.RequestException, ValueError):
        pass
    return ""


@st.cache_data(ttl=86400, show_spinner=False)
def google_books_description(isbn: str) -> str:
    try:
        r = requests.get(
            "https://www.googleapis.com/books/v1/volumes",
            params={"q": f"isbn:{isbn}"},
            timeout=10,
        )
        if r.status_code == 200:
            items = r.json().get("items") or []
            if items:
                return items[0].get("volumeInfo", {}).get("description", "")
    except (requests.RequestException, ValueError):
        pass
    return ""


def enrich(records: list[dict]) -> None:
    todo = [r for r in records if not r["description"] and r["isbn"]]
    if not todo:
        return
    bar = st.progress(0.0, text="Looking up missing summaries…")
    for i, rec in enumerate(todo, 1):
        if desc := openlibrary_description(rec["isbn"]):
            rec["description"], rec["source"] = desc, "Open Library"
        elif desc := google_books_description(rec["isbn"]):
            rec["description"], rec["source"] = desc, "Google Books"
        bar.progress(i / len(todo), text=f"Looking up missing summaries… {i}/{len(todo)}")
        time.sleep(0.2)
    bar.empty()


# ── Page ──────────────────────────────────────────────────────────

st.set_page_config(page_title="NYU Catalog Summaries", page_icon="📚", layout="centered")

st.title("NYU Catalog Summaries")
st.write(
    "Search NYU Libraries and read what each result is about, all on one page. "
    "When the catalog has no summary, it checks Open Library and Google Books by ISBN."
)

with st.form("search"):
    query = st.text_input("Search", placeholder="Dutch colonization New York")
    c1, c2, c3 = st.columns([2, 1, 2])
    type_label = c1.selectbox("Type", list(TYPE_FACETS), index=0)
    per_page = c2.selectbox("Results", [10, 25, 50], index=1)
    only_summaries = c3.checkbox("Hide results with no summary", value=False)
    do_enrich = st.checkbox("Fill gaps from Open Library / Google Books", value=True)
    submitted = st.form_submit_button("Search", type="primary")

if submitted:
    st.session_state.update(query=query.strip(), page=0)

q = st.session_state.get("query")
page = st.session_state.get("page", 0)

if not q:
    st.caption("Tip: try a subject plus a place or period, like “wampum trade New Netherland”.")
    st.stop()

try:
    with st.spinner("Searching the catalog…"):
        data = search_nyu(q, TYPE_FACETS[type_label], per_page, page * per_page)
except requests.HTTPError as e:
    st.error(f"The NYU catalog returned an error ({e.response.status_code}). Try again in a minute.")
    st.stop()
except requests.RequestException:
    st.error("Couldn't reach the NYU catalog. Check your connection and try again.")
    st.stop()

total = data.get("info", {}).get("total", 0)
records = parse_records(data)

if not records:
    st.info("No results. Try fewer or broader words.")
    st.stop()

if do_enrich:
    enrich(records)

shown = [r for r in records if r["description"]] if only_summaries else records
have = sum(1 for r in records if r["description"])

start = page * per_page + 1
st.markdown(
    f"**{total:,}** results for *{q}* · showing {start}–{start + len(records) - 1} · "
    f"{have} of {len(records)} have summaries"
)

for rec in shown:
    with st.container(border=True):
        title = f"[{rec['title']}]({rec['link']})" if rec["link"] else rec["title"]
        st.markdown(f"#### {title}")
        meta = [x for x in (rec["author"], rec["year"], rec["type"].capitalize()) if x]
        st.caption("  ·  ".join(meta))
        if rec["description"]:
            st.write(rec["description"])
            st.caption(f"Summary from {rec['source']}")
        else:
            st.caption("No summary found. Open the record for contents and notes.")
        if rec["subjects"]:
            with st.expander("Subjects"):
                st.write(rec["subjects"].replace("; ", "  \n"))

prev_col, mid, next_col = st.columns([1, 2, 1])
if page > 0 and prev_col.button("← Previous"):
    st.session_state.page = page - 1
    st.rerun()
if start + len(records) - 1 < total and next_col.button("Next →"):
    st.session_state.page = page + 1
    st.rerun()

df = pd.DataFrame(records)
mid.download_button(
    "Download this page as CSV",
    df.to_csv(index=False).encode("utf-8"),
    file_name=f"nyu_{q.replace(' ', '_')[:40]}_p{page + 1}.csv",
    mime="text/csv",
    use_container_width=True,
)
