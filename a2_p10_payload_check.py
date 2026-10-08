import asyncio, json, sys
sys.path.insert(0, "/app")
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from agent.host import _tool_payload, _strip
async def main():
    async with streamablehttp_client("http://localhost:8200/mcp") as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("solve_intermodal", {"orders": [
                {"origin": "Chicago", "destination": "Houston", "containers": 100, "deadline_hours": 48},
                {"origin": "New York", "destination": "Los Angeles", "containers": 250, "deadline_hours": 48}]})
            print(json.dumps(_strip(_tool_payload(res)), default=str)[:4000])
asyncio.run(main())
