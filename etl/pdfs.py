"""
ETL for PDF documents (papers).

Fetches metadata from the LLM Lit Review collection, resolves a PDF URL,
extracts text with PyPDFLoader, annotates endmatter pages, and inserts
into the document store via etl.shared.add_to_document_db.
"""
from langchain_community.document_loaders import PyPDFLoader
from pathlib import Path
import etl.shared
import docstore
import logging
import arxiv
import modal
import json
import re


# extend the shared image with PDF-handling dependencies
image = (
    etl.shared.base_image
    .pip_install(
        "arxiv>=2.1.0",
        "pypdf>=5.1.0",
        "langchain-community>=0.3",
    )
    .add_local_python_source("vecstore", "docstore", "utils", "prompts", "etl")
)

app = modal.App(
    name="etl-pdfs",
    image=image,
    secrets=[modal.Secret.from_name("mongodb-fsdl")]
)


@app.local_entrypoint()
def main(json_path="data/llm-papers.json", collection=None, db=None):
    """Runs the PDF ETL pipeline.

    modal run --env dev etl/pdfs.py --json-path /path/to/json
    """
    json_path = Path(json_path).resolve()

    if not json_path.exists():
        print(f"{json_path} not found, fetching from the source database.")
        paper_data = fetch_papers.call()
        with open(json_path, "w") as f:
            json.dump(paper_data, f, indent=2)

    with open(json_path) as f:
        paper_data = json.load(f)

    # Resolve a PDF URL for each paper, then extract text and metadata.
    paper_data = get_pdf_url.map(paper_data, return_exceptions=True)
    documents = etl.shared.unchunk(
        extract_pdf.map(paper_data, return_exceptions=True)
    )

    with etl.shared.app.run():
        chunked_documents = etl.shared.chunk_into(documents, 10)
        list(
            etl.shared.add_to_document_db.map(
                chunked_documents, kwargs={"db": db, "collection": collection}
            )
        )


@app.function(
    retries=modal.Retries(backoff_coefficient=2.0, initial_delay=5.0, max_retries=3),
    max_containers=50,
)
def extract_pdf(paper_data):
    """Extracts text from a PDF and attaches metadata."""
    if not isinstance(paper_data, dict):
        # get_pdf_url may have returned a RemoteError; skip silently.
        return []

    pdf_url = paper_data.get("pdf_url")
    if pdf_url is None:
        return []

    logging.getLogger("pypdf").setLevel(logging.ERROR)

    loader = PyPDFLoader(
        pdf_url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ask-fsdl-etl/1.0)"},
    )

    try:
        documents = loader.load_and_split()
    except Exception as e:
        print(f"failed to load PDF {pdf_url}: {type(e).__name__}: {e}")
        return []

    documents = [document.model_dump() for document in documents]
    for document in documents:
        document["text"] = (
            document["page_content"].encode("utf-8", errors="replace").decode()
        )
        document.pop("page_content", None)

    if "arxiv" in pdf_url.lower():
        arxiv_id = extract_arxiv_id_from_url(pdf_url)
        metadata = fetch_arxiv_metadata(arxiv_id)
        if metadata is None:
            metadata = {"title": paper_data.get("title")}
    else:
        metadata = {"title": paper_data.get("title")}

    documents = annotate_endmatter(documents)

    for document in documents:
        document["metadata"]["source"] = paper_data.get("url") or pdf_url
        document["metadata"] |= metadata
        title = document["metadata"].get("title")
        page = document["metadata"].get("page")
        if title:
            document["metadata"]["full-title"] = f"{title} - p{page}"

    documents = etl.shared.enrich_metadata(documents)
    return documents


@app.function()
def fetch_papers(collection_name="all-content"):
    """Fetches papers from the LLM Lit Review, https://tfs.ai/llm-lit-review."""
    client = docstore.connect()

    collection = client.get_database("llm-lit-review").get_collection(collection_name)

    # Papers flagged as having a PDF.
    query = {"properties.PDF?.checkbox": {"$exists": True, "$eq": True}}

    projection = {
        "properties.Name.title.plain_text": 1,
        "properties.Link.url": 1,
        "properties.Tags.multi_select.name": 1,
    }

    documents = list(collection.find(query, projection))
    if not documents:
        print(
            f"warning: no papers found in llm-lit-review.{collection_name} "
            f"matching {query}"
        )
        return []

    papers = []
    for doc in documents:
        props = doc.get("properties", {})
        try:
            title = props["Name"]["title"][0]["plain_text"]
            url = props["Link"]["url"]
        except (KeyError, IndexError) as e:
            print(f"skipping malformed record {doc.get('_id')}: {e}")
            continue

        paper = {
            "title": title,
            "url": url,
            "tags": [
                tag["name"]
                for tag in props.get("Tags", {}).get("multi_select", [])
            ],
        }
        papers.append(paper)

    if not papers:
        print("warning: no well-formed papers extracted")
    return papers


@app.function()
def get_pdf_url(paper_data):
    """Resolves a PDF URL for one paper.

    If no PDF can be found, sets pdf_url to None; extract_pdf skips those.
    """
    url = paper_data["url"]
    url_lower = url.lower()
    pdf_url = None

    if url.strip("#/").lower().endswith(".pdf"):
        pdf_url = url
    elif "arxiv.org" in url_lower:
        arxiv_id = extract_arxiv_id_from_url(url)
        if arxiv_id is not None:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    elif "aclanthology.org" in url_lower:
        pdf_url = url.strip("/") + ".pdf"

    paper_data["pdf_url"] = pdf_url
    return paper_data


def fetch_arxiv_metadata(arxiv_id):
    """Looks up title and last-updated date for an arXiv paper.

    Returns a dict with keys 'arxiv_id', 'title', 'date', or None if the
    lookup fails (rate limit, unknown ID, network issue).
    """
    if arxiv_id is None:
        return None

    client = arxiv.Client(page_size=1, delay_seconds=5, num_retries=5)
    search_query = arxiv.Search(id_list=[arxiv_id], max_results=1)

    try:
        result = next(client.results(search_query))
    except (ConnectionResetError, StopIteration) as e:
        print(f"arxiv lookup failed for {arxiv_id}: {type(e).__name__}: {e}")
        return None

    return {
        "arxiv_id": arxiv_id,
        "title": result.title,
        "date": result.updated.isoformat() if result.updated else None,
    }


def annotate_endmatter(pages, min_pages=6):
    """Heuristic for flagging reference sections."""
    out, after_references = [], False
    for idx, page in enumerate(pages):
        content = page["text"].lower()
        if idx >= min_pages and ("references" in content or "bibliography" in content):
            after_references = True
        page["metadata"]["is_endmatter"] = after_references
        out.append(page)
    return out


# New-style arXiv IDs: 2205.11916, 2205.11916v2.
# Old-style: quant-ph/0504081, hep-th/9901001.
_ARXIV_NEW = r"\d{4}\.\d{4,5}(?:v\d+)?"
_ARXIV_OLD = r"[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?"
_ARXIV_ID = re.compile(
    rf"(?:arxiv\.org/(?:abs|pdf)/)({_ARXIV_NEW}|{_ARXIV_OLD})",
    re.IGNORECASE,
)


def extract_arxiv_id_from_url(url):
    """Extracts an arXiv ID from a URL. Returns None if not present."""
    match = _ARXIV_ID.search(url)
    return match.group(1) if match else None
