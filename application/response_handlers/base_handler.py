from abc import ABC, abstractmethod
from pathlib import Path
from json import dump

from application.loggers import get_logger

logger = get_logger(__name__)


class BaseResponseHandler(ABC):

    def __init__(self, request_url, depth_of_search, response):
        self.request_url = request_url
        self.depth_of_search = depth_of_search
        self.response = response

    @property
    def name(self):
        return self.response["name"]

    @property
    def clean_name(self):
        return self.name.replace("/", "_slash_").replace("\\", "_back_slash_")

    @abstractmethod
    def check_url_match(self, url):
        pass

    @abstractmethod
    def write_to_disk(self):
        pass

    def _write_to_disk(self, output_path: Path):
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            dump(self.response, f, indent=4)

        logger.info(f'SUCCESS: {output_path.name}')

    @abstractmethod
    def write_to_neo4j(self, driver, database="neo4j"):
        pass

    @abstractmethod
    def follow_links(self):
        pass

    @abstractmethod
    def write_to_sqlite(self):
        pass
