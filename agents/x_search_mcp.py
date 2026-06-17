#!/usr/bin/env python3.11
"""
X Search MCP Server — uses DuckDuckGo to find prospect X handles and profiles.

twikit scraping is broken (X anti-bot changes). This approach:
  1. Find prospect's X handle via DuckDuckGo search
  2. Return profile URL so you can browse their recent tweets
  3. Use x_agent.grok_research_prompt() for finding specific tweet URLs

Tools:
  find_prospect_handle(name, company)   — find someone's X handle
  search_x_profiles(query)             — find X profiles matching query
  web_search(query)                    — general DuckDuckGo search for pipeline
"""

import asyncio
import json
import re
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

app = Server("x-search")


def _ddgs_search(query: str, max_results: int = 10) -> list[dict]:
    try:
        from ddgs import DDGS
        return list(DDGS().text(query, max_results=max_results))
    except Exception as e:
        return [{"error": str(e)}]


def _extract_x_handle(results: list[dict]) -> list[dict]:
    """Filter results that look like X profile URLs."""
    handles = []
    seen = set()
    for r in results:
        url = r.get("href", "")
        title = r.get("title", "")
        body = r.get("body", "")
        # Match twitter.com/username or x.com/username (not /status/, /search, /i/)
        m = re.search(r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,50})(?:/|$)", url)
        if m:
            handle = m.group(1)
            if handle.lower() in {"search", "i", "home", "explore", "notifications", "messages", "hashtag"}:
                continue
            if handle not in seen:
                seen.add(handle)
                handles.append({
                    "handle": f"@{handle}",
                    "profile_url": f"https://x.com/{handle}",
                    "source_title": title[:100],
                    "snippet": body[:150],
                })
    return handles


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="find_prospect_handle",
            description=(
                "Find a person's X (Twitter) handle using their name and company. "
                "Returns profile URL so you can browse their recent tweets for outreach warm-up."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Person's full name e.g. 'John Smith'"},
                    "company": {"type": "string", "description": "Company name e.g. 'Vermeer Capital'"},
                    "role": {"type": "string", "description": "Their role e.g. 'CEO'", "default": ""},
                },
                "required": ["name", "company"],
            },
        ),
        types.Tool(
            name="search_x_profiles",
            description="Find X/Twitter profiles matching a search query. Useful for finding CTOs, founders, investors.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "e.g. 'wealth management founder UK Twitter'"},
                    "max_results": {"type": "integer", "default": 8},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="web_search",
            description="General DuckDuckGo web search. Use for company research, finding contact emails, news.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 8},
                },
                "required": ["query"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "find_prospect_handle":
        person = arguments.get("name", "")
        company = arguments.get("company", "")
        role = arguments.get("role", "")
        role_str = f"{role} " if role else ""
        query = f'"{person}" {role_str}"{company}" Twitter OR X.com site:twitter.com OR site:x.com OR "@{person.split()[0]}"'
        raw = await asyncio.get_event_loop().run_in_executor(None, lambda: _ddgs_search(query, 10))
        handles = _extract_x_handle(raw)
        if not handles:
            # Broader fallback
            query2 = f'{person} {company} Twitter'
            raw2 = await asyncio.get_event_loop().run_in_executor(None, lambda: _ddgs_search(query2, 10))
            handles = _extract_x_handle(raw2)
        result = {
            "person": person,
            "company": company,
            "handles_found": handles,
            "note": "Visit profile_url to find recent tweets. Use x-reply CLI to reply once you have tweet URL.",
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "search_x_profiles":
        query = arguments["query"] + " site:twitter.com OR site:x.com"
        max_r = arguments.get("max_results", 8)
        raw = await asyncio.get_event_loop().run_in_executor(None, lambda: _ddgs_search(query, max_r))
        handles = _extract_x_handle(raw)
        return [types.TextContent(type="text", text=json.dumps(handles, indent=2))]

    elif name == "web_search":
        query = arguments["query"]
        max_r = arguments.get("max_results", 8)
        results = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _ddgs_search(query, max_r)
        )
        clean = [{"url": r.get("href", ""), "title": r.get("title", ""), "snippet": r.get("body", "")[:200]} for r in results]
        return [types.TextContent(type="text", text=json.dumps(clean, indent=2))]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
