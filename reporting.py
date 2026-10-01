"""Оформление результатов прогона: терминал, HTML-отчёт, сводка в GitHub Actions.

Отдельный модуль, а не часть conftest.py: conftest отвечает за ПОВЕДЕНИЕ тестов
(гидрация, таймауты, оверлеи), здесь — только ПРЕДСТАВЛЕНИЕ результатов.
Подключается из корневого conftest через `pytest_plugins`.

Что делает:
1. Достаёт человеческое имя кейса. Тесты называются `test_close_cart_via_x_button`,
   а над каждым стоит баннер `# Кейс 106: Закрыть блок Корзина ...` — в отчёте
   полезен именно он, поэтому вытаскиваем его из исходника и кладём в отдельную
   колонку. Название блока берём из докстринга модуля.
2. Схлопывает попытки. С `--reruns` один тест даёт несколько отчётов, и в сводке
   он двоился. Теперь на тест — одна строка: итог последней попытки, суммарное
   время и пометка «флак», если упал и прошёл с повтора (это отдельный сигнал:
   не баг продукта, но и не «всё хорошо»).
3. Пишет сводку в `$GITHUB_STEP_SUMMARY` — прямо на страницу прогона в Actions,
   без скачивания артефакта: счётчики, упавшие с хвостом ошибки, флаки,
   пропущенные с причинами, разбивка по блокам. Плюс `::error`-аннотации, чтобы
   упавшие кейсы были видны в шапке job'а.

Любая ошибка форматирования отчёта не должна ронять прогон — весь вывод обёрнут
в try/except: результаты тестов важнее их оформления.
"""

from __future__ import annotations

import functools
import html
import os
import re
import sys
import time
from collections import OrderedDict

import pytest

# ---------------------------------------------------------------------------
# Человеческие названия: «Кейс 106: ...» из баннера над тестом
# ---------------------------------------------------------------------------
_CASE_RE = re.compile(r"^#\s*(Кейс\s*\d+.*?)\s*$")
# Насколько высоко над `def` ищем баннер: между ними бывают декораторы,
# комментарии-разделители и пустые строки, но не десятки строк.
_BANNER_LOOKUP_DEPTH = 25


@functools.lru_cache(maxsize=None)
def _source_lines(path: str) -> tuple[str, ...]:
    try:
        with open(path, encoding="utf-8") as fh:
            return tuple(fh.read().splitlines())
    except OSError:
        return ()


@functools.lru_cache(maxsize=None)
def _case_title(path: str, lineno: int) -> str:
    """Текст `# Кейс N: ...` из комментария над функцией теста (или '')."""
    lines = _source_lines(path)
    if not lines:
        return ""
    start = min(lineno, len(lines)) - 1
    for i in range(start - 1, max(start - _BANNER_LOOKUP_DEPTH, -1), -1):
        line = lines[i].strip()
        if not line or line.startswith("@") or line.startswith("def "):
            continue
        if not line.startswith("#"):
            break  # дошли до чужого кода — своего баннера у теста нет
        match = _CASE_RE.match(line)
        if match:
            return match.group(1)
    return ""


@functools.lru_cache(maxsize=None)
def _suite_from_doc(doc: str, fallback: str) -> str:
    """Название блока из первой строки докстринга модуля.

    «Тесты блока «Корзина» (Qase suite 18: ...)» → «Тесты блока «Корзина»».
    """
    first = (doc or "").strip().splitlines()[0].strip() if (doc or "").strip() else ""
    first = re.sub(r"\s*\(.*$", "", first).rstrip(". ")
    return first or fallback


def _titles(item) -> tuple[str, str]:
    """(блок, кейс) для теста. Ошибки интроспекции гасим — отчёт не должен падать."""
    suite = case = ""
    try:
        module = getattr(item, "module", None)
        suite = _suite_from_doc(getattr(module, "__doc__", "") or "", item.path.stem)
    except Exception:
        suite = ""
    try:
        code = item.function.__code__
        # Файл, где функция ОБЪЯВЛЕНА, а не где собрана: мобильная суита
        # импортирует десктопные тесты целиком, и номер строки относится к
        # десктопному файлу, а item.path указывает на мобильный.
        case = _case_title(code.co_filename, code.co_firstlineno)
    except Exception:
        case = ""
    return suite, case


# ---------------------------------------------------------------------------
# Сбор результатов: одна запись на тест, попытки схлопнуты
# ---------------------------------------------------------------------------
_records: "OrderedDict[str, dict]" = OrderedDict()

_ICONS = {"passed": "✅", "failed": "❌", "error": "🔥", "skipped": "⏭"}
_ASCII_ICONS = {"passed": "[OK]", "failed": "[FAIL]", "error": "[ERR]", "skipped": "[SKIP]"}


def _skip_reason(report) -> str:
    longrepr = getattr(report, "longrepr", None)
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2]).replace("Skipped: ", "")
    return str(getattr(report, "wasxfail", "") or "")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    suite, case = _titles(item)
    # Кладём на report — отсюда их заберут хуки таблицы pytest-html.
    report.suite_title = suite
    report.case_title = case

    rec = _records.get(report.nodeid)
    if rec is None:
        rec = _records[report.nodeid] = {
            "nodeid": report.nodeid,
            "name": item.name,
            "file": str(getattr(report, "fspath", "") or ""),
            "lineno": (getattr(report, "location", None) or (None, 0, None))[1] or 0,
            "suite": suite,
            "case": case,
            "outcome": "passed",
            "duration": 0.0,
            "attempts": 0,
            "error": "",
            "reason": "",
        }
    rec["duration"] += report.duration

    # Считаем попытки по фазе setup: она выполняется ровно раз на попытку.
    # На сам флаг "rerun" полагаться нельзя — pytest-rerunfailures проставляет
    # его уже ПОСЛЕ makereport, здесь у отчёта ещё честный outcome "failed".
    if report.when == "setup":
        rec["attempts"] += 1
    if report.outcome == "rerun":
        return

    if report.when == "call":
        rec["outcome"] = report.outcome
        if report.failed:
            rec["error"] = report.longreprtext
        elif report.skipped:
            rec["reason"] = _skip_reason(report)
        else:
            rec["error"] = ""  # прошёл с повтора — ошибка прошлой попытки неактуальна
    elif report.when == "setup":
        if report.skipped:
            rec["outcome"] = "skipped"
            rec["reason"] = _skip_reason(report)
        elif report.failed:
            # Падение фикстуры — это ERROR, а не проваленная проверка.
            rec["outcome"] = "error"
            rec["error"] = report.longreprtext
    elif report.when == "teardown" and report.failed and rec["outcome"] == "passed":
        rec["outcome"] = "error"
        rec["error"] = report.longreprtext


def _stats() -> dict:
    recs = list(_records.values())
    return {
        "records": recs,
        "total": len(recs),
        "passed": sum(1 for r in recs if r["outcome"] == "passed"),
        "failed": sum(1 for r in recs if r["outcome"] == "failed"),
        "error": sum(1 for r in recs if r["outcome"] == "error"),
        "skipped": sum(1 for r in recs if r["outcome"] == "skipped"),
        "flaky": sum(1 for r in recs if r["attempts"] > 1 and r["outcome"] == "passed"),
        "duration": sum(r["duration"] for r in recs),
    }


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}м {seconds % 60:02d}s"
    return f"{seconds // 3600}ч {(seconds % 3600) // 60:02d}м"


def _plural_tests(n: int) -> str:
    """«1 тест / 2 теста / 5 тестов» — иначе в шапке отчёта висит «4 тестов»."""
    if 11 <= n % 100 <= 14:
        return "тестов"
    return {1: "тест", 2: "теста", 3: "теста", 4: "теста"}.get(n % 10, "тестов")


def _label(rec: dict) -> str:
    """Что показывать вместо `test_close_cart_via_x_button`."""
    return rec["case"] or rec["name"]


# ---------------------------------------------------------------------------
# Терминальная сводка
# ---------------------------------------------------------------------------
def _supports_unicode() -> bool:
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not _records:
        return

    unicode_ok = _supports_unicode()
    icons = _ICONS if unicode_ok else _ASCII_ICONS
    stats = _stats()
    tr = terminalreporter
    tr.write_sep("=", "Сводка по тест-кейсам" if unicode_ok else "Test cases summary", bold=True)

    width = max([len(_label(r)) for r in stats["records"]] + [30])
    width = min(width, 70)
    for i, rec in enumerate(stats["records"], 1):
        icon = icons.get(rec["outcome"], "?")
        flak = ("  🔁 флак" if unicode_ok else "  (flaky)") if rec["attempts"] > 1 and rec["outcome"] == "passed" else ""
        tr.write_line(f"{i:>3}. {icon} {_label(rec)[:width]:<{width}}  {rec['duration']:>6.2f}s{flak}")

    tr.write_sep("-")
    parts = [
        f"{stats['passed']} {icons['passed']}",
        f"{stats['failed']} {icons['failed']}",
        f"{stats['error']} {icons['error']}",
        f"{stats['skipped']} {icons['skipped']}",
    ]
    if stats["flaky"]:
        parts.append(f"{stats['flaky']} 🔁" if unicode_ok else f"{stats['flaky']} flaky")
    if unicode_ok:
        tr.write_line(f"   Итого: {stats['total']} за {_fmt_duration(stats['duration'])} — " + " / ".join(parts))
    else:
        tr.write_line(f"   Total: {stats['total']} in {_fmt_duration(stats['duration'])} -- " + " / ".join(parts))

    try:
        _write_github_summary(config, stats)
    except Exception as exc:  # оформление отчёта не должно ронять прогон
        tr.write_line(f"   (сводка для GitHub не записана: {exc})")


# ---------------------------------------------------------------------------
# Сводка на странице прогона в GitHub Actions ($GITHUB_STEP_SUMMARY)
# ---------------------------------------------------------------------------
_MAX_DETAILED_FAILURES = 40      # ниже — только строкой в таблице
_MAX_ERROR_LINES = 25            # хвост трейсбека: причина обычно в конце
_MAX_ANNOTATIONS = 20            # ::error-аннотации в шапке job'а


def _error_tail(text: str) -> str:
    lines = [ln.rstrip() for ln in (text or "").strip().splitlines() if ln.strip()]
    if not lines:
        return "(без текста ошибки)"
    tail = lines[-_MAX_ERROR_LINES:]
    return "\n".join(tail)[:4000]


def _md(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _write_github_summary(config, stats: dict) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return

    recs = stats["records"]
    broken = [r for r in recs if r["outcome"] in ("failed", "error")]
    flaky = [r for r in recs if r["attempts"] > 1 and r["outcome"] == "passed"]
    skipped = [r for r in recs if r["outcome"] == "skipped"]

    out: list[str] = []
    verdict = "❌ есть падения" if broken else ("⚠️ прошло с оговорками" if flaky else "✅ всё зелёное")
    out.append(f"## Результаты E2E — {verdict}")
    out.append("")
    out.append(
        f"**{stats['total']}** {_plural_tests(stats['total'])} за **{_fmt_duration(stats['duration'])}**"
    )
    out.append("")
    out.append("| ✅ Прошло | ❌ Упало | 🔥 Ошибки | ⏭ Пропущено | 🔁 Флаки |")
    out.append("|---:|---:|---:|---:|---:|")
    out.append(
        f"| {stats['passed']} | {stats['failed']} | {stats['error']} | {stats['skipped']} | {stats['flaky']} |"
    )
    out.append("")

    env_bits = []
    base_url = config.getoption("base_url", None) or config.getini("base_url") or ""
    if base_url:
        env_bits.append(f"стенд `{base_url}`")
    browsers = config.getoption("browser", None) or []
    if browsers:
        env_bits.append("браузер " + ", ".join(f"`{b}`" for b in browsers))
    env_bits.append("режим `headed`" if config.getoption("headed", False) else "режим `headless`")
    markers = config.getoption("markexpr", "") or ""
    if markers:
        env_bits.append(f"фильтр `-m \"{markers}\"`")
    out.append("<sub>" + " · ".join(env_bits) + "</sub>")
    out.append("")

    if broken:
        out.append(f"### ❌ Упавшие ({len(broken)})")
        out.append("")
        for rec in broken[:_MAX_DETAILED_FAILURES]:
            head = _md(_label(rec))
            suite = _md(rec["suite"])
            out.append("<details>")
            out.append(f"<summary><b>{html.escape(head)}</b>{f' — {html.escape(suite)}' if suite else ''}</summary>")
            out.append("")
            out.append(f"`{rec['nodeid']}`")
            out.append("")
            out.append("```")
            out.append(_error_tail(rec["error"]))
            out.append("```")
            out.append("")
            out.append("</details>")
        if len(broken) > _MAX_DETAILED_FAILURES:
            out.append("")
            out.append(f"<sub>…и ещё {len(broken) - _MAX_DETAILED_FAILURES} — см. HTML-отчёт в артефактах</sub>")
        out.append("")

    if flaky:
        out.append(f"### 🔁 Прошли только с повтора ({len(flaky)})")
        out.append("")
        out.append("<sub>С первой попытки упали. Обычно это тормоза стенда, но если тест в этом списке постоянно — стоит его чинить.</sub>")
        out.append("")
        for rec in flaky:
            out.append(f"- **{_md(_label(rec))}** — `{rec['name']}`")
        out.append("")

    if skipped:
        out.append("<details>")
        out.append(f"<summary>⏭ Пропущено ({len(skipped)})</summary>")
        out.append("")
        for rec in skipped:
            reason = _md(rec["reason"])
            out.append(f"- **{_md(_label(rec))}**" + (f" — {reason}" if reason else ""))
        out.append("")
        out.append("</details>")
        out.append("")

    # Разбивка по блокам: видно, локальная это поломка или «поехал» целый раздел.
    by_suite: "OrderedDict[str, dict]" = OrderedDict()
    for rec in recs:
        row = by_suite.setdefault(rec["suite"] or "—", {"passed": 0, "broken": 0, "skipped": 0})
        if rec["outcome"] == "passed":
            row["passed"] += 1
        elif rec["outcome"] == "skipped":
            row["skipped"] += 1
        else:
            row["broken"] += 1
    if len(by_suite) > 1:
        out.append("<details>")
        out.append("<summary>По блокам</summary>")
        out.append("")
        out.append("| Блок | ✅ | ❌ | ⏭ |")
        out.append("|---|---:|---:|---:|")
        for suite, row in by_suite.items():
            out.append(f"| {_md(suite)} | {row['passed']} | {row['broken']} | {row['skipped']} |")
        out.append("")
        out.append("</details>")
        out.append("")

    out.append("<sub>Полный отчёт со скриншотами падений — во вкладке **Artifacts** этого прогона.</sub>")
    out.append("")

    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(out))

    # Аннотации: упавшие кейсы всплывают в шапке job'а, без раскрытия сводки.
    for rec in broken[:_MAX_ANNOTATIONS]:
        file = (rec["file"] or "").replace("\\", "/")
        title = _label(rec).replace("\n", " ")[:120]
        first_line = (rec["error"] or "").strip().splitlines()
        message = (first_line[-1] if first_line else "тест упал")[:400]
        print(f"::error file={file},line={rec['lineno'] + 1},title={title}::{message}")


# ---------------------------------------------------------------------------
# HTML-отчёт (pytest-html)
# ---------------------------------------------------------------------------
@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    """Осмысленная шапка «Environment»: стенд, браузер, режим, коммит, прогон.

    trylast: pytest-base-url дописывает свой «Base URL» в метаданные из
    собственного pytest_configure. Запустись мы раньше — его строка легла бы
    поверх нашей и в шапке было бы два поля про один и тот же стенд.
    """
    try:
        from pytest_metadata.plugin import metadata_key
    except ImportError:
        return
    try:
        meta = config.stash[metadata_key]
    except Exception:
        return

    # Дефолтные Packages/Plugins — простыня версий, для триажа бесполезная.
    for noisy in ("Packages", "Plugins"):
        meta.pop(noisy, None)

    base_url = config.getoption("base_url", None) or config.getini("base_url") or ""
    if base_url:
        meta["Стенд"] = base_url
    meta.pop("Base URL", None)
    browsers = config.getoption("browser", None) or []
    if browsers:
        meta["Браузер"] = ", ".join(browsers)
    meta["Режим"] = "headed" if config.getoption("headed", False) else "headless"
    markexpr = config.getoption("markexpr", "") or ""
    if markexpr:
        meta["Фильтр"] = f'-m "{markexpr}"'
    meta["Запуск"] = time.strftime("%d.%m.%Y %H:%M")

    branch = os.environ.get("GITHUB_REF_NAME")
    sha = os.environ.get("GITHUB_SHA", "")
    if branch:
        meta["Ветка"] = f"{branch} @ {sha[:7]}" if sha else branch
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id:
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        meta["Прогон"] = f"{server}/{repo}/actions/runs/{run_id}"


def pytest_html_report_title(report):
    report.title = f"E2E stage.ecom.md — {time.strftime('%d.%m.%Y %H:%M')}"


def pytest_html_results_summary(prefix, summary, postfix):
    """Честные счётчики над таблицей.

    Штатное «N tests took …» считает попытки, а не тесты: с `--reruns` число
    расходится со списком ниже. Показываем свою строку — одна запись на тест.
    """
    if not _records:
        return
    stats = _stats()
    chips = [
        ("passed", "✅ прошло", stats["passed"]),
        ("failed", "❌ упало", stats["failed"]),
        ("error", "🔥 ошибки", stats["error"]),
        ("skipped", "⏭ пропущено", stats["skipped"]),
        ("flaky", "🔁 флаки", stats["flaky"]),
    ]
    html_chips = "".join(
        f'<span class="qa-chip qa-chip--{kind}">{label}: <b>{value}</b></span>'
        for kind, label, value in chips
        if value
    )
    prefix.append(
        '<div class="qa-stats">'
        f'<div class="qa-stats__total">{stats["total"]} {_plural_tests(stats["total"])}'
        f' за {_fmt_duration(stats["duration"])}</div>'
        f'<div class="qa-stats__chips">{html_chips}</div>'
        "</div>"
    )


def pytest_html_results_table_header(cells):
    # Колонка Links всегда пустая (ссылок к тестам не прикладываем) — убираем.
    if cells and ">Links<" in str(cells[-1]):
        cells.pop()
    cells.insert(1, "<th>Блок</th>")
    cells.insert(2, "<th>Кейс</th>")


def pytest_html_results_table_row(report, cells):
    if cells and 'class="col-links"' in str(cells[-1]):
        cells.pop()
    suite = html.escape(getattr(report, "suite_title", "") or "")
    case = html.escape(getattr(report, "case_title", "") or "")
    cells.insert(1, f'<td class="col-suite">{suite}</td>')
    cells.insert(2, f'<td class="col-case">{case}</td>')
