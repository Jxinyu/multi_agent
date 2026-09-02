from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from multi_domain_enterprise_project.core.auth import (
    AuthTokenResponse,
    CurrentUser,
    create_development_token,
    get_current_user,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])
Authenticated = Annotated[CurrentUser, Depends(get_current_user)]


class CurrentUserResponse(BaseModel):
    user: CurrentUser


@router.post("/development-token", response_model=AuthTokenResponse)
async def development_token() -> AuthTokenResponse:
    return create_development_token()


@router.get("/me", response_model=CurrentUserResponse)
async def get_me(current_user: Authenticated) -> CurrentUserResponse:
    return CurrentUserResponse(user=current_user)
