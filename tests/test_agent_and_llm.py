import pytest

from autodocs.agent import ExplorerAgent, normalize_notes
from autodocs.llm import FallbackLLM, LLMError, _retry_wait, chat_json, extract_json
from autodocs.tools import RepoTools
from tests.conftest import NOTES, ScriptedLLM


@pytest.mark.parametrize("text", [
    '{"a": 1}',
    'Here you go:\n```json\n{"a": 1}\n```',
    'Sure! {"a": 1} hope that helps',
    '{"a": 1,}',
    '{"a": "brace } in a string \\" quote", "b": 1}',
])
def test_extract_json_handles_messy_replies(text):
    assert extract_json(text)["a"] in (1, "brace } in a string \" quote")


def test_extract_json_raises_without_json():
    with pytest.raises(ValueError):
        extract_json("no json here")


class Broken:
    name = "broken"

    def chat(self, *a, **k):
        raise LLMError("503 overloaded")


class Echo:
    name = "echo"

    def chat(self, messages, *a, **k):
        return '{"ok": true}'


def test_fallback_switches_to_backup_and_reports_it():
    switched = []
    llm = FallbackLLM([Broken(), Echo()], on_switch=switched.append)
    assert chat_json(llm, [{"role": "user", "content": "hi"}]) == {"ok": True}
    assert llm.last_used == "echo" and switched


def test_fallback_raises_when_everything_fails():
    with pytest.raises(LLMError, match="All models failed"):
        FallbackLLM([Broken()]).chat([{"role": "user", "content": "x"}])


def test_retry_rules():
    class E(Exception):
        def __init__(self, code, msg=""):
            super().__init__(msg)
            self.status_code = code
    assert _retry_wait(E(401), 0) is None                     # bad key: don't retry
    assert _retry_wait(E(429, "try again in 2.5s"), 0) == 3.5   # Groq tells us how long
    assert _retry_wait(E(429, "try again in 3600s"), 0) is None  # daily limit: go to backup
    assert _retry_wait(E(503), 0) == 5 and _retry_wait(E(503), 2) == 20


def test_agent_explores_then_finishes(sample_repo):
    tools = RepoTools(sample_repo)
    llm = ScriptedLLM()
    res = ExplorerAgent(llm, tools, max_steps=6).run("summary")
    assert res.finished_cleanly
    assert [s["action"] for s in res.steps] == ["list_dir", "read_file", "search"]
    assert res.files_read == ["shop/main.py"]
    assert res.notes["purpose"] == NOTES["purpose"]
    # the tool results were fed back to the model
    assert any("include_router" in p for p in llm.prompts)


def test_agent_recovers_from_bad_json_and_step_limit(sample_repo):
    actions = ["I think I'll read a file", {"action": "read_file", "args": {"path": "README.md"}},
               {"action": "read_file", "args": {"path": "shop/main.py"}},
               {"action": "finish", "args": {"notes": {"purpose": "forced"}}}]
    res = ExplorerAgent(ScriptedLLM(actions), RepoTools(sample_repo), max_steps=2).run("summary")
    assert len(res.steps) == 2 and res.notes["purpose"] == "forced"


def test_tools_stay_inside_the_repo(sample_repo):
    t = RepoTools(sample_repo)
    assert "outside" in t.run("read_file", {"path": "../../etc/passwd"})
    assert "does not exist" in t.run("read_file", {"path": "nope.py"})
    assert "unknown action" in t.run("rm_rf", {})
    assert "shop/routers/items.py:" in t.run("search", {"pattern": "APIRouter", "glob": "*.py"})
    assert "   1 | " in t.run("read_file", {"path": "shop/main.py", "start_line": 1, "end_line": 3})


def test_normalize_notes_fixes_wrong_shapes():
    n = normalize_notes({"purpose": ["a", "b"], "features": "one", "components": [{"name": "X", "path": "x.py"}, "junk"]})
    assert n["purpose"] == "a b" and n["features"] == ["one"]
    assert n["components"] == [{"name": "X", "paths": ["x.py"], "responsibility": ""}]
    assert n["gotchas"] == []


def test_fit_messages_shrinks_the_middle_first():
    from autodocs.llm import fit_messages
    msgs = [{"role": "system", "content": "S" * 100}, {"role": "user", "content": "A" * 5000},
            {"role": "assistant", "content": "B" * 200}, {"role": "user", "content": "LAST" * 100}]
    out = fit_messages(msgs, 2000)
    assert out[0] == msgs[0] and out[-1] == msgs[-1]
    assert sum(len(m["content"]) for m in out) <= 2100
    assert msgs[1]["content"] == "A" * 5000  # original not modified


def test_build_llm_skips_providers_without_keys():
    from autodocs.config import Settings
    from autodocs.llm import build_llm
    llm = build_llm(Settings(gemini_api_key="", groq_api_key="k"))
    assert llm.name == "groq:openai/gpt-oss-20b"
    assert llm.models[0].max_input_chars == 20_000 and llm.models[0].reasoning_effort == "low"


def test_groq_tool_call_errors_are_turned_back_into_answers():
    import json
    from autodocs.llm import recover_tool_call

    class Bad(Exception):
        def __init__(self, gen):
            self.body = {"error": {"code": "tool_use_failed", "failed_generation": gen}}
    a = json.loads(recover_tool_call(Bad('{"name": "read_file", "arguments": {"path": "app/main.py"}}')))
    assert a == {"thought": "", "action": "read_file", "args": {"path": "app/main.py"}}
    b = json.loads(recover_tool_call(Bad('{"name": "json", "arguments": {"action": "finish", "args": {}}}')))
    assert b["action"] == "finish"
    c = json.loads(recover_tool_call(Bad('{"name": "json", "arguments": {"README": "x"}}')))
    assert c == {"README": "x"}
    assert recover_tool_call(Exception("other")) is None
