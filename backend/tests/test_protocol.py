import pytest

from app.orchestrator import sandbox
from app.orchestrator.protocol import ReplyError, Stance, parse_reply


def test_parses_fenced_json_with_chatter():
    text = 'Sure!\n```json\n{"stance": "Agree", "reply_to": "m2", "content": "Yes."}\n```'
    reply = parse_reply(text)
    assert reply.stance == Stance.AGREE
    assert reply.reply_to == "m2"


def test_null_strings_and_numeric_targets_are_normalised():
    reply = parse_reply('{"stance":"vote","reply_to":"null","content":"x","votes":[{"target":3}]}')
    assert reply.reply_to is None
    assert reply.votes[0].target == "3"


@pytest.mark.parametrize("text", ["no json here", '{"stance": "shout", "content": "x"}', "{bad"])
def test_invalid_replies_raise(text):
    with pytest.raises(ReplyError):
        parse_reply(text)


@pytest.mark.parametrize("path", ["../escape.txt", "a/../../escape.txt", "/etc/passwd"])
def test_sandbox_rejects_paths_outside_run(env, path):
    with pytest.raises(sandbox.SandboxError):
        sandbox.safe_path("run1", path)


def test_sandbox_rejects_bad_run_id(env):
    with pytest.raises(sandbox.SandboxError):
        sandbox.run_dir("../other")


def test_sandbox_allows_nested_paths(env):
    p = sandbox.write_text("run1", "notes/a.md", "hi")
    assert p.read_text() == "hi"
    assert p.is_relative_to(env / "projects" / "run1")
