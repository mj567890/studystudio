"""
apps/api/modules/auth/router.py
Block A：认证路由与依赖注入
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.db import get_db
from apps.api.modules.auth.service import AuthService, decode_token

router = APIRouter(prefix="/api", tags=["auth"])
security = HTTPBearer()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nickname: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    roles: list[str]


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        payload = decode_token(credentials.credentials)
        raw_user_id = payload.get("sub")
        if not raw_user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "AUTH_001", "msg": "Not authenticated"}
            )
        user_id = str(UUID(str(raw_user_id)))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_001", "msg": str(e)}
        )

    service = AuthService(db)
    try:
        return await service.get_current_user(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_001", "msg": "User not found"}
        )


def require_role(*roles: str):
    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        user_roles = set(current_user.get("roles", []))
        if not user_roles.intersection(roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "AUTH_002", "msg": "Insufficient permissions"}
            )
        return current_user
    return _check


@router.post("/auth/register", status_code=201)
async def register(
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = AuthService(db)
    try:
        user = await service.register(req.email, req.password, req.nickname)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "AUTH_003", "msg": str(e)})
    return {"code": 201, "msg": "success", "data": user}


@router.post("/auth/login", response_model=dict)
async def login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = AuthService(db)
    try:
        result = await service.login(req.email, req.password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_001", "msg": str(e)}
        )
    return {"code": 200, "msg": "success", "data": result}


@router.get("/users/me")
async def get_me(current_user: dict = Depends(get_current_user)) -> dict:
    return {"code": 200, "msg": "success", "data": current_user}
