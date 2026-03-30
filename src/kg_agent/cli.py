from __future__ import annotations

import argparse
import os
import sys

from .config import load_config
from .graph import build_agent


def _load_dotenv(path: str) -> None:
    if not path or not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as fp:
        for raw_line in fp:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            env_key = key.strip()
            env_value = value.strip()

            if not env_key:
                continue

            if env_value.startswith(("\"", "'")) and env_value.endswith(("\"", "'")) and len(env_value) >= 2:
                env_value = env_value[1:-1]

            os.environ.setdefault(env_key, env_value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LangGraph agent with tool/mcp/skill loading")
    parser.add_argument("--config", default="agent.yaml", help="Path to YAML config file")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser.add_argument("--message", default="", help="Run single-turn message and exit")
    parser.add_argument("--thread-id", default="default", help="Conversation thread id")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    _load_dotenv(args.env_file)

    config_path = args.config if os.path.exists(args.config) else None
    config = load_config(config_path)

    if not os.environ.get(config.api_key_env):
        print(f"{config.api_key_env} is required.", file=sys.stderr)
        sys.exit(1)

    runtime = build_agent(config)

    if runtime.warnings:
        print("[warnings]")
        for warning in runtime.warnings:
            print(f"- {warning}")

    if args.message:
        print(runtime.ask(args.message, thread_id=args.thread_id))
        return

    print("KG LangGraph Agent is ready. Type 'exit' to quit.")
    while True:
        try:
            user_input = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye")
            return

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Bye")
            return

        answer = runtime.ask(user_input, thread_id=args.thread_id)
        print(f"\nAgent> {answer}")


if __name__ == "__main__":
    main()
