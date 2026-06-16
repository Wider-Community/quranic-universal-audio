"""Jinja2 email templates.

Each event has one ``<event>.html`` in ``templates/`` that ``{% extends %}``
``base.html`` and defines a ``subject`` block + a ``content`` block. ``render``
returns ``(subject, html)``; the plaintext alternative is derived by the sender.
The base injects the greeting ("Assalamu Alaikum"), the site link, and the
per-recipient manage / unsubscribe links.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)


def render(event: str, ctx: dict) -> tuple[str, str]:
    """Render ``(subject, html)`` for ``event`` with ``ctx``.

    ``ctx`` carries the event fields plus the link vars the base needs:
    ``site_url``, ``manage_url``, ``unsubscribe_url`` (+ ``gh_releases_url`` for
    the release template).
    """
    tmpl = _env.get_template(f"{event}.html")
    context = tmpl.new_context(ctx)
    subject = "".join(tmpl.blocks["subject"](context)).strip()
    html = tmpl.render(ctx)
    return subject, html
