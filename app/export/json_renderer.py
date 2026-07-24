"""JSON export rendering (Milestone 7).

Renders the same envelope dict as `app.export.markdown_renderer`, just
pretty-printed JSON -- one shared envelope shape backs both formats.
"""

from __future__ import annotations

import json
from typing import Any


def render_export_json(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, default=str)
