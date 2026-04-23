from app.config import settings
from app.engram_service import schema_name_for_slug, slugify, workspace_engram_dsn


def test_slugify_basic():
    assert slugify("My Test Workspace") == "my-test-workspace"


def test_schema_name():
    assert schema_name_for_slug("my-test-workspace") == "ws_my_test_workspace"


def test_workspace_engram_dsn_encoding():
    dsn = workspace_engram_dsn("ws_my_test_workspace")

    assert dsn.startswith(settings.engram_postgres_dsn)
    assert "options=-c%20search_path%3Dws_my_test_workspace" in dsn
    assert "+search_path" not in dsn
