from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    app_id: str = "spotify"


class ChartSeries(BaseModel):
    name: str
    values: list[float]


class ChartSpec(BaseModel):
    type: Literal["line", "bar"]
    title: str
    x: list[str]
    series: list[ChartSeries]


class FinalAnswer(BaseModel):
    answer: str
    insufficient_data: bool
    chart: ChartSpec | None = None
