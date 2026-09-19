from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str
    llm_api_key: str
    llm_base_url: str = "https://cheapai.io/v1"
    llm_model: str = "gpt-5.6-luna"

    allowed_user_ids: str = ""
    history_limit: int = 36
    search_region: str = "ru-ru"
    search_results: int = 6
    lore_path: Path = ROOT / "lore.md"

    @property
    def allowed_ids(self) -> set[int]:
        if not self.allowed_user_ids.strip():
            return set()
        result: set[int] = set()
        for part in self.allowed_user_ids.split(","):
            part = part.strip()
            if part.isdigit():
                result.add(int(part))
        return result


settings = Settings()


def load_lore() -> str:
    if settings.lore_path.exists():
        return settings.lore_path.read_text(encoding="utf-8").strip()
    return "Персонаж без описания. Отвечай кратко и честно."
