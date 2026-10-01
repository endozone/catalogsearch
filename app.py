"""
NYU Concept Search
One concept, every name it goes by, every subject heading it hides under,
searched across the NYU catalog and NYU's archival collections at once.

Run locally:  streamlit run app.py
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
import streamlit as st

import sources

st.set_page_config(page_title="NYU Concept Search", page_icon="🗺️", layout="wide")

TYPES = {"Books": "books", "Everything": None, "Articles": "articles",
         "Book chapters": "book_chapters", "Dissertations": "dissertations"}

# ── Concepts ──────────────────────────────────────────────────────

if "concepts" not in st.session_state:
    st.session_state.concepts = json.loads(Path(__file__).with_name("concepts.json").read_text("utf-8"))


def load_concept():
    c = st.session_state.concepts.get(st.session_state.concept_name, {})
    st.session_state.terms = "\n".join(c.get("terms", []))
    st.session_state.core = c.get("core", "")
    st.session_state.headings = "\n".join(c.get("headings", []))


def lines(s: str) -> list[str]:
    out = []
    for x in s.splitlines():
        x = x.strip()
        if x and x not in out:
            out.append(x)
    return out


if "terms" not in st.session_state:
    st.session_state.concept_name = next(iter(st.session_state.concepts))
    load_concept()

# ── Cached backends ───────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def cached_primo(q, rtype, limit):
    return sources.primo_query(q, rtype, limit)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_archives(term):
    return sources.archives_query(term)


@st.cache_data(ttl=86400, show_spinner=False)
def cached_wikidata(name):
    return sources.wikidata_variants(name)


def run_search(terms, core, headings, rtype, limit, with_archives):
    jobs = []  # (label, kind, callable, args)
    for t in terms:
        jobs.append((t, "catalog", cached_primo, (sources.term_query(t), rtype, limit)))
        if with_archives:
            jobs.append((t, "archives", cached_archives, (t,)))
    for h in headings:
        jobs.append((f"⟨{h}⟩", "catalog", cached_primo, (sources.heading_query(h, core), rtype, limit)))

    merged = {"catalog": {}, "archives": {}}
    log = []
    bar = st.progress(0.0, text="Searching…")
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(fn, *args): (label, kind) for label, kind, fn, args in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            label, kind = futs[fut]
            try:
                recs = fut.result()
                log.append({"query": label, "source": kind, "hits": len(recs), "error": ""})
                for r in recs:
                    slot = merged[kind].setdefault(r["id"], {**r, "found_by": []})
                    if label not in slot["found_by"]:
                        slot["found_by"].append(label)
            except requests.HTTPError as e:
                log.append({"query": label, "source": kind, "hits": 0, "error": f"HTTP {e.response.status_code}"})
            except Exception as e:  # network, parse
                log.append({"query": label, "source": kind, "hits": 0, "error": type(e).__name__})
            bar.progress(i / len(jobs), text=f"Searching… {i}/{len(jobs)} queries")
    bar.empty()
    order = {t: i for i, t in enumerate(terms + [f"⟨{h}⟩" for h in headings])}
    for kind in merged:
        for r in merged[kind].values():
            r["found_by"].sort(key=lambda x: order.get(x, 999))
    return merged, log

# ── Export ────────────────────────────────────────────────────────

RIS_TYPE = {"book": "BOOK", "article": "JOUR", "book chapter": "CHAP",
            "dissertation": "THES", "conference proceeding": "CONF"}


def to_ris(records):
    out = []
    for r in records:
        if r["source"] == "catalog":
            out.append(f"TY  - {RIS_TYPE.get(r['type'], 'GEN')}")
            out.append(f"TI  - {r['title']}")
            if r.get("vernacular"):
                out.append(f"T2  - {r['vernacular']}")
            for a in re.split(r"\s*;\s*", r["author"] or ""):
                if a:
                    out.append(f"AU  - {a}")
            if y := re.search(r"\d{4}", r["year"] or ""):
                out.append(f"PY  - {y.group()}")
            for k, tag in (("publisher", "PB"), ("isbn", "SN"), ("description", "AB"), ("language", "LA")):
                if r.get(k):
                    out.append(f"{tag}  - {r[k]}")
            for s in r["subjects"]:
                out.append(f"KW  - {s}")
        else:
            out.append("TY  - MANSCPT")
            out.append(f"TI  - {r['title']}")
            if y := re.search(r"\d{4}", r["dates"] or ""):
                out.append(f"PY  - {y.group()}")
            out.append(f"PB  - {r['library']}")
            out.append(f"N1  - {r['path']} | {r['call_no']} | {r['location']}")
        out.append(f"UR  - {r['link']}")
        out.append(f"N1  - Found by: {', '.join(r['found_by'])}")
        out.append("ER  - \n")
    return "\n".join(out)

# ── Sidebar: concept library ──────────────────────────────────────

with st.sidebar:
    st.header("Concepts")
    st.selectbox("Saved concepts", list(st.session_state.concepts), key="concept_name", on_change=load_concept)
    note = st.session_state.concepts.get(st.session_state.concept_name, {}).get("note")
    if note:
        st.caption(note)

    st.divider()
    st.subheader("New concept")
    new_name = st.text_input("Name", placeholder="Kwantung Army")
    if st.button("Suggest names from Wikidata", disabled=not new_name):
        try:
            matched, names = cached_wikidata(new_name)
            if names:
                st.session_state.terms = "\n".join(names)
                st.session_state.core = new_name
                st.session_state.headings = ""
                st.success(f"Matched {matched}. Review the names before searching.")
            else:
                st.warning("No Wikidata match. Add names by hand.")
        except requests.RequestException:
            st.error("Couldn't reach Wikidata.")
    if st.button("Save current lists as this concept", disabled=not new_name):
        st.session_state.concepts[new_name] = {
            "terms": lines(st.session_state.terms),
            "core": st.session_state.core,
            "headings": lines(st.session_state.headings),
        }
        st.success(f"Saved “{new_name}” for this session.")

    st.download_button(
        "Download concepts.json",
        json.dumps(st.session_state.concepts, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="concepts.json", mime="application/json",
        help="Saved concepts only last for this session. Download the file and replace concepts.json in the repo to keep them.",
    )

# ── Main: query builder ───────────────────────────────────────────

st.title("NYU Concept Search")
st.write(
    "Every name a concept goes by, plus the subject headings it gets filed under, "
    "searched across the NYU catalog and the Special Collections archives. "
    "Each result shows which name or heading found it."
)

c1, c2 = st.columns(2)
with c1:
    st.text_area("Names and variants (one per line, first one is your baseline)", key="terms", height=230)
with c2:
    st.text_area("Subject headings to search inside (catalog only)", key="headings", height=150)
    st.text_input("Keyword to pair with each heading", key="core",
                  help="Each heading is searched as: subject contains HEADING and anywhere contains KEYWORD.")

o1, o2, o3, o4 = st.columns([1, 1, 1, 1])
rtype_label = o1.selectbox("Catalog type", list(TYPES))
limit = o2.selectbox("Results per query", [10, 25, 50], index=1)
with_archives = o3.checkbox("Search archives too", value=True)
go = o4.button("Search", type="primary")

terms, headings = lines(st.session_state.terms), lines(st.session_state.headings)
if go:
    if not terms and not headings:
        st.warning("Add at least one name or heading.")
        st.stop()
    merged, log = run_search(terms, st.session_state.core.strip(), headings,
                             TYPES[rtype_label], limit, with_archives)
    st.session_state.results = {"merged": merged, "log": log, "baseline": terms[0] if terms else None}

res = st.session_state.get("results")
if not res:
    st.stop()

merged, log, baseline = res["merged"], res["log"], res["baseline"]
cat, arc = list(merged["catalog"].values()), list(merged["archives"].values())
allrecs = cat + arc

# ── Headline: what the baseline search alone would have missed ───

missed = [r for r in allrecs if baseline not in r["found_by"]]
errors = [l for l in log if l["error"]]
m1, m2, m3, m4 = st.columns(4)
m1.metric("Catalog results", len(cat))
m2.metric("Archival results", len(arc))
m3.metric(f"Missed by “{baseline}” alone", len(missed),
          help="Results that only turned up through another name or a subject heading.")
m4.metric("Queries run", len(log), delta=f"{len(errors)} failed" if errors else None, delta_color="inverse")

f1, f2 = st.columns([1, 1])
only_missed = f1.toggle(f"Only show what “{baseline}” missed")
sort_by = f2.radio("Sort", ["Found by most queries", "Newest", "Oldest"], horizontal=True)


def sort_key(r):
    y = re.search(r"\d{4}", r.get("year") or r.get("dates") or "")
    y = int(y.group()) if y else 0
    if sort_by == "Newest":
        return -y
    if sort_by == "Oldest":
        return y or 9999
    return -len(r["found_by"])


def chips(r):
    return " ".join(f"`{x}`" for x in r["found_by"])


def pick_key(r):
    return "pick_" + re.sub(r"\W", "_", r["id"])[-80:]


def show(recs, kind):
    recs = [r for r in recs if not only_missed or baseline not in r["found_by"]]
    if not recs:
        st.info("Nothing here.")
        return
    for r in sorted(recs, key=sort_key):
        with st.container(border=True):
            left, right = st.columns([0.05, 0.95])
            left.checkbox("Select", key=pick_key(r), label_visibility="collapsed")
            with right:
                st.markdown(f"**[{r['title']}]({r['link']})**")
                if kind == "catalog":
                    if r.get("vernacular"):
                        st.markdown(r["vernacular"])
                    st.caption("  ·  ".join(x for x in (r["author"], r["year"], r["type"].capitalize(), r["language"]) if x))
                    st.markdown("Found by: " + chips(r))
                    if r["description"]:
                        d = r["description"]
                        st.write(d if len(d) < 450 else d[:420].rsplit(" ", 1)[0] + "…")
                        if len(d) >= 450:
                            with st.expander("Full summary"):
                                st.write(d)
                    if r["contents"]:
                        with st.expander("Contents"):
                            st.write(r["contents"].replace(" -- ", "  \n"))
                    if r["subjects"]:
                        with st.expander(f"Subjects ({len(r['subjects'])})"):
                            st.write("  \n".join(r["subjects"]))
                else:
                    st.caption(f"{r['library']}  ·  {r['kind'].capitalize()}" + (f"  ·  {r['dates']}" if r["dates"] else ""))
                    if r["path"]:
                        st.write(r["path"])
                    loc = "  ·  ".join(x for x in (r["call_no"], r["location"]) if x)
                    if loc:
                        st.caption(loc)
                    st.markdown("Found by: " + chips(r))


t1, t2, t3 = st.tabs([f"Catalog ({len(cat)})", f"Archives ({len(arc)})", "Query log"])
with t1:
    show(cat, "catalog")
with t2:
    show(arc, "archives")
with t3:
    st.caption("Each row is one search. Zero hits on a variant is useful information too.")
    st.dataframe(sorted(log, key=lambda l: (l["source"], -l["hits"])), hide_index=True)

selected = [r for r in allrecs if st.session_state.get(pick_key(r))]
export = selected or allrecs
st.download_button(
    f"Export {'selected (' + str(len(selected)) + ')' if selected else 'all (' + str(len(allrecs)) + ')'} to Zotero (.ris)",
    to_ris(export).encode("utf-8"),
    file_name=f"{re.sub(r'\W+', '_', baseline or 'search')}.ris",
    mime="application/x-research-info-systems",
    type="primary",
)
