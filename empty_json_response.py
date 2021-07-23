import requests
from json.decoder import JSONDecodeError


class EmptyJSONResponse(requests.Response):
    def __init__(self):
        super().__init__()
        self.__setstate__({"_content": "{}".encode()})
