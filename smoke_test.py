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


if __name__ == "__main__":
    print("🔄 Running sync tests...")
    test_sync()
    test_sync_stream()
    print("\n🔄 Running async tests...")
    asyncio.run(test_async())
    asyncio.run(test_async_stream())
    print("\n🎉 ALL SMOKE TESTS PASSED")