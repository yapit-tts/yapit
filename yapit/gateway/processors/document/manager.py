from yapit.gateway.processors.base import ProcessorManager
from yapit.gateway.processors.document.base import BaseDocumentProcessor


class DocumentProcessorManager(ProcessorManager[BaseDocumentProcessor]):
    def load_processors(self, config_path: str) -> None:
        self._load_processors(config_path)
