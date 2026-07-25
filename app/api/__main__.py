"""Entry point for `python -m app.api`. Runs the FastAPI app via uvicorn,
matching the `python -m app.workflows` precedent.

`configure_logging()` is called here -- not inside `app.api.main`'s
`lifespan`/`create_app()` -- for the same reason every other CLI in
this codebase (`app.rag.ask`, `app.workflows`, ...) calls it from its
own `main()` rather than at import time: `create_app()`/`lifespan` run
during every test via `TestClient`, and `configure_logging()` replaces
the root logger's handler list, which would silently evict pytest's
own `caplog` handler (used by `tests/test_guardrails.py`) for the rest
of the test process. `log_config=None` tells uvicorn not to install its
own logging config over this one.
"""

import uvicorn

from app.config.logging import configure_logging
from app.config.settings import ApiSettings


def main() -> None:
    configure_logging()
    settings = ApiSettings.from_env()
    uvicorn.run("app.api.main:app", host=settings.host, port=settings.port, reload=False, log_config=None)


if __name__ == "__main__":
    main()
