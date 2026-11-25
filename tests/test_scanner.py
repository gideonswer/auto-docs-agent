from autodocs.scanner import build_tree, parse_env_example, repo_summary, scan_repo


def test_finds_routes_with_router_and_app_prefixes(sample_repo):
    rm = scan_repo(sample_repo, "shop-api")
    ids = {r.id for r in rm.routes}
    assert {"GET /api/items", "POST /api/items", "GET /api/items/{item_id}", "GET /health"} <= ids
    assert "GET /hello/:name" in ids  # Express route


def test_detects_login_through_nested_dependencies(sample_repo):
    rm = scan_repo(sample_repo, "shop-api")
    auth = {r.id: r.auth for r in rm.routes}
    assert auth["GET /api/items"] is False
    assert auth["GET /api/items/{item_id}"] is True   # Depends(get_current_user)
    assert auth["POST /api/items"] is True            # Depends(require_admin) -> get_current_user


def test_env_vars_from_example_file_and_settings_class(sample_repo):
    rm = scan_repo(sample_repo, "shop-api")
    env = {e.name: e for e in rm.env_vars}
    assert env["SECRET_KEY"].comment == "Secret used to sign login tokens"
    assert env["DATABASE_URL"].default == "sqlite:///shop.db"   # from BaseSettings field
    assert "PORT" in env                                          # from process.env in JS


def test_run_commands_dependencies_and_schemas(sample_repo):
    rm = scan_repo(sample_repo, "shop-api")
    assert "uvicorn shop.main:app --reload" in rm.run_commands
    assert "npm run dev" in rm.run_commands
    assert "fastapi" in rm.dependencies["Python"] and "express" in rm.dependencies["JavaScript"]
    assert [f[0] for f in rm.schemas["ItemIn"]] == ["name", "price", "tags"]
    assert rm.has_tests and rm.license == "MIT License"


def test_import_graph_keeps_internal_modules_only(sample_repo):
    rm = scan_repo(sample_repo, "shop-api")
    mods = {m.name: m.imports for m in rm.modules}
    assert "shop.routers.items" in mods["shop.main"]
    assert set(mods["shop.routers.items"]) == {"shop.auth", "shop.schemas"}
    assert "web/lib/greet" in mods["web/server"]


def test_binary_files_are_listed_but_not_read(sample_repo):
    rm = scan_repo(sample_repo, "shop-api")
    png = next(f for f in rm.files if f.path == "logo.png")
    assert png.language == "Binary/large"


def test_summary_is_trimmed():
    from autodocs.models import RepoMap
    rm = RepoMap(name="x", url=None, root=".", tree="\n".join(f"file{i}.py" for i in range(5000)))
    assert len(repo_summary(rm, max_chars=2000)) < 2200


def test_env_example_parsing_resets_comments():
    env = parse_env_example("# Key A\nA=1\nB=2  # inline\n\nexport C='x'\n", ".env.example")
    assert [(e.name, e.default, e.comment) for e in env] == [("A", "1", "Key A"), ("B", "2", ""), ("C", "x", "")]


def test_tree_is_capped():
    tree = build_tree([f"d{i}/f.py" for i in range(200)], max_entries=10)
    assert tree.count("\n") <= 11 and tree.endswith("...")
