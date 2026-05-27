"""MCP server providing web search and web fetch tools via DuckDuckGo.

Configure in Claude Code settings.json:
  "mcpServers": {
    "web-search": {
      "type": "stdio",
      "command": "D:/conda/envs/pydantic_ai/Scripts/python.exe",
      "args": ["path/to/agent/web_search_mcp.py"]
    }
  }
"""

import logging
import re
import html
import sys

import httpx
from ddgs import DDGS
from fastmcp import FastMCP

# MCP over stdio requires NOTHING on stdout except JSON-RPC messages.
logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
mcp = FastMCP("web-search")


def _clean_html(raw: str) -> str:
    """Strip HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@mcp.tool()
def web_search(query: str, max_results: int = 10) -> list[dict]:
    """Search the web using DuckDuckGo.

    Args:
        query: The search query string.
        max_results: Maximum number of results (1-20). Default 10.

    Returns a list of dicts with keys: title, href, body.
    """
    max_results = max(1, min(max_results, 20))
    with DDGS() as ddgs:
        results = []
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title": r.get("title", ""),
                "href": r.get("href", ""),
                "body": r.get("body", ""),
            })
    return results


@mcp.tool()
def web_fetch(url: str, max_chars: int = 8000) -> str:
    """Fetch a web page and return its text content.

    Args:
        url: The URL to fetch.
        max_chars: Maximum characters to return. Default 8000.

    Returns the extracted text content.
    """
    resp = httpx.get(url, follow_redirects=True, timeout=15)
    content_type = resp.headers.get("content-type", "")
    if "text/html" in content_type:
        text = _clean_html(resp.text)
    else:
        text = resp.text
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n... [truncated]"
    return text


if __name__ == "__main__":
    # Suppress FastMCP banner and log noise on stdout (JSON-RPC requires clean stdout).
    # FastMCP uses its own logger; redirect it to stderr at WARNING+.
    for name in ("fastmcp", "mcp", "rich"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = False
    mcp.run(show_banner=False, log_level="ERROR")
