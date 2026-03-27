"""
Streamlit Chat UI for IPL 2025 Press Conference RAG Bot
Run: streamlit run app.py
"""

import json
import os
from datetime import datetime

import chromadb
import streamlit as st

import config
import rag

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="IPL 2025 Press Conference Bot",
    page_icon="🏏",
    layout="wide",
)

# ── Session state ─────────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []   # list of {role, content, sources}


# ── Sidebar stats ─────────────────────────────────────────────────────────────

def get_collection_stats() -> dict:
    try:
        client = chromadb.PersistentClient(path=config.VECTORSTORE_DIR)
        col    = client.get_collection(config.COLLECTION_NAME)
        count  = col.count()
    except Exception:
        count = 0

    doc_count = 0
    if os.path.exists(config.CHUNKS_PATH):
        try:
            with open(config.CHUNKS_PATH) as f:
                chunks = json.load(f)
            doc_count = len({c.get("source_url", c.get("file_path")) for c in chunks})
        except Exception:
            pass

    embed_time = ""
    if os.path.exists(config.VECTORSTORE_DIR):
        mtime = os.path.getmtime(config.VECTORSTORE_DIR)
        embed_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

    return {"vectors": count, "docs": doc_count, "embed_time": embed_time}


with st.sidebar:
    st.title("🏏 IPL 2025 RAG Bot")
    st.markdown("Ask questions about IPL 2025 player and captain interviews, match reports, and post-match reactions.")
    st.divider()

    stats = get_collection_stats()
    st.metric("Documents scraped", stats["docs"])
    st.metric("Chunks in vector store", stats["vectors"])
    st.caption(f"Collection: `{config.COLLECTION_NAME}`")
    st.caption(f"Embed model: `{config.EMBED_MODEL}`")
    st.caption(f"LLM: `{config.LLM_MODEL}`")
    if stats["embed_time"]:
        st.caption(f"Last embedded: {stats['embed_time']}")

    st.divider()
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()

    st.markdown("**Example questions:**")
    examples = [
        "What did Virat Kohli say after RCB won the IPL 2025 final?",
        "How did captains react to the May suspension?",
        "What did Suryakumar Yadav say about MI's batting?",
        "How did Punjab Kings captain react after losing the final?",
    ]
    for ex in examples:
        if st.button(ex, use_container_width=True):
            st.session_state._prefill = ex
            st.rerun()


# ── Main chat area ────────────────────────────────────────────────────────────

st.header("IPL 2025 Press Conference Q&A")

# Render existing conversation
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander(f"Sources used ({len(msg['sources'])})"):
                for i, s in enumerate(msg["sources"], 1):
                    st.markdown(
                        f"**[{i}] {s.get('title', 'N/A')}**  \n"
                        f"Date: {s.get('date', 'N/A')} | "
                        f"Teams: {s.get('teams', 'N/A')}  \n"
                        f"[View source]({s.get('url', '#')})"
                    )


# Handle prefilled question from sidebar buttons
prefill = st.session_state.pop("_prefill", None)

# Chat input
question = st.chat_input("Ask about IPL 2025 players, captains, coaches …") or prefill

if question:
    # Show user message
    st.session_state.messages.append({"role": "user", "content": question, "sources": []})
    with st.chat_message("user"):
        st.markdown(question)

    # Query RAG pipeline
    with st.chat_message("assistant"):
        with st.spinner("Retrieving context and querying Claude …"):
            try:
                result = rag.ask(question)
                answer  = result["answer"]
                sources = result["sources"]
            except EnvironmentError as e:
                answer  = f"⚠️ Configuration error: {e}"
                sources = []
            except Exception as e:
                answer  = f"⚠️ Something went wrong: {e}"
                sources = []

        st.markdown(answer)

        if sources:
            with st.expander(f"Sources used ({len(sources)})"):
                for i, s in enumerate(sources, 1):
                    st.markdown(
                        f"**[{i}] {s.get('title', 'N/A')}**  \n"
                        f"Date: {s.get('date', 'N/A')} | "
                        f"Teams: {s.get('teams', 'N/A')}  \n"
                        f"[View source]({s.get('url', '#')})"
                    )

    st.session_state.messages.append(
        {"role": "assistant", "content": answer, "sources": sources}
    )
