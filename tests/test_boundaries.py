"""Bounds for the five local-app security leads."""

import sys
import tempfile
import types
import unittest
import uuid
from pathlib import Path

from backend import config, storage
from backend.http_guards import host_is_loopback


class HostAllowlistTests(unittest.TestCase):
    def test_loopback_names_are_allowed(self):
        for host in (
            "localhost",
            "localhost:8001",
            "127.0.0.1",
            "127.0.0.1:8001",
            "::1",
            "[::1]",
            "[::1]:8001",
        ):
            self.assertTrue(host_is_loopback(host), host)

    def test_rebinding_and_lan_names_are_rejected(self):
        for host in (
            "",
            None,
            "evil.example",
            "evil.example:8001",
            "localhost.evil.example",
            "127.0.0.1.evil.example",
            "0.0.0.0",
            "0.0.0.0:8001",
            "192.168.1.5:8001",
            "localhost:8001@evil.example",
            "localhost:abc",
        ):
            self.assertFalse(host_is_loopback(host), host)


class ConversationPathTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old = storage.DATA_DIR
        self.data = Path(self._tmpdir.name) / "conversations"
        self.data.mkdir()
        storage.DATA_DIR = str(self.data)
        self.outside = Path(self._tmpdir.name) / "outside.json"
        self.outside.write_text('{"secret": true}', encoding="utf-8")

    def tearDown(self):
        storage.DATA_DIR = self._old
        self._tmpdir.cleanup()

    def test_canonical_id_stays_in_the_data_directory(self):
        conversation_id = str(uuid.uuid4())
        created = storage.create_conversation(conversation_id)
        self.assertEqual(created["id"], conversation_id)
        path = Path(storage.get_conversation_path(conversation_id))
        self.assertEqual(path.parent, self.data.resolve())
        self.assertEqual(storage.get_conversation(conversation_id)["id"], conversation_id)
        self.assertTrue(storage.delete_conversation(conversation_id))
        self.assertIsNone(storage.get_conversation(conversation_id))

    def test_crafted_id_does_not_read_or_delete_outside(self):
        for crafted in ("../outside", "/etc/passwd", "..", "not-a-uuid", self.outside.name):
            self.assertIsNone(storage.get_conversation(crafted), crafted)
            self.assertFalse(storage.delete_conversation(crafted), crafted)
        self.assertTrue(self.outside.exists())
        self.assertIn("secret", self.outside.read_text(encoding="utf-8"))
        self.assertFalse(any(self.data.iterdir()))


class WhisperPinTests(unittest.TestCase):
    def test_revision_is_a_commit_not_a_branch(self):
        self.assertEqual(len(config.WHISPER_REVISION), 40)
        self.assertTrue(all(c in "0123456789abcdef" for c in config.WHISPER_REVISION))
        self.assertNotIn(config.WHISPER_REVISION, {"main", "master", "base"})

    def test_first_load_passes_the_pinned_revision(self):
        from backend import extract

        captured = {}

        class FakeModel:
            def __init__(self, model, **kwargs):
                captured["model"] = model
                captured["kwargs"] = kwargs

            def transcribe(self, path):
                class Segment:
                    text = "hello"

                return [Segment()], None

        module = types.ModuleType("faster_whisper")
        module.WhisperModel = FakeModel
        previous = sys.modules.get("faster_whisper")
        sys.modules["faster_whisper"] = module
        extract._whisper = None
        try:
            text = extract._transcribe_sync(b"not-audio", "note.wav")
        finally:
            extract._whisper = None
            if previous is None:
                sys.modules.pop("faster_whisper", None)
            else:
                sys.modules["faster_whisper"] = previous
        self.assertEqual(text, "hello")
        self.assertEqual(captured["model"], config.WHISPER_MODEL)
        self.assertEqual(captured["kwargs"]["revision"], config.WHISPER_REVISION)


class ApiGuardTests(unittest.TestCase):
    def setUp(self):
        from backend import warmup
        from backend.main import app
        from fastapi.testclient import TestClient

        warmup.WARM_ON_STARTUP = False
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_data = storage.DATA_DIR
        storage.DATA_DIR = self._tmpdir.name
        self._old_limits = (
            config.MAX_UPLOAD_BYTES,
            config.MAX_REQUEST_BYTES,
            config.MAX_MESSAGE_BODY_BYTES,
            config.MAX_UPLOAD_FILES,
        )
        self.client = TestClient(app, base_url="http://127.0.0.1")

    def tearDown(self):
        storage.DATA_DIR = self._old_data
        (
            config.MAX_UPLOAD_BYTES,
            config.MAX_REQUEST_BYTES,
            config.MAX_MESSAGE_BODY_BYTES,
            config.MAX_UPLOAD_FILES,
        ) = self._old_limits
        self._tmpdir.cleanup()

    def test_health_and_conversation_round_trip_on_loopback(self):
        health = self.client.get("/", headers={"Host": "localhost:8001"})
        self.assertEqual(health.status_code, 200)
        created = self.client.post("/api/conversations", json={})
        self.assertEqual(created.status_code, 200, created.text)
        conversation_id = created.json()["id"]
        fetched = self.client.get(f"/api/conversations/{conversation_id}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["messages"], [])

    def test_vite_page_origins_can_read_the_api(self):
        for origin in ("http://127.0.0.1:5173", "http://localhost:5173"):
            response = self.client.get("/api/conversations", headers={"Origin": origin})
            self.assertEqual(response.status_code, 200, origin)
            self.assertEqual(response.headers.get("access-control-allow-origin"), origin)

    def test_non_loopback_host_cannot_read_conversations(self):
        response = self.client.get("/api/conversations", headers={"Host": "evil.example:8001"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("title", response.text)

    def test_crafted_conversation_id_is_not_found(self):
        response = self.client.get("/api/conversations/..%2Foutside")
        self.assertEqual(response.status_code, 404)

    def test_oversized_upload_is_rejected_before_extraction(self):
        from backend import main

        config.MAX_UPLOAD_BYTES = 8
        config.MAX_REQUEST_BYTES = 1024
        called = []

        async def explode(*_args, **_kwargs):
            called.append(True)
            raise AssertionError("extract_file should not run")

        original = main.file_extract.extract_file
        main.file_extract.extract_file = explode
        try:
            response = self.client.post(
                "/api/upload",
                files={"files": ("note.txt", b"0123456789abcdef", "text/plain")},
            )
        finally:
            main.file_extract.extract_file = original
        self.assertEqual(response.status_code, 413)
        self.assertEqual(called, [])

    def test_long_message_text_is_rejected_before_storage(self):
        from backend import extract

        created = self.client.post("/api/conversations", json={})
        conversation_id = created.json()["id"]
        original = extract.MAX_EXTRACT_CHARS
        extract.MAX_EXTRACT_CHARS = 5
        try:
            response = self.client.post(
                f"/api/conversations/{conversation_id}/message",
                json={"content": "hello world"},
            )
        finally:
            extract.MAX_EXTRACT_CHARS = original
        self.assertEqual(response.status_code, 413)
        self.assertEqual(storage.get_conversation(conversation_id)["messages"], [])

    def test_missing_stream_stays_a_404(self):
        missing = "00000000-0000-4000-8000-000000000000"
        response = self.client.post(
            f"/api/conversations/{missing}/message/stream",
            json={"content": "hi"},
        )
        self.assertEqual(response.status_code, 404)

    def test_oversized_message_is_rejected_before_the_council(self):
        created = self.client.post("/api/conversations", json={})
        conversation_id = created.json()["id"]
        config.MAX_MESSAGE_BODY_BYTES = 64
        response = self.client.post(
            f"/api/conversations/{conversation_id}/message",
            json={"content": "x" * 200},
        )
        self.assertEqual(response.status_code, 413)
        stored = storage.get_conversation(conversation_id)
        self.assertEqual(stored["messages"], [])

    def test_small_upload_still_reaches_extraction(self):
        from backend import main

        async def fake_extract(filename, data, content_type=""):
            return {"filename": filename, "kind": "document", "text": data.decode(), "chars": len(data)}

        original = main.file_extract.extract_file
        main.file_extract.extract_file = fake_extract
        try:
            response = self.client.post(
                "/api/upload",
                files={"files": ("note.txt", b"hello", "text/plain")},
            )
        finally:
            main.file_extract.extract_file = original
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["attachments"][0]["text"], "hello")


if __name__ == "__main__":
    unittest.main()
