"""
Builds a CLI, Webhook, and Gradio app for Q&A on the Full Stack corpus.
For details on corpus construction, see the accompanying notebook.
"""
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import ChatGoogleGenerativeAI
from fastapi.responses import RedirectResponse
from gradio.routes import App
from utils import pretty_log
from fastapi import FastAPI
import gradio as gr
import vecstore
import docstore
import prompts
import modal
import json
import os


# definition of our container image for jobs on Modal
# Modal gets really powerful when you start using multiple images!
image = (
    modal.Image.debian_slim(python_version="3.10")
    .pip_install(  # and we install the following packages:
        "langchain>=1.0.0",
        "langchain-google-genai>=4.0.0",
        "langchain-classic>=1.0",          # ← provides create_stuff_documents_chain
        "langchain-community>=0.3",        # ← provides FAISS vector store
        "langchain-text-splitters>=0.3",    # ← needed for RecursiveCharacterTextSplitter
        # 🦜🔗: a framework for building apps with LLMs, and the Google Gemini integration
        "faiss-cpu>=1.15.1",
        # vector storage and similarity search
        "pymongo>=4.18.1",
        # python client for MongoDB, our data persistence solution
        "gradio>=6.0.0",
        # simple web UIs in Python, from 🤗
    )
    # we make our local modules available to the container
    .add_local_python_source("vecstore", "docstore", "utils", "prompts")
)

VECTOR_DIR = vecstore.VECTOR_DIR
vector_storage = modal.Volume.from_name("vector-vol", create_if_missing=True)

app = modal.App(
    name="askfsdl-backend",
    image=image,
    secrets=[
        # this is where we add API keys, passwords, and URLs, which are stored on Modal
        modal.Secret.from_name("mongodb-fsdl"),
        modal.Secret.from_name("openai-api-key-fsdl"),
    ],
    volumes={
        str(VECTOR_DIR): vector_storage,
    },
)


@app.function()
@modal.fastapi_endpoint(method="GET")
def web(query: str, request_id: str | None = None):
    """Exposes our Q&A chain for queries via a web endpoint."""
    if request_id:
        pretty_log(f"handling request with client-provided id: {request_id}")

    answer = qanda.remote(
        query,
        request_id=request_id,
    )
    return {"answer": answer}


@app.function(min_containers=1)
def qanda(query: str, request_id: str | None = None) -> str:
    """Runs sourced Q&A for a query using LangChain.
    Arguments:
        query: The query to run Q&A on.
        request_id: A unique identifier for the request.
        with_logging: If True, logs the interaction to Gantry.
    """
    embedding_engine = vecstore.get_embedding_engine()

    pretty_log("connecting to vector storage")
    vector_index = vecstore.connect_to_vector_index(
        vecstore.INDEX_NAME, embedding_engine
    )
    pretty_log("connected to vector storage")
    pretty_log(f"found {vector_index.index.ntotal} vectors to search over")

    pretty_log(f"running on query: {query}")
    pretty_log("selecting sources by similarity to query")
    sources_and_scores = vector_index.similarity_search_with_score(query, k=3)
    if not sources_and_scores:
        pretty_log("no sources found for query")
        return "I could not find any relevant sources to answer that question."
    sources, _scores = zip(*sources_and_scores)

    pretty_log("running query against Q&A chain")

    llm = ChatGoogleGenerativeAI(model="gemini-3.7-flash", temperature=0, max_output_tokens=256)
    chain = create_stuff_documents_chain(
        llm,
        prompt=prompts.main,
        document_variable_name="sources",
    )

    result = chain.invoke({"input": query, "sources": sources})
    answer = result if isinstance(result, str) else result.get("output_text", str(result))

    if request_id:
        pretty_log(f"answered request {request_id}")

    return answer


@app.function(cpu=8.0) # use more cpu for vector storage creation
def create_vector_index(collection: str | None = None, db: str | None = None):
    """Creates a vector index for a collection in the document database."""
    pretty_log("connecting to document store")
    db = docstore.get_database(db)
    pretty_log(f"connected to database {db.name}")

    collection = docstore.get_collection(collection, db)
    pretty_log(f"collecting documents from {collection.name}")
    docs = docstore.get_documents(collection, db)

    pretty_log("splitting into bite-size chunks")
    _ids, texts, metadatas = prep_documents_for_vector_storage(docs)
    pretty_log(f"prepared {len(texts)} chunks")

    pretty_log(f"sending to vector index {vecstore.INDEX_NAME}")
    embedding_engine = vecstore.get_embedding_engine(task_type="retrieval_document")
    vector_index = vecstore.create_vector_index(
        vecstore.INDEX_NAME, embedding_engine, texts, metadatas
    )
    pretty_log(f"vector index {vecstore.INDEX_NAME} created")


def prep_documents_for_vector_storage(documents):
    """Prepare documents from document store for embedding and vector storage.
    Documents are split into chunks so that they can be used with sourced Q&A.
    Arguments:
        documents: A list of LangChain.Documents with text, metadata, and a hash ID.
    """
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500, 
        chunk_overlap=100
    )
    ids, texts, metadatas = [], [], []
    for document in documents:
        text, metadata = document["text"], document["metadata"]
        doc_texts = text_splitter.split_text(text)
        if not doc_texts:
            continue
        doc_metadatas = [metadata] * len(doc_texts)
        sha = metadata.get("sha256", "")
        ids += [sha] * len(doc_texts)
        texts += doc_texts
        metadatas += doc_metadatas

    return ids, texts, metadatas


@app.function()
def drop_docs(collection: str | None = None, db: str | None = None):
    """Drops a collection from the document storage."""
    docstore.drop(collection, db)


@app.function()
def cli(query: str):
    """Run a one-shot query against the Q&A chain, for local testing."""
    answer = qanda.remote(query)
    pretty_log("🦜 ANSWER 🦜")
    print(answer)


web_app = FastAPI(docs_url=None)


@web_app.get("/")
async def root():
    return {"message": "See /gradio for the dev UI."}


@web_app.get("/docs", response_class=RedirectResponse, status_code=308)
async def redirect_docs():
    """Redirects to the Gradio subapi docs."""
    return "/gradio/docs"


@app.function()
@modal.asgi_app()
def fastapi_app():
    """A simple Gradio interface for debugging."""

    def query_with_sources(question: str) -> str:
        return qanda.remote(question)

    interface = gr.Interface(
        fn=query_with_sources,
        inputs=gr.TextArea(
            label="Question",
            value="What is zero-shot chain-of-thought prompting?",
            show_label=True,
        ),
        outputs=gr.TextArea(
            label="Answer",
            value="The answer will appear here.",
            show_label=True,
        ),
        title="Ask Questions About The Full Stack.",
        description="Get answers with sources from an LLM.",
        examples=[
            "What is zero-shot chain-of-thought prompting?",
            "Would you rather fight 100 LLaMA-sized GPT-4s or 1 GPT-4-sized LLaMA?",
            "What are the differences in capabilities between GPT-3 davinci and GPT-3.5 code-davinci-002?",
            "What is PyTorch? How can I decide whether to choose it over TensorFlow?",
            "Is it cheaper to run experiments on cheap GPUs or expensive GPUs?",
            "How do I recruit an ML team?",
            "What is the best way to learn about ML?",
        ],
    )

    return gr.mount_gradio_app(
        web_app,
        interface,
        path="/gradio",
        theme=gr.themes.Default(radius_size="none", text_size="lg"),
        app_kwargs={"docs_url": "/gradio/docs", "title": "ask-FSDL"},
    )
