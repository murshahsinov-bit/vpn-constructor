from datetime import datetime
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, Boolean, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    # Используем Telegram ID как первичный ключ (он уникален)
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    
    # Режим: "auto", "whitelist", "relay"
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    
    # Ссылка на JSON-подписку (например, https://ваш-домен/sub/auto.json?token=123)
    subscription_url: Mapped[str] = mapped_column(String(500), nullable=False)
    
    # Дата окончания подписки
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    
    # Сумма в рублях (50, 100, 300)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Выбранный тариф: "1_month", "3_months", "1_year"
    tariff_id: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Статус: "pending", "success", "failed"
    status: Mapped[str] = mapped_column(String(20), default="pending")
    
    # ID платежа в Telegram Stars / YooKassa
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)