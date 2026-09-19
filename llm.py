from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from config import load_lore, settings
from search import fetch_page, web_search


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Ищет факты в интернете.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": "Читает страницу по URL.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
]


def build_system_prompt(extra_instruction: str = "") -> str:
    lore = load_lore()
    extra = ""
    if extra_instruction:
        extra = "\n\nДополнительная задача:\n" + extra_instruction
    return (
        "Ты живой участник Telegram-группы.\n\n"
        "=== ЛОР ===\n"
        + lore
        + "\n=== КОНЕЦ ЛОРА ===\n\n"
        "Правила:\n"
        "- Говори обычным разговорным русским.\n"
        "- Не украинский и не суржик.\n"
        "- Не заканчивай «ты как?» и «как тебе идея?».\n"
        "- Не добряк. Если оскорбляют — стебай в ответ, не соглашайся.\n"
        "- Не представляйся ботом.\n"
        "- Тегай человека через @ник только к месту.\n"
        "- Факты ищи через web_search, потом отвечай своим языком.\n"
        + extra
    )


client = AsyncOpenAI(
    api_key=settings.llm_api_key,
    base_url=settings.llm_base_url,
)


async def _run_tool(name, arguments):
    if name == "web_search":
        query = str(arguments.get("query") or "").strip()
        if not query:
            return "Пустой запрос."
        return await web_search(query, region=settings.search_region, max_results=settings.search_results)
    if name == "fetch_page":
        url = str(arguments.get("url") or "").strip()
        if not url.startswith("http"):
            return "Нужен URL."
        return await fetch_page(url)
    return "Неизвестный инструмент"


def _dump_tool_args(raw):
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


async def ask_character(history, extra_instruction="", max_tool_rounds=4, image_data_url=None):
    messages = [{"role": "system", "content": build_system_prompt(extra_instruction)}]
    messages.extend(history)
    if image_data_url:
        last = messages[-1] if messages else None
        text = ""
        if last and last.get("role") == "user":
            text = str(last.get("content") or "")
            messages.pop()
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": text or "Смотри фото."},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        })
    for _ in range(max_tool_rounds + 1):
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            tools=TOOLS,
            temperature=0.7,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            return (message.content or "").strip() or "Мне нечего ответить."
        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in message.tool_calls
            ],
        })
        for call in message.tool_calls:
            args = _dump_tool_args(call.function.arguments)
            tool_result = await _run_tool(call.function.name, args)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": tool_result})
    return "Слишком много поиска."
