"""Jinja2 prompt rendering (feature 1.5).

Prompts are files, not f-strings in Python, for one practical reason: the
groundedness rule lives in the wording, and a rule you can diff is a rule you can
review. `system_grounded.j2` is the single place decision #8 is expressed to a
model, and every task template ends by restating it.

`autoescape` is deliberately **off**. These render plain text for a language model,
not HTML, and escaping would turn a legitimate `<` in an indicator name into
`&lt;` inside the data block — which the groundedness verifier would then see as a
different string from the value it is checking against.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATE_DIR = Path(__file__).parent / "prompt_templates"

# StrictUndefined: a template referencing a context key that was not supplied is a
# bug that would otherwise render as an empty string — a silently truncated data
# block, which is the worst possible failure for a grounded prompt.
_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    undefined=StrictUndefined,
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def render(template_name: str, **context: Any) -> str:
    return _env.get_template(template_name).render(**context).strip()


def system_prompt() -> str:
    return render("system_grounded.j2")


def chat_messages(user_prompt: str, *, system: str | None = None) -> list[dict[str, str]]:
    """The two-message shape every provider in the rotation accepts."""
    return [
        {"role": "system", "content": system or system_prompt()},
        {"role": "user", "content": user_prompt},
    ]
