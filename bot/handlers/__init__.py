"""Aiogram routers."""

from aiogram import Router

from bot.handlers import (
    admin,
    calculator,
    common,
    dailypicks,
    extras,
    feedback,
    h2h,
    leagues,
    main_menu,
    matches,
    players,
    predictions,
    profile,
    referral,
    settings,
    subscription,
    teams,
    topmatches,
)


def get_root_router() -> Router:
    router = Router(name="root")
    router.include_router(common.router)
    router.include_router(main_menu.router)
    router.include_router(predictions.router)
    router.include_router(matches.router)
    router.include_router(leagues.router)
    router.include_router(teams.router)
    router.include_router(players.router)
    router.include_router(h2h.router)
    router.include_router(dailypicks.router)
    router.include_router(topmatches.router)
    router.include_router(profile.router)
    router.include_router(calculator.router)
    router.include_router(extras.router)
    router.include_router(subscription.router)
    router.include_router(referral.router)
    router.include_router(feedback.router)
    router.include_router(settings.router)
    router.include_router(admin.router)
    return router


__all__ = ["get_root_router"]
