from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)
import sqlite3


class Settings(BaseSettings):
    threads_guild: int
    threads_channel: int
    threads_role: int
    genai_thread: int
    everyone_thread: int
    owner: int
    bot_token: str
    enable_genai: bool
    enable_api: bool
    model_config = SettingsConfigDict(toml_file="config.toml")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (TomlConfigSettingsSource(settings_cls),)


settings: Settings = Settings()  # type: ignore
db = sqlite3.connect("state.db")