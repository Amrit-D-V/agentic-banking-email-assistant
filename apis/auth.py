from secrets import compare_digest
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from config.settings import settings

_basic = HTTPBasic(auto_error=False)


def require_admin(credentials: Optional[HTTPBasicCredentials] = Depends(_basic)) -> str:
    if not settings.ADMIN_PASSWORD:
        return "anonymous"
    if credentials and compare_digest(credentials.username.encode(), settings.ADMIN_USER.encode()) \
            and compare_digest(credentials.password.encode(), settings.ADMIN_PASSWORD.encode()):
        return credentials.username
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Login required",
        headers={"WWW-Authenticate": 'Basic realm="Email Automation"'},
    )
