from sqlmodel import SQLModel

from yapit.gateway.domain import models  # noqa: F401, imports tables

target_metadata = SQLModel.metadata
