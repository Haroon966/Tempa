from __future__ import annotations

import json
from typing import Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition
from pydantic import BaseModel, Field

from tempa.rag.hybrid import reciprocal_rank_fusion
from tempa.rag.ingest import search_memory
from tempa.rag.retriever import retrieve_with_sources
from tempa.router.groq_router import get_router

MAX_REWRITE_ITERATIONS = 3
MAX_SUB_QUERIES = 3

GRADE_PROMPT = (
    "You are a grader assessing relevance of a retrieved document to a user question.\n"
    "Here is the retrieved document:\n\n{context}\n\n"
    "Here is the user question: {question}\n"
    "If the document contains keyword(s) or semantic meaning related to the user question, "
    "grade it as relevant.\n"
    "Give a binary score 'yes' or 'no' to indicate whether the document is relevant."
)

REWRITE_PROMPT = (
    "Look at the input and try to reason about the underlying semantic intent / meaning.\n"
    "Here is the initial question:\n ------- \n{question}\n ------- \n"
    "Formulate an improved question:"
)

GENERATE_PROMPT = (
    "You are an assistant for question-answering tasks. "
    "Use the following pieces of retrieved context to answer the question. "
    "If you don't know the answer, just say that you don't know. "
    "Use three sentences maximum and keep the answer concise.\n"
    "Question: {question}\nContext: {context}"
)


class GradeDocuments(BaseModel):
    binary_score: str = Field(description="Relevance score: 'yes' or 'no'")


class RagState(TypedDict, total=False):
    messages: list
    rewrite_count: int
    tool_filter: str | None
    sub_queries: list[str]
    retrieved_sources: list[dict]


@tool
def retrieve_unified_memory(query: str) -> str:
    """Search Tempa's unified Agentic RAG memory across all tools."""
    text, _sources = retrieve_with_sources(query, top_k=5)
    return text


def _infer_tool_filter(question: str) -> str | None:
    from tempa.rag.filters import extract_filters_from_query

    filters = extract_filters_from_query(question)
    return filters.get("tool")


def _llm_text(messages: list[dict], category: str = "reasoning") -> str:
    router = get_router()
    response = router.chat_completion(category=category, messages=messages, max_tokens=1024)
    return response.choices[0].message.content or ""


def _langchain_role(message) -> str:
    role = getattr(message, "type", "user")
    mapping = {"human": "user", "ai": "assistant", "tool": "tool", "system": "system"}
    return mapping.get(role, "user")


def _to_groq_message(message) -> dict:
    role = _langchain_role(message)
    content = message.content
    if content is None:
        content = ""
    if not isinstance(content, str):
        content = str(content)
    if role == "tool":
        tool_call_id = getattr(message, "tool_call_id", None)
        if tool_call_id:
            return {"role": "tool", "content": content, "tool_call_id": tool_call_id}
        return {"role": "user", "content": f"Retrieved context:\n{content}"}
    if role == "assistant":
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            formatted_calls = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    args = tc.get("args", {})
                    call_id = tc.get("id", "")
                    name = tc.get("name", "")
                else:
                    args = getattr(tc, "args", {})
                    call_id = getattr(tc, "id", "")
                    name = getattr(tc, "name", "")
                formatted_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args),
                        },
                    }
                )
            return {
                "role": "assistant",
                "content": content,
                "tool_calls": formatted_calls,
            }
    return {"role": role, "content": content}


def decompose_query(state: RagState) -> dict:
    question = state["messages"][0].content if state.get("messages") else ""
    if not question or len(question.split()) < 8 or " and " not in question.lower():
        return {"sub_queries": [question] if question else []}
    try:
        router = get_router()
        response = router.chat_completion(
            category="reasoning",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Split this question into 1-3 focused sub-queries for memory search. "
                        'Return JSON only: {"queries": ["...", "..."]}\n\n'
                        f"Question: {question}"
                    ),
                }
            ],
            response_format={"type": "json_object"},
            max_tokens=256,
            temperature=0.0,
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        queries = payload.get("queries") if isinstance(payload, dict) else None
        if isinstance(queries, list) and queries:
            cleaned = [str(q).strip() for q in queries[:MAX_SUB_QUERIES] if str(q).strip()]
            if cleaned:
                return {"sub_queries": cleaned}
    except Exception:
        pass
    return {"sub_queries": [question]}


def generate_query_or_respond(state: RagState):
    router = get_router()
    response = router.chat_completion(
        category="tool_use",
        messages=[_to_groq_message(m) for m in state["messages"]],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "retrieve_unified_memory",
                    "description": retrieve_unified_memory.description,
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
    )
    msg = response.choices[0].message
    if msg.tool_calls:
        return {
            "messages": [
                AIMessage(
                    content=msg.content or "",
                    tool_calls=[
                        {
                            "id": tc.id,
                            "name": tc.function.name,
                            "args": json.loads(tc.function.arguments),
                        }
                        for tc in msg.tool_calls
                    ],
                )
            ]
        }
    return {"messages": [AIMessage(content=msg.content or "")]}


def grade_documents(state: RagState) -> Literal["generate_answer", "rewrite_question"]:
    if state.get("rewrite_count", 0) >= MAX_REWRITE_ITERATIONS:
        return "generate_answer"
    question = state["messages"][0].content
    context = state["messages"][-1].content
    prompt = GRADE_PROMPT.format(question=question, context=context)
    router = get_router()
    response = router.chat_completion(
        category="reasoning",
        messages=[{"role": "user", "content": prompt + "\nReply with only yes or no."}],
        max_tokens=16,
    )
    score = (response.choices[0].message.content or "no").strip().lower()
    return "generate_answer" if score.startswith("y") else "rewrite_question"


def rewrite_question(state: RagState):
    question = state["messages"][0].content
    prompt = REWRITE_PROMPT.format(question=question)
    text = _llm_text([{"role": "user", "content": prompt}], category="reasoning")
    return {
        "messages": [HumanMessage(content=text)],
        "rewrite_count": state.get("rewrite_count", 0) + 1,
    }


def retrieve_memory(state: RagState):
    messages = state.get("messages") or []
    question = messages[0].content if messages else ""
    sub_queries = state.get("sub_queries") or [question]
    tool_filter = state.get("tool_filter")

    ranked_lists: list[list[str]] = []
    doc_by_id: dict[str, dict] = {}
    all_sources: list[dict] = list(state.get("retrieved_sources") or [])

    for sub_query in sub_queries:
        results = search_memory(sub_query, top_k=5, tool=tool_filter)
        ranked: list[str] = []
        for item in results:
            meta = item["metadata"]
            doc_id = f"{meta.get('tool')}:{meta.get('source')}:{hash(item['content'])}"
            ranked.append(doc_id)
            doc_by_id[doc_id] = item
            source = {
                "label": f"{meta.get('tool', '?')}/{meta.get('source', '?')}",
                "tool": meta.get("tool"),
                "source": meta.get("source"),
                "title": meta.get("title") or "",
                "timestamp": meta.get("timestamp") or "",
                "score": item.get("score"),
            }
            if source not in all_sources:
                all_sources.append(source)
        if ranked:
            ranked_lists.append(ranked)

    if ranked_lists:
        fused_ids = [doc_id for doc_id, _score in reciprocal_rank_fusion(ranked_lists)[:8]]
    else:
        fused_ids = []

    parts = []
    for doc_id in fused_ids:
        item = doc_by_id.get(doc_id)
        if not item:
            continue
        meta = item["metadata"]
        header = f"[{meta.get('tool', '?')}/{meta.get('source', '?')}]"
        parts.append(f"{header}\n{item['content']}")

    context = "\n\n---\n\n".join(parts)
    tool_call_id = "retrieve"
    for msg in reversed(messages):
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            first = tool_calls[0]
            if isinstance(first, dict):
                tool_call_id = first.get("id", tool_call_id)
            break

    return {
        "messages": [ToolMessage(content=context, tool_call_id=tool_call_id)],
        "retrieved_sources": all_sources,
    }


def generate_answer(state: RagState):
    question = state["messages"][0].content
    context = state["messages"][-1].content
    prompt = GENERATE_PROMPT.format(question=question, context=context)
    text = _llm_text([{"role": "user", "content": prompt}], category="text")
    return {"messages": [AIMessage(content=text)]}


def build_rag_graph():
    workflow = StateGraph(RagState)
    workflow.add_node("decompose_query", decompose_query)
    workflow.add_node("generate_query_or_respond", generate_query_or_respond)
    workflow.add_node("retrieve", retrieve_memory)
    workflow.add_node("rewrite_question", rewrite_question)
    workflow.add_node("generate_answer", generate_answer)

    workflow.add_edge(START, "decompose_query")
    workflow.add_edge("decompose_query", "generate_query_or_respond")
    workflow.add_conditional_edges(
        "generate_query_or_respond",
        tools_condition,
        {"tools": "retrieve", END: END},
    )
    workflow.add_conditional_edges("retrieve", grade_documents)
    workflow.add_edge("generate_answer", END)
    workflow.add_edge("rewrite_question", "generate_query_or_respond")
    return workflow.compile()


_rag_graph = None


def get_rag_graph():
    global _rag_graph
    if _rag_graph is None:
        _rag_graph = build_rag_graph()
    return _rag_graph


def invoke_rag_graph(query: str) -> dict:
    result = invoke_rag_graph_with_sources(query)
    return {"messages": [AIMessage(content=result["answer"])]}


def invoke_rag_graph_with_sources(query: str) -> dict[str, object]:
    tool_filter = _infer_tool_filter(query)
    initial: RagState = {
        "messages": [HumanMessage(content=query)],
        "rewrite_count": 0,
        "tool_filter": tool_filter,
        "sub_queries": [],
        "retrieved_sources": [],
    }
    graph = get_rag_graph()
    final = graph.invoke(initial)
    answer = final["messages"][-1].content if final.get("messages") else ""
    return {
        "answer": answer or "",
        "sources": final.get("retrieved_sources") or [],
        "messages": final.get("messages") or [],
    }


def invoke_rag_fast(query: str) -> str:
    answer, _sources = invoke_rag_fast_with_sources(query)
    return answer


def invoke_rag_fast_with_sources(query: str) -> tuple[str, list[dict]]:
    """Single retrieve + grade + answer pass for low-latency channels (e.g. WhatsApp)."""
    tool_filter = _infer_tool_filter(query)
    context, sources = retrieve_with_sources(query, top_k=5, tool=tool_filter)
    if not context.strip():
        return "No relevant memory found.", []

    grade_prompt = GRADE_PROMPT.format(question=query, context=context)
    router = get_router()
    response = router.chat_completion(
        category="reasoning",
        messages=[{"role": "user", "content": grade_prompt + "\nReply with only yes or no."}],
        max_tokens=16,
    )
    score = (response.choices[0].message.content or "no").strip().lower()
    if not score.startswith("y"):
        return "No relevant memory found.", []

    answer_prompt = GENERATE_PROMPT.format(question=query, context=context)
    return _llm_text([{"role": "user", "content": answer_prompt}], category="text"), sources
