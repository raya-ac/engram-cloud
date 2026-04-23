from app.engram_service import schema_name_for_slug, slugify


def test_slugify_basic():
    assert slugify("My Test Workspace") == "my-test-workspace"


def test_schema_name():
    assert schema_name_for_slug("my-test-workspace") == "ws_my_test_workspace"
