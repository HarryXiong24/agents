from pydantic import BaseModel, Field


class CityReport(BaseModel):
    city: str = Field(description="The city name")
    weather: str = Field(description="A short weather description")
    population: str = Field(description="The population")
    other_info: str = Field(
        description="Other information in the reply, if any. This is optional and can be empty.",
        default="",
    )
