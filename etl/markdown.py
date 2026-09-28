"""
ETL for Markdown-format lecture notes from the Full Stack Deep Learning course.

Fetches lecture notes from GitHub-hosted markdown files, splits each into
per-heading documents, and inserts them into the document store via
etl.shared.add_to_document_db.
"""
from smart_open import open as smart_open
from slugify import slugify
import etl.shared
import mistune
import modal
import json


# extend the shared image with markdown-handling dependencies
image = (
    etl.shared.base_image
    .pip_install(
        "mistune==2.0.5",
        "python-slugify>=8.0.1",
        "smart-open[http]>=7.0",
    )
    .add_local_python_source("vecstore", "docstore", "utils", "prompts", "etl")
)

app = modal.App(
    name="etl-markdown",
    image=image,
    secrets=[
        modal.Secret.from_name("mongodb-fsdl"),
    ],
)


@app.local_entrypoint()
def main(json_path="data/lectures-2022.json", collection=None, db=None):
    """Runs the markdown ETL pipeline.

    modal run --env dev etl/markdown.py --json-path /path/to/json
    """
    with open(json_path) as f:
        markdown_corpus = json.load(f)

    website_url = markdown_corpus["website_url_base"]
    md_url = markdown_corpus["md_url_base"]
    lectures = markdown_corpus["lectures"]

    # Each lecture produces multiple documents (one per heading).
    documents = etl.shared.unchunk(
        to_documents.map(
            lectures,
            kwargs={"website_url": website_url, "md_url": md_url},
            return_exceptions=True,
        )
    )

    with etl.shared.app.run():
        chunked_documents = etl.shared.chunk_into(documents, 10)
        list(
            etl.shared.add_to_document_db.map(
                chunked_documents, kwargs={"db": db, "collection": collection}
            )
        )


@app.function()
def to_documents(lecture, website_url, md_url):
    """Fetches one lecture's markdown and splits it into per-heading documents."""
    title = lecture["title"]
    title_slug = lecture["slug"]
    markdown_url = f"{md_url}/{title_slug}/index.md"
    lecture_website_url = f"{website_url}/{title_slug}"

    text = get_text_from(markdown_url)
    if not text:
        return []

    headings, heading_slugs = get_target_headings_and_slugs(text)
    subtexts = split_by_headings(text, headings)

    # Prepend an empty heading so the preamble becomes the first document.
    headings = [""] + headings
    heading_slugs = [""] + heading_slugs

    sources = [f"{lecture_website_url}#{slug}" for slug in heading_slugs]
    metadatas = [
        {
            "source": source,
            "heading": heading,
            "title": title,
            "full-title": f"{title} - {heading}" if heading else title,
        }
        for heading, source in zip(headings, sources)
    ]

    documents = [
        {"text": subtext, "metadata": metadata}
        for subtext, metadata in zip(subtexts, metadatas)
    ]

    return etl.shared.enrich_metadata(documents)


def get_text_from(url):
    """Fetches the contents of a markdown file from a URL."""
    from smart_open import open as smart_open

    try:
        with smart_open(url) as f:
            return f.read()
    except Exception as e:
        print(f"failed to fetch {url}: {type(e).__name__}: {e}")
        return ""


def get_target_headings_and_slugs(text):
    """Pulls level-2 headings out of a markdown document and slugifies them."""
    import mistune
    from slugify import slugify

    markdown_parser = mistune.create_markdown(renderer="ast")
    parsed_text = markdown_parser(text)

    heading_objects = [obj for obj in parsed_text if obj["type"] == "heading"]
    h2_objects = [obj for obj in heading_objects if obj["level"] == 2]

    # Skip the "description: " pseudo-heading that appears in some lecture pages.
    targets = [
        obj
        for obj in h2_objects
        if not obj["children"][0]["text"].startswith("description: ")
    ]
    target_headings = [tgt["children"][0]["text"] for tgt in targets]
    heading_slugs = [slugify(h) for h in target_headings]
    return target_headings, heading_slugs


def split_by_headings(text, headings):
    """Splits a markdown document by level-1 headings, preserving the preamble."""
    texts = []
    for heading in reversed(headings):
        marker = "# " + heading
        if marker not in text:
            # Heading not found in the body — skip rather than crash.
            continue
        text, section = text.split(marker, 1)
        texts.append(f"## {heading}{section}")
    texts.append(text)
    return list(reversed(texts))
