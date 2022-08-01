import os
import sys
import logging
import time
from http import HTTPStatus
from typing import Dict
import datetime

import requests
from telegram import Bot
from dotenv import load_dotenv

from endpoints import PRACTICUM_ENDPOINT
from exceptions import (
    SendMessageException, ApiResponseException, ApiResponseStatusException
)

load_dotenv()


TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TELEGRAM_RETRY_TIME: int = 600
PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
LAST_HOMEWORK_LIST_ID: int = 0
ONE_MONTH_SECONDS: int = 2629743
ENDPOINT = PRACTICUM_ENDPOINT
HEADERS: Dict[str, str] = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}
HOMEWORK_VERDICTS: Dict[str, str] = {
    'approved': 'Замечаний нет.',
    'reviewing': 'Ревьювер проверяет работу.',
    'rejected': 'Есть замечания.'
}

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

cache_errors = []


def send_message(bot, message):
    """Отправляет сообщение пользователю о статусе домашней работы."""
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
    except SendMessageException:
        message = 'Сбой при отправке сообщения пользователю'
        logger.exception(message)
        raise SendMessageException(message)
    else:
        logger.info('Сообщение успешно отправлено')


def get_api_answer(current_timestamp):
    """Запрашивает у API Яндекс информацию о домашней работе."""
    timestamp = current_timestamp or int(time.time())
    params = {'from_date': timestamp}
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=params)
        if response.status_code == HTTPStatus.OK:
            return response.json()
        message = f'Ошибка эндпоинта. Статус код  - {response.status_code}'
        logger.error(message)
        raise ApiResponseStatusException(message)
    except ApiResponseException:
        message = 'Не удалось выполнить запрос. Эндпоинт API Яндекс недоступен'
        logger.exception(message)
        raise ApiResponseException(message)


def check_response(response):
    """Проверяет ответ API Яндекс на корректность.
    Корректным считается ответ в виде словаря, располагающим в качестве ключей
    строками homeworks и current_date.
    """
    logger.debug('Производится проверка ответа API Яндекс на корректность')
    if not isinstance(response, dict):
        message = (
            'Функция принимает словарь в качестве аргумента,'
            f'передан - {type(response)}'
        )
        logger.error(message)
        raise TypeError(message)
    check_keys = ('homeworks', 'current_date')
    if (
        all(key in response for key in check_keys)
        and isinstance(response.get('homeworks'), list)
    ):
        return response.get('homeworks')
    message = 'Отсутствуют ожидаемые ключи в ответе API Яндекс'
    logger.error(message)
    raise KeyError(message)


def parse_status(homework):
    """Формирует сообщение со статусом проверки домашней работы."""
    if 'homework_name' not in homework:
        message = 'Ключ homework_name отсутствует в ответе от API Яндекс'
        logger.error(message)
        raise KeyError(message)
    homework_name = homework.get('homework_name')
    reviewer_comment = homework.get('reviewer_comment', 'коммента нет')
    homework_status = homework.get('status')
    if homework_status not in HOMEWORK_VERDICTS:
        message = (
            'Недокументированный статус проверки'
            f'в ответе API Яндекс - {homework_status}'
        )
        logger.error(message)
        raise KeyError(message)
    verdict = HOMEWORK_VERDICTS.get(homework_status)
    cache_errors.clear()
    now = datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
    return (
        f'{now}\n'
        f'Работа - "{homework_name}".\n'
        f'Вердикт - {verdict}\n'
        f'Комментарий - {reviewer_comment}\n'
    )


def check_tokens():
    """Проверяет доступность переменных окружения."""
    if not PRACTICUM_TOKEN:
        logger.critical('Отсутствует переменная окружения PRACTICUM_TOKEN')
        return False
    if not TELEGRAM_TOKEN:
        logger.critical('Отсутствует переменная окружения TELEGRAM_TOKEN')
        return False
    if not TELEGRAM_CHAT_ID:
        logger.critical('Отсутствует переменная окружения TELEGRAM_CHAT_ID')
        return False
    return True


def send_error_message(message):
    """Отправляет пользователю сообщение об ошибке."""
    if message not in cache_errors:
        bot = Bot(token=TELEGRAM_TOKEN)
        send_message(bot, message)
        cache_errors.append(message)


def main():
    """Основная логика работы бота."""
    if check_tokens() is False:
        logger.critical('Программа принудительно остановлена.')
        sys.exit()
    current_timestamp = int(time.time()) - TELEGRAM_RETRY_TIME
    while True:
        try:
            bot = Bot(token=TELEGRAM_TOKEN)
            response = get_api_answer(current_timestamp)
            homework = check_response(response)
            message = parse_status(homework[LAST_HOMEWORK_LIST_ID])
            send_message(bot, message)
            current_timestamp = int(time.time())
        except IndexError:
            message = 'В ответе API Яндекс отсутствуют новые статусы'
            logger.debug(message)
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logger.exception(message)
            send_error_message(message)
        finally:
            time.sleep(TELEGRAM_RETRY_TIME)


if __name__ == '__main__':
    main()
