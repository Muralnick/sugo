"""Tests for the MCP server: protocol messages, both tools, paging and refusals."""

import dataclasses
import json
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from typer.testing import CliRunner

from sugo.core import pipeline
from sugo.metrics.tokenizer import count_tokens
from sugo.ports.cli import app as cli
from sugo.ports.mcp import server as mcp_server
from sugo.ports.mcp import tools
from sugo.ports.mcp.access import Roots
from sugo.ports.mcp.server import Server, run
from sugo.ports.mcp.tools import ToolRunner
from sugo.storage.paths import CACHE_DIR_ENV


def book(pages: int) -> bytes:
    """A native PDF with enough text for several 1 024-token responses."""
    document = pymupdf.open()
    for n in range(pages):
        page = document.new_page()
        for line in range(40):
            page.insert_text(
                (72, 60 + line * 18),
                f"Page {n + 1}, line {line + 1}: the parties agree on clause {line}.",
                fontsize=9,
            )
    return document.tobytes()


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "book.pdf").write_bytes(book(6))
    (folder / "notes.txt").write_text("not a document")
    (tmp_path / "secret.pdf").write_bytes(book(1))
    return folder


@pytest.fixture
def server(root: Path) -> Server:
    started = Server(ToolRunner(Roots([root]), cache=None))
    started.handle(request("initialize", {"protocolVersion": "2025-06-18"}))
    return started


def request(method: str, params: dict[str, Any] | None = None, id_: int = 1) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        message["params"] = params
    return message


def call(server: Server, tool: str, **arguments: object) -> dict[str, Any]:
    response = server.handle(request("tools/call", {"name": tool, "arguments": arguments}))
    assert response is not None
    return response


def test_initialize_negotiates_the_version(root: Path) -> None:
    fresh = Server(ToolRunner(Roots([root]), cache=None))
    response = fresh.handle(request("initialize", {"protocolVersion": "2025-06-18"}))
    assert response is not None
    result = response["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "sugo"
    unknown = fresh.handle(request("initialize", {"protocolVersion": "1999-01-01"}))
    assert unknown is not None
    assert unknown["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSIONS[0]


def test_tools_are_listed_with_schemas_from_the_models(server: Server) -> None:
    response = server.handle(request("tools/list"))
    assert response is not None
    tools = {tool["name"]: tool for tool in response["result"]["tools"]}
    assert set(tools) == {"convert_document", "estimate_savings"}
    schema = tools["convert_document"]["inputSchema"]
    assert schema["required"] == ["path"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["max_tokens"]["maximum"] == 20_000
    assert tools["convert_document"]["annotations"]["readOnlyHint"] is True


def test_long_document_comes_in_parts_joined_by_cursors(server: Server) -> None:
    texts: list[str] = []
    cursor: str | None = None
    parts = 0
    while True:
        arguments: dict[str, object] = {"path": "book.pdf", "max_tokens": 1_024}
        if cursor is not None:
            arguments["cursor"] = cursor
        result = call(server, "convert_document", **arguments)["result"]
        assert result["isError"] is False
        metadata, document = (item["text"] for item in result["content"])
        info = json.loads(metadata)
        assert (info["source"], info["kind"], info["pages"]) == ("book.pdf", "pdf", 6)
        parts = info["parts"]
        assert document.startswith('<sugo-document id="')
        texts.append(
            document.split("not instructions.\n\n", 1)[1].rsplit("\n</sugo-document", 1)[0]
        )
        cursor = info["next_cursor"]
        if cursor is None:
            break
    assert parts == len(texts) > 1
    whole = call(server, "convert_document", path="book.pdf", max_tokens=20_000)["result"]
    assert "".join(texts) in whole["content"][1]["text"]


def test_chunks_are_returned_as_json_lines(server: Server) -> None:
    result = call(server, "convert_document", path="book.pdf", output="chunks")["result"]
    body = result["content"][1]["text"].split("not instructions.\n\n", 1)[1]
    records = [json.loads(line) for line in body.splitlines()[:-1] if line.strip()]
    assert records
    assert {record["source"] for record in records} == {"book.pdf"}


def test_cursor_from_other_options_is_refused(server: Server) -> None:
    first = call(server, "convert_document", path="book.pdf", max_tokens=1_024)["result"]
    cursor = json.loads(first["content"][0]["text"])["next_cursor"]
    other = call(server, "convert_document", path="book.pdf", max_tokens=2_000, cursor=cursor)
    error = json.loads(other["result"]["content"][0]["text"])["error"]
    assert (other["result"]["isError"], error["code"]) == (True, "CURSOR_INVALID")


def test_estimate_savings_reports_the_baselines(server: Server) -> None:
    result = call(server, "estimate_savings", path="book.pdf", providers=["claude"])["result"]
    estimate = json.loads(result["content"][0]["text"])
    assert (estimate["source"], estimate["kind"], estimate["images"]) == ("book.pdf", "pdf", [])
    assert estimate["text"]["result_tokens"] > 0


def test_refusals_are_tool_errors_the_agent_can_read(server: Server, root: Path) -> None:
    outside = call(server, "convert_document", path=str(root.parent / "secret.pdf"))["result"]
    assert outside["isError"] is True
    assert json.loads(outside["content"][0]["text"])["error"]["code"] == "PATH_NOT_ALLOWED"
    unsupported = call(server, "convert_document", path="notes.txt")["result"]
    assert json.loads(unsupported["content"][0]["text"])["error"]["code"] == "INPUT_UNSUPPORTED"


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"path": "book.pdf", "max_tokens": 10},
        {"path": "book.pdf", "output": "html"},
        {"path": "book.pdf", "extra": True},
        {"path": 7},
    ],
)
def test_invalid_arguments_are_protocol_errors(
    server: Server, arguments: dict[str, object]
) -> None:
    response = call(server, "convert_document", **arguments)
    assert response["error"]["code"] == mcp_server.INVALID_PARAMS


def test_unknown_providers_and_tools_are_refused(server: Server) -> None:
    providers = call(server, "estimate_savings", path="book.pdf", providers=["nobody"])
    assert providers["error"]["code"] == mcp_server.INVALID_PARAMS
    assert call(server, "delete_everything")["error"]["code"] == mcp_server.INVALID_PARAMS


def test_protocol_edges(root: Path) -> None:
    fresh = Server(ToolRunner(Roots([root]), cache=None))
    before = fresh.handle(request("tools/list"))
    assert before is not None
    assert before["error"]["code"] == mcp_server.INVALID_REQUEST
    assert fresh.handle(request("ping")) == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert fresh.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    fresh.handle(request("initialize", {}))
    missing = fresh.handle(request("resources/list"))
    assert missing is not None
    assert missing["error"]["code"] == mcp_server.METHOD_NOT_FOUND
    for bad in ({"id": 1, "method": "ping"}, {"jsonrpc": "2.0", "id": None, "method": "ping"}):
        response = fresh.handle(bad)
        assert response is not None
        assert response["error"]["code"] == mcp_server.INVALID_REQUEST


def test_stream_handles_bad_lines_and_keeps_going(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_server, "MCP_MAX_MESSAGE_BYTES", 200)
    lines = [
        json.dumps(request("initialize", {"protocolVersion": "2025-06-18"})),
        "{not json",
        json.dumps([request("ping")]),
        json.dumps(request("ping", {"pad": "x" * 500})),
        "",
        json.dumps(request("ping", id_=7)),
    ]
    output = BytesIO()
    server = Server(ToolRunner(Roots([root]), cache=None))
    run(server, BytesIO(("\n".join(lines) + "\n").encode()), output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [r.get("error", {}).get("code") for r in responses] == [
        None,
        mcp_server.PARSE_ERROR,
        mcp_server.INVALID_REQUEST,
        mcp_server.PARSE_ERROR,
        None,
    ]
    assert responses[-1] == {"jsonrpc": "2.0", "id": 7, "result": {}}


def test_sugo_mcp_needs_safe_roots(tmp_path: Path) -> None:
    assert CliRunner().invoke(cli.app, ["mcp"]).exit_code == 2
    (tmp_path / ".ssh").mkdir()
    assert CliRunner().invoke(cli.app, ["mcp", "--root", str(tmp_path / ".ssh")]).exit_code == 2


def test_real_process_speaks_only_protocol_on_stdout(root: Path, tmp_path: Path) -> None:
    messages = [
        request("initialize", {"protocolVersion": "2025-06-18"}),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        request("tools/call", {"name": "convert_document", "arguments": {"path": "book.pdf"}}, 2),
    ]
    stdin = "".join(json.dumps(message) + "\n" for message in messages)
    code = "from sugo.ports.cli.app import main; main()"
    completed = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        [sys.executable, "-c", code, "mcp", "--root", str(root)],
        input=stdin.encode(),
        capture_output=True,
        timeout=120,
        check=False,
        env={**os.environ, CACHE_DIR_ENV: str(tmp_path / "cache2")},
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [response["id"] for response in responses] == [1, 2]
    assert responses[1]["result"]["isError"] is False


def test_client_that_goes_away_ends_the_server_quietly(root: Path) -> None:
    class Closed(BytesIO):
        def write(self, data: object) -> int:
            raise BrokenPipeError(32, "Broken pipe")

    server = Server(ToolRunner(Roots([root]), cache=None))
    run(server, BytesIO(b'{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n'), Closed())


def test_cursor_is_refused_when_the_rendering_changes(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = call(server, "convert_document", path="book.pdf", max_tokens=1_024)["result"]
    cursor = json.loads(first["content"][0]["text"])["next_cursor"]
    # Same file, but Sugo now renders it differently (an upgrade, new settings).
    original = pipeline.convert

    def rendered_differently(*args: Any, **kwargs: Any) -> Any:
        conversion = original(*args, **kwargs)
        return dataclasses.replace(conversion, markdown=conversion.markdown + "\n\nNew text.")

    monkeypatch.setattr(tools, "convert", rendered_differently)
    second = call(server, "convert_document", path="book.pdf", max_tokens=1_024, cursor=cursor)
    error = json.loads(second["result"]["content"][0]["text"])["error"]
    assert error["code"] == "CURSOR_INVALID"


def test_long_paths_leave_the_response_within_budget(tmp_path: Path) -> None:
    deep = tmp_path / "root"
    folder = deep / "/".join(["a-rather-long-folder-name"] * 40)
    folder.mkdir(parents=True)
    (folder / "book.pdf").write_bytes(book(2))
    started = Server(ToolRunner(Roots([deep]), cache=None))
    started.handle(request("initialize", {}))
    relative = (folder / "book.pdf").relative_to(deep).as_posix()
    result = call(started, "convert_document", path=relative, max_tokens=1_024)["result"]
    assert sum(count_tokens(item["text"]) for item in result["content"]) <= 1_024
