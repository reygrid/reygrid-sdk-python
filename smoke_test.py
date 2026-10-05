"""Smoke test for the ReyGrid Python SDK using httpx MockTransport."""
import json
import asyncio
import httpx
from reygrid import ReyGrid


def make_transport(stream_mode: bool = False, base: str = "https://reygrid.test"):
    """Mock every endpoint the SDK uses."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        # strip the configured base path so internal routes match cleanly
        if base and not path.startswith("/"):
            path = "/" + path

        # ---- SSE streaming response ----
        if stream_mode and method == "POST" and path.endswith("/chat"):
            sse_chunks = (
                'data: {"success":true,"delta":{"reply":{"content":"Hello"}}}\n\n'
                'data: {"delta":{"reply":{"content":" there"}}}\n\n'
                'data: {"delta":{"reply":{"content":"!"}}}\n\n'
                'data: {"delta":{"reply":{"content":""},"finish_reason":"stop"},"usage":{"credits":0.001}}\n\n'
                "data:\n\n"
            )
            return httpx.Response(
                200,
                text=sse_chunks,
                headers={"Content-Type": "text/event-stream"},
            )

        if method == "POST" and path.endswith("/chat"):
            return httpx.Response(200, json={
                "success": True, "conversationId": "conv-1", "userId": "u-1",
                "messageId": "m-1",
                "output": {"reply": {"id": "r-1", "content": "Hello there!"},
                           "finish_reason": "stop"},
                "usage": {"credits": 0.005},
            })

        if path == "/ping":
            return httpx.Response(200, json={
                "success": True, "status": "UP", "service": "reygrid",
                "version": "1.0.1",
                "metadata": {"uptime": 42, "timestamp": "2026-08-27T10:00:00Z"},
            })

        if path == "/validate":
            return httpx.Response(200, json={
                "success": True, "valid": True,
                "usage": {"total": 1337, "quotaLimit": 5000},
            })

        if path.endswith("/conversations") and method == "GET":
            return httpx.Response(200, json={
                "success": True,
                "conversations": [{"conversationId": "c1", "userId": "u1",
                                   "messagesCount": 3, "createdAt": "2026-08-27T10:00:00Z"}],
                "pagination": {"totalPages": 1, "currentPage": 1, "pagingCounter": 1,
                               "hasNextPage": False, "totalConversations": 1},
            })

        if "/messages" in path and method == "GET":
            return httpx.Response(200, json={
                "success": True, "conversationId": "c1",
                "messages": [{"id": "m1", "role": "assistant", "content": "hi",
                              "createdAt": "2026-08-27T10:00:00Z"}],
                "pagination": {"totalPages": 1, "currentPage": 1, "pagingCounter": 1,
                               "hasNextPage": False, "totalMessages": 1},
            })

        if method == "DELETE" and "/messages/" in path:
            return httpx.Response(200, json={
                "success": True, "deletedMessages": {"count": 1},
            })

        if method == "DELETE" and "/conversations/" in path and "/messages/" not in path:
            return httpx.Response(200, json={
                "success": True, "deletedMessages": {"count": 3},
            })

        if "/tool/cancel/" in path:
            return httpx.Response(200, json={
                "success": True, "canceled": True,
            })

        if path == "/bad":
            return httpx.Response(401, json={
                "error": "Unauthorized", "code": "AUTH_REQUIRED",
            })

        return httpx.Response(404, json={
            "success": False,
            "error": {"code": "NOT_FOUND", "message": "nope"},
        })

    return handler


def test_sync():
    handler = make_transport(stream_mode=False)
    sync_client = httpx.Client(transport=httpx.MockTransport(handler))
    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = ReyGrid(api_key="x", base_url="https://reygrid.test", httpx_client=sync_client, httpx_async_client=async_client)

    # Ping
    ping = client.ping()
    assert ping.status == "UP", ping
    assert ping.metadata.uptime == 42
    print("  ✅ ping()")

    # Validate / usage
    usage = client.get_usage()
    assert usage.total == 1337 and usage.quotaLimit == 5000
    print("  ✅ get_usage()")

    # Chat
    chat = client.chat("agent-1", "hi")
    assert chat.output.reply.content == "Hello there!"
    assert chat.usage.credits == 0.005
    print("  ✅ chat()")

    # List conversations
    convos = client.list_conversations("agent-1")
    assert convos.conversations[0].messagesCount == 3
    print("  ✅ list_conversations()")

    # Paginator (sync)
    all_convos = [c for page in client.paginate_conversations("agent-1") for c in page.data]
    assert len(all_convos) == 1
    print("  ✅ paginate_conversations()")

    # Messages
    msgs = client.list_messages("agent-1", "ref")
    assert msgs.messages[0].content == "hi"
    print("  ✅ list_messages()")

    # Delete conversation
    assert client.delete_conversation("agent-1", "c1").success
    print("  ✅ delete_conversation()")

    # Delete message
    assert client.delete_message("agent-1", "c1", "m1", cascade=True).success
    print("  ✅ delete_message()")

    # Cancel tool call
    assert client.cancel_tool_call("agent-1", "c1", "t1").canceled
    print("  ✅ cancel_tool_call()")

    # Error mapping
    try:
        client._request_sync("GET", "/bad")
        assert False, "should have raised"
    except Exception as e:
        from reygrid import ReyGridAuthError
        assert isinstance(e, ReyGridAuthError), type(e)
        print(f"  ✅ error mapping -> {type(e).__name__}")

    sync_client.close()
    asyncio.run(_async_close(async_client))
    print("✅ SYNC ALL PASSED")


def test_sync_stream():
    handler = make_transport(stream_mode=True)
    sync_client = httpx.Client(transport=httpx.MockTransport(handler))
    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = ReyGrid(api_key="x", base_url="https://reygrid.test", httpx_client=sync_client, httpx_async_client=async_client)

    parts = []
    for delta in client.stream_chat("agent-1", "test"):
        if delta.delta and delta.delta.reply and delta.delta.reply.content:
            parts.append(delta.delta.reply.content)
    result = "".join(parts)
    assert result == "Hello there!", repr(result)
    print(f"  ✅ stream_chat() -> '{result}'")
    sync_client.close()
    asyncio.run(_async_close(async_client))
    print("✅ STREAM SYNC PASSED")


async def _async_close(c):
    await c.aclose()

async def test_async():
    handler = make_transport(stream_mode=False)
    sync_client = httpx.Client(transport=httpx.MockTransport(handler))
    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = ReyGrid(api_key="x", base_url="https://reygrid.test", httpx_client=sync_client, httpx_async_client=async_client)

    ping = await client.async_ping()
    assert ping.status == "UP"
    print("  ✅ async_ping()")

    chat = await client.async_chat("agent-1", "hi")
    assert chat.output.reply.content == "Hello there!"
    print("  ✅ async_chat()")

    convos = await client.async_list_conversations("agent-1")
    assert convos.conversations[0].messagesCount == 3
    print("  ✅ async_list_conversations()")

    assert (await client.async_delete_conversation("agent-1", "c1")).success
    print("  ✅ async_delete_conversation()")

    await client.aclose()
    print("✅ ASYNC ALL PASSED")


async def test_async_stream():
    handler = make_transport(stream_mode=True)
    sync_client = httpx.Client(transport=httpx.MockTransport(handler))
    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = ReyGrid(api_key="x", base_url="https://reygrid.test", httpx_client=sync_client, httpx_async_client=async_client)

    parts = []
    async for delta in client.async_stream_chat("agent-1", "test"):
        if delta.delta and delta.delta.reply and delta.delta.reply.content:
            parts.append(delta.delta.reply.content)
    result = "".join(parts)
    assert result == "Hello there!", repr(result)
    print(f"  ✅ async_stream_chat() -> '{result}'")

    await client.aclose()
    print("✅ ASYNC STREAM PASSED")


def make_v103_transport(seen: list):
    """Mock the endpoints added in 1.0.3."""

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        seen.append((method, path, request.headers.get("content-type", ""), request.content))

        if path == "/agents" and method == "GET":
            return httpx.Response(200, json={"success": True, "agents": [
                {"id": "a1", "name": "Support", "model": "gpt", "instructions": "Be kind", "usage": 1.5,
                 "createdAt": "2026-10-05T10:00:00Z"}]})
        if path == "/agents/a1" and method == "GET":
            return httpx.Response(200, json={"success": True, "agent": {
                "id": "a1", "name": "Support", "model": "gpt", "instructions": "Be kind", "usage": 1.5,
                "sources": {"text": 2, "qa": 1, "file": 0, "website": 3},
                "storage": {"used": 1200, "limit": 256000}}})
        if path == "/agents/a1" and method == "PATCH":
            body = json.loads(request.content)
            return httpx.Response(200, json={"success": True, "agent": {
                "id": "a1", "name": "Support", "model": "gpt", "instructions": body["instructions"]}})
        if path == "/agents/a1/sources" and method == "GET":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json={"success": True, "sources": [
                {"id": f"s{page}", "type": "text", "title": f"Doc {page}", "content": "..."}],
                "pagination": {"totalSources": 2, "totalPages": 2, "currentPage": page,
                               "pagingCounter": page, "hasNextPage": page < 2}})
        if path == "/agents/a1/sources/text":
            return httpx.Response(201, json={"success": True, "source": {"id": "t1", "type": "text", "title": "Refunds"}})
        if path == "/agents/a1/sources/qa":
            return httpx.Response(201, json={"success": True, "source": {"id": "q1", "type": "qa", "title": "Ship?"}})
        if path == "/agents/a1/sources/files":
            return httpx.Response(201, json={"success": True, "source": {"id": "f1", "type": "file", "title": "notes.txt", "size": 5}})
        if path == "/agents/a1/sources/website":
            return httpx.Response(200, json={"success": True, "pagesCrawled": 1, "pages": [{"id": "p1", "path": "/"}]})
        if path == "/agents/a1/sources/missing" and method == "DELETE":
            return httpx.Response(404, json={"success": False, "error": {"code": "SOURCE_NOT_FOUND", "message": "This source does not exist"}})
        if path == "/agents/a1/search":
            return httpx.Response(200, json={"success": True, "results": [
                {"score": 0.81, "content": "30 days", "source": {"id": "t1", "type": "text", "title": "Refunds"}}]})
        if path.endswith("/feedback"):
            return httpx.Response(200, json={"success": True, "feedback": {"rating": "up", "createdAt": "2026-10-05T10:00:00Z"}})
        if path == "/models":
            return httpx.Response(200, json={"success": True, "models": [
                {"id": "gpt", "name": "GPT", "provider": "OpenAI", "pricing": 0.5, "available": True}]})
        if path == "/usage":
            return httpx.Response(200, json={
                "success": True,
                "balance": {"credits": 212.55, "plan": "free", "renewsAt": None},
                "period": {"days": 7, "from": "2026-09-29T00:00:00Z", "to": "2026-10-05T10:00:00Z"},
                "totals": {"requests": 28, "failed": 3, "credits": 15.75},
                "daily": [{"date": "2026-10-05", "requests": 4, "failed": 0, "credits": 2}],
                "agents": [{"id": "a1", "name": None, "requests": 21, "credits": 11.2}]})
        if path == "/agents/a1/sources/plan":
            return httpx.Response(403, json={"success": False, "error": {"code": "PLAN_LIMIT_REACHED", "message": "You need to upgrade your plan"}})
        return httpx.Response(404, json={"success": False, "error": {"code": "NOT_FOUND", "message": "nope"}})

    return handler


def test_v103():
    from reygrid import ReyGridNotFoundError, ReyGridPermissionError

    seen: list = []
    handler = make_v103_transport(seen)
    client = ReyGrid(
        api_key="x",
        base_url="https://reygrid.test",
        httpx_client=httpx.Client(transport=httpx.MockTransport(handler), base_url=""),
        httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    assert client.list_agents().agents[0].name == "Support"
    agent = client.get_agent("a1").agent
    assert agent.sources["website"] == 3 and agent.storage.limit == 256000
    assert client.update_agent("a1", instructions="Short answers").agent.instructions == "Short answers"
    print("  ✅ agents")

    assert [s.id for s in client.paginate_sources("a1", size=1).all()] == ["s1", "s2"]
    assert client.add_text_source("a1", "Refunds", "30 days").source.id == "t1"
    assert client.add_qa_source("a1", "Ship?", "Yes").source.type == "qa"
    created = client.upload_file("a1", b"hello", "notes.txt")
    method, path, content_type, body = seen[-1]
    assert content_type.startswith("multipart/form-data"), content_type
    assert b'filename="notes.txt"' in body and b"Content-Type: text/plain" in body
    assert created.source.size == 5
    assert client.crawl_website("a1", "https://example.com").pagesCrawled == 1
    try:
        client.delete_source("a1", "missing")
        raise AssertionError("expected ReyGridNotFoundError")
    except ReyGridNotFoundError as err:
        assert err.code == "SOURCE_NOT_FOUND" and err.status_code == 404
    print("  ✅ sources (incl. multipart upload & error codes)")

    assert client.search("a1", "refund", limit=3).results[0].source.title == "Refunds"
    assert client.rate_message("a1", "c1", "m1", "up").feedback.rating == "up"
    assert client.list_models().models[0].available is True
    report = client.get_usage_report(days=7)
    assert report.period.from_ == "2026-09-29T00:00:00Z" and report.totals.failed == 3
    assert report.daily[0].date == "2026-10-05" and report.agents[0].name is None
    print("  ✅ search, feedback, models, usage")

    try:
        client._request_sync("GET", "/agents/a1/sources/plan")
        raise AssertionError("expected ReyGridPermissionError")
    except ReyGridPermissionError as err:
        assert err.code == "PLAN_LIMIT_REACHED" and str(err) == "You need to upgrade your plan"
    print("  ✅ 403 -> ReyGridPermissionError")

    client.close()
    print("✅ 1.0.3 ENDPOINTS PASSED")


if __name__ == "__main__":
    print("🔄 Running sync tests...")
    test_sync()
    test_sync_stream()
    print("\n🔄 Running async tests...")
    asyncio.run(test_async())
    asyncio.run(test_async_stream())
    print("\n🔄 Running 1.0.3 endpoint tests...")
    test_v103()
    print("\n🎉 ALL SMOKE TESTS PASSED")