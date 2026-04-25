"""Aiogram routers."""

from aiogram import Router

from bot.handlers import (
    admin,
    common,
    feedback,
    leagues,
    main_menu,
    matches,
    predictions,
    referral,
    settings,
    subscription,
)


def get_root_router() -> Router:
    router = Router(name="root")
    router.include_router(common.router)
    router.include_router(main_menu.router)
    router.include_router(predictions.router)
    router.include_router(matches.router)
    router.include_router(leagues.router)
    router.include_router(subscription.router)
    router.include_router(referral.router)
    router.include_router(feedback.router)
    router.include_router(settings.router)
    router.include_router(admin.router)
    return router


__all__ = ["get_root_router"]
