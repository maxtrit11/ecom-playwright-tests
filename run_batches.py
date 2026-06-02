"""Запуск тестов пофайловыми батчами против stage.ecom.md.

Зачем: прогон всего suite одним залпом (23–53 мин) перегружает stage —
он отвечает 502/таймаутами, и тесты падают ложно. Гоняем файл-за-файлом
с короткой паузой между ними, чтобы stage «дышал». Реальные результаты,
без ложных провалов из-за нагрузки.

Использование:
    python run_batches.py                 # все файлы в tests/
    python run_batches.py --headed        # видимый браузер
    python run_batches.py --pause 15       # пауза между файлами, сек (по умолч. 10)
"""

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

TESTS_DIR = Path(__file__).parent / "tests"
SUMMARY_RE = re.compile(
    r"(?:(\d+) failed)?.*?(?:(\d+) passed)?.*?(?:(\d+) skipped)?.*?"
    r"(?:(\d+) errors?)?.*?(?:(\d+) xfailed)?.*?(?:(\d+) rerun)?",
)


def discover_files() -> list[Path]:
    """Все test_*.py в tests/ (включая подпапки), отсортированы."""
    return sorted(TESTS_DIR.rglob("test_*.py"))


def parse_counts(last_line: str) -> dict:
    """Вытащить passed/failed/skipped/errors/xfailed/rerun из итоговой строки pytest."""
    def grab(word):
        m = re.search(rf"(\d+) {word}", last_line)
        return int(m.group(1)) if m else 0

    return {
        "passed": grab("passed"),
        "failed": grab("failed"),
        "skipped": grab("skipped"),
        "errors": grab("error"),
        "xfailed": grab("xfailed"),
        "rerun": grab("rerun"),
    }


def run_file(path: Path, headed: bool) -> dict:
    rel = path.relative_to(Path(__file__).parent).as_posix()
    cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
           "--tb=line", str(path)]
    if headed:
        cmd.append("--headed")

    start = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    dur = time.time() - start

    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    last = lines[-1] if lines else ""
    counts = parse_counts(last)
    counts.update(file=rel, duration=dur, last=last)
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true", help="видимый браузер")
    ap.add_argument("--pause", type=int, default=10,
                    help="пауза между файлами, сек (даём stage отдышаться)")
    args = ap.parse_args()

    files = discover_files()
    print(f"Найдено файлов: {len(files)}. Пауза между ними: {args.pause}s. "
          f"Headed: {args.headed}\n")

    results = []
    t0 = time.time()
    for i, f in enumerate(files, 1):
        rel = f.relative_to(Path(__file__).parent).as_posix()
        print(f"[{i}/{len(files)}] {rel} ...", flush=True)
        r = run_file(f, args.headed)
        results.append(r)
        print(f"      {r['last']}  ({r['duration']:.0f}s)\n", flush=True)
        if i < len(files):
            time.sleep(args.pause)

    total = time.time() - t0

    # ---- Итоговый отчёт ----
    print("=" * 78)
    print("СВОДНЫЙ ОТЧЁТ (батчи пофайлово)")
    print("=" * 78)
    name_w = max(len(r["file"]) for r in results)
    agg = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0,
           "xfailed": 0, "rerun": 0}
    for r in results:
        for k in agg:
            agg[k] += r[k]
        flag = "OK" if (r["failed"] == 0 and r["errors"] == 0) else "<-- ВНИМАНИЕ"
        print(f"{r['file']:<{name_w}}  "
              f"P:{r['passed']:<3} F:{r['failed']:<3} E:{r['errors']:<3} "
              f"S:{r['skipped']:<3} rr:{r['rerun']:<3} {r['duration']:>5.0f}s  {flag}")

    print("-" * 78)
    print(f"ИТОГО за {total/60:.1f} мин:  "
          f"{agg['passed']} passed / {agg['failed']} failed / "
          f"{agg['errors']} errors / {agg['skipped']} skipped / "
          f"{agg['xfailed']} xfailed  (reruns: {agg['rerun']})")

    # Файлы с проблемами — крупно, чтобы сразу видеть
    problem = [r for r in results if r["failed"] or r["errors"]]
    if problem:
        print("\nФайлы с падениями (проверить через MCP перед вердиктом):")
        for r in problem:
            print(f"  - {r['file']}: {r['failed']} failed, {r['errors']} errors")
    else:
        print("\nВсе файлы зелёные.")


if __name__ == "__main__":
    main()
