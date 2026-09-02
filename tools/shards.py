"""Раскладка суиты по шардам CI: выдача матрицы и проверка полноты.

Зачем проверка. Шардинг ускоряет прогон, но приносит собственный, очень
неприятный отказ: новый файл тестов, который забыли вписать в раскладку, просто
НЕ ГОНЯЕТСЯ. Прогон при этом зелёный, в отчёте его тестов нет, и заметить это
можно только случайно. Поэтому раскладка лежит в одном файле (tools/shards.json),
workflow берёт матрицу отсюда же, а `check` падает, если хоть один
tests/test_*.py не покрыт или покрыт дважды.

Использование:
    python tools/shards.py check     # проверить полноту (падает с кодом 1)
    python tools/shards.py matrix    # компактный JSON для fromJSON в workflow
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG = Path(__file__).resolve().parent / "shards.json"


def _load() -> dict:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))


def _all_test_files() -> set[str]:
    return {
        p.relative_to(_ROOT).as_posix()
        for p in (_ROOT / "tests").rglob("test_*.py")
        if "__pycache__" not in p.parts
    }


def _expand(paths: list[str], known: set[str]) -> set[str]:
    """Развернуть пути шарда (файл или каталог) в множество файлов тестов."""
    files: set[str] = set()
    for raw in paths:
        if raw.endswith(".py"):
            files.add(raw)
        else:
            files |= {f for f in known if f.startswith(raw.rstrip("/") + "/")}
    return files


def check() -> int:
    config = _load()
    known = _all_test_files()

    covered: set[str] = set(config.get("cart_view_2_only", []))
    seen_twice: set[str] = set()
    for shard in config["shards"]:
        files = _expand(shard["paths"], known)
        seen_twice |= covered & files
        covered |= files

    problems = []

    missing = sorted(known - covered)
    if missing:
        problems.append(
            "Эти файлы тестов НЕ ПОПАЛИ ни в один шард и в CI не гоняются:\n  "
            + "\n  ".join(missing)
            + "\nВпиши их в tools/shards.json — в самый разгруженный шард."
        )

    if seen_twice:
        problems.append(
            "Эти файлы указаны в НЕСКОЛЬКИХ шардах и отработают дважды:\n  "
            + "\n  ".join(sorted(seen_twice))
        )

    phantom = sorted(
        p
        for shard in config["shards"]
        for p in shard["paths"]
        if p.endswith(".py") and p not in known
    )
    if phantom:
        problems.append(
            "В раскладке указаны несуществующие файлы (переименовали/удалили?):\n  "
            + "\n  ".join(phantom)
        )

    if problems:
        print("\n\n".join(problems), file=sys.stderr)
        return 1

    print(f"OK: все {len(known)} файлов тестов разложены по шардам")
    return 0


def matrix() -> int:
    config = _load()
    # В workflow матрица подставляется через fromJSON, поэтому нужен ОДНОСТРОЧНЫЙ
    # компактный JSON: многострочное значение в $GITHUB_OUTPUT не поедет.
    # Пути отдаём строкой — pytest принимает их как есть.
    print(
        json.dumps(
            [
                {
                    "shard": s["shard"],
                    "title": s["title"],
                    "paths": " ".join(s["paths"]),
                }
                for s in config["shards"]
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    if command == "check":
        raise SystemExit(check())
    if command == "matrix":
        raise SystemExit(matrix())
    print(f"неизвестная команда: {command}; ожидается check или matrix", file=sys.stderr)
    raise SystemExit(2)
