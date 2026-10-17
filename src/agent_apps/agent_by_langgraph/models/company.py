from pydantic import BaseModel, Field


class Company(BaseModel):
    name: str = Field(description="The company name")
    ticker: str = Field(description="The stock ticker symbol")
    founded_year: int = Field(description="The year the company was founded")
