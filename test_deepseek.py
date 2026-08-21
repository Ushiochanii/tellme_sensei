"""Manual Phase 1 smoke test: python test_deepseek.py [question]."""

from __future__ import annotations

import argparse
import sys

from app.config import ConfigError, ConfigManager
from app.logging_config import configure_logging
from app.services.deepseek_service import DeepSeekError, DeepSeekService


def main() -> int:
    parser = argparse.ArgumentParser(description="Test DeepSeek API service")
    parser.add_argument("question", nargs="?", default="RAM 和 ROM 有什么区别？")
    args = parser.parse_args()
    configure_logging()
    try:
        answer = DeepSeekService(ConfigManager().load()).analyze(args.question)
    except (ConfigError, DeepSeekError) as exc:
        print(f"测试失败：{exc}", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
