from pydantic import BaseModel, Field


class DatasetCreate(BaseModel):
    name: str = Field(default="", max_length=500)
    source: str = Field(default="", max_length=500)


class CollectRequest(BaseModel):
    query: str = Field(default="", max_length=1000)


class PlanRequest(CollectRequest):
    dataset_id: str | None = None
    collect: bool = False


class QuestionRequest(BaseModel):
    question: str = Field(default="", max_length=1000)
