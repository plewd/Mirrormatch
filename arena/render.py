"""pygame renderer. Reads sim state; never modifies it."""

import math

import pygame

from arena.sim.game import Game
from arena.sim.types import Vec2

HUD_HEIGHT = 56

BG = (18, 20, 26)
FLOOR = (34, 38, 48)
GRID = (42, 47, 59)
BORDER = (90, 98, 120)
TEXT = (225, 228, 235)
DIM = (130, 136, 150)
PLAYER_COLORS = ((80, 160, 255), (240, 90, 80))  # (human, opponent)
CAST_RING = (255, 230, 120)
SHIELD = (120, 230, 255)
ROOT = (170, 170, 185)
WALL = (200, 205, 220)
PICKUP = (250, 200, 80)
HEAL = (110, 220, 130)


class Renderer:
    def __init__(self, screen: pygame.Surface, game: Game, scale: float) -> None:
        self.screen = screen
        self.scale = scale
        self.font = pygame.font.Font(None, 26)
        self.big_font = pygame.font.Font(None, 72)
        self.params = game.params

    # world <-> screen

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        return int(x * self.scale), int(HUD_HEIGHT + y * self.scale)

    def to_world(self, sx: float, sy: float) -> Vec2:
        return Vec2(sx / self.scale, (sy - HUD_HEIGHT) / self.scale)

    # drawing

    def draw(
        self,
        game: Game,
        human: int,
        names: tuple[str, str],
        move_marker: Vec2 | None,
        cast_aim: Vec2 | None,
    ) -> None:
        p = self.params
        s = game.state
        scr = self.screen
        scr.fill(BG)

        arena = pygame.Rect(*self.to_screen(0, 0), int(p.width * self.scale), int(p.height * self.scale))
        pygame.draw.rect(scr, FLOOR, arena)
        step = 100
        for gx in range(step, int(p.width), step):
            pygame.draw.line(scr, GRID, self.to_screen(gx, 0), self.to_screen(gx, p.height))
        for gy in range(step, int(p.height), step):
            pygame.draw.line(scr, GRID, self.to_screen(0, gy), self.to_screen(p.width, gy))
        pygame.draw.rect(scr, BORDER, arena, 2)

        if move_marker is not None and not s.done:
            mx, my = self.to_screen(move_marker.x, move_marker.y)
            pygame.draw.line(scr, PLAYER_COLORS[0], (mx - 6, my - 6), (mx + 6, my + 6), 2)
            pygame.draw.line(scr, PLAYER_COLORS[0], (mx - 6, my + 6), (mx + 6, my - 6), 2)

        self._draw_heal(game)

        pr = max(4, int(p.pickup_radius * self.scale))
        for pk in s.pickups:
            center = self.to_screen(pk.x, pk.y)
            pygame.draw.circle(scr, PICKUP, center, pr, 3)
            label = self.font.render(pk.ability_id[0].upper(), True, PICKUP)
            scr.blit(label, (center[0] - label.get_width() // 2, center[1] - label.get_height() // 2))

        for zone in s.zones:
            color = PLAYER_COLORS[0 if zone.owner == human else 1]
            center = self.to_screen(zone.x, zone.y)
            zr = max(4, int(zone.radius * self.scale))
            fuse = max(1, p.abilities[zone.ability_id].duration_ticks)
            frac = 1.0 - zone.ticks_remaining / fuse
            disc = pygame.Surface((2 * zr, 2 * zr), pygame.SRCALPHA)
            pygame.draw.circle(disc, (*color, 50), (zr, zr), zr)
            pygame.draw.circle(disc, (*color, 120), (zr, zr), max(1, int(zr * frac)))
            scr.blit(disc, (center[0] - zr, center[1] - zr))
            pygame.draw.circle(scr, color, center, zr, 2)

        for wall in s.walls:
            color = PLAYER_COLORS[0 if wall.owner == human else 1]
            a = self.to_screen(wall.ax, wall.ay)
            b = self.to_screen(wall.bx, wall.by)
            pygame.draw.line(scr, WALL, a, b, max(4, int(10 * self.scale)))
            pygame.draw.line(scr, color, a, b, 2)

        for proj in s.projectiles:
            color = PLAYER_COLORS[0 if proj.owner == human else 1]
            if proj.ability_id == "hook":  # rope back to the caster
                owner = s.champions[proj.owner]
                pygame.draw.line(scr, ROOT, self.to_screen(owner.x, owner.y), self.to_screen(proj.x, proj.y), 2)
            trail = min(proj.traveled, 3 * proj.speed)
            tail = self.to_screen(proj.x - proj.dir_x * trail, proj.y - proj.dir_y * trail)
            head = self.to_screen(proj.x, proj.y)
            pygame.draw.line(scr, color, tail, head, max(2, int(proj.radius * self.scale * 0.5)))
            core = {"root": ROOT, "boomerang": PICKUP, "hook": WALL}.get(proj.ability_id, (255, 255, 255))
            pygame.draw.circle(scr, core, head, max(3, int(proj.radius * self.scale)))
            pygame.draw.circle(scr, color, head, max(3, int(proj.radius * self.scale)), 3)

        r = max(4, int(p.champion_radius * self.scale))
        for i, champ in enumerate(s.champions):
            color = PLAYER_COLORS[0 if i == human else 1]
            center = self.to_screen(champ.x, champ.y)
            if champ.forced is not None:  # motion trail
                for k in (3, 2, 1):
                    ghost = self.to_screen(champ.x - champ.vx * k, champ.y - champ.vy * k)
                    pygame.draw.circle(scr, tuple(c // (k + 1) for c in color), ghost, r)
            pygame.draw.circle(scr, color, center, r)
            if champ.root_ticks > 0:
                pygame.draw.circle(scr, ROOT, center, r + 3, 4)
                for k in range(8):  # spikes around the ring
                    c, sn = math.cos(k * math.pi / 4), math.sin(k * math.pi / 4)
                    pygame.draw.line(scr, ROOT, (center[0] + c * (r + 3), center[1] + sn * (r + 3)),
                                     (center[0] + c * (r + 11), center[1] + sn * (r + 11)), 3)
            if champ.shield_ticks > 0:
                pygame.draw.circle(scr, SHIELD, center, r + 9, 3)
            if champ.cast is not None:
                total = max(1, p.abilities[champ.cast.ability_id].cast_ticks)
                frac = 1.0 - champ.cast.ticks_remaining / total
                rect = pygame.Rect(center[0] - r - 6, center[1] - r - 6, 2 * r + 12, 2 * r + 12)
                pygame.draw.arc(scr, CAST_RING, rect, math.pi / 2, math.pi / 2 + 2 * math.pi * max(frac, 0.02), 4)
                if i == human and cast_aim is not None:
                    end = self.to_screen(champ.x + champ.cast.dir_x * 120, champ.y + champ.cast.dir_y * 120)
                    pygame.draw.line(scr, CAST_RING, center, end, 2)
            pip_y = center[1] - r - 18
            if pip_y < HUD_HEIGHT + 4:  # near the top wall: draw below instead
                pip_y = center[1] + r + 12
            for k in range(p.champion_hp):
                pip_color = color if k < champ.hp else (70, 70, 80)
                px = center[0] - (p.champion_hp - 1) * 9 + k * 18
                pygame.draw.rect(scr, pip_color, (px - 6, pip_y, 12, 6))

        self._draw_hud(game, human, names)
        if s.done:
            self._draw_end(game, human)

    def _draw_heal(self, game: Game) -> None:
        p = self.params
        s = game.state
        center = self.to_screen(p.width / 2, p.height / 2)
        r = max(4, int(p.heal_radius * self.scale))
        if s.heal_up:
            pygame.draw.circle(self.screen, HEAL, center, r)
            arm = r // 2
            pygame.draw.line(self.screen, BG, (center[0] - arm, center[1]), (center[0] + arm, center[1]), 4)
            pygame.draw.line(self.screen, BG, (center[0], center[1] - arm), (center[0], center[1] + arm), 4)
            return
        left = (s.next_heal_tick - s.tick) / p.tick_rate
        pygame.draw.circle(self.screen, (60, 90, 70), center, r, 1)  # where it will appear
        if left < 3.0:  # countdown ring for the last few seconds
            rect = pygame.Rect(center[0] - r - 4, center[1] - r - 4, 2 * r + 8, 2 * r + 8)
            pygame.draw.arc(self.screen, HEAL, rect, math.pi / 2, math.pi / 2 + 2 * math.pi * (1 - left / 3.0), 3)

    def _draw_hud(self, game: Game, human: int, names: tuple[str, str]) -> None:
        p = self.params
        s = game.state
        scr = self.screen
        w = scr.get_width()
        keys = "QW"

        x = 14
        for side, i in (("left", human), ("right", 1 - human)):
            champ = s.champions[i]
            color = PLAYER_COLORS[0 if i == human else 1]
            held = f"  [{champ.item}]" if champ.item and side == "right" else ""
            label = self.font.render(f"{names[i]}  HP {champ.hp}/{p.champion_hp}{held}", True, color)
            if side == "left":
                scr.blit(label, (x, 8))
                bx = x
                for slot, aid in enumerate(p.loadout):
                    cd = champ.cooldowns[aid]
                    total = max(1, p.abilities[aid].cooldown_ticks)
                    box = pygame.Rect(bx, 30, 120, 18)
                    pygame.draw.rect(scr, (60, 64, 76), box)
                    fill = 1.0 - cd / total
                    pygame.draw.rect(scr, color if cd == 0 else DIM, (bx, 30, int(120 * fill), 18))
                    text = f"{keys[slot]} {aid}" + ("" if cd == 0 else f" {cd / p.tick_rate:.1f}s")
                    scr.blit(self.font.render(text, True, BG if cd == 0 else TEXT), (bx + 4, 31))
                    bx += 130
                box = pygame.Rect(bx, 30, 120, 18)
                pygame.draw.rect(scr, PICKUP if champ.item else (60, 64, 76), box, 0 if champ.item else 1)
                text = f"E {champ.item}" if champ.item else "E -"
                scr.blit(self.font.render(text, True, BG if champ.item else DIM), (bx + 4, 31))
            else:
                scr.blit(label, (w - label.get_width() - 14, 8))

        remaining = max(0, p.time_limit_ticks - s.tick) / p.tick_rate
        clock = self.font.render(f"{remaining:4.1f}s", True, TEXT)
        scr.blit(clock, (w // 2 - clock.get_width() // 2, 18))

    def _draw_end(self, game: Game, human: int) -> None:
        scr = self.screen
        overlay = pygame.Surface(scr.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        scr.blit(overlay, (0, 0))
        winner = game.state.winner
        if winner is None:
            title, color = "Draw", TEXT
        elif winner == human:
            title, color = "You win", PLAYER_COLORS[0]
        else:
            title, color = "You lose", PLAYER_COLORS[1]
        cx, cy = scr.get_width() // 2, scr.get_height() // 2
        t = self.big_font.render(title, True, color)
        scr.blit(t, (cx - t.get_width() // 2, cy - 60))
        hint = self.font.render("R: play again    Esc: quit", True, TEXT)
        scr.blit(hint, (cx - hint.get_width() // 2, cy + 10))
