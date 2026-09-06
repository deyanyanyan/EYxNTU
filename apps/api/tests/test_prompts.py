from app.core.prompts.service import load_file_defaults, substitute


def test_substitute_leaves_unknown_braces():
    assert substitute("Hello {name}, keep {\"json\": 1}", name="Ada") == 'Hello Ada, keep {"json": 1}'


def test_file_defaults_exist_for_core_tasks():
    for task in ("critique", "quiz", "plan", "slides"):
        ps = load_file_defaults(task)
        assert ps.system_prompt.strip(), f"{task}: empty system prompt"
        assert ps.templates, f"{task}: no templates"
