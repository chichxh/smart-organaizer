import os
from langchain_gigachat import GigaChat
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from .config import SYSTEM_PROMPT
from .calendar_tools import TOOLS


def create_agent():
    """
    Создает и настраивает LLM-агента с инструментами для работы с календарем.
    """
    # Инициализация GigaChat
    GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS", "")
    llm = GigaChat(
        credentials=GIGACHAT_CREDENTIALS,
        model="GigaChat",
        verify_ssl_certs=False  # в проде включите True при корректном сертификате
    )

    # Создание агента с инструментами
    memory = MemorySaver()
    agent = create_react_agent(
        model=llm,
        tools=TOOLS,
        checkpointer=memory,
        state_modifier=SYSTEM_PROMPT
    )
    
    return agent


def get_agent_config():
    """
    Возвращает конфигурацию для агента.
    """
    return {
        "configurable": {"thread_id": "demo"}, 
        "recursion_limit": 50
    }
