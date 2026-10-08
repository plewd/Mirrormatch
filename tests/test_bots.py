import numpy as np
import pytest

from arena.bots import BOTS, make_bot
from arena.bots.common import incoming_threat
from arena.config import DEFAULT_CONFIG, DIFFICULTIES
from arena.fairness import FairController
from arena.match import run_match
from arena.sim import NOOP, Action, Game, Vec2
from arena.sim.types import ChampionView, Observation, PickupView, ProjectileView


def view(x, y, vx=0.0, vy=0.0, cd=0.0, casting=None, dash_cd=0.0) -> ChampionView:
    return ChampionView(Vec2(x, y), Vec2(vx, vy), 3, {"bolt": cd, "dash": dash_cd}, casting, 0.0)


def obs(me, enemy, projectiles=()) -> Observation:
    return Observation(me, enemy, tuple(projectiles), 60.0)


@pytest.mark.parametrize("name", sorted(BOTS))
def test_every_bot_plays_a_full_game(name):
    res = run_match(make_bot(name), make_bot("random"), seed=3)
    assert res.ticks > 0


def test_unknown_bot():
    with pytest.raises(ValueError):
        make_bot("nope")


def test_idle_does_nothing():
    assert make_bot("idle").act(obs(view(100, 100), view(900, 100))) is NOOP


def test_aimer_fires_at_current_position_only_when_ready():
    bot = make_bot("aimer")
    a = bot.act(obs(view(100, 100), view(900, 300, vx=300)))
    assert a.move is None and a.cast.aim == Vec2(900, 300)
    assert bot.act(obs(view(100, 100, cd=0.5), view(900, 300))) is NOOP


def test_leader_leads_a_moving_target_and_hits_it():
    bot = make_bot("leader")
    a = bot.act(obs(view(300, 400), view(900, 400, vy=-DEFAULT_CONFIG.champion_speed)))
    assert a.cast.aim.y < 400 - 100  # well ahead of the target's current position

    class Walker:
        """Walks up and down the arena at constant speed."""
        def reset(self, rng): self.up = True
        def act(self, o):
            if o.me.pos.y < 100: self.up = False
            if o.me.pos.y > 700: self.up = True
            return Action(move=Vec2(o.me.pos.x, 50 if self.up else 750))

    res = run_match(make_bot("leader"), Walker(), seed=0, spawns=((300.0, 400.0), (900.0, 400.0)))
    assert res.winner == 0


def test_leader_walks_into_range_then_stops():
    bot = make_bot("leader")
    far = bot.act(obs(view(50, 400), view(1150, 400)))
    assert far.move == Vec2(1150, 400) and far.cast is None
    near = bot.act(obs(view(400, 400), view(800, 400)))
    assert near.move == Vec2(400, 400) and near.cast is not None
    assert bot.act(obs(view(400, 400, cd=1.0), view(800, 400))).move is None  # stop sent once


def test_dodger_steps_off_the_line_of_an_incoming_bolt():
    bot = make_bot("dodger")
    bolt = ProjectileView(Vec2(800, 410), Vec2(-1200, 0), is_own=False, ability_id="bolt")  # far enough to walk
    a = bot.act(obs(view(300, 400), view(900, 400), [bolt]))
    assert a.cast is None and a.move is not None
    assert a.move.y < 400 - 100  # bolt is slightly below us, so step up
    # Own bolts and bolts that have passed are ignored.
    own = ProjectileView(Vec2(600, 400), Vec2(-1200, 0), is_own=True, ability_id="bolt")
    passed = ProjectileView(Vec2(200, 400), Vec2(-1200, 0), is_own=False, ability_id="bolt")
    assert incoming_threat(obs(view(300, 400), view(900, 400), [own, passed]), DEFAULT_CONFIG) is None


def test_dodger_dodges_toward_open_space_at_a_wall():
    bot = make_bot("dodger")
    bolt = ProjectileView(Vec2(600, 35), Vec2(-1200, 0), is_own=False, ability_id="bolt")
    a = bot.act(obs(view(300, 31), view(900, 400), [bolt]))  # pinned at top wall, bolt just below
    assert a.move.y > 100  # can't go up, so it goes down past the bolt


def test_dodger_survives_aimer_point_blank_less_than_at_range():
    """Sanity check on the skill gradient: dodging is easy from range, hard up close."""
    def hits_taken(gap):
        taken = 0
        for g in range(10):
            d = FairController(make_bot("dodger"), DIFFICULTIES["normal"])
            a = FairController(make_bot("aimer"), DIFFICULTIES["normal"])
            game = Game(DEFAULT_CONFIG, g, ((600 - gap / 2, 400.0), (600 + gap / 2, 400.0)))
            d.reset(np.random.default_rng([g, 1])); a.reset(np.random.default_rng([g, 2]))
            for _ in range(90):
                if game.state.done:
                    break
                game.step(d.act(game.observe(0)), a.act(game.observe(1)))
            taken += 3 - game.state.champions[0].hp
        return taken
    assert hits_taken(250) > hits_taken(850)


def test_dodger_dashes_when_walking_is_too_slow():
    bot = make_bot("dodger")
    close = ProjectileView(Vec2(420, 400), Vec2(-1200, 0), is_own=False, ability_id="bolt")  # 0.1 s away
    a = bot.act(obs(view(300, 400), view(900, 400), [close]))
    assert a.cast is not None and a.cast.ability_id == "dash"
    far = ProjectileView(Vec2(900, 400), Vec2(-1200, 0), is_own=False, ability_id="bolt")  # 0.5 s away
    assert bot.act(obs(view(300, 400), view(900, 400), [far])).cast is None  # walking is enough
    on_cd = bot.act(obs(view(300, 400, dash_cd=2.0), view(900, 400), [close]))
    assert on_cd.cast is None and on_cd.move is not None


def test_leader_detours_for_a_pickup_it_reaches_first():
    bot = make_bot("leader")
    near = PickupView(Vec2(450, 300), "boomerang")
    o = Observation(view(400, 400, cd=1.0), view(800, 400), (), 60.0, pickups=(near,))
    assert bot.act(o).move == near.pos
    far_side = PickupView(Vec2(750, 400), "boomerang")  # enemy is closer
    o = Observation(view(400, 400, cd=1.0), view(800, 400), (), 60.0, pickups=(far_side,))
    assert bot.act(o).move != far_side.pos


def test_leader_throws_items_while_bolt_is_on_cooldown():
    bot = make_bot("leader")
    me = ChampionView(Vec2(400, 400), Vec2(0, 0), 3, {"bolt": 1.0, "dash": 0.0}, None, 0.0, item="boomerang")
    a = bot.act(obs(me, view(800, 400)))
    assert a.cast is not None and a.cast.ability_id == "boomerang"


def test_bots_use_wall_hook_and_blast():
    held = lambda item, bolt_cd=1.0: ChampionView(Vec2(400, 400), Vec2(0, 0), 3, {"bolt": bolt_cd, "dash": 0.0}, None, 0.0, item=item)
    enemy = view(800, 400)
    leader = make_bot("leader")
    assert leader.act(obs(held("hook"), enemy)).cast.ability_id == "hook"
    blast = leader.act(obs(held("blast"), enemy)).cast
    assert blast.ability_id == "blast" and blast.aim == Vec2(800, 400)
    near = ProjectileView(Vec2(600, 400), Vec2(-1200, 0), is_own=False, ability_id="bolt")
    wall = leader.act(obs(held("wall", bolt_cd=0.0), enemy, [near])).cast
    assert wall.ability_id == "wall" and 400 < wall.aim.x < 600  # between us and the bolt
