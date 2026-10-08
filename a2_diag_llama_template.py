#!/usr/bin/env python3
"""
Diagnose llama3.1:8b failures in A2 (P02, P09, P10): is it the model or the
tool-calling harness?

1. Prints the Ollama chat template of the model (how tools and tool results
   are rendered into the prompt).
2. Replays a prompt through agent.host's message loop, but for every turn also
   asks Ollama for the *raw* completion of the same rendered prompt (no tool
   parsing), so the model's actual text can be compared with the parsed calls.

Run inside the recoil-mcp-optimizer image (like run_a2.sh):
  docker run --rm --network host -v $PWD:/exp recoil-mcp-optimizer:dev \
      python -u /exp/a2_diag_llama_template.py --prompt P02_defaults
"""
import argparse
import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/exp")
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402
from agent.host import SYSTEM_PROMPT, _inline_refs, _strip, _tool_payload, ollama_client  # noqa: E402
from a2_stage_latency import PROMPTS  # noqa: E402


async def main(args):
    llm = ollama_client()
    show = await llm.show(args.model)
    if args.template:
        print("===== TEMPLATE\n", show.template, "\n===== END TEMPLATE")
    text = next(p["text"] for p in PROMPTS if p["id"] == args.prompt)
    async with streamablehttp_client(args.mcp) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                      "parameters": _inline_refs(t.inputSchema)}} for t in (await s.list_tools()).tools]
            messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}]
            for turn in range(args.max_turns):
                resp = await llm.chat(model=args.model, messages=messages, tools=tools,
                                      options={"temperature": 0.0, "num_ctx": 8192})
                msg = resp.message
                print(f"\n===== TURN {turn}  prompt_tokens={resp.prompt_eval_count}")
                print("content:", repr(msg.content)[:1500])
                print("parsed tool_calls:", [(c.function.name, dict(c.function.arguments))
                                             for c in (msg.tool_calls or [])])
                messages.append(msg.model_dump(exclude_none=True))
                if not msg.tool_calls:
                    break
                for c in msg.tool_calls:
                    res = await s.call_tool(c.function.name, dict(c.function.arguments))
                    payload = _strip(_tool_payload(res))
                    print(f"tool {c.function.name} ->", json.dumps(payload, default=str)[:300])
                    messages.append({"role": "tool", "tool_name": c.function.name,
                                     "content": json.dumps(payload, default=str)})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="llama3.1:8b")
    ap.add_argument("--prompt", default="P02_defaults")
    ap.add_argument("--max-turns", type=int, default=4)
    ap.add_argument("--template", action="store_true")
    ap.add_argument("--mcp", default="http://localhost:8200/mcp")
    asyncio.run(main(ap.parse_args()))
