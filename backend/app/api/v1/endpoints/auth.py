"""Authentication endpoints: register, login, refresh, logout, password reset."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import AuthServiceDep, CurrentUser, RequestContextDep
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenPair,
)
from app.schemas.common import ErrorResponse, Message
from app.schemas.user import PasswordChange, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
    responses={409: {"model": ErrorResponse, "description": "Email already registered"}},
)
async def register(
    payload: UserCreate,
    service: AuthServiceDep,
    ctx: RequestContextDep,
) -> UserRead:
    """Create an account with the default ``viewer`` role.

    An administrator can grant elevated roles afterwards via `/users/{id}`.
    """
    user = await service.register(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        ctx=ctx,
    )
    return UserRead.model_validate(user)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Exchange credentials for tokens",
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        403: {"model": ErrorResponse, "description": "Account inactive"},
        423: {"model": ErrorResponse, "description": "Account locked"},
    },
)
async def login(
    payload: LoginRequest,
    service: AuthServiceDep,
    ctx: RequestContextDep,
) -> LoginResponse:
    """Authenticate and receive an access/refresh token pair.

    After `MAX_FAILED_LOGIN_ATTEMPTS` consecutive failures the account is
    locked for `ACCOUNT_LOCKOUT_MINUTES`.
    """
    user, tokens = await service.authenticate(
        email=payload.email, password=payload.password, ctx=ctx
    )
    return LoginResponse(
        **tokens.model_dump(),
        user=UserRead.model_validate(user),
    )


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotate a refresh token",
    responses={401: {"model": ErrorResponse, "description": "Invalid or reused token"}},
)
async def refresh_tokens(
    payload: RefreshRequest,
    service: AuthServiceDep,
    ctx: RequestContextDep,
) -> TokenPair:
    """Issue a new token pair and revoke the presented refresh token."""
    return await service.refresh(payload.refresh_token, ctx=ctx)


@router.post("/logout", response_model=Message, summary="Revoke the current session")
async def logout(
    payload: LogoutRequest,
    current_user: CurrentUser,
    service: AuthServiceDep,
    ctx: RequestContextDep,
) -> Message:
    """Revoke one refresh token, or every session when ``all_sessions`` is set."""
    revoked = await service.logout(
        user=current_user,
        refresh_token=payload.refresh_token,
        all_sessions=payload.all_sessions,
        ctx=ctx,
    )
    return Message(message=f"Logged out. {revoked} session(s) revoked.")


@router.post(
    "/forgot-password",
    response_model=Message,
    summary="Request a password-reset email",
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    service: AuthServiceDep,
    ctx: RequestContextDep,
) -> Message:
    """Always returns success so the endpoint cannot be used to enumerate users."""
    await service.request_password_reset(payload.email, ctx=ctx)
    return Message(message="If an account exists for that email, a reset link has been sent.")


@router.post(
    "/reset-password",
    response_model=Message,
    summary="Complete a password reset",
    responses={401: {"model": ErrorResponse, "description": "Invalid or expired token"}},
)
async def reset_password(
    payload: ResetPasswordRequest,
    service: AuthServiceDep,
    ctx: RequestContextDep,
) -> Message:
    """Consume a reset token, set the new password and revoke all sessions."""
    await service.reset_password(token=payload.token, new_password=payload.new_password, ctx=ctx)
    return Message(message="Password updated. Please sign in again.")


@router.post(
    "/change-password",
    response_model=Message,
    summary="Change your own password",
    responses={401: {"model": ErrorResponse, "description": "Current password incorrect"}},
)
async def change_password(
    payload: PasswordChange,
    current_user: CurrentUser,
    service: AuthServiceDep,
    ctx: RequestContextDep,
) -> Message:
    """Change the password of the authenticated user and revoke all sessions."""
    await service.change_password(
        user=current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        ctx=ctx,
    )
    return Message(message="Password changed. Please sign in again.")


@router.get("/me", response_model=UserRead, summary="Current user profile")
async def read_current_user(current_user: CurrentUser) -> UserRead:
    """Return the profile and roles of the authenticated user."""
    return UserRead.model_validate(current_user)
