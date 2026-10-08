"""Headless smoke test of the play front end (SDL dummy video driver)."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

from arena.play import PlayApp  # noqa: E402
from arena.render import HUD_HEIGHT  # noqa: E402

TICK = 1 / 30


def screen_pos(x, y):
    return (int(x), int(y + HUD_HEIGHT))


@pytest.fixture
def app():
    a = PlayApp("idle", "normal", seed=5)
    yield a
    pygame.quit()


def post_right_click(x, y):
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=screen_pos(x, y), button=3))


def post_aim_and_cast(x, y):
    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=screen_pos(x, y), rel=(0, 0), buttons=(0, 0, 0)))
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q, mod=0, unicode="q", scancode=0))


def test_right_click_moves_human(app):
    me = app.game.state.champions[0]
    start = (me.x, me.y)
    post_right_click(600, 400)
    for _ in range(10):
        app.frame(TICK)
    assert (me.x, me.y) != start
    assert app.game.state.tick == 10


def test_human_can_beat_idle_and_restart(app):
    for _ in range(600):
        if app.game.state.done:
            break
        enemy = app.game.state.champions[1]
        me = app.game.state.champions[0]
        # Walk into range, then fire at the stationary idle bot.
        post_right_click(enemy.x - 400, enemy.y)
        if abs(me.x - enemy.x) < 500:
            post_aim_and_cast(enemy.x, enemy.y)
        app.frame(TICK)
    assert app.game.state.done and app.game.state.winner == 0
    app.frame(TICK)  # draws the end screen

    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r, mod=0, unicode="r", scancode=0))
    app.frame(TICK)
    assert not app.game.state.done
    assert app.game.state.tick <= 1


def test_escape_quits(app):
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode="", scancode=0))
    app.frame(TICK)
    assert not app.running


def test_w_dashes_toward_cursor(app):
    me = app.game.state.champions[0]
    start_x = me.x
    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=screen_pos(me.x + 300, me.y), rel=(0, 0), buttons=(0, 0, 0)))
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w, mod=0, unicode="w", scancode=0))
    for _ in range(6):
        app.frame(TICK)
    assert me.x == pytest.approx(min(start_x + 250, 1170))


def test_e_uses_held_item(app):
    me = app.game.state.champions[0]
    me.item = "boomerang"
    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=screen_pos(me.x + 300, me.y), rel=(0, 0), buttons=(0, 0, 0)))
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e, mod=0, unicode="e", scancode=0))
    app.frame(TICK)
    assert me.item is None and me.cast is not None and me.cast.ability_id == "boomerang"
