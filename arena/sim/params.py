"""The one place where config values in seconds become values in ticks."""

from dataclasses import dataclass

from arena.config import AbilityStats, GameConfig


def seconds_to_ticks(seconds: float, tick_rate: int) -> int:
    """Round half up, so e.g. 0.25 s at 30 Hz is 8 ticks."""
    return int(seconds * tick_rate + 0.5)


@dataclass(frozen=True, slots=True)
class AbilityParams:
    cooldown_ticks: int
    cast_ticks: int
    speed: float  # units/tick
    range: float
    radius: float
    damage: int
    duration_ticks: int
    length: float
    move_speed: float  # units/tick
    heal: int

    @staticmethod
    def from_stats(stats: AbilityStats, tick_rate: int) -> "AbilityParams":
        return AbilityParams(
            cooldown_ticks=seconds_to_ticks(stats.cooldown, tick_rate),
            cast_ticks=seconds_to_ticks(stats.cast_time, tick_rate),
            speed=stats.speed / tick_rate,
            range=stats.range,
            radius=stats.radius,
            damage=stats.damage,
            duration_ticks=seconds_to_ticks(stats.duration, tick_rate),
            length=stats.length,
            move_speed=stats.move_speed / tick_rate,
            heal=stats.heal,
        )


@dataclass(frozen=True, slots=True)
class SimParams:
    tick_rate: int
    width: float
    height: float
    time_limit_ticks: int
    champion_radius: float
    champion_speed: float  # units/tick
    champion_hp: int
    loadout: tuple[str, ...]
    abilities: dict[str, AbilityParams]
    pickup_pool: tuple[str, ...]
    pickup_first_tick: int
    pickup_interval_ticks: int
    pickup_max: int
    pickup_min_distance: float
    pickup_radius: float
    heal_first_tick: int
    heal_respawn_ticks: int
    heal_radius: float
    heal_amount: int

    @staticmethod
    def from_config(cfg: GameConfig) -> "SimParams":
        for ability_id in cfg.loadout + cfg.pickup_pool:
            if ability_id not in cfg.abilities:
                raise ValueError(f"ability {ability_id!r} has no stats in config")
        return SimParams(
            tick_rate=cfg.tick_rate,
            width=cfg.arena_width,
            height=cfg.arena_height,
            time_limit_ticks=seconds_to_ticks(cfg.time_limit, cfg.tick_rate),
            champion_radius=cfg.champion_radius,
            champion_speed=cfg.champion_speed / cfg.tick_rate,
            champion_hp=cfg.champion_hp,
            loadout=cfg.loadout,
            abilities={
                aid: AbilityParams.from_stats(stats, cfg.tick_rate)
                for aid, stats in cfg.abilities.items()
            },
            pickup_pool=cfg.pickup_pool,
            pickup_first_tick=seconds_to_ticks(cfg.pickup_first_spawn, cfg.tick_rate),
            pickup_interval_ticks=max(1, seconds_to_ticks(cfg.pickup_interval, cfg.tick_rate)),
            pickup_max=cfg.pickup_max,
            pickup_min_distance=cfg.pickup_min_distance,
            pickup_radius=cfg.pickup_radius,
            heal_first_tick=seconds_to_ticks(cfg.heal_first_spawn, cfg.tick_rate),
            heal_respawn_ticks=seconds_to_ticks(cfg.heal_respawn, cfg.tick_rate),
            heal_radius=cfg.heal_radius,
            heal_amount=cfg.heal_amount,
        )
