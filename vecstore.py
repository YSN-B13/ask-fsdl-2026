"""
Utilities for creating and using vector indexes.
"""
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from utils import pretty_log
from pathlib import Path


INDEX_NAME = "gemini-embedding-fsdl"
VECTOR_DIR = Path("/vectors")


def connect_to_vector_index(index_name: str, embedding_engine):
    """Loads an existing FAISS index from the volume."""
    return FAISS.load_local(
        str(VECTOR_DIR),
        embedding_engine,
        index_name,
        allow_dangerous_deserialization=True,
    )


def get_embedding_engine(model="gemini-embedding-001", **kwargs):
    """Retrieves a Gemini embedding engine."""
    return GoogleGenerativeAIEmbeddings(model=model, **kwargs)


def create_vector_index(index_name, embedding_engine, documents, metadatas):
    """Creates a vector index that offers similarity search."""
    removed = False
    for file in VECTOR_DIR.glob(f"{index_name}.*"):
        file.unlink()
        removed = True
    if removed:
        pretty_log("existing index wiped")
    # Build the new index from the provided documents.
    index = FAISS.from_texts(
        texts=documents,
        embedding=embedding_engine,
        metadatas=metadatas,
    )
    # Persist to the volume so it survives container restarts.
    index.save_local(str(VECTOR_DIR), index_name)
    pretty_log(f"vector index saved as {index_name}")
    return index
