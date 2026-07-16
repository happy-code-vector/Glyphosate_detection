"""Firebase App Check enforcement.

When config.REQUIRE_APPCHECK is true, every protected request must carry a valid
App Check token in the X-Firebase-AppCheck header. Verification uses the Firebase
Admin SDK with Application Default Credentials (on Cloud Run this is the runtime
service account; locally, `gcloud auth application-default login`). No
service-account JSON is ever committed.

Start in monitor mode (REQUIRE_APPCHECK=false), observe traffic in the Firebase
console, then flip to enforce.
"""
from __future__ import annotations

import logging

from fastapi import Header, HTTPException, status

from api.config import FIREBASE_PROJECT_ID, REQUIRE_APPCHECK

logger = logging.getLogger("api.security")
_app_initialized = False


def _init_firebase() -> None:
    global _app_initialized
    if _app_initialized:
        return
    import firebase_admin
    from firebase_admin import credentials

    cred = credentials.ApplicationDefault()
    if FIREBASE_PROJECT_ID:
        firebase_admin.initialize_app(cred, {"projectId": FIREBASE_PROJECT_ID})
    else:
        firebase_admin.initialize_app(cred)
    _app_initialized = True


def verify_appcheck(
    x_firebase_appcheck: str | None = Header(default=None, alias="X-Firebase-AppCheck"),
) -> None:
    """FastAPI dependency: reject requests lacking a valid App Check token.

    Returns immediately in monitor mode (REQUIRE_APPCHECK=false). firebase_admin
    is imported lazily so the server boots without it installed/configured for
    local dev.
    """
    if not REQUIRE_APPCHECK:
        return
    if not x_firebase_appcheck:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing App Check token")
    _init_firebase()
    from firebase_admin import app_check

    try:
        app_check.verify_token(x_firebase_appcheck)
    except Exception as exc:  # any verification failure -> 401
        logger.warning("App Check token rejected: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid App Check token")
