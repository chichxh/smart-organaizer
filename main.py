import os
from dotenv import load_dotenv

from src.calendar_api import get_calendar_service
from src.text_utils import try_handle_create_event_locally, handle_quick_responses, _sanitize_llm
from src.llm_agent import create_agent, get_agent_config

# Загружаем переменные окружения
load_dotenv()


def main():
    """
    Запускает основной цикл общения с пользователем.
    """
    print("Привет! Я смарт-органайзер. Спроси меня о расписании, добавь встречу или забронируй фокус-время.")
    print("Например: «Повестка на 2025-10-10», «Создай событие «Встреча» 2025-10-12 14:00–15:00», «Забронируй 45 минут сегодня».")
    print("Напиши 'выход' для завершения.")

    # Инициируем сервис заранее — чтобы сразу запросить авторизацию при первом запуске
    try:
        _ = get_calendar_service()
    except FileNotFoundError:
        print("Не найден credentials.json. Поместите файл в каталог проекта и перезапустите.")
        return
    except Exception as e:
        print("Не удалось инициализировать доступ к Google Calendar:", e)

    # Создаем агента
    agent = create_agent()
    cfg = get_agent_config()

    while True:
        try:
            user_input = input("Ты: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nРабота агента завершена.")
            break

        if user_input.lower() == "выход":
            print("Работа агента завершена.")
            break

        # 1) локальная обработка «создай/добавь событие ...»
        local_created = try_handle_create_event_locally(user_input)
        if local_created is not None:
            print("Агент:", local_created)
            continue

        # 2) локальные быстрые ответы «какой сегодня день/дата»
        quick_response = handle_quick_responses(user_input)
        if quick_response is not None:
            print("Агент:", quick_response)
            continue

        # 3) иначе — отдаём в LLM-агента
        try:
            response = agent.invoke({"messages": [("user", user_input)]}, config=cfg)
            answer = response["messages"][-1].content
            print("Агент:", _sanitize_llm(answer))
        except Exception as e:
            print("Агент: Произошла ошибка:", e)



if __name__ == "__main__":
    main()