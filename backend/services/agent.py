"""The economic agent — a LangGraph loop over two database tools.

This replaces the RAG retrieval path for the chatbot. The reason is not that
retrieval was implemented badly; it is that retrieval is the wrong shape for the
questions being asked. Asked which country has the highest debt-to-GDP, a vector
search returns whichever chunks are nearest in embedding space, and an answer
built from them names a country that was *retrieved*, not one that was *highest*.
The old chat answered "Montenegro" that way — a real figure, correctly quoted,
wrong about 193 other countries. Asked about Japan's unemployment it returned
fragments about Estonia, the Philippines and Andorra, because those sentences look
almost identical to a sentence about Japan.

A query has neither problem. "Every country ranked by X" is a question SQL can
answer exactly, and "Japan's unemployment" is a lookup with a WHERE clause. So the
model's job stops being *retrieve then summarise* and becomes *choose the right
query, then read its result* — and the result it reads is structured, so what it
is allowed to say is bounded by what a tool actually returned.

**The verifiers still gate the output.** `groundedness.verify()` runs on the final
answer against the tool results, exactly as it ran against retrieved chunks, and
the semantic checks (decisions #32-#34) run beside it. The context is stronger now
than it was: a tool result is a JSON object holding precisely the numbers the model
saw, so "every figure must appear in the evidence" is enforced against a set the
system built rather than one it hoped was complete.

**Provider rotation is its own list** (decision #38), not decision #7's. Tool
calling is a capability rather than a preference — a provider that cannot emit a
structured tool call cannot run this loop at all — and the owner judged the
remaining rotation members too weak for multi-step reasoning over real data. A
provider that fails mid-loop hands over *in place*: `AgentTurn` is deliberately
neither provider's dialect, so the conversation so far converts to the next
provider's format and the tool results already gathered are not thrown away.
"""

from __future__ import annotations

import json
import operator
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from logging_config import get_logger
from services import agent_tools, prompts, providers
from services.agent_tools import RANK_COUNTRIES, TOOL_SCHEMAS, ToolResult
from services.providers import (
    AgentTurn,
    ProviderError,
    ProviderNotConfigured,
    ProviderRateLimited,
    ToolCompletion,
)

logger = get_logger(__name__)

MAX_WORDS = 220

#: Superlative vocabulary, used to *prompt* the model toward the ranking tool.
#: "most recent" and "at most" are excluded because they are not superlatives about
#: countries, and forcing a ranking for "the most recent figure for Japan" would
#: spend a call and pull an irrelevant list into the answer.
_SUPERLATIVE_RE = re.compile(
    r"\b(highest|lowest|most|least|top|bottom|best|worst|rank(?:ed|ing)?|leading|"
    r"largest|smallest|greatest|fewest|maximum|minimum|richest|poorest)\b",
    re.IGNORECASE,
)
_NOT_SUPERLATIVE_RE = re.compile(r"\b(most recent|at most|most of|for the most part)\b", re.I)

#: Scope markers that turn a superlative into a claim about *every* country.
#: The enforcement check below keys on these rather than on the superlative alone,
#: because "the highest reading in Japan's own history" is a perfectly good answer
#: from a single-country lookup and must not be rejected.
#: "the world's …" is deliberately NOT here. It reads as a scope marker and is
#: usually a noun phrase describing a subset — "lower than in the world's largest
#: economies" is a comparison against big economies, not a claim to be the largest,
#: and the two are not distinguishable by pattern. Including it made the guard
#: reject that sentence, which is the failure mode this whole check is supposed to
#: avoid being. Missing one phrasing costs a guard; rejecting honest prose costs
#: the feature.
#: The `(?!'?s)` on "in the world" is load-bearing, not tidiness: without it the
#: phrase matches inside "in the world's largest economies", because an apostrophe
#: is a word boundary. That one character is the difference between the guard
#: rejecting a correct comparison and leaving it alone.
_GLOBAL_SCOPE_RE = re.compile(
    r"\b(in the world(?!'?s)|worldwide|globally|of all countries|of any country|"
    r"across (?:all )?countries|among all countries)\b",
    re.IGNORECASE,
)

#: The same claim in the negative: "no country has a lower rate" *is* "this is the
#: lowest", and a guard that only knew superlatives would wave it through. Bounded
#: to a negative-universal frame on purpose — a bare comparative near a scope
#: marker ("lower than in the world's largest economies") is a comparison against a
#: subset and must not be rejected.
_NEGATIVE_UNIVERSAL_RE = re.compile(
    r"\bno\s+(?:other\s+)?(?:country|economy|nation)\b[^.!?]{0,80}?"
    r"\b(higher|lower|greater|larger|smaller|more|less|worse|better)\b",
    re.IGNORECASE,
)


# ── presentation ─────────────────────────────────────────────────────────────
# The chat panel renders an answer with `whitespace-pre-line` and no Markdown, by
# decision #26: extend `components/ui.tsx` rather than adopt a component library.
# Mistral writes Markdown regardless of being asked not to — measured, in a browser,
# after the prompt rule was added and deployed:
#
#     EconRadar's Japan unemployment series begins in **1991** … \[1\].
#
# So the prompt asks and this enforces. Stripping presentation markup is not the
# repair `groundedness.py` refuses to do: no digit, word or claim changes, and the
# same normalised string is what gets verified, cached and displayed — one text,
# three consumers, which is the rule everywhere else here.

_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_MD_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+", re.MULTILINE)
_MD_BOLD_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_MD_ITALIC_RE = re.compile(r"(?<![\w*])[*_](?=\S)([^*_\n]+?)(?<=\S)[*_](?![\w*])")
_MD_CODE_RE = re.compile(r"`+([^`\n]+?)`+")
#: Unescaped last, so `\*` becomes a literal asterisk rather than being read as
#: emphasis by the rules above.
_MD_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!])")


def strip_markup(text: str) -> str:
    """Markdown out, meaning untouched."""
    if not text:
        return text
    text = _MD_HEADING_RE.sub("", text)
    text = _MD_BULLET_RE.sub(r"\1• ", text)
    text = _MD_BOLD_RE.sub(r"\2", text)
    text = _MD_ITALIC_RE.sub(r"\1", text)
    text = _MD_CODE_RE.sub(r"\1", text)
    return _MD_ESCAPE_RE.sub(r"\1", text).strip()


def asks_for_a_ranking(question: str) -> bool:
    """Whether a question is superlative enough to need the whole dataset."""
    stripped = _NOT_SUPERLATIVE_RE.sub(" ", question or "")
    return bool(_SUPERLATIVE_RE.search(stripped))


def claims_a_global_superlative(answer: str) -> bool:
    """Whether an answer asserts something about *every* country.

    Deliberately narrow. It fires only when a sentence pairs a global scope marker
    with either a superlative or a negative-universal comparative, so a within-series
    statement ("its highest reading since 1998") is untouched. This is the check
    that would have caught the Montenegro answer, and it is a veto, not a hint.

    Narrowness is the whole design. An over-strict version of this rejects correct
    answers, which is worse than the failure it prevents — the lesson decision #33
    records from a direction rule that took a country's narration dark.
    """
    for sentence in re.split(r"(?<=[.!?])\s+", answer or ""):
        cleaned = _NOT_SUPERLATIVE_RE.sub(" ", sentence)
        if not _GLOBAL_SCOPE_RE.search(cleaned):
            continue
        if _SUPERLATIVE_RE.search(cleaned) or _NEGATIVE_UNIVERSAL_RE.search(cleaned):
            return True
    return False


#: Sent back to a model that tried to answer without querying anything. Written as
#: a user turn rather than a system rule because the system prompt already says this
#: and was ignored — a model that has just produced an answer responds to being told
#: the answer was rejected, not to being told the rule again.
NO_QUERY_NUDGE = (
    "That answer was rejected: it was written without querying the database, so "
    "nothing in it can be checked. Every answer here must come from a tool result. "
    "If the question names something ambiguous, call a tool with the word the "
    "question used and report the options it gives back — do not list series from "
    "your own knowledge, because this database holds 23 indicators and most of the "
    "ones you can name are not among them."
)


class AgentState(TypedDict, total=False):
    """Graph state. Lists accumulate; scalars are replaced by the latest write."""

    turns: Annotated[list[AgentTurn], operator.add]
    results: Annotated[list[ToolResult], operator.add]
    calls_made: int
    answer: str
    provider: str | None
    model: str | None
    attempts: Annotated[list[str], operator.add]
    failure: str | None
    nudged: bool


@dataclass(slots=True)
class AgentAnswer:
    text: str
    provider: str | None
    model: str | None
    results: list[ToolResult] = field(default_factory=list)
    attempts: list[str] = field(default_factory=list)
    failure: str | None = None

    @property
    def called_ranking(self) -> bool:
        return any(r.name == RANK_COUNTRIES and r.ok for r in self.results)


def system_prompt() -> str:
    return prompts.render(
        "agent_system.j2",
        query_tool=agent_tools.QUERY_OBSERVATIONS,
        rank_tool=RANK_COUNTRIES,
        max_calls=settings.agent_max_tool_calls,
        max_words=MAX_WORDS,
        comparability_reminder=True,
    )


def _configured_agent_providers() -> list[str]:
    return providers.configured_providers(settings.agent_provider_order)


async def _model_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """One model step, walking the agent rotation until a provider answers."""
    system = config["configurable"]["system"]
    turns = list(state.get("turns", []))
    attempts: list[str] = []

    for provider in _configured_agent_providers():
        try:
            completion: ToolCompletion = await providers.complete_with_tools(
                provider, system, turns, TOOL_SCHEMAS
            )
        except ProviderRateLimited as exc:
            attempts.append(f"{provider}: rate limited")
            logger.warning("agent: %s rate limited, handing over — %s", provider, exc)
            continue
        except (ProviderNotConfigured, ProviderError) as exc:
            attempts.append(f"{provider}: {exc}")
            logger.warning("agent: %s failed, handing over — %s", provider, exc)
            continue

        if not completion.text and not completion.tool_calls:
            attempts.append(f"{provider}: empty response")
            continue

        return {
            "turns": [
                AgentTurn(
                    role="assistant",
                    text=completion.text or None,
                    tool_calls=completion.tool_calls,
                )
            ],
            "answer": completion.text,
            "provider": completion.provider,
            "model": completion.model,
            "attempts": attempts,
        }

    return {
        "attempts": attempts,
        "failure": "no agent provider could answer: " + ("; ".join(attempts) or "none configured"),
    }


async def _tools_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Execute every tool call the last assistant turn asked for."""
    session: AsyncSession = config["configurable"]["session"]
    last = state["turns"][-1]

    new_turns: list[AgentTurn] = []
    results: list[ToolResult] = []
    for call in last.tool_calls:
        result = await agent_tools.execute(session, call.name, call.arguments)
        results.append(result)
        new_turns.append(
            AgentTurn(
                role="tool",
                # The payload the model reads is byte-identical to the payload the
                # verifier will check the answer against. One object, two consumers —
                # the same discipline services/context.py applies to narration.
                text=json.dumps(result.payload, default=str),
                tool_call_id=call.id,
                tool_name=call.name,
            )
        )

    return {
        "turns": new_turns,
        "results": results,
        "calls_made": state.get("calls_made", 0) + len(last.tool_calls),
    }


async def _nudge_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Tell the model its unqueried answer was rejected, and let it try once."""
    del config
    logger.info("agent: answered without querying — asking once more")
    return {"turns": [AgentTurn(role="user", text=NO_QUERY_NUDGE)], "nudged": True}


def _route(state: AgentState) -> str:
    """Loop while the model wants tools and the budget allows."""
    if state.get("failure"):
        return END
    turns = state.get("turns", [])
    if not turns:
        return END
    last = turns[-1]
    if last.role != "assistant" or not last.tool_calls:
        # Prose with no query behind it. `run_agent` refuses it outright, but a
        # refusal is a worse answer than the one the tools would have given, and the
        # cause is usually a model deciding it already knows — "What is Japan's GDP?"
        # produced five invented series names rather than one lookup. Worth exactly
        # one more attempt; a second would be a model that cannot be told.
        if not state.get("nudged") and not state.get("calls_made", 0):
            return "nudge"
        return END
    if state.get("calls_made", 0) >= settings.agent_max_tool_calls:
        # Out of budget. The loop stops rather than being cut mid-call, and the
        # model gets one more turn to answer from what it already has.
        logger.info("agent: tool budget of %d exhausted", settings.agent_max_tool_calls)
        return END
    return "tools"


def build_graph():
    """The loop: model -> (tools -> model)* -> end.

    Compiled once at import. It holds no per-request state — the session and the
    system prompt arrive through `configurable`, which is where LangGraph puts
    runtime dependencies that must not be part of graph state.
    """
    graph = StateGraph(AgentState)
    graph.add_node("model", _model_node)
    graph.add_node("tools", _tools_node)
    graph.add_node("nudge", _nudge_node)
    graph.set_entry_point("model")
    graph.add_conditional_edges("model", _route, {"tools": "tools", "nudge": "nudge", END: END})
    graph.add_edge("tools", "model")
    graph.add_edge("nudge", "model")
    return graph.compile()


AGENT_GRAPH = build_graph()


def trim_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep the last N turns (feature 2.2 specifies four).

    Enforced here rather than trusted from the client, because the client sends the
    history and a crafted request could otherwise send a thousand turns — which is
    an unbounded prompt on a public endpoint with no rate limit. Counted in turns
    rather than messages, and trimmed from the end, so a long conversation keeps its
    most recent context rather than its opening.
    """
    clean = [
        {"role": t.get("role", "user"), "content": (t.get("content") or "").strip()}
        for t in history
        if (t.get("content") or "").strip()
    ]
    return clean[-(settings.rag_context_turns * 2) :]


def _opening_turns(question: str, history: list[dict[str, str]]) -> list[AgentTurn]:
    """The conversation the model starts from.

    History is prior turns of *this* chat, already trimmed by the caller. The
    ranking directive is appended to the question rather than to the system prompt
    so it applies to this question only — a follow-up that is not superlative
    should not inherit the instruction.
    """
    turns = [
        AgentTurn(role="assistant" if turn.get("role") == "assistant" else "user", text=content)
        for turn in history
        if (content := (turn.get("content") or "").strip())
    ]
    text = question
    if asks_for_a_ranking(question):
        text += (
            f"\n\n[This question uses superlative or comparative language, so it is a "
            f"question about every country in the database. Call {RANK_COUNTRIES} — "
            f"looking up countries individually cannot answer it.]"
        )
    turns.append(AgentTurn(role="user", text=text))
    return turns


async def run_agent(
    session: AsyncSession,
    question: str,
    history: list[dict[str, str]] | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    """Run one question, yielding ("tool", ToolResult) then ("answer", AgentAnswer).

    A generator rather than a plain coroutine so the caller can surface progress
    while tool calls are running. The agent's first move is a tool call, not prose,
    so without these events the UI would sit blank for the whole query phase.
    """
    system = system_prompt()
    config: RunnableConfig = {
        "configurable": {"session": session, "system": system},
        # A hard stop independent of the tool budget: a model that alternates
        # between two calls forever is stopped by graph depth even if each
        # individual step looks reasonable.
        "recursion_limit": 2 * settings.agent_max_tool_calls + 4,
    }
    state: AgentState = {
        "turns": _opening_turns(question, trim_history(history or [])),
        "results": [],
        "calls_made": 0,
        "attempts": [],
    }

    seen_results = 0
    final: dict[str, Any] = {}
    async for update in AGENT_GRAPH.astream(state, config, stream_mode="values"):
        final = update
        results = update.get("results", [])
        for result in results[seen_results:]:
            yield "tool", result
        seen_results = len(results)

    answer = AgentAnswer(
        # Normalised before anything reads it, so the guard below, the verifier, the
        # cache and the reader all see the same string.
        text=strip_markup(final.get("answer") or ""),
        provider=final.get("provider"),
        model=final.get("model"),
        results=list(final.get("results", [])),
        attempts=list(final.get("attempts", [])),
        failure=final.get("failure"),
    )

    # An answer with no tool call behind it came from the model's training data,
    # whatever it says. Caught live: asked "What is Japan's GDP?", the agent skipped
    # the tools entirely and listed five GDP variants from memory — PPP, constant
    # local currency, current US dollars — of which this database holds exactly none.
    # It scored 1.00, because prose with no digits in it cannot fail a numeric
    # verifier. That is problem 4 taking the one route left open to it, and the only
    # reliable check is structural: no query, no answer.
    if answer.text and not answer.results:
        logger.warning(
            "agent: answer produced without querying the database — refusing: %r",
            answer.text[:160],
        )
        answer.failure = "the answer was written without querying the database"
        answer.text = ""

    # The guarantee, not the hint. A global superlative reached without ranking
    # every country is the Montenegro failure, whatever produced it — a model that
    # ignored the directive, or one that ranked nothing and answered from the tail
    # of a country lookup.
    if answer.text and claims_a_global_superlative(answer.text) and not answer.called_ranking:
        logger.warning(
            "agent: answer claims a global superlative without ranking — refusing: %r",
            answer.text[:160],
        )
        answer.failure = "the answer claimed a worldwide superlative without ranking every country"
        answer.text = ""

    logger.info(
        "agent: question=%r provider=%s tools=%d answer_chars=%d failure=%s",
        question[:70],
        answer.provider,
        len(answer.results),
        len(answer.text),
        answer.failure,
    )
    yield "answer", answer


def evidence_context(results: list[ToolResult]) -> dict[str, Any]:
    """The object the answer is verified against — the tool payloads, nothing else.

    This is what makes the groundedness check meaningful under an agent: the model
    saw exactly these payloads, so the set of numbers it may legitimately write is
    exactly the set walked out of them. Failed calls are included on purpose — their
    payload is an error message with no figures in it, and a model quoting a number
    from a failed lookup should not be grounded by it.
    """
    return {"tool_results": [{"tool": r.name, "ok": r.ok, "payload": r.payload} for r in results]}


def agent_available() -> bool:
    return settings.agent_enabled and settings.llm_enabled and bool(_configured_agent_providers())
