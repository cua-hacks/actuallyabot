"""DOM helpers — thin wrappers over kernel.browsers.playwright.execute.

Reminder: that endpoint runs JS in NODE, not the page. Use page.evaluate() for
DOM access. We always wrap callers to make that explicit.
"""
from __future__ import annotations

import json
from typing import Any

from kernel import Kernel


def evaluate(k: Kernel, session_id: str, page_fn_body: str) -> Any:
    """Run JS in the page context. `page_fn_body` is the body of an arrow function.

    Example: evaluate(k, sid, "return document.title") -> 'Some Title'
    """
    code = f"return await page.evaluate(() => {{ {page_fn_body} }});"
    resp = k.browsers.playwright.execute(id=session_id, code=code)
    if not resp.success:
        raise RuntimeError(f"page.evaluate failed: error={resp.error} stderr={resp.stderr}")
    return resp.result


def goto(k: Kernel, session_id: str, url: str, timeout_ms: int = 20000) -> dict:
    code = f"""
    await page.goto({json.dumps(url)}, {{ waitUntil: 'domcontentloaded', timeout: {timeout_ms} }});
    try {{ await page.waitForLoadState('networkidle', {{ timeout: 8000 }}); }} catch (_) {{}}
    return {{ url: page.url(), title: await page.title() }};
    """
    resp = k.browsers.playwright.execute(id=session_id, code=code)
    if not resp.success:
        raise RuntimeError(f"goto failed: error={resp.error}")
    return resp.result or {}


def predicate(k: Kernel, session_id: str, page_fn_body: str) -> bool:
    """Convenience: evaluate JS that returns a boolean, default False on error."""
    try:
        v = evaluate(k, session_id, page_fn_body)
        return bool(v)
    except Exception as e:
        print(f"[dom.predicate] {e}")
        return False
