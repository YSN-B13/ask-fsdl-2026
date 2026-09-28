"""
Shared utilities for the ETL pipeline.
"""
from pymongo.errors import BulkWriteError
from pymongo import InsertOne
import docstore
import hashlib
import modal


# definition of our container image and app for deployment on Modal
# see app.py for more details
base_image  = (
    modal.Image.debian_slim(python_version="3.10")
    .pip_install("pymongo>=4.18.1")
)

image = base_image.add_local_python_source(
    "vecstore", "docstore", "utils", "prompts", "etl"
)

app = modal.App(
    name="etl-shared",
    image=image,
    secrets=[
        modal.Secret.from_name("mongodb-fsdl"),
    ]
)


@app.function()
def add_to_document_db(documents_json, collection=None, db=None):
    """Adds a collection of JSON documents to the database in batches.

    Uses ordered=False so a single duplicate _id doesn't abort the batch,
    and catches BulkWriteError to log partial failures without crashing.
    """
    collection = docstore.get_collection(collection, db)
    batch, CHUNK_SIZE = [], 250
    total_inserted = 0

    def flush(pending):
        nonlocal total_inserted
        if not pending:
            return
        try:
            result = collection.bulk_write(pending, ordered=False)
            total_inserted += result.inserted_count
        except BulkWriteError as e:
            total_inserted += e.details.get("nInserted", 0)
            print(f"bulk_write partial failure: {e.details.get('writeErrors', [])}")

    for document in documents_json:
        batch.append(InsertOne(document))
        if len(batch) >= CHUNK_SIZE:
            flush(batch)
            batch = []

    flush(batch)
    print(f"inserted {total_inserted} documents into {collection.full_name}")


def enrich_metadata(pages):
    """Add metadata fields: sha256 hash and an ignore flag."""
    for page in pages:
        m = hashlib.sha256()
        m.update(page["text"].encode("utf-8", "replace"))
        page["metadata"]["sha256"] = m.hexdigest()
        page["metadata"]["ignore"] = bool(page["metadata"].get("is_endmatter"))
    return pages


def chunk_into(items, n_chunks):
    """Splits `items` into n_chunks pieces, non-contiguously."""
    for ii in range(n_chunks):
        yield items[ii::n_chunks]


def unchunk(list_of_lists):
    """Recombines a list of lists into a single list.

    Skips items that aren't iterable — e.g. RemoteError objects returned
    by `map(..., return_exceptions=True)` when a call fails.
    """
    out = []
    for sublist in list_of_lists:
        if isinstance(sublist, BaseException):
            print(f"skipping failed batch: {type(sublist).__name__}: {sublist}")
            continue
        out.extend(sublist)
    return out
