"""Entry point for `python -m app.api`. Runs the FastAPI app via uvicorn,
matching the `python -m app.workflows` precedent."""

import uvicorn

from app.config.settings import ApiSettings


def main() -> None:
    settings = ApiSettings.from_env()
    uvicorn.run("app.api.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
