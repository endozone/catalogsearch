# NYU Concept Search

Search one concept under every name it goes by (romanizations, scripts, period
names) and inside every subject heading it gets filed under, across both the
NYU Libraries catalog and the NYU Special Collections archival portal
(Tamiment, Fales, University Archives, New-York Historical, Brooklyn History).
Every result shows which name or heading found it, and the headline number
tells you how much your usual single search would have missed.

## Run locally

    pip install -r requirements.txt
    streamlit run app.py

## Put it online

Same as before: push this folder to a public GitHub repo, then create an app
at https://share.streamlit.io pointing at app.py.

## Concepts

concepts.json holds the saved concepts (names, a pairing keyword, and subject
headings). The starter lists are drafts to correct, not authorities. New
concepts made in the app only last for the session. Use "Download
concepts.json" and commit the file to keep them.

## Exporting

Tick results and export them as a .ris file, which Zotero imports with
File > Import. With nothing ticked, everything exports.
