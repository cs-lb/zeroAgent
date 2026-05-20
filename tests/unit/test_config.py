"""config 加载与环境变量插值测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from zeroagent.config import load_config


def test_load_config_with_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_KEY", "sk-yes")
    cfg_path = tmp_path / "agent.yaml"
    cfg_path.write_text(
        """
llm:
  default: a
  providers:
    a:
      type: openai_compatible
      model: gpt-x
      api_key: ${FAKE_KEY}
      base_url: https://x.test/v1
""".strip(),
        encoding="utf-8",
    )

    cfg = load_config(cfg_path)
    assert cfg.llm.default == "a"
    assert cfg.llm.providers["a"].api_key == "sk-yes"
    assert cfg.llm.providers["a"].base_url == "https://x.test/v1"


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")
