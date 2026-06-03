from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 口令哈希，格式 pbkdf2_sha256$iterations$salt_hex$hash_hex（见 app.auth）
    password_hash: Mapped[str] = mapped_column(String(256))
