from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_KEY: str | None = None
    USE_API_KEY: bool | None = False

    # Source engine (Parallel Constrained Decision Engine) connection.
    # host.docker.internal resolves to the Docker host from inside the container.
    SOURCE_API_BASE_URL: str = "http://host.docker.internal:9321"
    SOURCE_API_TIMEOUT_SECONDS: float = 120.0  # engine queues behind a GPU lock

    # Response model id. Empty -> echo the model string the client sent.
    REPORTED_MODEL_ID: str = ""

    # Comma-separated list of accepted model ids. Empty -> accept any model string.
    ALLOWED_MODELS: str = ""

    # chars -> tokens estimate for usage.input_tokens (documented as an estimate).
    USAGE_TOKEN_DIVISOR: float = 4.0


config = Settings()
