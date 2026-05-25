from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from typing import Annotated, TypedDict
from pathlib import Path

from config import get_settings
from db.database import get_db
from db.crud import create_task, get_task, list_tasks, update_task_status, list_overdue_tasks, update_task_fields, log_decisions, list_decisions, set_sprint_goal, get_sprint_goal, list_members, get_history, append_message
from agent.tools import ALL_TOOLS, set_chat_id

settings = get_settings()


# System prompt

_SYSTEM_PROMPT = Path("prompts/system.md").read_text(encoding="utf-8")

# LLM Setup

LLM = ChatGoogleGenerativeAI(
    api_key=settings.gemini_api_key,
    model=settings.model_name,
    # temperature=settings.temperature,
    max_tokens=1024
).bind_tools(ALL_TOOLS)


# Define state

class AgentState(TypedDict):
    chat_id: str
    sender_name: str
    messages: Annotated[list[BaseMessage], add_messages]


# Define graph nodes
# Node1: Context node

def context_node(state: AgentState) -> dict:
    """
    Load conversation history from DB and prepend the system prompt
    (with live sprint goal injected).
    Called once at the start of every agent run.
    """
    chat_id = state["chat_id"]

    with get_db() as db:
        sg = get_sprint_goal(db, chat_id)
        sprint_text = sg.goal if sg else None

    system_content = _SYSTEM_PROMPT
    if sprint_text:
        system_content += f"\n\n## Current Sprint Goal\n{sprint_text}"

    # load message history from DB
    with get_db() as db:
        rows = get_history(db, chat_id)
        history: list[BaseMessage] = []
        for row in rows:
            if row.role == "user":
                content = row.content
                if row.sender:
                    content = f"[{row.sender}]: {content}"
                history.append(HumanMessage(content=content))
            elif row.role == "assistant":
                history.append(AIMessage(content=row.content))
 
    # System message goes first, then history, then the new user message
    # (new user message is already in state["messages"] from the caller)
    new_messages = state["messages"]
    full_messages = [SystemMessage(content=system_content)] + history + new_messages
 
    return {"messages": full_messages}


# Node2: call LLM with tools

def call_llm(state: AgentState) -> dict:
    """Invoke Gemini. May return text, tool calls, or both."""
    response = LLM.invoke(state["messages"])
    return {"messages": [response]}


# Node3: run tools

def run_tools(state: AgentState) -> dict:
    """
    Execute every tool call in the last AI message.
    Returns ToolMessage results which get appended to state.
    """
    set_chat_id(state["chat_id"])
 
    last_message = state["messages"][-1]
    tool_results: list[ToolMessage] = []
 
    tool_map = {t.name: t for t in ALL_TOOLS}

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id   = tool_call["id"]

        tool_fn = tool_map.get(tool_name)
        if tool_fn is None:
            result = f"Unknown tool: {tool_name}"
        else:
            try:
                result = tool_fn.invoke(tool_args)
            except Exception as e:
                result = f"Tool '{tool_name}' failed: {e}"
 
        tool_results.append(
            ToolMessage(content=str(result), tool_call_id=tool_id)
        )
 
    return {"messages": tool_results}


# Node2: should continue or not?

def should_continue(state: AgentState) -> str:
    """Route: if the last AI message has tool calls → run_tools, else → end."""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "run_tools"
    return END


# Build the graph

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)  

    graph.add_node("build_context", context_node)
    graph.add_node("call_llm", call_llm)
    graph.add_node("run_tools", run_tools)

    graph.set_entry_point("build_context")

    graph.add_edge("build_context", "call_llm")
    graph.add_conditional_edges("call_llm", should_continue, {"run_tools": "run_tools", END: END})
    graph.add_edge("run_tools", "call_llm")

    return graph.compile()


agent_graph = build_graph()


# Calling the agent as API

async def run_agent(chat_id: str, sender_name: str, user_message: str) -> str:
    """
    Entry point called by the bot and scheduler.
 
    Persists the incoming message, runs the graph, persists the reply,
    and returns the final text to send back to Telegram.
    """
    with get_db() as db:
        append_message(db, chat_id, "user", user_message, sender=sender_name)

    initial_state: AgentState = {
        "chat_id":     chat_id,
        "sender_name": sender_name,
        "messages":    [HumanMessage(content=f"[{sender_name}]: {user_message}")],
    }

    final_state = await agent_graph.ainvoke(initial_state)

    reply = ""
    for msg in reversed(final_state["messages"]):
        if not isinstance(msg, AIMessage):
            continue

        # Plain string content
        if isinstance(msg.content, str) and msg.content.strip():
            reply = msg.content.strip()
            break

        # List content (mixed text + tool_use blocks)
        if isinstance(msg.content, list):
            text_parts = []
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = block.get("text", "").strip()
                    if t:
                        text_parts.append(t)
            if text_parts:
                reply = "\n".join(text_parts)
                break

    # If Claude used tools but gave no final text, generate a confirmation
    if not reply:
        from langchain_core.messages import ToolMessage
        tool_results = [
            m for m in final_state["messages"]
            if isinstance(m, ToolMessage)
        ]
        if tool_results:
            # Agent acted but didn't narrate — ask it to summarise
            last_tool_output = tool_results[-1].content
            reply = last_tool_output if last_tool_output else "Done"
        else:
            reply = "Got it!"
            
    # Persistent reply
    with get_db() as db:
        append_message(db, chat_id, "assistant", reply)
    return reply
