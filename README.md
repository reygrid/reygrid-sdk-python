# ReyGrid Python SDK

> Powerful, typed Python client for the [ReyGrid API](https://reygrid.com/api/v1) with sync and async support.

[![PyPI](https://img.shields.io/badge/pypi-reygrid-red)](https://pypi.org/project/reygrid/)
[![Python](https://img.shields.io/badge/python-%3E%3D3.9-brightgreen)](https://python.org)

## Features

- **Full base URL control** — point at any deployment, proxy, or local instance
- **Sync + Async** — use sync methods or `async_*` variants with `async for`
- **Typed models** — all responses, errors, and stream events as dataclasses
- **SSE streaming** — sync and async generators for streaming chat
- **Tool calling** — full agent tools support with result submission
- **Pagination helpers** — `Paginator` with sync/async iteration over all pages
- **Conversation management** — paginate, read, delete conversations and messages
- **Rich error hierarchy** — typed exceptions per status code

## Install

```bash
pip install reygrid
# or with dev extras
pip install reygrid[dev]
```

Requires `httpx>=0.27`.

## Quick Start

```python
from reygrid import ReyGrid

# Create the client — base URL defaults to https://reygrid.com/api/v1
client = ReyGrid(api_key='your-api-key')

# Health check
ping = client.ping()
print(f'Status: {ping.status}')  # 'UP'

# Validate key & check usage
usage = client.get_usage()
print(f'Usage: {usage.total} / {usage.quotaLimit}')
```

### Custom base URL

```python
client = ReyGrid(
    api_key='your-api-key',
    base_url='https://custom-gateway.example.com/reygrid',
)
```

## Chat — Assistant Agent

Realistic example: a customer-support assistant that can check the caller's plan and hours.

### Non-streaming

```python
reply = client.chat(
    'agent-id',
    'Check my current subscription',
    user_id='user-42',              # persistent conversation per user
    tools=[{
        'type': 'function',
        'function': {
            'name': 'check_subscription',
            'instructions': (
                'Opens the customer current plan, renewal date, '
                'and payment status.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'userId': {'type': 'string', 'description': 'The customer user id'},
                },
                'required': ['userId'],
            },
        },
    }],
)
print(reply.output.reply.content)
# e.g. 'Your current subscription: Pro plan — active until Sep 30, prepaid.'
```

> **Tip:** pass a fixed `user_id` per user — ReyGrid stores the full conversation
> and returns it automatically on each message, so you do not manage history yourself.

### Streaming (SSE)

```python
# Sync streaming. Each frame: {"delta": {"reply": {"content": ...}}}
for frame in client.stream_chat('agent-id', 'What are your hours?'):
    if frame.delta and frame.delta.reply and frame.delta.reply.content:
        print(frame.delta.reply.content, end='')

# Async streaming
async for frame in client.async_stream_chat('agent-id', 'Tell me about the Pro plan'):
    if frame.delta and frame.delta.reply and frame.delta.reply.content:
        print(frame.delta.reply.content, end='')
```

### Tool results

After the assistant asks for a tool call, send the result back so it can continue:

```python
reply = client.chat(
    'agent-id',
    'What is the status of my account?',
    user_id='user-42',
    tools=[check_subscription_tool],
    results=[{
        'toolCallId': 'call_xyz',
        'output': json.dumps({
            'plan': 'pro',
            'status': 'active',
            'renewsAt': '2026-09-30',
            'paymentMethod': '****4242',
        }),
    }],
)
```

## Pagination

```python
# Sync iteration
paginator = client.paginate_conversations('agent-1')
for page in paginator:
    for convo in page.data:
        print(convo.conversationId, convo.messagesCount)

# Async iteration
paginator = client.async_paginate_conversations('agent-1')
async for page in paginator:
    for convo in page.data:
        print(convo.conversationId)

# All items at once (use with caution)
all_convos = paginator.all()
```

## Error Handling

```python
from reygrid import (
    ReyGridError,
    ReyGridApiError,
    ReyGridAuthError,
    ReyGridNetworkError,
)

try:
    client.validate()
except ReyGridAuthError:
    print('Bad API key!')
except ReyGridNetworkError:
    print('Network is down')
except ReyGridApiError as e:
    print(f'API {e.status_code}: {e.code} — {e}')
```

## API Reference

| Endpoint                                            | Method | Sync                           | Async                                |
| --------------------------------------------------- | ------ | ------------------------------ | ------------------------------------ |
| `/ping`                                             | GET    | `client.ping()`                | `client.async_ping()`                |
| `/validate`                                         | GET    | `client.validate()`            | `client.async_validate()`            |
| `/agents/{id}/chat`                                 | POST   | `client.chat()`                | `client.async_chat()`                |
| `/agents/{id}/chat` (stream)                        | POST   | `client.stream_chat()`         | `client.async_stream_chat()`         |
| `/agents/{id}/conversations`                        | GET    | `client.list_conversations()`  | `client.async_list_conversations()`  |
| `/agents/{id}/conversations/{ref}/messages`         | GET    | `client.list_messages()`       | `client.async_list_messages()`       |
| `/agents/{id}/conversations/{ref}`                  | DELETE | `client.delete_conversation()` | `client.async_delete_conversation()` |
| `/agents/{id}/conversations/{ref}/messages/{id}`    | DELETE | `client.delete_message()`      | `client.async_delete_message()`      |
| `/agents/{id}/conversations/{ref}/tool/cancel/{id}` | POST   | `client.cancel_tool_call()`    | `client.async_cancel_tool_call()`    |

## Development

```bash
cd python
pip install -e .
python -m build --sdist --wheel --outdir dist
pip install dist/reygrid-1.0.2-py3-none-any.whl
python smoke_test.py
```
