# NYU Catalog Summaries

Search NYU Libraries and see a summary for every result on one page, instead of
clicking into each record. When the catalog has no summary, the app looks the
book up by ISBN on Open Library, then Google Books.

## Run it on your own computer

    pip install -r requirements.txt
    streamlit run app.py

It opens at http://localhost:8501.

## Put it online with a shareable link (free)

1. Make a new public GitHub repo and upload `app.py`, `requirements.txt`
   and the `.streamlit` folder.
2. Go to https://share.streamlit.io, sign in with GitHub, click "Create app",
   pick the repo, and set the main file to `app.py`.
3. Deploy. You'll get a link like `https://your-app.streamlit.app` to send around.

## How it works

The NYU catalog website is powered by a public JSON endpoint
(`/primaws/rest/pub/pnxs`) that the page calls every time you search. This app
calls the same endpoint directly and reads the `description` field from each
record. No login or API key is involved.
