from sqlmodel import SQLModel

from gateway.domain import models  # noqa: F401, imports tables

target_metadata = SQLModel.metadata
