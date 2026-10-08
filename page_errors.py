"""Ошибки страниц, которые видит браузер, но не видят ассерты.

Тест проверяет свой сценарий: «товар в корзине», «фильтр сузил выдачу». Если
по дороге страница бросила необработанное исключение или API ответил 500 на
соседний виджет — тест всё равно зелёный, и об ошибке никто не узнаёт. Так на
проде жила мёртвая кнопка подарка (ecom-5273, HierarchyRequestError в консоли).

Этот плагин слушает каждый браузерный контекст теста и собирает:
- необработанные JS-исключения страницы (`weberror`);
- `console.error` из скриптов самого сайта (сторонние виджеты — шум, мимо);
- ответы 4xx/5xx с доменов стенда (сайт и его API).

Тесты НЕ роняет: ошибка консоли — сигнал для разбора, а не вердикт. Результат:
- в логе каждого теста, где что-то поймано, — секция «Ошибки страницы»;
- в HTML-отчёте над таблицей — сводка «уникальная ошибка → в скольких тестах»;
- в сводке GitHub Actions — та же таблица.

Одинаковые ошибки склеиваются по «подписи»: числа в URL и тексте заменяются на
`{n}`, query-строка отбрасывается — иначе `/order/226247/` и `/order/226245/`
были бы разными ошибками.

Ожидаемые ошибки сценария (тест специально вводит неверный пароль или
промокод, и API честно отвечает 4xx) — это не дефект. Такой тест помечается
`@pytest.mark.expected_http(401, 422)`, и эти коды для него не собираются.
"""

from __future__ import annotations

import html
import os
import re
from collections import OrderedDict
from urllib.parse import urlsplit

import pytest

# Домены платформы: stage и его API (stage.admin.ecom.md), медиа
# (media.ecom.md) и прод-магазины из tests/prod. Всё прочее — Bitrix24,
# Google, YouTube, Facebook — чужое, его ошибки нам ни о чём не говорят.
_OWN_HOST_RE = re.compile(r"(^|\.)(ecom|jblstore|alo)\.md$")

# Дубли сетевых ошибок: на каждый 4xx/5xx Chromium пишет ещё и строку в
# консоль. Сам ответ уже пойман как http — консольную копию не считаем.
_CONSOLE_NOISE = (
    re.compile(r"^Failed to load resource", re.I),
    # Свой обработчик onerror сайта пишет каждое необработанное исключение
    # ещё и в консоль — оригинал уже пойман как js.
    re.compile(r"^\[Window OnError\]"),
)

# Известные ответы-«не ошибки»: разобраны и признаны штатным поведением. Без
# этого списка они забивали бы сводку в каждом прогоне и прятали новое.
# Добавлять сюда только разобранное, с причиной.
_KNOWN_HTTP = (
    # Блок «Преимущества» на главной: у магазина они не заведены, и API
    # отвечает 404 {"error": "Преимущества не существуют"} вместо пустого
    # списка. Запрос уходит почти с каждой страницы (39 из 65 тестов,
    # 08.10.2026), на вёрстку не влияет.
    re.compile(r"^404 GET [^ ]*/base/advantage/main_page/$"),
)

_MAX_SAMPLE = 300
_MAX_SUMMARY_ROWS = 40

# Подпись → {"kind", "signature", "sample", "tests": OrderedDict[nodeid, None], "hits"}
_registry: "OrderedDict[str, dict]" = OrderedDict()

_ITEM_ERRORS = pytest.StashKey[list]()


def _is_own(url: str) -> bool:
    host = urlsplit(url or "").hostname or ""
    return bool(_OWN_HOST_RE.search(host))


def _normalize(text: str) -> str:
    text = re.sub(r"\d+", "{n}", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _url_signature(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.hostname}{_normalize(parts.path)}"


def _expected_statuses(item) -> set[int]:
    codes: set[int] = set()
    for mark in item.iter_markers("expected_http"):
        codes.update(int(c) for c in mark.args)
    return codes


def _record(item, kind: str, signature: str, sample: str) -> None:
    errors = item.stash.setdefault(_ITEM_ERRORS, [])
    errors.append((kind, sample[:_MAX_SAMPLE]))

    key = f"{kind}|{signature}"
    entry = _registry.get(key)
    if entry is None:
        entry = _registry[key] = {
            "kind": kind,
            "signature": signature,
            "sample": sample[:_MAX_SAMPLE],
            "tests": OrderedDict(),
            "hits": 0,
        }
    entry["hits"] += 1
    entry["tests"][item.nodeid] = None


def _watch_context(context, item) -> None:
    expected = _expected_statuses(item)

    def on_weberror(web_error):
        try:
            err = web_error.error
            message = str(getattr(err, "message", "") or err)
            name = str(getattr(err, "name", "") or "Error")
            stack = str(getattr(err, "stack", "") or "")
        except Exception:
            return
        # Исключение из чужого скрипта (виджет, аналитика) — не наше.
        frames = re.findall(r"https?://[^\s)]+", stack)
        if frames and not _is_own(frames[0]):
            return
        _record(item, "js", _normalize(f"{name}: {message}"), f"{name}: {message}")

    def on_console(msg):
        try:
            if msg.type != "error":
                return
            text = msg.text
            src = (msg.location or {}).get("url", "")
        except Exception:
            return
        if any(rx.search(text) for rx in _CONSOLE_NOISE):
            return
        if src and not _is_own(src):
            return
        _record(item, "console", _normalize(text), text)

    def on_response(resp):
        try:
            status = resp.status
            if status < 400 or status in expected:
                return
            url = resp.url
            if not _is_own(url):
                return
            method = resp.request.method
        except Exception:
            return
        sig = f"{status} {method} {_url_signature(url)}"
        if any(rx.search(sig) for rx in _KNOWN_HTTP):
            return
        _record(item, "http", sig, f"{status} {method} {url}")

    context.on("weberror", on_weberror)
    context.on("console", on_console)
    context.on("response", on_response)


@pytest.fixture(autouse=True)
def _collect_page_errors(request):
    """Повесить слушателей на контекст теста, если тест вообще открывает браузер."""
    if "page" not in request.fixturenames and "context" not in request.fixturenames:
        yield
        return
    context = request.getfixturevalue("context")
    _watch_context(context, request.node)
    yield


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "expected_http(*codes): коды ответа API, которые тест вызывает намеренно "
        "(неверный пароль, промокод) — плагин page_errors их не собирает.",
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    errors = item.stash.get(_ITEM_ERRORS, None)
    if not errors:
        return
    lines = [f"[{kind}] {sample}" for kind, sample in errors]
    report.sections.append(("Ошибки страницы (тест не роняют)", "\n".join(lines)))
    # Следующая попытка (--reruns) собирает свои
    item.stash[_ITEM_ERRORS] = []


_KIND_LABEL = {"js": "JS-исключение", "console": "console.error", "http": "HTTP"}


def _sorted_entries() -> list[dict]:
    # Сначала то, что задело больше всего тестов: чем шире, тем вероятнее
    # системная поломка, а не особенность одного сценария.
    return sorted(_registry.values(), key=lambda e: (-len(e["tests"]), e["kind"]))


def _short_test(nodeid: str) -> str:
    return nodeid.split("::")[-1]


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not _registry:
        return
    try:
        entries = _sorted_entries()
        terminalreporter.write_sep("-", f"Ошибки страниц: {len(entries)} уникальных (тесты не роняют)")
        # Без «×» и «—»: консоль Windows (cp1251) их не кодирует и экранирует
        # всю строку целиком, вместе с кириллицей.
        for e in entries[:_MAX_SUMMARY_ROWS]:
            terminalreporter.write_line(
                f"  [{e['kind']}] в {len(e['tests'])} тест.: {e['signature'][:160]}"
            )
        _write_github_summary(entries)
    except Exception as exc:  # оформление не должно ронять прогон
        terminalreporter.write_line(f"page_errors: не удалось вывести сводку: {exc}")


def _md(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").replace("`", "'").strip()


def _write_github_summary(entries: list[dict]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    out = [
        "",
        f"### 🧩 Ошибки страниц ({len(entries)} уникальных)",
        "",
        "<sub>JS-исключения, console.error и ответы 4xx/5xx стенда, пойманные по ходу тестов. "
        "Тесты из-за них не падают — это список на разбор. Подробности — в логе теста "
        "в HTML-отчёте, секция «Ошибки страницы».</sub>",
        "",
        "| Тип | Ошибка | Тестов | Пример теста |",
        "|---|---|---:|---|",
    ]
    for e in entries[:_MAX_SUMMARY_ROWS]:
        first = _short_test(next(iter(e["tests"])))
        out.append(
            f"| {_KIND_LABEL.get(e['kind'], e['kind'])} | `{_md(e['sample'][:200])}` "
            f"| {len(e['tests'])} | `{_md(first)}` |"
        )
    if len(entries) > _MAX_SUMMARY_ROWS:
        out.append("")
        out.append(f"<sub>…и ещё {len(entries) - _MAX_SUMMARY_ROWS}</sub>")
    out.append("")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(out))


def pytest_html_results_summary(prefix, summary, postfix):
    if not _registry:
        return
    try:
        entries = _sorted_entries()
        rows = "".join(
            "<tr>"
            f"<td>{_KIND_LABEL.get(e['kind'], e['kind'])}</td>"
            f"<td><code>{html.escape(e['sample'])}</code></td>"
            f"<td>{len(e['tests'])}</td>"
            f"<td>{html.escape(', '.join(_short_test(t) for t in list(e['tests'])[:5]))}"
            f"{' …' if len(e['tests']) > 5 else ''}</td>"
            "</tr>"
            for e in entries
        )
        postfix.append(
            '<details class="qa-page-errors">'
            f"<summary>🧩 Ошибки страниц: {len(entries)} уникальных (тесты не роняют)</summary>"
            "<table><thead><tr><th>Тип</th><th>Ошибка</th><th>Тестов</th><th>Где</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            "</details>"
        )
    except Exception:
        pass
