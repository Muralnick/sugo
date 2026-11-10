"""Check that an MCP server command answers like Glama's introspection (ADR-065).

Starts the command, sends ``initialize`` and ``tools/list`` over stdio, as
Glama does with the container image, and checks that Sugo's two tools come
back. Standard library only, so it runs before any environment is set up.

Usage (from the repository root):
    python3 scripts/container/mcp_probe.py docker run -i --rm sugo
    python3 scripts/container/mcp_probe.py uv run sugo mcp --root DIR
"""

import json
import subprocess
import sys

EXPECTED_TOOLS = {"convert_document", "estimate_savings"}
TIMEOUT_SECONDS = 120


def _requests() -> str:
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "sugo-mcp-probe", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    return "".join(json.dumps(message) + "\n" for message in messages)


def probe(command: list[str]) -> str | None:
    """Return None if the server answered as expected, else what went wrong."""
    try:
        finished = subprocess.run(  # noqa: S603 - the command is the caller's own
            command,
            input=_requests(),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"no answer within {TIMEOUT_SECONDS} s"
    except OSError as error:
        return f"cannot start the command: {error}"
    answers = {}
    for line in finished.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return "the server wrote something that is not JSON-RPC to stdout"
        if isinstance(message, dict) and "id" in message:
            answers[message["id"]] = message
    if "result" not in answers.get(1, {}):
        return f"initialize failed (exit code {finished.returncode})"
    tools = answers.get(2, {}).get("result", {}).get("tools", [])
    names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
    if names != EXPECTED_TOOLS:
        return f"tools/list returned {sorted(map(str, names))}"
    return None


def main() -> int:
    if len(sys.argv) < 2:  # noqa: PLR2004 - script name plus a command
        sys.stderr.write("usage: mcp_probe.py COMMAND [ARGUMENT...]\n")
        return 2
    problem = probe(sys.argv[1:])
    if problem is not None:
        sys.stderr.write(f"MCP probe failed: {problem}\n")
        return 1
    sys.stderr.write("MCP probe passed: initialize and tools/list answered\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
