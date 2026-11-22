"""8502 独立页面入口（`CHG-013` S4）：多轮问答。

启动（项目根目录下，先设环境变量）：
    set RAG_DB_PATH=data\\rag.db
    set HF_HOME=.cache/models
    set RAG_LLM_API_KEY=<key>
    .venv\\Scripts\\python.exe -m streamlit run app_agent.py --server.port 8502

与 `app.py`／8501 的检索单页互不影响；不新增 HTTP 接口，问答只在页面进程内调用编排层。
"""

from __future__ import annotations

import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="法规问答 Agent · 8502", layout="wide")

from src.agent import ui  # noqa: E402

ui.render()
