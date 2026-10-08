"""Play against a bot: python -m arena.play --opponent <bot> [--difficulty easy|normal|hard]

Right-click (or hold) to move, Q to cast Bolt toward the cursor, Esc to quit.
"""

import argparse
import time

import pygame

from arena.bots import available_bots, make_bot, policy_path
from arena.config import DEFAULT_CONFIG, DIFFICULTIES, GameConfig
from arena.fairness import FairController
from arena.human import HumanController
from arena.match import controller_rng
from arena.render import HUD_HEIGHT, Renderer
from arena.sim.game import Game
from arena.sim.spawns import mirrored_random_spawns, spawn_rng
from arena.sim.types import Vec2

ABILITY_KEYS = (pygame.K_q, pygame.K_w)  # loadout slots
ITEM_KEY = pygame.K_e  # held pickup
HUMAN = 0  # the human is always player 0, so their canonical frame is the world frame


class PlayApp:
    def __init__(
        self,
        opponent: str,
        difficulty: str = "normal",
        seed: int | None = None,
        scale: float = 1.0,
        config: GameConfig = DEFAULT_CONFIG,
    ) -> None:
        self.opponent = opponent
        self.difficulty = difficulty
        self.config = config
        self.seed = int(time.time()) if seed is None else seed
        pygame.init()
        size = (int(config.arena_width * scale), int(config.arena_height * scale) + HUD_HEIGHT)
        self.screen = pygame.display.set_mode(size)
        pygame.display.set_caption(f"Mirrormatch vs {opponent} ({difficulty})")
        self.scale = scale
        self.running = True
        self.mouse = Vec2(0.0, 0.0)
        self.new_game()

    def new_game(self) -> None:
        cfg = self.config
        spawns = mirrored_random_spawns(cfg, spawn_rng(self.seed))
        self.game = Game(cfg, self.seed, spawns)
        self.human = HumanController()
        self.bot = FairController(make_bot(self.opponent, cfg), DIFFICULTIES[self.difficulty])
        self.human.reset(controller_rng(self.seed, HUMAN))
        self.bot.reset(controller_rng(self.seed, 1 - HUMAN))
        self.renderer = Renderer(self.screen, self.game, self.scale)
        self.move_marker: Vec2 | None = None
        self.last_aim: Vec2 | None = None
        self.accumulator = 0.0

    # input

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.running = False
            elif event.key == pygame.K_r and self.game.state.done:
                self.seed += 1
                self.new_game()
            elif event.key == ITEM_KEY:
                item = self.game.state.champions[HUMAN].item
                if item is not None and not self.game.state.done:
                    self.human.command_cast(item, self.mouse)
                    self.last_aim = self.mouse
            elif event.key in ABILITY_KEYS:
                slot = ABILITY_KEYS.index(event.key)
                loadout = self.game.params.loadout
                if slot < len(loadout) and not self.game.state.done:
                    self.human.command_cast(loadout[slot], self.mouse)
                    self.last_aim = self.mouse
        elif event.type == pygame.MOUSEMOTION:
            self.mouse = self.renderer.to_world(*event.pos)
            if event.buttons[2]:
                self._move_to(self.mouse)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            self.mouse = self.renderer.to_world(*event.pos)
            if event.button == 3:
                self._move_to(self.mouse)

    def _move_to(self, target: Vec2) -> None:
        self.human.command_move(target)
        self.move_marker = target

    # loop

    def frame(self, dt: float) -> None:
        """Process input, advance the sim by however many fixed ticks fit in dt, draw."""
        for event in pygame.event.get():
            self.handle_event(event)
        tick_dt = 1.0 / self.game.params.tick_rate
        self.accumulator = min(self.accumulator + dt, 0.25)  # don't spiral after a stall
        game = self.game
        while self.accumulator >= tick_dt and not game.state.done:
            a_human = self.human.act(game.observe(HUMAN))
            a_bot = self.bot.act(game.observe(1 - HUMAN))
            game.step(a_human, a_bot)
            self.accumulator -= tick_dt
        names = ("You", f"{self.opponent} ({self.difficulty})")
        self.renderer.draw(game, HUMAN, names, self.move_marker, self.last_aim)
        pygame.display.flip()

    def run(self) -> None:
        clock = pygame.time.Clock()
        while self.running:
            dt = clock.tick(120) / 1000.0
            self.frame(dt)
        pygame.quit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Play Mirrormatch against a bot.")
    parser.add_argument("--opponent", required=True, help="bot name or trained model (see models/)")
    parser.add_argument("--difficulty", default="normal", choices=sorted(DIFFICULTIES))
    parser.add_argument("--seed", type=int, default=None, help="spawn/noise seed (default: from clock)")
    parser.add_argument("--scale", type=float, default=1.0, help="window scale factor")
    args = parser.parse_args(argv)
    if args.opponent not in available_bots() and policy_path(args.opponent) is None and not args.opponent.endswith(".json"):
        parser.error(f"unknown opponent {args.opponent!r}; known: {', '.join(available_bots())}")
    PlayApp(args.opponent, args.difficulty, args.seed, args.scale).run()


if __name__ == "__main__":
    main()
