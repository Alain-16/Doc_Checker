import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.industry.profile import current_profile
from src.copilot.answers import NOT_FOUND, Claim, check_grounding, compose, draft_answer, out_of_scope_message
from src.copilot.content_search import find_passages
from src.copilot.database_tools import FindingsTool, choose_tool, read_each_document, run_findings, run_tool
from src.copilot.source import Source, number_sources, stored_sources
from src.copilot.understanding import QuestionPlan, Scope, plan_question, resolve_scope, search_query
from src.llm.models import MODEL_BY_TASK, LlmTask
from src.models import Conversation, DocumentType, Message, QueryLog, User
from src.models.copilot import MessageRole, QuestionRoute

ASSISTANT_TASKS = [
    LlmTask.ROUTE_QUESTION, LlmTask.RERANK_PASSAGES, LlmTask.CHOOSE_QUERY_TOOL,
    LlmTask.ANSWER_QUESTION, LlmTask.CHECK_GROUNDING,
]


class AnswerState(TypedDict, total=False):
    """What flows between the steps. Each step returns only the keys it sets."""

    question: str
    history: list[tuple[MessageRole, str]]
    previous_sources: list[dict[str, Any]]  # the last answer's sources, as saved on its message
    plan: QuestionPlan
    scope: Scope
    notes: list[str]  # said before the answer: broadened search, unknown names
    sources: list[Source]
    retrieved: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    claims: list[Claim]
    removed: list[dict[str, Any]]
    answer: str
    cited: list[Source]
    not_found: bool


def db(config: RunnableConfig) -> Session:
    """The database session, passed in the graph's config (not the state: it isn't data)."""
    return config["configurable"]["session"]


# --- The steps ---


def understand(state: AnswerState, config: RunnableConfig) -> AnswerState:
    session = db(config)
    types = dict(session.execute(select(DocumentType.name, DocumentType.display_name)).tuples().all())
    plan = plan_question(state["question"], state["history"], types, current_profile(session))
    scope = resolve_scope(session, plan)
    notes = [f"I have no documents from a vendor or component called '{name}'." for name in scope.unmatched]
    if scope.searched_as_topic:
        # Not a known component: search for it as a subject instead of stopping.
        plan.topic = " ".join([plan.topic, *(name for name in scope.searched_as_topic if name.casefold() not in plan.topic.casefold())])
    return {"plan": plan, "scope": scope, "notes": notes, "retrieved": [], "tool_calls": []}


def next_step(state: AnswerState) -> str:
    """The router's choice, except: a named vendor or component we don't know stops here.
    Searching everything instead could answer about a different vendor's product."""
    if state["scope"].unmatched and state["plan"].route != "out_of_scope":
        return "answer"
    return state["plan"].route


def content(state: AnswerState, config: RunnableConfig) -> AnswerState:
    plan = state["plan"]
    if plan.about_previous_answer and state["previous_sources"]:
        # "Show me the source for that": the evidence already shown, not a new search
        # (a new search can keep different passages and lose some of them).
        return {"sources": stored_sources(db(config), state["previous_sources"]), "retrieved": []}
    sources, broadened, log = find_passages(db(config), plan.standalone_question, plan.topic, state["scope"], search_query(plan))
    notes = state["notes"] + ([f"Nothing matched the exact scope, so I searched {broadened}."] if broadened else [])
    return {"sources": sources, "retrieved": log, "notes": notes}


def with_summary(sources: list[Source], summary: str) -> list[Source]:
    # The count itself is evidence the answer may cite ("5 documents are stale [1]").
    return [Source(kind="summary", text=summary, context=None), *sources]


def aggregate(state: AnswerState, config: RunnableConfig) -> AnswerState:
    session = db(config)
    call = choose_tool(session, state["plan"].standalone_question)
    sources, summary = run_tool(session, call, state["scope"])
    return {"sources": with_summary(sources, summary), "tool_calls": [{"call": call.model_dump(mode="json"), "result": summary}]}


def findings(state: AnswerState, config: RunnableConfig) -> AnswerState:
    call = FindingsTool(tool="findings", statuses=[])
    sources, summary = run_findings(db(config), call, state["scope"])
    return {"sources": with_summary(sources, summary), "tool_calls": [{"call": call.model_dump(mode="json"), "result": summary}]}


def cross_document(state: AnswerState, config: RunnableConfig) -> AnswerState:
    plan = state["plan"]
    sources, summary, call = read_each_document(db(config), plan.standalone_question, plan.topic, state["scope"], search_query(plan))
    log = {"tool": "read_each_document", "topic": plan.topic, "documents": call.model_dump(mode="json")}
    return {"sources": with_summary(sources, summary), "tool_calls": [{"call": log, "result": summary}]}


def answer(state: AnswerState, config: RunnableConfig) -> AnswerState:
    sources = number_sources(state.get("sources", []))
    question = state["plan"].standalone_question
    if not sources:
        return {"answer": "\n".join([*state["notes"], NOT_FOUND]), "cited": [], "claims": [], "removed": [], "not_found": True}
    cover = None
    if state["plan"].route == "cross_document":
        cover = list(dict.fromkeys(s.context.label for s in sources if s.kind == "record" and s.context))
    profile = current_profile(db(config))
    draft = draft_answer(question, sources, profile, cover)
    kept, removed = check_grounding(draft.claims, sources) if not draft.not_found else ([], [])
    if not kept:
        return {"answer": "\n".join([*state["notes"], NOT_FOUND]), "cited": [], "claims": [], "removed": removed, "not_found": True}
    text, cited = compose(kept, sources, state["notes"], profile)
    return {"answer": text, "cited": cited, "claims": kept, "removed": removed, "not_found": False}


def out_of_scope(state: AnswerState, config: RunnableConfig) -> AnswerState:
    message = out_of_scope_message(current_profile(db(config)))
    return {"answer": message, "cited": [], "claims": [], "removed": [], "not_found": False, "sources": []}


def build_graph():
    graph = StateGraph(AnswerState)
    for name,step in [

        ("understand", understand),
        ("content", content),
        ("aggregate", aggregate),
        ("findings", findings),
        ("cross_document", cross_document),
        ("answer", answer),
        ("out_of_scope", out_of_scope),
        
        ]:
        graph.add_node(name,step)
    graph.add_edge(START, "understand")
    graph.add_conditional_edges("understand", next_step)
    for route in ("content","aggregate","findings","cross_document"):
        graph.add_edge(route, "answer")
    graph.add_edge("answer", END)
    graph.add_edge("out_of_scope", END)
    return graph.compile()


ASSISTANT = build_graph()

def ask(session: Session, user: User, conversation: Conversation, question: str) -> Message:
    """Answer a question in a conversation; save both messages and the audit log. The caller commits."""
    started = time.perf_counter()
    history = [(message.role, message.content) for message in conversation.messages]
    answers_so_far = [m for m in conversation.messages if m.role == MessageRole.ASSISTANT]
    previous_sources = answers_so_far[-1].sources if answers_so_far else []
    state = ASSISTANT.invoke(
        {"question": question, "history": history, "previous_sources": previous_sources},
        config={"configurable": {"session": session}},
    )

    plan, scope = state["plan"], state["scope"]
    # Appended to the conversation (not just added to the session), so its loaded
    # message list stays current for the response and the next question.
    conversation.messages.append(Message(role=MessageRole.USER, content=question))
    reply = Message(
        role=MessageRole.ASSISTANT,
        content=state["answer"],
        route=QuestionRoute(plan.route),
        sources=[source.as_json() for source in state["cited"]],
    )
    conversation.messages.append(reply)
    session.flush()  # reply.id for the log
    session.add(
        QueryLog(
            message_id=reply.id,
            user_id=user.id,
            question=question,
            standalone_question=plan.standalone_question,
            route=QuestionRoute(plan.route),
            plan={**plan.model_dump(mode="json"), "matched": {
                "vendor_ids": [str(i) for i in scope.vendor_ids], "component_ids": [str(i) for i in scope.component_ids],
                "document_types": scope.document_type_names, "unmatched": scope.unmatched,
                "searched_as_topic": scope.searched_as_topic}},
            retrieved=state.get("retrieved", []),
            tool_calls=state.get("tool_calls", []),
            answer=state["answer"],
            removed_claims=state.get("removed", []),
            not_found=state["not_found"],
            models={task.value: MODEL_BY_TASK[task] for task in ASSISTANT_TASKS},
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    )
    return reply