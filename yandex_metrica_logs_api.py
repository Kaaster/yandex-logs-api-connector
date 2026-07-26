import requests
from datetime import datetime
from time import sleep as time_sleep
from csv import reader as csv_reader, writer as csv_writer
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class YandexMetricaLogsAPI:
    """
    Класс для работы с Logs API Яндекс.Метрики
    """

    DEFAULT_VALUE = 'unknown'
    DATE_FORMAT = '%Y-%m-%d'
    DEFAULT_TIMEOUT = 30
    DEFAULT_SLEEP_SEC = 30
    BYTES_PER_GB = 1e9

    def __init__(self, counter_id, access_token):
        """
        :param counter_id: номер счетчика
        :param access_token: токен
        """
        self.access_token = access_token
        self.counter_id = counter_id
        self.headers = {
            'Accept': 'application/json',
            'Authorization': f'OAuth {access_token}',
        }

    @property
    def request_credentials(self):
        return dict(counter_id=self.counter_id, access_token=self.access_token, headers=self.headers)

    def handle_bad_response(self, response):
        return dict(status_code=response.status_code, message=response.json().get('message', self.DEFAULT_VALUE))

    @staticmethod
    def response_content_to_csv(request_id, part_number, content):
        """
        Сохранение данных в csv формате
        """
        content_decoded = content.decode('utf-8').splitlines()
        content_reader = csv_reader(content_decoded, delimiter='\t')
        content_list = [row for row in content_reader]
        file_name = f'{request_id}-{part_number}.csv'

        with open(file_name, mode='w', encoding='utf-8', newline='') as file:
            writer = csv_writer(file)
            writer.writerows(content_list)

        logger.info(f'data saved to {file_name}')

    def query_metrics(self, params, response_json):
        log_request_evaluation = response_json.get('log_request_evaluation', {})
        return dict(
            possible=log_request_evaluation.get('possible'),
            query_params=dict(
                size_requested_gb=log_request_evaluation.get('expected_size', 0.0) / self.BYTES_PER_GB,
                days_requested=(datetime.strptime(params.get('date2'), self.DATE_FORMAT) -
                                datetime.strptime(params.get('date1'), self.DATE_FORMAT)).days + 1,
            ),
            max_possible_params=dict(
                max_possible_size_gb=log_request_evaluation.get('log_request_sum_max_size', 0.0) / self.BYTES_PER_GB,
                max_possible_days=log_request_evaluation.get('max_possible_day_quantity', 0)
            )
        )

    def make_api_call(self, url, method='GET', params=None, data=None, timeout=DEFAULT_TIMEOUT):
        """
        Общий метод для выполнения API-запросов
        """
        try:
            if method == 'GET':
                response = requests.get(url=url, headers=self.headers, params=params, timeout=timeout)
            elif method == 'POST':
                response = requests.post(url=url, headers=self.headers, data=data, timeout=timeout)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if response.status_code == 200:
                return response.json()

            return self.handle_bad_response(response)

        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            return dict(status_code=500, message=str(e))

    def get_logrequests(self, timeout=DEFAULT_TIMEOUT):
        """
        Запрос списка запрошенных логов
        """
        url = f'https://api-metrika.yandex.net/management/v1/counter/{self.counter_id}/logrequests'
        return self.make_api_call(url, method='GET', timeout=timeout)

    def get_logrequests_evaluate(self, params, timeout=DEFAULT_TIMEOUT):
        """
        Проверка возможности выполнения запроса
        """
        url = f'https://api-metrika.yandex.net/management/v1/counter/{self.counter_id}/logrequests/evaluate'
        return self.make_api_call(url, method='GET', params=params, timeout=timeout)

    def post_logrequests(self, params, timeout=DEFAULT_TIMEOUT):
        """
        Запрос на подготовку логов
        """
        url = f'https://api-metrika.yandex.net/management/v1/counter/{self.counter_id}/logrequests'
        return self.make_api_call(url, method='POST', data=params, timeout=timeout)

    def get_logrequests_result(self, request_id, timeout=DEFAULT_TIMEOUT):
        """
        Статус подготовки логов
        """
        url = f'https://api-metrika.yandex.net/management/v1/counter/{self.counter_id}/logrequest/{request_id}'
        return self.make_api_call(url, method='GET', timeout=timeout)

    def get_logrequest_download(self, request_id, part_number, timeout=DEFAULT_TIMEOUT):
        """
        Скачивание готовых данных
        """
        url = f'https://api-metrika.yandex.net/management/v1/counter/{self.counter_id}/logrequest/{request_id}/part/{part_number}/download'
        return self.make_api_call(url, method='GET', timeout=timeout)

    def post_logrequest_clean(self, request_id, timeout=DEFAULT_TIMEOUT):
        """
        Очистка запрошенных логов по request_id
        """
        url = f'https://api-metrika.yandex.net/management/v1/counter/{self.counter_id}/logrequest/{request_id}/clean'
        return self.make_api_call(url, method='POST', timeout=timeout)

    def post_logrequest_cancel(self, request_id, timeout=DEFAULT_TIMEOUT):
        """
        Отмена еще не обработанного запроса логов по request_id
        """
        url = f'https://api-metrika.yandex.net/management/v1/counter/{self.counter_id}/logrequest/{request_id}/cancel'
        return self.make_api_call(url, method='POST', timeout=timeout)

    def make_job(self, params, timeout=DEFAULT_TIMEOUT, sleep_sec=DEFAULT_SLEEP_SEC):
        if not params:
            logger.error("Error: 'params' parameter is required.")
            return dict(status_code=400, message="Params are missing")

        log_request_evaluate = self.get_logrequests_evaluate(params=params, timeout=timeout)

        if log_request_evaluate.get('possible', False):
            post_logrequest_response = self.post_logrequests(params=params, timeout=timeout)
            request_id = post_logrequest_response.get('request_id', None)
            query_params = log_request_evaluate.get('query_params', self.DEFAULT_VALUE)

            if request_id is not None:
                logger.info(f'request_id: {request_id}. query_params: {query_params}')

                for attempt in range(100):
                    time_sleep(sleep_sec)
                    log_request_result = self.get_logrequests_result(request_id=request_id, timeout=timeout)
                    status = log_request_result.get('status', None)

                    if status is None or status not in ['created', 'processed']:
                        return log_request_result
                    elif status == 'created':
                        logger.info(f'Attempt #{attempt}: {log_request_result}')
                    else:
                        for part_number in log_request_result.get('parts', []):
                            log_request_download = self.get_logrequest_download(request_id=request_id, part_number=part_number, timeout=timeout)

                            if log_request_download.get('content', None) is not None:
                                self.response_content_to_csv(request_id=request_id, part_number=part_number, content=log_request_download.get('content', None))
                            else:
                                logger.error(log_request_download)
                        return self.post_logrequest_clean(request_id=request_id, timeout=timeout)
            else:
                return post_logrequest_response
        else:
            return log_request_evaluate
