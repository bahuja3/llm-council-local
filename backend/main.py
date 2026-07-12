"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio

from . import storage
from .council import run_full_council, generate_conversation_title, stage1_collect_responses, stage2_collect_rankings, stage3_synthesize_final, calculate_aggregate_rankings, build_history
from .web_search import augment_query
from .routing import route_council, stage2_is_concise
from .extract import extract_file, build_attachment_context

app = FastAPI(title="LLM Council API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _warm_on_startup():
    """Pin the fast-council models resident in Ollama (LOCAL mode) — non-blocking."""
    import asyncio
    from .warmup import warm_council
    asyncio.create_task(warm_council())


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str
    fast: bool = False
    force_search: Optional[bool] = None
    attachments: Optional[List[Dict[str, Any]]] = None


class RenameConversationRequest(BaseModel):
    """Request to rename a conversation."""
    title: str


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations(q: str = ""):
    """List all conversations (metadata only), or search title + content when q is given."""
    if q.strip():
        return storage.search_conversations(q.strip())
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a conversation."""
    if storage.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    storage.delete_conversation(conversation_id)
    return {"status": "deleted", "id": conversation_id}


@app.patch("/api/conversations/{conversation_id}")
async def rename_conversation(conversation_id: str, request: RenameConversationRequest):
    """Rename a conversation."""
    if storage.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    storage.update_conversation_title(conversation_id, request.title)
    return {"status": "renamed", "id": conversation_id, "title": request.title}


@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """Extract text from uploaded files (documents / images / audio) for the council."""
    results = []
    for f in files:
        data = await f.read()
        results.append(await extract_file(f.filename or "file", data, f.content_type or ""))
    return {"attachments": results}


def _attachment_meta(attachments):
    """Keep only what the UI shows on the message (strip the extracted text)."""
    if not attachments:
        return None
    return [{"filename": a.get("filename"), "kind": a.get("kind"), "chars": a.get("chars")} for a in attachments]


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content, _attachment_meta(request.attachments))

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process (prior turns give context-aware follow-ups)
    history = build_history(conversation["messages"])
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content,
        fast=request.fast,
        force_search=request.force_search,
        history=history,
        attach_text=await build_attachment_context(request.attachments, request.content)
    )

    # Add assistant message with all stages (+ metadata for the routing indicator)
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result,
        metadata
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        try:
            # Add user message
            storage.add_user_message(conversation_id, request.content, _attachment_meta(request.attachments))

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Gated local web search: prepend fresh SearXNG context on
            # time-sensitive queries (degrades to plain query if SearXNG is down).
            query_for_models, search_meta = await augment_query(request.content, force=request.force_search)
            attach_text = await build_attachment_context(request.attachments, request.content)
            if attach_text:
                query_for_models = attach_text + query_for_models
            searched = bool(search_meta.get('searched') and search_meta.get('results', 0) > 0)

            # Per-seat routing: specialists by query signal, generalists fill the rest.
            models, chairman, signals = route_council(request.content, searched, request.fast)
            # Prior turns (context-aware follow-ups). conversation holds the messages
            # from before this turn's user message was appended above.
            history = build_history(conversation["messages"])

            # Stage 1: Collect responses
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(query_for_models, models, history=history)
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Stage 2: Collect rankings
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2_collect_rankings(query_for_models, stage1_results, models, concise=stage2_is_concise(signals))
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            stage_metadata = {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings, 'search': search_meta, 'council': models, 'chairman': chairman, 'fast': request.fast, 'signals': signals}
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': stage_metadata})}\n\n"

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(query_for_models, stage1_results, stage2_results, chairman, history=history)
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Save complete assistant message (+ metadata so the routing/search
            # indicator persists across reloads)
            storage.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result,
                stage_metadata
            )

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    import uvicorn
    # Loopback only: this is a personal local app with no auth — don't expose it to the LAN.
    uvicorn.run(app, host="127.0.0.1", port=8001)
