"""The sim loop. See "Precise rules" in game_overview.md for the tick order."""

import math

import numpy as np

from arena.config import DEFAULT_CONFIG, GameConfig
from arena.sim.abilities import ABILITY_TYPES, Ability
from arena.sim.collision import segment_box_exit, segment_capsule_entry, segment_circle_entry
from arena.sim.params import SimParams
from arena.sim.spawns import Spawns, default_spawns
from arena.sim.state import CastState, Champion, GameState, Pickup, Projectile, Wall
from arena.sim.types import Action, ChampionView, Observation, PickupView, ProjectileView, Vec2, WallView, ZoneView

# What a projectile's path runs into first this tick.
EVENT_NONE = 0
EVENT_CHAMPION = 1
EVENT_WALL = 2
EVENT_EDGE = 3


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


class Game:
    def __init__(
        self,
        config: GameConfig = DEFAULT_CONFIG,
        seed: int = 0,
        spawns: Spawns | None = None,
        ability_types: dict[str, type[Ability]] = ABILITY_TYPES,
    ) -> None:
        self.config = config
        self.params = p = SimParams.from_config(config)
        # The sim's own random stream. Controllers get separate streams (see arena/match.py).
        self.rng = np.random.default_rng([seed, 0])
        self.abilities: dict[str, Ability] = {}
        for aid in p.abilities:
            if aid in ability_types:
                self.abilities[aid] = ability_types[aid](p.abilities[aid], p)
        for aid in p.loadout + p.pickup_pool:
            if aid not in self.abilities:
                raise ValueError(f"unknown ability {aid!r}")

        if spawns is None:
            spawns = default_spawns(config)
        r = p.champion_radius
        self.state = GameState(
            tick=0,
            champions=[
                Champion(
                    x=_clamp(sx, r, p.width - r),
                    y=_clamp(sy, r, p.height - r),
                    hp=p.champion_hp,
                    cooldowns={aid: 0 for aid in p.loadout},
                )
                for sx, sy in spawns
            ],
            next_pickup_tick=p.pickup_first_tick,
            next_heal_tick=p.heal_first_tick,
        )

    # ---- stepping -------------------------------------------------------

    def step(self, action0: Action, action1: Action) -> None:
        s = self.state
        if s.done:
            raise RuntimeError("game is over")
        p = self.params
        s.events.clear()

        # 2. apply both actions
        self._apply_action(0, action0)
        self._apply_action(1, action1)

        # 3. advance casts; finished casts fire
        for i, champ in enumerate(s.champions):
            cast = champ.cast
            if cast is not None:
                if cast.ticks_remaining == 0:
                    champ.cast = None
                    self.abilities[cast.ability_id].on_cast(s, i, cast)
                else:
                    cast.ticks_remaining -= 1

        # 4. move champions, then spawn and collect pickups
        for champ in s.champions:
            self._move_champion(champ)
        if p.pickup_pool:
            self._update_pickups()
        self._update_heal()

        # 5. move projectiles, collide, cull; then detonate zones whose fuse ran out
        if s.projectiles:
            self._step_projectiles()
        if s.zones:
            self._step_zones()

        # 6. apply damage simultaneously, then check for game end
        if s.pending_damage:
            for target, amount, ability, source in s.pending_damage:
                champ = s.champions[target]
                lost = min(champ.hp, amount)
                champ.hp -= lost
                s.events.append(("damage", source, target, ability, lost))
            s.pending_damage.clear()
            dead0 = s.champions[0].hp <= 0
            dead1 = s.champions[1].hp <= 0
            if dead0 or dead1:
                s.done = True
                s.winner = None if (dead0 and dead1) else (1 if dead0 else 0)

        # 7. timers and clock
        for champ in s.champions:
            cds = champ.cooldowns
            for aid in cds:
                if cds[aid] > 0:
                    cds[aid] -= 1
            if champ.shield_ticks > 0:
                champ.shield_ticks -= 1
        if s.walls:
            for wall in s.walls:
                wall.ticks_remaining -= 1
            s.walls = [wall for wall in s.walls if wall.ticks_remaining > 0]
        s.tick += 1
        if not s.done and s.tick >= p.time_limit_ticks:
            s.done = True
            hp0, hp1 = s.champions[0].hp, s.champions[1].hp
            s.winner = None if hp0 == hp1 else (0 if hp0 > hp1 else 1)

    def _move_champion(self, champ: Champion) -> None:
        p = self.params
        forced = champ.forced
        if forced is not None:
            r = p.champion_radius
            step = min(forced.speed, forced.remaining)
            nx = champ.x + forced.dir_x * step
            ny = champ.y + forced.dir_y * step
            cx = _clamp(nx, r, p.width - r)
            cy = _clamp(ny, r, p.height - r)
            champ.vx = cx - champ.x
            champ.vy = cy - champ.y
            champ.x = cx
            champ.y = cy
            forced.remaining -= step
            if forced.remaining <= 1e-9 or cx != nx or cy != ny:  # done, or stopped by the edge
                champ.forced = None
            return
        rooted = champ.root_ticks > 0
        if rooted:  # counted down here, so N ticks of root block exactly N movement steps
            champ.root_ticks -= 1
        if champ.cast is not None or rooted or not champ.has_target:
            champ.vx = 0.0
            champ.vy = 0.0
            return
        speed = p.champion_speed
        dx = champ.target_x - champ.x
        dy = champ.target_y - champ.y
        d2 = dx * dx + dy * dy
        if d2 <= speed * speed:
            champ.x = champ.target_x
            champ.y = champ.target_y
            champ.has_target = False
            champ.vx = dx
            champ.vy = dy
        else:
            k = speed / math.sqrt(d2)
            champ.vx = dx * k
            champ.vy = dy * k
            champ.x += champ.vx
            champ.y += champ.vy

    def heal_spot(self) -> tuple[float, float]:
        return self.params.width / 2, self.params.height / 2

    def _update_heal(self) -> None:
        s = self.state
        p = self.params
        if not s.heal_up:
            if s.tick < s.next_heal_tick:
                return
            s.heal_up = True
        hx, hy = self.heal_spot()
        reach2 = (p.champion_radius + p.heal_radius) ** 2
        takers = [c for c in s.champions if (c.x - hx) ** 2 + (c.y - hy) ** 2 <= reach2]
        if not takers:
            return
        for champ in takers:  # same tick: both heal, like pickups. At full HP it just denies the other player.
            gained = min(p.champion_hp, champ.hp + p.heal_amount) - champ.hp
            champ.hp += gained
            s.events.append(("heal", s.champions.index(champ), gained))
        s.heal_up = False
        s.next_heal_tick = s.tick + p.heal_respawn_ticks

    def _update_pickups(self) -> None:
        s = self.state
        p = self.params
        if s.tick >= s.next_pickup_tick:
            s.next_pickup_tick += p.pickup_interval_ticks
            if len(s.pickups) < p.pickup_max:
                on_map = {pk.ability_id for pk in s.pickups}
                pool = [a for a in p.pickup_pool if a not in on_map] or list(p.pickup_pool)
                aid = pool[int(self.rng.integers(len(pool)))]
                x, y = self._fair_spot()
                s.pickups.append(Pickup(x, y, aid))
        if not s.pickups:
            return
        reach2 = (p.champion_radius + p.pickup_radius) ** 2
        remaining = []
        for pickup in s.pickups:
            # Everyone touching it this tick with an empty slot gets it, so a
            # same-tick contest gives both players the ability.
            takers = [
                champ for champ in s.champions
                if champ.item is None and (champ.x - pickup.x) ** 2 + (champ.y - pickup.y) ** 2 <= reach2
            ]
            for champ in takers:
                champ.item = pickup.ability_id
                s.events.append(("pickup", s.champions.index(champ), pickup.ability_id))
            if not takers:
                remaining.append(pickup)
        s.pickups = remaining

    def _fair_spot(self) -> tuple[float, float]:
        """A random point equidistant from both champions: on the perpendicular bisector of
        the line between them, inside the arena, at least `pickup_min_distance` from them and
        clear of the heal orb. Constraints are dropped in that order when the line has no room."""
        s = self.state
        p = self.params
        a, b = s.champions
        mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
        dx, dy = b.x - a.x, b.y - a.y
        sep = math.hypot(dx, dy)
        if sep > 1e-6:
            nx, ny = -dy / sep, dx / sep
        else:  # stacked: every point is equidistant, so any line through them will do
            angle = float(self.rng.uniform(0.0, 2.0 * math.pi))
            nx, ny = math.cos(angle), math.sin(angle)
        # The stretch of the line m + t*n inside the arena (less a margin so it can be reached).
        margin = p.champion_radius + p.pickup_radius
        lo, hi = -math.inf, math.inf
        for m, n, size in ((mx, nx, p.width), (my, ny, p.height)):
            if abs(n) < 1e-12:
                if not margin <= m <= size - margin:
                    lo, hi = 1.0, 0.0  # parallel to this edge and outside the margin: no room
            else:
                t1, t2 = (margin - m) / n, (size - margin - m) / n
                lo, hi = max(lo, min(t1, t2)), min(hi, max(t1, t2))
        if lo > hi:  # the bisector misses the playable area: the nearest spot to the midpoint
            return (min(max(mx, margin), p.width - margin), min(max(my, margin), p.height - margin))
        # Distance to each champion is sqrt((sep/2)^2 + t^2), so "far enough" means |t| >= t_near.
        t_near = math.sqrt(max(0.0, p.pickup_min_distance ** 2 - (sep / 2) ** 2))
        hx, hy = self.heal_spot()
        t_heal = (hx - mx) * nx + (hy - my) * ny  # where the line passes closest to the heal orb
        off = abs((hx - mx) * ny - (hy - my) * nx)
        clear = p.heal_radius + p.pickup_radius + 20.0
        heal_gap = math.sqrt(clear * clear - off * off) if off < clear else 0.0
        for cuts in (((-t_near, t_near), (t_heal - heal_gap, t_heal + heal_gap)),
                     ((t_heal - heal_gap, t_heal + heal_gap),),
                     ()):
            spans = [(lo, hi)]
            for c_lo, c_hi in cuts:
                spans = [piece for s_lo, s_hi in spans
                         for piece in ((s_lo, min(s_hi, c_lo)), (max(s_lo, c_hi), s_hi)) if piece[1] > piece[0]]
            total = sum(s_hi - s_lo for s_lo, s_hi in spans)
            if total > 0.0:
                u = float(self.rng.uniform(0.0, total))
                for s_lo, s_hi in spans:
                    if u <= s_hi - s_lo:
                        t = s_lo + u
                        break
                    u -= s_hi - s_lo
                else:
                    t = spans[-1][1]
                return (mx + t * nx, my + t * ny)
        return (mx + lo * nx, my + lo * ny)  # a single point of room

    def _step_projectiles(self) -> None:
        s = self.state
        p = self.params
        w = p.width
        h = p.height
        survivors = []
        for proj in s.projectiles:
            ability = self.abilities[proj.ability_id]
            ability.on_tick(s, proj)
            # Handle events along this tick's path in order. A projectile that pierces a
            # champion keeps going and can still meet a wall or the edge in the same tick.
            for _ in range(len(s.champions) + 1):
                if not proj.alive:
                    break
                kind, t, target, wall = self._first_event(proj)
                if kind == EVENT_NONE:
                    break
                cx = proj.prev_x + (proj.x - proj.prev_x) * t
                cy = proj.prev_y + (proj.y - proj.prev_y) * t
                if kind != EVENT_CHAMPION:
                    ability.on_wall_hit(s, proj, wall, cx, cy)
                    break
                champ = s.champions[target]
                proj.hit_mask |= 1 << target
                if champ.shield_ticks > 0:  # spell shield eats the hit and the projectile
                    proj.alive = False
                    self._block(target, proj.owner, proj.ability_id)
                else:
                    s.events.append(("hit", proj.owner, target, proj.ability_id))
                    s.acting = (proj.owner, proj.ability_id)
                    ability.on_hit(s, proj, target)
                    s.acting = None
                proj.prev_x, proj.prev_y = cx, cy  # look for the next event past this point
            if not proj.alive or proj.expired:
                continue
            if proj.x < 0.0 or proj.x > w or proj.y < 0.0 or proj.y > h:
                continue
            survivors.append(proj)
        s.projectiles = survivors

    def _step_zones(self) -> None:
        s = self.state
        r = self.params.champion_radius
        pending = []
        for zone in s.zones:
            if zone.ticks_remaining > 0:  # same convention as casts: N ticks of fuse, fires on the next
                zone.ticks_remaining -= 1
                pending.append(zone)
                continue
            ability = self.abilities[zone.ability_id]
            reach2 = (zone.radius + r) ** 2
            for i, champ in enumerate(s.champions):
                if i == zone.owner or (champ.x - zone.x) ** 2 + (champ.y - zone.y) ** 2 > reach2:
                    continue
                if champ.shield_ticks > 0:
                    self._block(i, zone.owner, zone.ability_id)
                else:
                    s.events.append(("hit", zone.owner, i, zone.ability_id))
                    s.acting = (zone.owner, zone.ability_id)
                    ability.on_zone_hit(s, zone, i)
                    s.acting = None
        s.zones = pending

    def _block(self, target: int, source: int, ability_id: str) -> None:
        """A spell shield blocks an enemy effect: it's used up, and it heals (capped at max HP).
        This happens before the tick's damage, like the center heal."""
        s = self.state
        champ = s.champions[target]
        champ.shield_ticks = 0
        s.events.append(("blocked", target, source, ability_id))
        gained = min(self.params.champion_hp, champ.hp + champ.shield_heal) - champ.hp
        if gained > 0:
            champ.hp += gained
            s.events.append(("heal", target, gained))
        champ.shield_heal = 0

    def _first_event(self, proj: Projectile) -> tuple[int, float, int, Wall | None]:
        """The earliest thing this tick's path touches: (kind, t, champion index, wall).
        Ties go to champions, so standing inside a wall gives no protection."""
        x0, y0, x1, y1 = proj.prev_x, proj.prev_y, proj.x, proj.y
        kind, best_t, best_i, best_wall = EVENT_NONE, 2.0, -1, None
        reach = self.params.champion_radius + proj.radius
        for i, champ in enumerate(self.state.champions):
            if i == proj.owner or proj.hit_mask & (1 << i):
                continue
            t = segment_circle_entry(x0, y0, x1, y1, champ.x, champ.y, reach)
            if 0.0 <= t < best_t:
                kind, best_t, best_i = EVENT_CHAMPION, t, i
        for wall in self.state.walls:
            t = segment_capsule_entry(x0, y0, x1, y1, wall.ax, wall.ay, wall.bx, wall.by, proj.radius)
            if 0.0 <= t < best_t:
                kind, best_t, best_wall = EVENT_WALL, t, wall
        t = segment_box_exit(x0, y0, x1, y1, self.params.width, self.params.height)
        if 0.0 <= t < best_t:
            kind, best_t, best_wall = EVENT_EDGE, t, None
        return kind, best_t, best_i, best_wall

    def _apply_action(self, player: int, action: Action) -> None:
        p = self.params
        champ = self.state.champions[player]
        mirror = player == 1
        r = p.champion_radius

        if action.move is not None:
            tx = action.move.x
            if mirror:
                tx = p.width - tx
            champ.target_x = _clamp(tx, r, p.width - r)
            champ.target_y = _clamp(action.move.y, r, p.height - r)
            champ.has_target = True

        cmd = action.cast
        if cmd is None:
            return
        aid = cmd.ability_id
        ability = self.abilities.get(aid)
        if ability is None:
            raise ValueError(f"unknown ability {aid!r}")
        from_item = aid not in champ.cooldowns
        if from_item and champ.item != aid:
            return  # not in the loadout and not held
        if champ.cast is not None or champ.forced is not None:
            return
        if not from_item and champ.cooldowns[aid] > 0:
            return
        if ability.is_movement and champ.root_ticks > 0:
            return
        ax = p.width - cmd.aim.x if mirror else cmd.aim.x
        ay = cmd.aim.y
        dx = ax - champ.x
        dy = ay - champ.y
        d = math.hypot(dx, dy)
        if d >= 1.0:
            dx /= d
            dy /= d
        elif ability.targeted:
            return
        else:
            dx, dy = 1.0, 0.0
        ap = p.abilities[aid]
        champ.cast = CastState(aid, ap.cast_ticks, dx, dy, ax, ay)
        self.state.events.append(("cast", player, aid))
        if from_item:
            champ.item = None
        else:
            champ.cooldowns[aid] = ap.cooldown_ticks

    # ---- observations ---------------------------------------------------

    def observe(self, player: int) -> Observation:
        s = self.state
        p = self.params
        mirror = player == 1
        w = p.width
        rate = p.tick_rate

        def champ_view(c: Champion) -> ChampionView:
            x = w - c.x if mirror else c.x
            vx = -c.vx if mirror else c.vx
            cast = c.cast
            return ChampionView(
                pos=Vec2(x, c.y),
                vel=Vec2(vx * rate, c.vy * rate),
                hp=c.hp,
                cooldowns={aid: t / rate for aid, t in c.cooldowns.items()},
                cast_ability=None if cast is None else cast.ability_id,
                cast_remaining=0.0 if cast is None else cast.ticks_remaining / rate,
                rooted=c.root_ticks / rate,
                shielded=c.shield_ticks / rate,
                forced=c.forced is not None,
                item=c.item,
            )

        projectiles = []
        for proj in s.projectiles:
            x = w - proj.x if mirror else proj.x
            dx = -proj.dir_x if mirror else proj.dir_x
            v = proj.speed * rate
            projectiles.append(
                ProjectileView(
                    pos=Vec2(x, proj.y),
                    vel=Vec2(dx * v, proj.dir_y * v),
                    is_own=proj.owner == player,
                    ability_id=proj.ability_id,
                )
            )

        walls = tuple(
            WallView(
                a=Vec2(w - wall.ax if mirror else wall.ax, wall.ay),
                b=Vec2(w - wall.bx if mirror else wall.bx, wall.by),
                remaining=wall.ticks_remaining / rate,
                is_own=wall.owner == player,
            )
            for wall in s.walls
        )

        pickups = tuple(
            PickupView(Vec2(w - pk.x if mirror else pk.x, pk.y), pk.ability_id) for pk in s.pickups
        )
        zones = tuple(
            ZoneView(Vec2(w - z.x if mirror else z.x, z.y), z.radius, z.ticks_remaining / rate,
                     z.owner == player, z.ability_id)
            for z in s.zones
        )

        hx, hy = self.heal_spot()  # the center, so mirroring leaves it unchanged
        return Observation(
            me=champ_view(s.champions[player]),
            enemy=champ_view(s.champions[1 - player]),
            projectiles=tuple(projectiles),
            time_remaining=(p.time_limit_ticks - s.tick) / rate,
            walls=walls,
            pickups=pickups,
            zones=zones,
            heal=Vec2(hx, hy) if s.heal_up else None,
            heal_in=0.0 if s.heal_up else max(0, s.next_heal_tick - s.tick) / rate,
        )
