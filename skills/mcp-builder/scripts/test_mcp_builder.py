"""Tests for skills/mcp-builder/scripts/evaluation.py (round 6,
3-F2-06 / 3-F2-07 / 3-F2-08 / 3-F2-09).

No live MCP server and no real Anthropic API exist in this VM, so
the tests stub `anthropic` and `connections` in sys.modules (the
same approach the round-6 verifier used) and drive
parse_evaluation_file / agent_loop / run_evaluation directly. The
CLI exit codes are covered by subprocess runs against stub modules
written to a temp dir.

Run: python3 -m pytest skills/mcp-builder/scripts/test_mcp_builder.py -q
"""

import asyncio
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Stub the two imports evaluation.py needs before importing it:
# `anthropic` (no API key, no SDK here) and the bundled
# `connections` (which imports `mcp` — no MCP server here either).
_anthropic = types.ModuleType("anthropic")


class _StubAnthropic:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("stub Anthropic must be patched per test")


_anthropic.Anthropic = _StubAnthropic
sys.modules.setdefault("anthropic", _anthropic)
_connections = types.ModuleType("connections")
_connections.create_connection = lambda **kwargs: None
sys.modules.setdefault("connections", _connections)

import evaluation  # noqa: E402


# --- fakes ---


class FakeText:
    type = "text"

    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class FakeToolUse:
    type = "tool_use"

    def __init__(self, name, tool_input, tool_id):
        self.name = name
        self.input = tool_input
        self.id = tool_id


class FakeMessages:
    """messages.create returns the queued responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


class FakeConnection:
    def __init__(self, tool_results=None):
        self.tool_results = tool_results or {}
        self.calls = []

    async def list_tools(self):
        return []

    async def call_tool(self, name, tool_input):
        self.calls.append((name, tool_input))
        if name in self.tool_results:
            result = self.tool_results[name]
            if isinstance(result, Exception):
                raise result
            return result
        return [{"type": "text", "text": "ok"}]


class FakeTextContent:
    """Stands in for mcp.types.TextContent: not JSON-serialisable,
    but model_dump() gives a plain dict (verified against the real
    SDK: model_dump() -> {'type': 'text', 'text': 'ok',
    'annotations': None})."""

    type = "text"

    def __init__(self, text):
        self.text = text

    def model_dump(self):
        return {"type": "text", "text": self.text, "annotations": None}


def _qa_file(tmp_path, pairs):
    body = "".join(
        f"<qa_pair><question>{q}</question><answer>{a}</answer></qa_pair>"
        for q, a in pairs
    )
    path = tmp_path / "eval.xml"
    path.write_text(f"<evaluation>{body}</evaluation>", encoding="utf-8")
    return path


def _tool_result_contents(client, call_index):
    """The tool_result message(s) a create call saw. The messages
    list is mutated after the call (the assistant reply is
    appended), so select by role/type instead of indexing [-1]."""
    messages = client.messages.calls[call_index]["messages"]
    out = []
    for msg in messages:
        content = msg.get("content")
        if msg.get("role") == "user" and isinstance(content, list):
            out.extend(
                block["content"]
                for block in content
                if isinstance(block, dict) and block.get("type") == "tool_result"
            )
    return out


def _end_turn(text):
    return FakeResponse("end_turn", [FakeText(text)])


# --- 3-F2-09: parse errors, incomplete tasks, zero tasks ---


def test_malformed_xml_raises(tmp_path):
    """3-F2-09: malformed XML used to parse to [] and report 0/0
    with a passing exit. It is a controlled error now."""
    path = tmp_path / "bad.xml"
    path.write_text("<evaluation><qa_pair><question>q</question>", encoding="utf-8")
    with pytest.raises(ValueError, match="parse"):
        evaluation.parse_evaluation_file(path)


def test_incomplete_qa_pair_raises(tmp_path):
    """3-F2-09: a qa_pair missing its answer used to be skipped
    silently — a file with one good pair and one broken pair
    reported 1/1. The broken pair is an error now."""
    path = tmp_path / "eval.xml"
    path.write_text(
        "<evaluation>"
        "<qa_pair><question>q1</question><answer>a1</answer></qa_pair>"
        "<qa_pair><question>q2</question></qa_pair>"
        "</evaluation>",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="incomplete"):
        evaluation.parse_evaluation_file(path)


def test_zero_tasks_raises(tmp_path):
    """3-F2-09: a well-formed file with no qa_pair at all used to
    report 0/0 (0.0%) and exit 0. Zero tasks is an error now."""
    path = tmp_path / "eval.xml"
    path.write_text("<evaluation></evaluation>", encoding="utf-8")
    with pytest.raises(ValueError, match="no .*task"):
        evaluation.parse_evaluation_file(path)


def test_valid_file_still_parses(tmp_path):
    """Control: a well-formed file with complete pairs parses."""
    path = _qa_file(tmp_path, [("q1", "a1"), ("q2", "a2")])
    pairs = evaluation.parse_evaluation_file(path)
    assert pairs == [{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": "a2"}]


def test_run_evaluation_returns_structured_result(tmp_path, monkeypatch):
    """3-F2-09: run_evaluation returns a structured result (report
    + correct/total/accuracy), not just a report string — the CLI
    needs the numbers to enforce a threshold."""
    path = _qa_file(tmp_path, [("q", "42")])
    client = FakeClient([_end_turn("<response>42</response><summary>s</summary><feedback>f</feedback>")])
    monkeypatch.setattr(evaluation, "Anthropic", lambda: client)
    result = asyncio.run(evaluation.run_evaluation(path, FakeConnection(), "model"))
    assert isinstance(result, dict)
    assert result["correct"] == 1
    assert result["total"] == 1
    assert result["accuracy"] == 100.0
    assert "1/1" in result["report"]


# --- 3-F2-07: serialisation ---


def test_text_content_blocks_serialise(monkeypatch):
    """3-F2-07: json.dumps([TextContent(...)]) raises TypeError, and
    the harness used to turn that into a fake 'Error executing
    tool' message. The tool result must serialise to JSON carrying
    the block's text, and must not mention an execution error."""
    tool_use = FakeToolUse("echo", {"x": 1}, "t1")
    first = FakeResponse("tool_use", [tool_use])
    second = _end_turn("<response>ok</response>")
    client = FakeClient([first, second])
    conn = FakeConnection({"echo": [FakeTextContent("hello")]})
    monkeypatch.setattr(evaluation, "Anthropic", lambda: client)
    text, _ = asyncio.run(
        evaluation.agent_loop(client, "model", "q", [], conn)
    )
    # agent_loop returns the raw reply text; the <response> tag is
    # extracted by evaluate_single_task, not here.
    assert text == "<response>ok</response>"
    # The tool_result the model saw is in the second create call's
    # messages: it must be valid JSON with the text, not an error.
    contents = _tool_result_contents(client, 1)
    assert len(contents) == 1
    content = contents[0]
    assert "Error executing tool" not in content
    assert json.loads(content) == [{"type": "text", "text": "hello", "annotations": None}]


def test_execution_error_and_serialisation_error_differ(monkeypatch):
    """3-F2-07: an execution failure says 'Error executing tool';
    a serialisation failure says 'Error serialising tool result' —
    the two must not be conflated."""

    class Unserialisable:
        def model_dump(self):
            raise RuntimeError("no dump")

        def __str__(self):
            raise RuntimeError("no str")

    tool_use = FakeToolUse("bad", {}, "t1")
    client = FakeClient([FakeResponse("tool_use", [tool_use]), _end_turn("<response>x</response>")])
    conn = FakeConnection({"bad": [Unserialisable()]})
    monkeypatch.setattr(evaluation, "Anthropic", lambda: client)
    asyncio.run(evaluation.agent_loop(client, "model", "q", [], conn))
    content = _tool_result_contents(client, 1)[0]
    assert "Error serialising tool result" in content
    assert "Error executing tool" not in content

    tool_use2 = FakeToolUse("boom", {}, "t2")
    client2 = FakeClient([FakeResponse("tool_use", [tool_use2]), _end_turn("<response>x</response>")])
    conn2 = FakeConnection({"boom": RuntimeError("server died")})
    monkeypatch.setattr(evaluation, "Anthropic", lambda: client2)
    asyncio.run(evaluation.agent_loop(client2, "model", "q", [], conn2))
    content2 = _tool_result_contents(client2, 1)[0]
    assert "Error executing tool" in content2


# --- 3-F2-08: all tool_use blocks ---


def test_all_tool_use_blocks_are_executed(monkeypatch):
    """3-F2-08: only the first tool_use block was processed
    (next(...) in evaluation.py). Both blocks must run, in order,
    with one tool-result each and the ids preserved."""
    first = FakeResponse(
        "tool_use",
        [FakeToolUse("a", {"n": 1}, "t1"), FakeToolUse("b", {"n": 2}, "t2")],
    )
    client = FakeClient([first, _end_turn("<response>done</response>")])
    conn = FakeConnection()
    monkeypatch.setattr(evaluation, "Anthropic", lambda: client)
    asyncio.run(evaluation.agent_loop(client, "model", "q", [], conn))
    assert conn.calls == [("a", {"n": 1}), ("b", {"n": 2})]
    results = _tool_result_contents(client, 1)
    assert len(results) == 2
    # The ids are preserved — but the content strings are JSON, so
    # check the ids on the raw message blocks instead.
    messages = client.messages.calls[1]["messages"]
    blocks = [
        block
        for msg in messages
        if msg.get("role") == "user" and isinstance(msg.get("content"), list)
        for block in msg["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert [b["tool_use_id"] for b in blocks] == ["t1", "t2"]


# --- 3-F2-06: the mcp floor ---


def test_requirements_pin_mcp_minimum():
    """3-F2-06: mcp>=1.1.0 does not have streamable_http, which
    connections.py imports unconditionally. The floor is 1.8.0,
    the lowest version with all three transports (verified by
    testing 1.1.0–1.8.0)."""
    reqs = (HERE / "requirements.txt").read_text(encoding="utf-8")
    assert "mcp>=1.8.0" in reqs
    assert "mcp>=1.1.0" not in reqs


# --- CLI: --min-accuracy and error exits (subprocess, stub modules) ---

_STUB_ANTHROPIC = '''\
class _Text:
    type = "text"
    text = "<response>42</response><summary>s</summary><feedback>f</feedback>"

class _Response:
    stop_reason = "end_turn"
    content = [_Text()]

class _Messages:
    def create(self, **kwargs):
        return _Response()

class Anthropic:
    def __init__(self, *args, **kwargs):
        self.messages = _Messages()
'''

_STUB_CONNECTIONS = '''\
class _Conn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def list_tools(self):
        return []

    async def call_tool(self, name, args):
        return [{"type": "text", "text": "ok"}]

def create_connection(**kwargs):
    return _Conn()
'''


def _cli(tmp_path, *argv):
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    (stubs / "anthropic.py").write_text(_STUB_ANTHROPIC, encoding="utf-8")
    (stubs / "connections.py").write_text(_STUB_CONNECTIONS, encoding="utf-8")
    # Run a COPY of evaluation.py in an otherwise empty dir: the
    # script's own directory is sys.path[0], so running it in place
    # would import the real connections.py (which needs `mcp`)
    # instead of the stub. A fresh run dir per call: _cli is called
    # twice by the threshold test.
    import uuid

    rundir = tmp_path / ("run-" + uuid.uuid4().hex[:8])
    rundir.mkdir()
    script = rundir / "evaluation.py"
    script.write_text((HERE / "evaluation.py").read_text(encoding="utf-8"), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(stubs))
    proc = subprocess.run(
        [sys.executable, str(script), *argv],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=str(rundir),
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_cli_help_lists_min_accuracy(tmp_path):
    """3-F2-09: the CLI enforces a threshold with --min-accuracy
    (default: none — no invented threshold policy)."""
    rc, out = _cli(tmp_path, "--help")
    assert rc == 0, out
    assert "--min-accuracy" in out


def test_cli_malformed_file_exits_1(tmp_path):
    """3-F2-09: a malformed eval file fails the CLI with a
    controlled error and exit 1, not a 0/0 report."""
    bad = tmp_path / "bad.xml"
    bad.write_text("<evaluation><qa_pair>", encoding="utf-8")
    rc, out = _cli(tmp_path, str(bad))
    assert rc == 1, out
    assert "0/0" not in out


def test_cli_min_accuracy_enforced(tmp_path):
    """3-F2-09: accuracy 100 passes --min-accuracy 100 and fails
    --min-accuracy 101."""
    path = _qa_file(tmp_path, [("q", "42")])
    rc, out = _cli(tmp_path, "--min-accuracy", "100", str(path))
    assert rc == 0, out
    rc, out = _cli(tmp_path, "--min-accuracy", "101", str(path))
    assert rc == 1, out
    assert "min-accuracy" in out.lower() or "accuracy" in out.lower()


def test_cli_output_survives_non_utf8_stdout(tmp_path, monkeypatch):
    """Windows: stdout defaults to cp1252, which cannot encode the
    emoji the harness prints (🔗/✅/🚀/📋) or in the report (✅/❌) —
    the CLI used to die with UnicodeEncodeError before doing
    anything. PYTHONIOENCODING=cp1252 reproduces the Windows
    console encoding on Linux. The harness reconfigures stdout /
    stderr to UTF-8, and the report file is written as UTF-8, so
    both survive a non-UTF-8 console."""
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    path = _qa_file(tmp_path, [("q", "42")])
    out_path = tmp_path / "report.md"
    rc, out = _cli(tmp_path, "--min-accuracy", "100", "-o", str(out_path), str(path))
    assert rc == 0, out
    assert "✅" in out_path.read_text(encoding="utf-8")
