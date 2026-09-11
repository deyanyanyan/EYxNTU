from pydantic import BaseModel, EmailStr


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: str
    email: str  # Existing local bootstrap accounts may use a reserved .local domain.
    name: str
    role: str
    org_unit: str | None = None
    is_active: bool = True

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str = "learner"
    org_unit: str | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    org_unit: str | None = None
    is_active: bool | None = None
    password: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


Token.model_rebuild()
