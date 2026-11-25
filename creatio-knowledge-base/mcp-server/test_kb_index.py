"""
Checks for the search core. Pure standard library:  python test_kb_index.py
(also collected by pytest).
"""

from pathlib import Path

from kb_index import KnowledgeBase, default_root, tokenize

KB = KnowledgeBase(default_root())


def top(query: str, area: str | None = None) -> str:
    return KB.search(query, area=area, limit=1)[0][0].id


def test_tokenize_splits_dotted_and_camel_and_stems():
    toks = tokenize("crt.OpenLookupPageRequest pagination files")
    assert "crt.openlookuppagerequest" in toks
    assert "lookup" in toks and "page" in toks
    assert tokenize("pagination") == tokenize("paginate")
    assert tokenize("files") == tokenize("file")
    assert tokenize("Freedom UI") == []


def test_index_is_complete_and_headers_parse():
    assert len(KB.recipes) >= 430
    assert KB.recipes["Frontend/Mobile/HowToCreateMobileRequestHandlerModule"].title.startswith("How to create a Mobile SDK")
    assert not KB.skipped, KB.skipped


def test_ranking_on_known_queries():
    assert top("filter a lookup field", "ClassicUI") == "Frontend/ClassicUI/Fields/HowToFilterLookupField"
    assert top("EntitySchemaQuery pagination") == "Backend/C#/ESQ/HowToPaginateWithEntitySchemaQueryOptions"
    assert top("upload file freedom ui", "FreedomUI") == "Frontend/FreedomUI/HowToUploadAndShowFiles"
    # Area words are stopwords, so this must not surface the JS-library recipe.
    assert "Frontend/FreedomUI/HowToUploadAndShowFiles" in [r.id for r, _ in KB.search("upload file freedom ui", limit=2)]
    assert top("event listener prevent save") == "Backend/C#/HowToPreventRecordSaveWithEventListener"
    assert top("mobile request handler module") == "Frontend/Mobile/HowToCreateMobileRequestHandlerModule"
    assert top("custom angular component remote module") == "Frontend/RemoteModule/HowToCreateCustomAngularViewElement"
    assert top("freedom ui request handler remote module scopes") == "Frontend/RemoteModule/HowToCreateRequestHandlerInRemoteModule"
    # Project template folders (package.json inside) are not indexed as recipes.
    assert not [r for r in KB.recipes if "/template/" in r]


def test_clio_area_skills_and_reference():
    assert len(KB.list(area="Clio", topic="reference")) >= 250
    skill = KB.get("clio-sql-and-data")
    assert skill is not None and skill.id == "no-code/clio-sql-and-data" and skill.area == "Clio"
    assert skill.title == "clio: SQL and data" and skill.description.startswith("Read and change Creatio data")
    assert KB.get("execute-sql-script").id == "no-code/reference/execute-sql-script"
    assert top("execute sql script", "Clio") == "no-code/reference/execute-sql-script"
    assert top("run sql script with clio") == "no-code/clio-sql-and-data"
    # Without an area filter a platform question is still answered by a platform recipe.
    assert top("upload file freedom ui").startswith("Backend/") or top("upload file freedom ui").startswith("Frontend/")


def test_tool_readmes_are_their_folders():
    assert KB.get("tools/objects").id == "no-code/tools/objects"
    assert KB.get("sqlscripts").id == "no-code/tools/sqlscripts"
    assert KB.get("creatio_schemas").title == "creatio_schemas"
    assert KB.get("no-code/README") is not None  # the area's own README keeps its name
    for q, want in (("add a column to an object as package files", "tools/objects"), ("rename a schema", "tools/process"),
                    ("create a package sql script view", "tools/sqlscripts"), ("business rule required field page", "tools/rules")):
        ids = [r.id for r, _ in KB.search(q, area="Tools", limit=3)]
        assert any(i.endswith(want) for i in ids), (q, ids)
    assert KB.get("tools/objects").area == "Tools" and "Tools" in KB.areas() and not KB.list(area="Clio", topic="tools")
    # Unfiltered, the toolkit README comes first (they used to be damped as clio pages).
    for q, want in (("scaffold entity", "tools/scaffold"), ("data binding rows", "tools/data"), ("push package", "tools/push"),
                    ("describe schema", "tools/describe")):
        assert top(q).endswith(want), (q, top(q))


def test_get_tolerates_ext_and_bare_name_but_not_ambiguity():
    assert KB.get("Backend/C#/HowToRunBackgroundTask.cs") is not None
    assert KB.get("HowToRunBackgroundTask") is not None
    assert KB.get("HowToFilterLookupField") is None
    assert {r.area for r in KB.same_name("HowToFilterLookupField")} == {"ClassicUI", "FreedomUI"}


def test_find_api_matches_bare_and_dotted():
    ids = [r.id for r, _ in KB.find_api("OpenLookupPageRequest")]
    assert "Frontend/FreedomUI/Navigation/HowToOpenLookupPageAndCreateLinks" in ids


def test_code_style_whole_and_section():
    if not (Path(KB.root) / "CREATIO_CODE_STYLE.md").is_file():
        return
    assert KB.code_style().startswith("# Creatio C# Code Style")
    assert KB.code_style("5").startswith("## 5. Logging")
    assert KB.code_style("review checklist").startswith("## 9.")
    assert KB.code_style("3.8").startswith("### 3.8 ") and "\n## " not in KB.code_style("3.8")  # gap line 11: one sub-section
    assert KB.code_style("3").startswith("## 3. ")
    assert KB.code_style("nonsense") == ""
    if (Path(KB.root) / "CREATIO_FRONTEND_CODE_STYLE.md").is_file():
        assert KB.code_style(guide="frontend").startswith("# Creatio Front-End Code Style")
        assert KB.code_style("review checklist", "frontend").startswith("## ")
    assert KB.code_style(guide="cobol") is None


def test_a_recipe_comes_in_parts():
    from kb_index import PARTS, recipe_part
    assert PARTS == ("summary", "code", "traps", "all")
    # a .cs recipe: the `/// <summary>` block is the header, the rest is the code, no bullet opens with Trap / Verified
    cs = KB.recipes["Backend/C#/API/HowToCreateCustomWebService"]
    summary, code = recipe_part(cs, "summary"), recipe_part(cs, "code")
    assert summary.startswith("Pattern: minimal Creatio custom web service") and "namespace" in summary.lower()
    assert "/// <summary>" not in code and "[ServiceContract]" in code and code.lstrip().startswith("using System;")
    assert recipe_part(cs, "all") == cs.source and recipe_part(cs, "traps") == "(this recipe has no traps part)"
    assert len(summary) + len(code) < len(cs.source) + 50 and len(code) < len(cs.source)
    # a .js recipe: the traps are the header bullets that open with TRAP / VERIFIED / GAP, with their continuation lines
    js = KB.recipes["Frontend/FreedomUI/Data/HowToLoadDataWithSdkModel"]
    traps = recipe_part(js, "traps").splitlines()
    assert traps[0] == "Traps:" and traps[1].startswith("- TRAP (8.x") and "primaryColumnValue" in traps[1] and any(l.startswith("- GAP") for l in traps)
    assert all(l.startswith("- ") or l.startswith("  ") or l == "Traps:" for l in traps), traps
    assert "viewConfigDiff" in recipe_part(js, "code") and "Traps:" not in recipe_part(js, "code")
    # a .md recipe: the text before the first `##`, the fenced blocks, the Traps section
    md = KB.recipes["no-code/clio-sql-and-data"]
    assert recipe_part(md, "summary").startswith("# clio: SQL and data") and "## " not in recipe_part(md, "summary")
    assert recipe_part(md, "code").startswith("```bash") and recipe_part(md, "code").count("```") % 2 == 0
    assert recipe_part(md, "traps").startswith("## Traps (verified)") and "OData after a schema change" in recipe_part(md, "traps")
    assert len(recipe_part(md, "traps")) < len(md.source) / 3
    try:
        recipe_part(md, "nonsense")
    except ValueError as e:
        assert "summary, code, traps, all" in str(e)
    else:
        raise AssertionError("an unknown part")


def test_platform_facts_register_answers_a_platform_question():
    # S29-T01: the facts register wins a fact-shaped question and does not steal a recipe question
    assert top("process must be published") == "no-code/reference/platform-facts"
    assert top("IsChanged before push-pkg") == "no-code/reference/platform-facts"
    assert top("how to filter a lookup field").endswith("HowToFilterLookupField")
    facts = KB.recipes["no-code/reference/platform-facts"]
    assert "P-A4" in facts.source and "## Not verified" in facts.source


def test_every_tool_has_a_home():
    """S41-T01: an agent picks a tool by its name, so each creatio-kb tool is named in a skill or in the operator paragraph of the kit README."""
    import re
    here = Path(__file__).resolve().parent
    names = re.findall(r"@mcp\.tool\(\)\s+def (\w+)\(", (here / "server.py").read_text(encoding="utf-8"))
    skills = "\n".join(p.read_text(encoding="utf-8") for p in (here.parent / "skill").glob("*/SKILL.md"))
    readme = (here.parent.parent / "README.md").read_text(encoding="utf-8")
    at = readme.lower().find("the human's tools")
    operator = readme[at:].split("\n\n", 1)[0] if at >= 0 else ""  # that paragraph only, not the rest of the README
    homeless = [n for n in names if not re.search(rf"`{n}[`(]", skills) and not re.search(rf"`{n}[`(]", operator)]
    assert len(names) > 60 and not homeless, f"tools named in no skill and not in the README operator paragraph: {', '.join(homeless)}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
