#!/usr/bin/env python3.11
"""
X (Twitter) Search MCP Server — uses twikit scraping, no API key needed.

Tools:
  search_tweets(query, limit)     — find tweets matching query
  get_user_tweets(username, limit) — recent tweets from a specific user
  find_prospect_tweet(company, role) — find tweet URL for outreach warm-up

Usage:
  python3.11 agents/x_search_mcp.py

Register:
  claude mcp add x-search -- python3.11 /Users/aitsgroup/networking-agent/agents/x_search_mcp.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

load_dotenv(Path(__file__).parent.parent / ".env")

COOKIES_PATH = Path(__file__).parent.parent / "x_twikit_cookies.json"

app = Server("x-search")

_client = None


async def _get_client():
    global _client
    if _client is not None:
        return _client

    from twikit import Client
    c = Client("en-US")

    if COOKIES_PATH.exists():
        c.load_cookies(str(COOKIES_PATH))
    else:
        username = os.environ.get("X_USERNAME", "")
        email = os.environ.get("X_EMAIL", "")
        password = os.environ.get("X_PASSWORD", "")
        if not (username and email and password):
            raise RuntimeError(
                "Set X_USERNAME, X_EMAIL, X_PASSWORD in .env for twikit login\n"
                "Or run x_twikit_login.py once to save cookies."
            )
        await c.login(auth_info_1=username, auth_info_2=email, password=password)
        c.save_cookies(str(COOKIES_PATH))

    _client = c
    return c


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_tweets",
            description="Search X (Twitter) for tweets matching a query. Useful for finding prospect tweets before outreach.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query e.g. 'AI automation wealth management'"},
                    "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_user_tweets",
            description="Get recent tweets from a specific X user by username. Use to find a good tweet to reply to.",
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "X username without @ e.g. 'elonmusk'"},
                    "limit": {"type": "integer", "description": "Max tweets to fetch (default 10)", "default": 10},
                },
                "required": ["username"],
            },
        ),
        types.Tool(
            name="find_prospect_tweet",
            description="Find a recent tweet from a company's CEO/CTO/Founder to use as outreach warm-up target.",
            inputSchema={
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"},
                    "role": {"type": "string", "description": "Role to search for (default: CEO OR CTO OR Founder)", "default": "CEO OR CTO OR Founder"},
                },
                "required": ["company"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        client = await _get_client()
    except Exception as e:
        return [types.TextContent(type="text", text=f"X auth error: {e}")]

    if name == "search_tweets":
        query = arguments["query"]
        limit = arguments.get("limit", 10)
        try:
            results = await client.search_tweet(query, product="Latest", count=limit)
            tweets = []
            for t in results:
                tweets.append({
                    "url": f"https://x.com/{t.user.screen_name}/status/{t.id}",
                    "user": t.user.screen_name,
                    "name": t.user.name,
                    "text": t.text[:280],
                    "likes": t.favorite_count,
                    "retweets": t.retweet_count,
                    "created_at": str(t.created_at),
                })
            return [types.TextContent(type="text", text=json.dumps(tweets, indent=2))]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Search error: {e}")]

    elif name == "get_user_tweets":
        username = arguments["username"].lstrip("@")
        limit = arguments.get("limit", 10)
        try:
            user = await client.get_user_by_screen_name(username)
            tweets_obj = await client.get_user_tweets(user.id, tweet_type="Tweets", count=limit)
            tweets = []
            for t in tweets_obj:
                tweets.append({
                    "url": f"https://x.com/{username}/status/{t.id}",
                    "text": t.text[:280],
                    "likes": t.favorite_count,
                    "retweets": t.retweet_count,
                    "created_at": str(t.created_at),
                })
            return [types.TextContent(type="text", text=json.dumps(tweets, indent=2))]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Error fetching @{username} tweets: {e}")]

    elif name == "find_prospect_tweet":
        company = arguments["company"]
        role = arguments.get("role", "CEO OR CTO OR Founder")
        query = f"{company} ({role}) AI OR tech OR automation OR product"
        try:
            results = await client.search_tweet(query, product="Latest", count=5)
            tweets = []
            for t in results:
                tweets.append({
                    "url": f"https://x.com/{t.user.screen_name}/status/{t.id}",
                    "user": f"@{t.user.screen_name}",
                    "name": t.user.name,
                    "bio": getattr(t.user, "description", ""),
                    "text": t.text[:280],
                    "likes": t.favorite_count,
                    "created_at": str(t.created_at),
                    "use_for_reply": True,
                })
            return [types.TextContent(type="text", text=json.dumps(tweets, indent=2))]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Search error for {company}: {e}")]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
