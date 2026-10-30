"""Tests for layered TOML settings: layers, validation, reserved keys and errors (ADR-051)."""

import os
from pathlib import Path

import pytest

from sugo.config import settings as settings_module
from sugo.config.settings import ENVIRONMENT, ConfigError, Settings, default_languages, load


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No real user file, no SUGO_* variables, English system locale."""
    user = tmp_path / "user" / "config.toml"
    monkeypatch.setattr(settings_module, "user_config_path", lambda: user)
    for variable in ENVIRONMENT:
        monkeypatch.delenv(variable, raising=False)
    for variable in ("LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    project = tmp_path / "project"
    project.mkdir()
    return user


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_without_any_file(tmp_path: Path) -> None:
    loaded = load(cwd=tmp_path / "project")
    assert loaded.settings.cleaning == Settings().cleaning
    assert loaded.settings.storage == Settings().storage
    assert loaded.settings.languages == ("en",)
    assert loaded.sources == ()


def test_system_language_is_added_to_english(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANG", "it_IT.UTF-8")
    assert default_languages() == ("en", "it")
    monkeypatch.setenv("LANG", "ja_JP.UTF-8")  # no pack yet: English only
    assert default_languages() == ("en",)


def test_layers_override_in_order(
    isolated: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(isolated, '[general]\nlanguages = ["it"]\n[chunking]\nmax_tokens = 300\n')
    project = tmp_path / "project"
    write(project / "sugo.toml", "[chunking]\nmax_tokens = 400\n")
    monkeypatch.setenv("SUGO_STRIP_TRACKING_URLS", "false")
    loaded = load(cwd=project)
    assert loaded.settings.languages == ("it",)
    assert loaded.settings.chunking.max_tokens == 400
    assert loaded.settings.cleaning.strip_tracking_urls is False
    assert loaded.sources == (isolated, project / "sugo.toml")
    monkeypatch.setenv("SUGO_CHUNK_MAX_TOKENS", "600")
    assert load(cwd=project).settings.chunking.max_tokens == 600


def test_project_table_in_pyproject(tmp_path: Path) -> None:
    project = tmp_path / "project"
    write(
        project / "pyproject.toml",
        '[project]\nname = "x"\n[tool.sugo.storage]\ncache = "ephemeral"\n',
    )
    assert load(cwd=project).settings.storage.cache == "ephemeral"


def test_sugo_toml_wins_over_pyproject(tmp_path: Path) -> None:
    project = tmp_path / "project"
    write(project / "sugo.toml", '[storage]\ncache = "persistent"\n')
    write(project / "pyproject.toml", '[tool.sugo.storage]\ncache = "ephemeral"\n')
    assert load(cwd=project).settings.storage.cache == "persistent"


def test_broken_pyproject_of_another_tool_is_only_a_warning(tmp_path: Path) -> None:
    project = tmp_path / "project"
    write(project / "pyproject.toml", "[project\n")
    loaded = load(cwd=project)
    assert loaded.sources == ()
    assert any("[tool.sugo] ignored" in warning for warning in loaded.warnings)


def test_project_file_in_a_parent_folder_is_not_read(tmp_path: Path) -> None:
    write(tmp_path / "sugo.toml", '[storage]\ncache = "ephemeral"\n')
    assert load(cwd=tmp_path / "project").settings.storage.cache == "persistent"


def test_mcp_layer_reads_the_user_file_only(
    isolated: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(isolated, '[general]\nlanguages = ["fr"]\n')
    project = tmp_path / "project"
    write(project / "sugo.toml", '[general]\nlanguages = ["de"]\n')
    monkeypatch.setenv("SUGO_LANGUAGES", "es")
    loaded = load(cwd=project, project=False, environment=False)
    assert loaded.settings.languages == ("fr",)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[clening]\nx = 1\n", "clening"),  # a typo is never ignored
        ("[storage]\ncache = 'disk'\n", "storage.cache"),
        ("[general]\nlanguages = ['xx']\n", "general.languages"),
        ("[general]\nlanguages = []\n", "general.languages"),
        ("[chunking]\nmax_tokens = 8\n", "chunking.max_tokens"),
        ("[chunking]\nmax_tokens = '512'\n", "chunking.max_tokens"),
        ("[cleaning]\nstrip_tracking_urls = 'yes'\n", "cleaning.strip_tracking_urls"),
        ("storage = 3\n", "storage"),
        ("[storage\n", "not valid TOML"),
    ],
)
def test_invalid_files_stop_with_file_and_key(isolated: Path, text: str, expected: str) -> None:
    write(isolated, text)
    with pytest.raises(ConfigError, match=expected) as error:
        load()
    assert str(isolated) in str(error.value)
    assert error.value.code == "CONFIG_INVALID"


def test_errors_never_quote_the_value(isolated: Path) -> None:
    write(isolated, '[storage]\ncache = "secret-value"\n')
    with pytest.raises(ConfigError) as error:
        load()
    assert "secret-value" not in str(error.value)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("SUGO_STRIP_TRACKING_URLS", "maybe"),
        ("SUGO_CHUNK_MAX_TOKENS", "many"),
        ("SUGO_CACHE", "disk"),
        ("SUGO_LANGUAGES", "it,xx"),
        ("SUGO_UI_LANGUAGE", "klingon"),
    ],
)
def test_invalid_variables_are_named(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ConfigError) as error:
        load()
    assert variable in str(error.value)
    assert value not in str(error.value)


def test_reserved_keys_only_warn(isolated: Path) -> None:
    write(isolated, '[general]\nlevel = "normal"\n[privacy]\noffline = true\n')
    loaded = load()
    assert loaded.settings.cleaning == Settings().cleaning
    assert len(loaded.warnings) == 2
    assert all("not used in this version" in warning for warning in loaded.warnings)


def test_oversized_file_is_refused(isolated: Path) -> None:
    write(isolated, "# " + "x" * settings_module.MAX_CONFIG_BYTES)
    with pytest.raises(ConfigError, match="larger than"):
        load()


def test_languages_are_sorted_and_unique(isolated: Path) -> None:
    write(isolated, '[general]\nlanguages = ["it", "en", "it"]\n')
    assert load().settings.languages == ("en", "it")


def test_unsearchable_configuration_folder_is_a_config_error(
    isolated: Path, tmp_path: Path
) -> None:
    folder = isolated.parent
    folder.mkdir(parents=True)
    folder.chmod(0)
    try:
        if os.access(folder, os.X_OK):
            pytest.skip("running with privileges that ignore permissions")
        with pytest.raises(ConfigError, match="cannot be read"):
            load(cwd=tmp_path / "project")
    finally:
        folder.chmod(0o700)


def test_non_utf8_file_does_not_quote_the_byte(isolated: Path) -> None:
    isolated.parent.mkdir(parents=True)
    isolated.write_bytes(b"[general]\nx = '\xff'\n")
    with pytest.raises(ConfigError, match=r"not UTF-8 \(byte \d+\)") as error:
        load()
    assert "0xff" not in str(error.value)


def test_control_characters_in_keys_are_not_printed(isolated: Path) -> None:
    write(isolated, '[general]\n"\\u001b]52;c;QQ==\\u0007" = 1\n')
    with pytest.raises(ConfigError) as error:
        load()
    assert all(char.isprintable() for char in str(error.value))


def test_mcp_view_ignores_the_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANG", "it_IT.UTF-8")
    assert load(project=False, environment=False).settings.languages == ("en",)
    assert load().settings.languages == ("en", "it")


def test_chunk_size_has_an_upper_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUGO_CHUNK_MAX_TOKENS", "99999999999999999999999")
    with pytest.raises(ConfigError, match="SUGO_CHUNK_MAX_TOKENS"):
        load()
