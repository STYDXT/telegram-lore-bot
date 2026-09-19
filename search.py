from __future__ import annotations

import asyncio
import re
from html import unescape

import aiohttp
from bs4 import BeautifulSoup
from ddgs import DDGS

MAX_PAGE_CHARS = 6000


def _search_sync(query, region, max_results):
    with DDGS() as client:
        rows = client.text(query, region=region, safesearch="moderate", max_results=max_results) or []
    cleaned = []
    for row in rows:
        cleaned.append({
            "title": (row.get("title") or "").strip(),
            "url": (row.get("href") or row.get("url") or "").strip(),
            "snippet": (row.get("body") or row.get("snippet") or "").strip(),
        })
    return cleaned


async def web_search(query, region="ru-ru", max_results=6):
    rows = await asyncio.to_thread(_search_sync, query, region, max_results)
    if not rows:
        return "По запросу ничего не нашлось: " + query
    lines = ["Результаты поиска: " + query]
    for i, row in enumerate(rows, 1):
        lines.append(str(i) + ". " + row["title"] + "\n" + row["url"] + "\n" + row["snippet"])
    return "\n".join(lines)


def _extract_text(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form"]):
        tag.decompose()
    text = unescape(soup.get_text("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


async def fetch_page(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status >= 400:
                    return "Не открылась страница: " + url
                raw = await resp.text(errors="ignore")
    except Exception as exc:
        return "Ошибка страницы: " + str(exc)
    text = _extract_text(raw)
    if not text:
        return "Пустая страница: " + url
    if len(text) > MAX_PAGE_CHARS:
        text = text[:MAX_PAGE_CHARS] + "\nобрезано"
    return "Содержимое " + url + ":\n" + text
