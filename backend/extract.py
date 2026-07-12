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
import re
import base64
import asyncio

import httpx

from .config import (
    OPENROUTER_API_URL, VISION_MODEL, WHISPER_MODEL, OLLAMA_NUM_CTX,
    RERANK_DOC_CHUNK_CHARS, RERANK_DOC_TOP_CHUNKS, RERANK_DOC_MAX_CHUNKS, RERANK_DOC_TIMEOUT,
)
from .rerank import rerank

# Two decoupled caps:
#  - MAX_EXTRACT_CHARS: how much text we RETAIN per file (the reranker chooses its
#    top chunks from anywhere in this, so it's "the whole document" for realistic files).
#  - MAX_INJECT_CHARS: how much we ever put in the prompt WITHOUT rerank selection
#    (small files injected whole; the reranker-down fallback). Bounds model context so
#    raising the extract cap can't blow it — degraded mode is never worse than before.
MAX_EXTRACT_CHARS = 300000   # ~150 pages; tune up for bigger docs (also bump RERANK_DOC_MAX_CHUNKS)
MAX_INJECT_CHARS = 40000     # prior whole-file cap, kept as the non-reranked ceiling

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
    """Cap RETAINED text (what the reranker gets to choose from)."""
    text = text or ""
    if len(text) > MAX_EXTRACT_CHARS:
        return text[:MAX_EXTRACT_CHARS].rstrip() + f"\n…[truncated at {MAX_EXTRACT_CHARS} chars]"
    return text


def _cap_inject(text: str) -> str:
    """Cap text injected WITHOUT rerank selection (small files / reranker-down fallback)."""
    text = text or ""
    if len(text) > MAX_INJECT_CHARS:
        return text[:MAX_INJECT_CHARS].rstrip() + f"\n…[truncated at {MAX_INJECT_CHARS} chars]"
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


_ATTACH_LABELS = {"image": "IMAGE (described by a vision model)",
                  "audio": "AUDIO (transcribed)", "error": "ATTACHMENT (error)"}


def _wrap_blocks(blocks) -> str:
    return (
        "The user attached the following file(s); use them as context for the question.\n\n"
        + "\n\n".join(blocks)
        + "\n\n"
    )


def _block(label: str, filename: str, text: str) -> str:
    return f"=== ATTACHED {label}: {filename} ===\n{text}\n=== END: {filename} ==="


def _chunk_text(text: str, size: int) -> list:
    """Split text into ~`size`-char chunks on paragraph boundaries.

    Paragraphs are packed greedily so semantic units stay together; a single
    oversized paragraph is hard-split.
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(p) > size:
            if cur:
                chunks.append(cur); cur = ""
            for i in range(0, len(p), size):
                chunks.append(p[i:i + size])
            continue
        if cur and len(cur) + len(p) + 2 > size:
            chunks.append(cur); cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


async def _relevant_text(att: dict, query: str):
    """Return (text_to_inject, reranked) for one attachment given the query.

    Large attachments are chunked and trimmed to the most relevant chunks; small
    ones (or any failure/disable) fall back to the whole text — never worse.
    """
    text = att.get("text", "") or ""
    if not query or att.get("kind") == "error" or not text.strip():
        return _cap_inject(text), False
    chunks = _chunk_text(text, RERANK_DOC_CHUNK_CHARS)
    if len(chunks) <= RERANK_DOC_TOP_CHUNKS:
        return text, False  # already small enough (≤ TOP_CHUNKS × CHUNK_CHARS) — inject whole
    pool = chunks[:RERANK_DOC_MAX_CHUNKS]  # bound the rerank request size on very large docs
    order = await rerank(query, pool, top_k=RERANK_DOC_TOP_CHUNKS, timeout=RERANK_DOC_TIMEOUT)
    if not order:
        # reranker disabled/unavailable/timed out — inject a BOUNDED head, never the full doc
        return _cap_inject(text), False
    keep = sorted(order)  # preserve original document order among the selected chunks
    excerpt = "\n\n…\n\n".join(pool[i] for i in keep)
    return excerpt, True


def format_attachments(attachments) -> str:
    """Render whole extracted attachment text as a prompt block (query-agnostic).

    Used as the fallback when no query is available; the query-aware, reranked
    path is build_attachment_context() below.
    """
    if not attachments:
        return ""
    blocks = [
        _block(_ATTACH_LABELS.get(a.get("kind"), "DOCUMENT"), a.get("filename", "file"), _cap_inject(a.get("text", "")))
        for a in attachments
    ]
    return _wrap_blocks(blocks)


async def build_attachment_context(attachments, query: str = "") -> str:
    """Query-aware attachment rendering: rerank each large file's chunks down to the
    ones most relevant to `query`, keeping small files whole. Falls back to
    format_attachments() behavior (whole text) when there's no query or the
    reranker is unavailable.
    """
    if not attachments:
        return ""
    if not query:
        return format_attachments(attachments)
    blocks = []
    for a in attachments:
        base = _ATTACH_LABELS.get(a.get("kind"), "DOCUMENT")
        text, reranked = await _relevant_text(a, query)
        label = f"{base} — most relevant excerpts" if reranked else base
        blocks.append(_block(label, a.get("filename", "file"), text))
    return _wrap_blocks(blocks)
