import asyncio, json, sys
sys.path.insert(0, "/app"); sys.path.insert(0, "/exp")
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from agent.host import SYSTEM_PROMPT, _inline_refs, ollama_client
from a2_stage_latency import PROMPTS
async def main():
    llm = ollama_client()
    async with streamablehttp_client("http://localhost:8200/mcp") as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                      "parameters": _inline_refs(t.inputSchema)}} for t in (await s.list_tools()).tools]
    for pid in sys.argv[1:]:
        text = next(p["text"] for p in PROMPTS if p["id"] == pid)
        prompt = ("<|start_header_id|>system<|end_header_id|>\n\n" + SYSTEM_PROMPT +
                  "\n\nCutting Knowledge Date: December 2023\n\nWhen you receive a tool call response, use the output to format an answer to the orginal user question.\n\nYou are a helpful assistant with tool calling capabilities.<|eot_id|>"
                  "<|start_header_id|>user<|end_header_id|>\n\nGiven the following functions, please respond with a JSON for a function call with its proper arguments that best answers the given prompt.\n\nRespond in the format {\"name\": function name, \"parameters\": dictionary of argument name and its value}. Do not use variables.\n\n"
                  + "".join(json.dumps(t) + "\n" for t in tools) + "\nQuestion: " + text +
                  "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n")
        resp = await llm.generate(model="llama3.1:8b", prompt=prompt, raw=True,
                                  options={"temperature": 0.0, "num_ctx": 8192})
        print(f"== {pid} prompt_tokens={resp.prompt_eval_count}\nRAW: {resp.response!r}")
asyncio.run(main())
