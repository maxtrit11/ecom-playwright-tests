# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python-based end-to-end test suite using Playwright with pytest. Tests run against web applications via browser automation.

## Tech Stack

- **Playwright** (1.50.0) for browser automation
- **pytest** (8.3.4) as the test runner
- **pytest-playwright** (0.6.2) for Playwright/pytest integration

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (required once)
playwright install

# Run all tests
pytest

# Run a single test file
pytest tests/test_example.py

# Run a specific test by name
pytest -k "test_example"

# Run with headed browser (visible)
pytest --headed

# Run in a specific browser
pytest --browser chromium
pytest --browser firefox
pytest --browser webkit
```

## Architecture

- `pytest.ini` — pytest config; test discovery is scoped to the `tests/` directory
- `tests/` — all test files live here; pytest collects files matching `test_*.py`
- Tests use Playwright's sync API (`playwright.sync_api`) with pytest-playwright fixtures (e.g., `page: Page` is auto-injected)
