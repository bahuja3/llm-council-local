"""Turn uploaded files into text for the council.

Everything an upload contains becomes text that gets injected into the council's
prompt (same idea as the web-search injection):
- documents: PDF (pypdf), DOCX (python-docx), or plain decode (txt/md/code/csv/json)
- images:    a local Ollama VISION model describes/OCRs the image
- audio:     local Whisper transcription (faster-whisper), lazy-loaded

Each extractor degrades gracefully — a failure returns an explanatory string
rather than raising, so one bad file can't break a request.
"""

import io
import base64
import asyncio

import httpx

from .config import OPENROUTER_API_URL, VISION_MODEL, WHISPER_MODEL, OLLAMA_NUM_CTX

MAX_CHARS = 40000  # cap injected text per file so we don't blow the context window

DOC_EXTS = {
    "txt", "md", "markdown", "csv", "tsv", "json", "yaml", "yml", "log",
    "py", "js", "ts", "jsx", "tsx", "java", "c", "h", "cpp", "go", "rs",
    "rb", "php", "sh", "sql", "html", "css",
}
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "heic"}
AUDIO_EXTS = {"mp3", "wav", "m4a", "flac", "ogg", "aac", "aiff", "aif", "mp4", "mov", "webm"}


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _truncate(text: str) -> str:
    text = text or ""
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS].rstrip() + f"\n…[truncated at {MAX_CHARS} chars]"
    return text


def _ollama_base() -> str:
    # LOCAL OPENROUTER_API_URL is http://localhost:11434/v1/chat/completions
    return OPENROUTER_API_URL.rsplit("/v1/", 1)[0]


# ---------------------------------------------------------------- documents ---

def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _extract_docx(data: bytes) -> str:
    import docx
    d = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in d.paragraphs).strip()


# ------------------------------------------------------------------- images ---

async def _describe_image(data: bytes) -> str:
    """Ask the local vision model to describe + transcribe the image."""
    b64 = base64.b64encode(data).decode()
    payload = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": "Describe this image in thorough detail, and transcribe any visible text verbatim.",
            "images": [b64],
        }],
        "stream": False,
        "keep_alive": 0,  # unload right after so the big vision model doesn't hog RAM
    }
    async with httpx.AsyncClient(timeout=600.0) as client:
        r = await client.post(_ollama_base() + "/api/chat", json=payload)
        r.raise_for_status()
        return (r.json().get("message", {}) or {}).get("content", "").strip()


# -------------------------------------------------------------------- audio ---

_whisper = None


def _transcribe_sync(data: bytes, filename: str) -> str:
    global _whisper
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return ("[audio not transcribed — faster-whisper isn't installed. "
                "Run `uv sync` (it's a dependency) and retry.]")
    if _whisper is None:
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

    import tempfile, os
    suffix = "." + (_ext(filename) or "audio")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        segments, _info = _whisper.transcribe(path)
        return " ".join(seg.text.strip() for seg in segments).strip()
    finally:
        os.unlink(path)


# --------------------------------------------------------------- dispatcher ---

async def extract_file(filename: str, data: bytes, content_type: str = "") -> dict:
    """Return {filename, kind, text, chars} for one uploaded file."""
    ext = _ext(filename)
    ct = content_type or ""
    try:
        if ext == "pdf" or ct == "application/pdf":
            kind, text = "document", _extract_pdf(data)
        elif ext == "docx" or "wordprocessingml" in ct:
            kind, text = "document", _extract_docx(data)
        elif ext in IMAGE_EXTS or ct.startswith("image/"):
            kind, text = "image", await _describe_image(data)
        elif ext in AUDIO_EXTS or ct.startswith(("audio/", "video/")):
            kind, text = "audio", await asyncio.to_thread(_transcribe_sync, data, filename)
        elif ext in DOC_EXTS or ct.startswith("text/"):
            kind, text = "document", data.decode("utf-8", errors="replace")
        else:
            kind, text = "document", data.decode("utf-8", errors="replace")
    except Exception as e:
        kind, text = "error", f"[could not extract '{filename}': {e}]"
    text = _truncate(text)
    return {"filename": filename, "kind": kind, "text": text, "chars": len(text)}


def format_attachments(attachments) -> str:
    """Render extracted attachment text as a prompt block prepended to the query."""
    if not attachments:
        return ""
    labels = {"image": "IMAGE (described by a vision model)",
              "audio": "AUDIO (transcribed)", "error": "ATTACHMENT (error)"}
    blocks = []
    for a in attachments:
        fn = a.get("filename", "file")
        label = labels.get(a.get("kind"), "DOCUMENT")
        blocks.append(f"=== ATTACHED {label}: {fn} ===\n{a.get('text', '')}\n=== END: {fn} ===")
    return (
        "The user attached the following file(s); use them as context for the question.\n\n"
        + "\n\n".join(blocks)
        + "\n\n"
    )
