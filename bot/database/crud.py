from datetime import datetime, timedelta
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from .models import User, Subscription, Payment

async def get_or_create_user(session: AsyncSession, telegram_id: int, username: str | None = None, first_name: str | None = None) -> User:
    """Ищет пользователя по Telegram ID, если нет — создаёт нового."""
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            created_at=datetime.utcnow()
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        
    return user

async def get_user_subscription(session: AsyncSession, telegram_id: int) -> Subscription | None:
    """Возвращает активную подписку пользователя, если она есть."""
    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == telegram_id)
        .where(Subscription.is_active == True)
        .order_by(Subscription.expires_at.desc())
    )
    return result.scalars().first()

async def create_subscription(
    session: AsyncSession, 
    user_id: int, 
    mode: str, 
    days: int, 
    subscription_url: str
) -> Subscription:
    """Создаёт новую запись о подписке."""
    expires_at = datetime.utcnow() + timedelta(days=days)
    
    subscription = Subscription(
        user_id=user_id,
        mode=mode,
        subscription_url=subscription_url,
        expires_at=expires_at,
        is_active=True,
        created_at=datetime.utcnow()
    )
    
    session.add(subscription)
    await session.commit()
    await session.refresh(subscription)
    return subscription

async def create_payment(
    session: AsyncSession, 
    user_id: int, 
    amount: int, 
    tariff_id: str, 
    external_id: str | None = None
) -> Payment:
    """Регистрирует платёж в базе данных со статусом 'pending'."""
    payment = Payment(
        user_id=user_id,
        amount=amount,
        tariff_id=tariff_id,
        external_id=external_id,
        status="pending",
        created_at=datetime.utcnow()
    )
    
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    return payment

async def update_payment_status(session: AsyncSession, payment_id: int, status: str) -> bool:
    """Обновляет статус платежа (например, после успешной оплаты)."""
    stmt = update(Payment).where(Payment.id == payment_id).values(status=status)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount > 0