import pytest

from app.orchestrator.files import clean_path, parse_build_reply
from app.orchestrator.protocol import ReplyError

HEAD = '{"stance": "report", "reply_to": null, "content": "Built it."}\n'


def block(path, body):
    return f"=== FILE: {path} ===\n{body}\n=== END FILE ===\n"


def test_parses_json_then_files_with_braces_inside():
    css = "body { color: red; }\n.a { margin: 0 }"
    js = 'document.querySelector("b").addEventListener("click", () => { alert("{}"); });'
    reply, files = parse_build_reply(HEAD + block("site/styles.css", css) + block("site/script.js", js))
    assert reply.content == "Built it."
    assert [f.path for f in files] == ["site/styles.css", "site/script.js"]
    assert files[0].content == css + "\n" and "{}" in files[1].content


def test_reply_without_files_is_fine():
    reply, files = parse_build_reply(HEAD)
    assert files == [] and reply.stance == "report"


@pytest.mark.parametrize("path", ["../etc/passwd", "/site/index.html", "site/../../x.html", "index.html",
                                  "site/app.py", "site/.env", "src/index.html", "site/run.sh"])
def test_rejects_bad_paths(path):
    with pytest.raises(ReplyError):
        clean_path(path)


def test_normalises_ok_paths():
    assert clean_path(" `site/css/main.css` ") == "site/css/main.css"
    assert clean_path("docs\\plan.md") == "docs/plan.md"


def test_rejects_cut_off_block():
    with pytest.raises(ReplyError, match="END FILE"):
        parse_build_reply(HEAD + "=== FILE: site/index.html ===\n<html>")


def test_rejects_duplicates_and_huge_files():
    with pytest.raises(ReplyError, match="twice"):
        parse_build_reply(HEAD + block("site/a.html", "x") + block("site/a.html", "y"))
    with pytest.raises(ReplyError, match="too large"):
        parse_build_reply(HEAD + block("site/a.html", "x" * 200_000))
