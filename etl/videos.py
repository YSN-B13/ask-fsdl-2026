from youtube_transcript_api import YouTubeTranscriptApi
import etl.shared
import requests
import modal
import json


# extend the shared image with YouTube-handling dependencies
image = (
    etl.shared.base_image
    .pip_install(
        "youtube-transcript-api>=1.0",
        "requests>=2.32",
    )
    .add_local_python_source("vecstore", "docstore", "utils", "prompts", "etl")
)

app = modal.App(
    name="etl-videos",
    image=image,
    secrets=[
        modal.Secret.from_name("mongodb-fsdl"),
    ],
)


@app.local_entrypoint()
def main(json_path="data/videos.json", collection=None, db=None):
    """Runs the YouTube ETL pipeline.

    modal run --env dev etl/videos.py --json-path /path/to/json
    """
    with open(json_path) as f:
        video_infos = json.load(f)

    documents = etl.shared.unchunk(
        extract_subtitles.map(video_infos, return_exceptions=True)
    )

    with etl.shared.app.run():
        chunked_documents = etl.shared.chunk_into(documents, 10)
        list(
            etl.shared.add_to_document_db.map(
                chunked_documents, kwargs={"db": db, "collection": collection}
            )
        )


@app.function(
    retries=modal.Retries(max_retries=3, backoff_coefficient=2.0, initial_delay=5.0)
)
def extract_subtitles(video_info):
    """Extracts chapters + transcripts for one video and returns documents."""
    video_id = video_info["id"]
    video_title = video_info["title"]

    subtitles = get_transcript(video_id)
    chapters = get_chapters(video_id)

    if not chapters:
        # Videos without chapter metadata still produce one document
        # covering the whole transcript.
        chapters = [{"title": "Full video", "time": 0}]

    chapters = add_transcript(chapters, subtitles)
    return create_documents(chapters, video_id, video_title)


def get_transcript(video_id):
    """Fetches the transcript for a video as a list of dicts.

    youtube-transcript-api 1.x returns Snippet objects; we convert them back
    to plain dicts so the rest of this module stays unchanged.
    """
    ytt = YouTubeTranscriptApi()
    transcript = ytt.fetch(video_id)
    return [
        {"text": s.text, "start": s.start, "duration": s.duration}
        for s in transcript.snippets
    ]


def get_chapters(video_id):
    """Fetches chapter metadata from yt.lemnoslife.com.

    Returns [] if the lookup fails — the caller falls back to treating
    the whole video as one chapter.
    """
    base_url = "https://yt.lemnoslife.com"
    try:
        response = requests.get(
            base_url + "/videos",
            params={"id": video_id, "part": "chapters"},
            timeout=30,
        )
        response.raise_for_status()
        items = response.json().get("items") or []
        if not items:
            return []
        chapters = items[0].get("chapters", {}).get("chapters", [])
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"failed to fetch chapters for {video_id}: {e}")
        return []

    for chapter in chapters:
        chapter.pop("thumbnails", None)

    return chapters


def add_transcript(chapters, subtitles):
    """Attaches the transcript text to each chapter."""
    for ii, chapter in enumerate(chapters):
        next_chapter = chapters[ii + 1] if ii < len(chapters) - 1 else {"time": 1e10}
        chapter["text"] = " ".join(
            seg["text"]
            for seg in subtitles
            if chapter["time"] <= seg["start"] < next_chapter["time"]
        )
    return chapters


def create_documents(chapters, video_id, video_title):
    """Converts chapter dicts into documents ready for the document DB."""
    base_url = f"https://www.youtube.com/watch?v={video_id}"
    documents = []

    for chapter in chapters:
        text = chapter["text"].strip()
        if not text:
            continue
        url = f"{base_url}&t={chapter['time']}s"
        documents.append({
            "text": text,
            "metadata": {
                "source": url,
                "title": video_title,
                "chapter-title": chapter["title"],
                "full-title": f"{video_title} - {chapter['title']}",
            },
        })

    return etl.shared.enrich_metadata(documents)

