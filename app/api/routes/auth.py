"""FastAPI REST API endpoints for Verse Authentication delegating strictly to AuthService."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, get_current_user, get_db
from app.api.schemas import (
    FirstRunResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    SuccessResponse,
    UserResponse,
)
from app.auth import (
    AuthService,
    InvalidCredentials,
    InvalidUsername,
    RegistrationError,
    UsernameAlreadyExists,
    WeakPassword,
)
from app.auth.sessions import SESSION_COOKIE, SessionService
from app.config.settings import settings

router = APIRouter(tags=["Authentication"])


@router.get("/auth/first-run", response_model=FirstRunResponse)
def check_first_run(db: Session = Depends(get_db)):
    """Checks whether the application is running for the first time with zero registered users."""
    is_first = AuthService.is_first_run(session=db)
    return FirstRunResponse(first_run=is_first)


@router.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Registers a new user account."""
    try:
        user = AuthService.register(
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
            session=db,
        )
        return UserResponse.model_validate(user)
    except UsernameAlreadyExists as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except (InvalidUsername, WeakPassword, RegistrationError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )


@router.post("/auth/login", response_model=LoginResponse)
def login_user(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Authenticates credentials and issues a persistent browser session."""
    try:
        user = AuthService.authenticate(
            username=payload.username,
            password=payload.password,
            session=db,
        )
        AuthService.login(user=user, session=db)
        token = SessionService.create(user, db, request.cookies.get(SESSION_COOKIE))
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=settings.session_max_age,
            httponly=True,
            secure=settings.session_cookie_secure or request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
        return LoginResponse(
            user=UserResponse.model_validate(user),
            message="Login successful",
        )
    except InvalidCredentials as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )


@router.post("/auth/logout", response_model=SuccessResponse)
def logout_user(request: Request, response: Response, db: Session = Depends(get_db)):
    """Revoke this browser's session and clear its cookie."""
    SessionService.revoke(request.cookies.get(SESSION_COOKIE), db)
    db.commit()
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure or request.url.scheme == "https",
        samesite="lax",
    )
    AuthService.logout()
    return SuccessResponse(message="Logout successful", success=True)


@router.get("/auth/me", response_model=UserResponse)
def get_current_authenticated_user(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Retrieves the profile of the currently authenticated user."""
    if not current_user.is_authenticated or not current_user.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )

    user = AuthService.get_user(current_user.id, session=db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account not found.",
        )

    return UserResponse.model_validate(user)
