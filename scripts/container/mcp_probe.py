"""Check that an MCP server command answers like Glama's introspection (ADR-065).

Starts the command, sends ``initialize``, ``tools/list``, ``resources/list``
and ``prompts/list`` over stdio, as Glama does with the container image, and
checks that Sugo's two tools come back, that the other two lists get an
answer (Sugo has neither, so a JSON-RPC error is fine) and that the server
then exits cleanly. Standard library only, so it runs before any environment
is set up.

Usage (from the repository root):
    python3 scripts/container/mcp_probe.py docker run -i --rm sugo
    python3 scripts/container/mcp_probe.py uv run sugo mcp --root DIR
"""

import json
import subprocess
import sys

EXPECTED_TOOLS = {"convert_document", "estimate_savings"}
TIMEOUT_SECONDS = 120
STDERR_TAIL_LINES = 20


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
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 4, "method": "prompts/list"},
    ]
    return "".join(json.dumps(message) + "\n" for message in messages)


def _answers(stdout: str) -> dict[int, dict[str, object]] | None:
    """The server's answers by request id, or None if stdout is not JSON-RPC."""
    answers: dict[int, dict[str, object]] = {}
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(message, dict):
            return None
        request_id = message.get("id")
        if isinstance(request_id, int):
            answers[request_id] = message
    return answers


def _tool_names(answer: dict[str, object]) -> set[str]:
    result = answer.get("result")
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        return set()
    return {str(tool.get("name")) for tool in tools if isinstance(tool, dict)}


def _check(finished: subprocess.CompletedProcess[str]) -> str | None:
    answers = _answers(finished.stdout)
    if answers is None:
        return "the server wrote something that is not JSON-RPC to stdout"
    if "result" not in answers.get(1, {}):
        return f"initialize failed (exit code {finished.returncode})"
    names = _tool_names(answers.get(2, {}))
    if names != EXPECTED_TOOLS:
        return f"tools/list returned {sorted(names)}"
    for request_id, method in ((3, "resources/list"), (4, "prompts/list")):
        if not answers.get(request_id, {}).keys() & {"result", "error"}:
            return f"{method} got no answer"
    if finished.returncode != 0:
        return f"the server exited with code {finished.returncode}"
    return None


def probe(command: list[str]) -> str | None:
    """Return None if the server answered as expected, else what went wrong."""
    try:
        finished = subprocess.run(  # noqa: S603 - the command is the caller's own
            command,
            input=_requests(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"no answer within {TIMEOUT_SECONDS} s"
    except OSError as error:
        return f"cannot start the command: {error}"
    problem = _check(finished)
    if problem is not None and finished.stderr.strip():
        tail = "\n".join(finished.stderr.splitlines()[-STDERR_TAIL_LINES:])
        problem += f"; the server's stderr ends with:\n{tail}"
    return problem


def main() -> int:
    if len(sys.argv) < 2:  # noqa: PLR2004 - script name plus a command
        sys.stderr.write("usage: mcp_probe.py COMMAND [ARGUMENT...]\n")
        return 2
    problem = probe(sys.argv[1:])
    if problem is not None:
        sys.stderr.write(f"MCP probe failed: {problem}\n")
        return 1
    sys.stderr.write("MCP probe passed: the server answered and exited cleanly\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
