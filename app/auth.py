from __future__ import annotations

from functools import wraps

from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from fastapi.responses import RedirectResponse

from app.config import settings


oauth = OAuth()
oauth.register(
    name="github",
    client_id=settings.github_client_id,
    client_secret=settings.github_client_secret,
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "read:user user:email"},
)


def current_user_id(request: Request) -> str | None:
    return request.session.get("user_id")


def login_required(handler):
    @wraps(handler)
    async def wrapper(request: Request, *args, **kwargs):
        if not current_user_id(request):
            return RedirectResponse("/login", status_code=302)
        return await handler(request, *args, **kwargs)

    return wrapper
