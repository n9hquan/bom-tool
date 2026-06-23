from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mouser_api_key: str = ""
    digikey_client_id: str = ""
    digikey_client_secret: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
