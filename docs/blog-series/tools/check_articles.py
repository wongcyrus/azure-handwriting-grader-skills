"""Check inline source fidelity and syntax without importing grader or Azure code."""

import ast
import json
from pathlib import Path
import re

from article_walkthroughs import banner_walkthrough


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parents[1] / "src/handwriting_grader"
articles = {int(path.name[:2]): path.read_text() for path in ROOT.glob("[0-9][0-9]-*.md")}


def tree(name):
    return ast.parse((SOURCE / name).read_text())


def function(name, method):
    return next(node for node in ast.walk(tree(name))
                if isinstance(node, ast.FunctionDef) and node.name == method)


def assignment(node, name):
    return next(item.value for item in ast.walk(node) if isinstance(item, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == name for target in item.targets))


def render(node):
    aliases = {"question['question_text']": "question_text",
               "question['marking_scheme']": "marking_scheme",
               "question['marks']": "maximum_marks", "len(roster_list)": "roster_count"}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(render(value) for value in node.values)
    if isinstance(node, ast.FormattedValue):
        value = ast.unparse(node.value)
        return "{" + aliases.get(value, value) + "}"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return render(node.left) + render(node.right)
    if isinstance(node, ast.Call) and ast.unparse(node.func) == "json.dumps":
        return "{question_and_scheme_json}"
    raise ValueError(f"Unsupported prompt syntax: {ast.dump(node)}")


def expect_prompt(part, prompt):
    blocks = re.findall(r"```text\n(.*?)\n```", articles[part], flags=re.DOTALL)
    assert prompt.strip() in [block.strip() for block in blocks], f"Part {part}: prompt differs from source"


expect_prompt(1, assignment(tree("rubric.py"), "PROMPT").value)
expect_prompt(4, assignment(tree("suggestions.py"), "PROMPT").value)
expect_prompt(5, render(assignment(function("grading.py", "grade"), "prompt")))
expect_prompt(5, render(assignment(function("grading.py", "grade_question_batch"), "prompt")))
metadata = function("grading.py", "ocr_metadata_batch")
roster_branch = next(node for node in metadata.body if isinstance(node, ast.If)
                     and isinstance(node.test, ast.Name) and node.test.id == "roster_list")
suffix = next(node.value for node in roster_branch.body if isinstance(node, ast.AugAssign)
              and isinstance(node.target, ast.Name) and node.target.id == "prompt")
expect_prompt(2, render(assignment(metadata, "prompt")) + render(suffix))
expect_prompt(8, render(assignment(function("advanced.py", "_run_info"), "prompt")))
for method in ("_student_task", "_question_task"):
    expect_prompt(8, assignment(function("advanced.py", method), "task").value)
expect_prompt(8, assignment(function("advanced.py", "create_analysis"), "overview_task").value)

for name in ("build_grading_workflow", "run_grading_workflow"):
    expected = ast.dump(function("workflow.py", name), include_attributes=False)
    blocks = re.findall(r"```python\n(.*?)\n```", articles[6], flags=re.DOTALL)
    definitions = [node for block in blocks for node in ast.walk(ast.parse(block))
                   if isinstance(node, ast.FunctionDef) and node.name == name]
    assert any(ast.dump(node, include_attributes=False) == expected for node in definitions), name

provenance = json.loads((ROOT / "branding/artwork-provenance.json").read_text())
python_blocks = json_blocks = 0
for part, text in articles.items():
    assert banner_walkthrough(text, part, provenance) == text, f"Part {part}: banner section is stale"
    for block in re.findall(r"```python\n(.*?)\n```", text, flags=re.DOTALL):
        ast.parse(block)
        python_blocks += 1
    for block in re.findall(r"```json\n(.*?)\n```", text, flags=re.DOTALL):
        json.loads(block)
        json_blocks += 1
    row = next(item for item in provenance["artworks"] if item["part"] == part)
    expect_prompt(part, (ROOT / "branding" / row["prompt_file"]).read_text())
    assert f"](branding/{row['publication_file']})" in text
observed = (ROOT / "observed/offline-framework-smoke.txt").read_text().strip()
assert observed in articles[6]
smoke = ast.dump(ast.parse((ROOT / "snippets/offline-framework-smoke.py").read_text()),
                 include_attributes=False)
assert any(ast.dump(ast.parse(block), include_attributes=False) == smoke
           for block in re.findall(r"```python\n(.*?)\n```", articles[6], flags=re.DOTALL))
print(f"Verified nine production prompt/task templates, two complete Framework functions, "
      f"the complete offline smoke script, eight actual banner prompts, "
      f"{python_blocks} Python blocks and {json_blocks} JSON blocks.")
