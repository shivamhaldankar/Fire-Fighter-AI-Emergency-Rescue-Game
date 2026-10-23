"""
main.py
Firefighter AI: Intelligent Emergency Rescue Game

STATES: MENU -> PLAYING -> (PAUSED) -> LEVEL_COMPLETE / GAME_OVER

CONTROLS
  Menu       : UP/DOWN pick level, ENTER start, ESC quit
  Playing    : 1-3 select algorithm
               SPACE  ask Expert System what to do next (pick up / deliver / evacuate)
               L      run propositional-resolution safety check on firefighter's cell
               V      toggle explored/path overlay
               P      pause
               R      restart level
               ESC    back to menu
  Game Over / Level Complete : ENTER continue, ESC menu, R retry
"""

import sys
import pygame

from environment import build_level_by_index, LEVELS, FIRE_MAX, SMOKE_MAX, FIRE_IMPASSABLE
from algorithms import ALGORITHMS, ALGORITHM_LABELS, bfs, manhattan
from expert_system import ExpertSystem

CELL = 22
MARGIN_TOP = 92
FOOTER_H = 150
PANEL_W = 300
FPS = 30
FIRE_TICK_MS = 1800
MOVE_TICK_MS = 150

STATE_MENU = "menu"
STATE_PLAYING = "playing"
STATE_PAUSED = "paused"
STATE_LEVEL_COMPLETE = "level_complete"
STATE_GAME_OVER = "game_over"

COLOR_BG = (16, 16, 20)
COLOR_WALL = (40, 40, 46)
COLOR_FLOOR = (58, 60, 68)
COLOR_EXIT = (60, 200, 120)
COLOR_EXPLORED = (70, 90, 140)
COLOR_PATH = (250, 220, 80)
COLOR_FIRE = (230, 70, 30)
COLOR_SMOKE = (140, 140, 150)
COLOR_FIREFIGHTER = (60, 160, 255)
COLOR_TEXT = (235, 235, 240)
COLOR_DIM = (150, 150, 160)
COLOR_PANEL = (26, 26, 32)
COLOR_PANEL_ALT = (34, 34, 42)

PRIORITY_COLORS = {
    "CRITICAL": (255, 70, 90),
    "HIGH": (255, 150, 60),
    "MEDIUM": (255, 210, 90),
    "LOW": (170, 220, 90),
    "RESCUED": (90, 210, 150),
    "LOST": (130, 130, 140),
}

SCORE_BY_PRIORITY = {"CRITICAL": 200, "HIGH": 150, "MEDIUM": 100, "LOW": 60}
DEATH_PENALTY = 80
LEVEL_CLEAR_BONUS_CLEAN = 250
LEVEL_CLEAR_BONUS_LOSSES = 100

WATER_MAX = 100
WATER_SPRAY_COST = 12
WATER_REGEN_PER_FIRE_TICK = 2
SPRAY_FIRE_REDUCTION = 4
SPRAY_SMOKE_REDUCTION = 3
SPRAY_RADIUS = 1


def lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


# ---------------------------------------------------------------------------
# Procedural sound effects (no external asset files needed)
# ---------------------------------------------------------------------------
class SoundBank:
    def __init__(self):
        self.enabled = False
        self.sounds = {}
        try:
            pygame.mixer.pre_init(44100, -16, 2, 256)
            pygame.mixer.init()
            import numpy as np
            self.np = np
            self.sounds["rescue"] = self._chime([(660, 100), (880, 100), (1175, 150)])
            self.sounds["pickup"] = self._chime([(500, 90), (700, 110)])
            self.sounds["alarm"] = self._chime([(220, 220)])
            self.sounds["death"] = self._chime([(320, 150), (220, 260)])
            self.sounds["level_complete"] = self._chime(
                [(523, 120), (659, 120), (784, 120), (1047, 240)])
            self.sounds["game_over"] = self._chime([(400, 160), (300, 160), (180, 320)])
            self.sounds["replan"] = self._chime([(380, 80), (300, 80)])
            self.sounds["spray"] = self._chime([(900, 50), (750, 50), (900, 50)])
            self.enabled = True
        except Exception:
            self.enabled = False

    def _chime(self, notes, volume=0.25, sample_rate=44100):
        np = self.np
        segments = []
        for freq, dur_ms in notes:
            n = int(sample_rate * dur_ms / 1000)
            t = np.linspace(0, dur_ms / 1000, n, False)
            wave = np.sin(freq * t * 2 * np.pi)
            env = np.clip(np.minimum(t, dur_ms / 1000 - t) * 40 + 0.08, 0, 1)
            segments.append(wave * env)
        audio = np.concatenate(segments)
        audio = (audio * volume * 32767).astype(np.int16)
        stereo = np.column_stack([audio, audio]).copy()
        return pygame.sndarray.make_sound(stereo)

    def play(self, name):
        if self.enabled and name in self.sounds:
            try:
                self.sounds[name].play()
            except Exception:
                pass


class Notification:
    def __init__(self, text, color, now, duration_ms=2600):
        self.text = text
        self.color = color
        self.expires = now + duration_ms


class Game:
    def __init__(self):
        pygame.init()
        self.sound = SoundBank()
        self.font = pygame.font.SysFont("consolas", 16)
        self.font_small = pygame.font.SysFont("consolas", 12)
        self.font_big = pygame.font.SysFont("consolas", 24, bold=True)
        self.font_mid = pygame.font.SysFont("consolas", 18, bold=True)
        self.clock = pygame.time.Clock()

        # window sized for the largest level so it never needs resizing
        max_rooms_w = max(c["rooms_w"] for c in LEVELS)
        max_rooms_h = max(c["rooms_h"] for c in LEVELS)
        max_grid_w = (max_rooms_w * 2 + 1) * CELL
        max_grid_h = (max_rooms_h * 2 + 1) * CELL
        self.win_w = max_grid_w + PANEL_W
        self.win_h = MARGIN_TOP + max_grid_h + FOOTER_H
        self.screen = pygame.display.set_mode((self.win_w, self.win_h))
        pygame.display.set_caption("Firefighter AI: Intelligent Emergency Rescue Game")

        self.state = STATE_MENU
        self.selected_level_idx = 0
        self.score = 0
        self.notifications = []

        self.level_index = 0
        self.grid = None
        self.expert = None

    # ------------------------------------------------------------------
    def notify(self, text, color=COLOR_TEXT):
        now = pygame.time.get_ticks()
        self.notifications.append(Notification(text, color, now))
        self.notifications = self.notifications[-6:]

    def start_level(self, idx):
        self.level_index = idx
        self.grid, self.cfg = build_level_by_index(idx)
        self.expert = ExpertSystem(self.grid)
        self.firefighter = list(self.grid.exits[0]) if self.grid.exits else [1, 1]
        self.anim_from = tuple(self.firefighter)
        self.anim_to = tuple(self.firefighter)
        self.anim_start = pygame.time.get_ticks()
        self.oxygen = self.cfg.get("start_oxygen", 100)
        self.algorithm_key = "2"  # default A*
        self.current_result = None
        self.current_target = None
        self.current_target_person = None
        self.pending_action = None     # "PICKUP" | "DELIVER" | "EVACUATE" | "EXTINGUISH"
        self.pending_priority = None
        self.carrying = None
        self.water = WATER_MAX
        self.extinguish_cell = None
        self.saved_mission = None      # mission to resume once a blocking fire is cleared
        self._low_water_notified = False
        self.move_index = 0
        self.show_explored = True
        self.lost_count = 0
        self.level_start_score = self.score
        self.status_lines = [f"{self.cfg['name']} loaded. Press SPACE to ask the Expert System."]
        self.trace_lines = []
        self.auto_fire = True
        self.rescued_count = 0
        self.last_fire_tick = pygame.time.get_ticks()
        self.last_move_tick = pygame.time.get_ticks()
        self.state = STATE_PLAYING

    def reset_level(self):
        self.score = self.level_start_score
        self.start_level(self.level_index)

    # ------------------------------------------------------------------
    # Expert-system-driven decision making
    # ------------------------------------------------------------------
    def request_target(self):
        action, ranked, trace = self.expert.rank_targets(self.oxygen, carrying=self.carrying is not None)
        self.trace_lines = trace

        if action == "DELIVER_TO_EXIT":
            self.current_target = self._nearest_exit()
            self.current_target_person = None
            self.pending_action = "DELIVER"
            self.status_lines = [f"Carrying {self.carrying.id} -> heading to nearest exit (R8)."]
        elif action == "RETURN_TO_EXIT":
            self.current_target = self._nearest_exit()
            self.current_target_person = None
            self.pending_action = "EVACUATE"
            self.status_lines = ["Oxygen critical -> RETURN TO EXIT (R5)."]
        elif action == "NONE":
            self.current_target = None
            self.current_result = None
            self.status_lines = ["No unrescued persons remain."]
            self._check_level_complete()
            return
        else:  # RESCUE
            person, priority, facts = ranked[0]
            self.current_target = person.pos()
            self.current_target_person = person
            self.pending_action = "PICKUP"
            self.pending_priority = priority
            self.status_lines = [
                f"Target: {person.id} priority={priority} "
                f"(health={facts['health']}, fire_dist={facts['fire_distance']})"
            ]

        self._plan_path()

    def _nearest_exit(self):
        best, best_d = None, None
        for ex in self.grid.exits:
            d = abs(ex[0] - self.firefighter[0]) + abs(ex[1] - self.firefighter[1])
            if best_d is None or d < best_d:
                best, best_d = ex, d
        return best

    def _plan_path(self):
        if self.current_target is None:
            self.current_result = None
            return
        algo_fn = ALGORITHMS[self.algorithm_key]
        start = tuple(self.firefighter)
        result = algo_fn(self.grid, start, self.current_target)
        self.current_result = result
        self.move_index = 0
        if result["path"] is None:
            self.status_lines.append(
                f"{result['name']}: NO PATH FOUND"
                + (f" (stuck at {result.get('stuck_at')})" if result.get("stuck_at") else "")
            )
            self.sound.play("alarm")
            if self.pending_action != "EXTINGUISH":
                handled = self._attempt_auto_extinguish(start, self.current_target)
                if not handled:
                    if self.algorithm_key == "3":
                        self.status_lines.append(
                            "Hill Climbing is stuck at a local maximum - press 1 (BFS) or 2 (A*) to switch.")
                    else:
                        self.status_lines.append("No reachable fire blocking the route either - truly cut off.")
        else:
            cost_txt = f" cost={result['cost']:.1f}" if result["cost"] is not None else ""
            self.status_lines.append(
                f"{result['name']}: len={len(result['path'])-1} explored={len(result['explored'])}{cost_txt}"
            )

    # ------------------------------------------------------------------
    # Auto-extinguish: if a route is blocked by impassable fire, route the
    # firefighter to the nearest reachable spot next to that fire, spray it
    # down with water until passable, then resume the original mission.
    # ------------------------------------------------------------------
    def _find_blocking_fire(self, start, goal):
        """Among cells reachable from `start` under current fire conditions,
        find an adjacent impassable-fire cell - preferring the one closest
        to `goal`, since that's most likely to be the cell actually blocking
        the route we wanted."""
        reach = set(bfs(self.grid, start, goal)["explored"])
        candidates = []
        for (x, y) in reach:
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                nx, ny = x + dx, y + dy
                if (self.grid.in_bounds(nx, ny) and not self.grid.is_wall(nx, ny)
                        and self.grid.fire[ny][nx] >= FIRE_IMPASSABLE):
                    candidates.append(((nx, ny), (x, y)))
        if not candidates:
            return None
        candidates.sort(key=lambda c: manhattan(c[0], goal))
        return candidates[0]  # (fire_cell, stand_cell)

    def _attempt_auto_extinguish(self, start, goal):
        found = self._find_blocking_fire(start, goal)
        if found is None:
            return False
        fire_cell, stand_cell = found

        self.saved_mission = dict(target=self.current_target,
                                   target_person=self.current_target_person,
                                   pending_action=self.pending_action,
                                   priority=self.pending_priority)
        self.extinguish_cell = fire_cell
        self.current_target_person = None
        self.pending_action = "EXTINGUISH"
        self.status_lines.append(
            f"Route blocked by fire at {fire_cell} -> moving in to extinguish it (R10).")
        self.trace_lines.append(
            f"R10: route blocked by impassable fire at {fire_cell} -> action(EXTINGUISH_PATH)")
        self.notify(f"Fire blocking the route - moving to extinguish {fire_cell}", (255, 170, 90))

        stand_result = bfs(self.grid, start, stand_cell)
        self.current_target = stand_cell
        self.current_result = stand_result
        self.move_index = 0
        return True

    def _extinguish_step(self):
        if self.extinguish_cell is None:
            self._resume_saved_mission()
            return
        ex, ey = self.extinguish_cell
        if self.grid.is_passable(ex, ey):
            self.notify(f"Fire at {self.extinguish_cell} cleared! Resuming rescue.", (120, 220, 255))
            self._resume_saved_mission()
            return
        if self.water < WATER_SPRAY_COST:
            if not self._low_water_notified:
                self.notify("Low on water - tank recharging...", (120, 180, 255))
                self._low_water_notified = True
            return
        self._low_water_notified = False
        self.water -= WATER_SPRAY_COST
        self.grid.spray_water(ex, ey, fire_reduction=SPRAY_FIRE_REDUCTION,
                               smoke_reduction=SPRAY_SMOKE_REDUCTION, radius=SPRAY_RADIUS)
        self.sound.play("spray")
        if self.grid.is_passable(ex, ey):
            self.notify(f"Fire at {self.extinguish_cell} knocked down! Resuming rescue.", (120, 220, 255))
            self._resume_saved_mission()
        else:
            self.status_lines.append(
                f"Spraying fire at {self.extinguish_cell} (intensity {self.grid.fire[ey][ex]})...")

    def _resume_saved_mission(self):
        m = self.saved_mission
        self.extinguish_cell = None
        self.saved_mission = None
        if m is None:
            self.current_result = None
            return
        self.current_target = m["target"]
        self.current_target_person = m["target_person"]
        self.pending_action = m["pending_action"]
        self.pending_priority = m["priority"]
        self._plan_path()

    def _manual_spray(self):
        if self.water < WATER_SPRAY_COST:
            self.notify("Not enough water to spray.", (255, 150, 150))
            return
        x, y = self.firefighter
        self.water -= WATER_SPRAY_COST
        changed = self.grid.spray_water(x, y, fire_reduction=SPRAY_FIRE_REDUCTION,
                                         smoke_reduction=SPRAY_SMOKE_REDUCTION, radius=SPRAY_RADIUS)
        self.sound.play("spray")
        if changed:
            self.notify("Sprayed water - fire/smoke reduced nearby.", (120, 200, 255))
        else:
            self.notify("No fire or smoke nearby to spray.", (160, 160, 170))

    # ------------------------------------------------------------------
    def advance_step(self):
        """Advance the firefighter one grid cell along the current path."""
        if not self.current_result or not self.current_result["path"]:
            return
        path = self.current_result["path"]
        if self.move_index >= len(path) - 1:
            self._on_arrival()
            return

        nxt = path[self.move_index + 1]
        if not self.grid.is_passable(*nxt):
            self.status_lines.append("Fire blocked the planned route -> REPLANNING...")
            self.sound.play("replan")
            self._plan_path()
            return

        self.move_index += 1
        self.anim_from = tuple(self.firefighter)
        self.anim_to = nxt
        self.anim_start = pygame.time.get_ticks()
        self.firefighter = [nxt[0], nxt[1]]

        self.oxygen = max(0.0, self.oxygen - 0.3 - self.grid.smoke[nxt[1]][nxt[0]] / 15)
        if self.oxygen <= 0:
            self.state = STATE_GAME_OVER
            self.sound.play("game_over")

    def _on_arrival(self):
        pos = tuple(self.firefighter)
        if self.pending_action == "PICKUP" and self.current_target_person is not None:
            p = self.current_target_person
            if pos == p.pos() and not p.rescued and p.health > 0:
                self.carrying = p
                self.notify(f"Picked up {p.id} - heading for the exit", (120, 200, 255))
                self.sound.play("pickup")
                self.current_target_person = None
                self.current_result = None
                self.request_target()
        elif self.pending_action == "DELIVER" and self.carrying is not None:
            if self.grid.is_exit(*pos):
                p = self.carrying
                p.rescued = True
                pts = SCORE_BY_PRIORITY.get(self.pending_priority, 80)
                self.score += pts
                self.rescued_count += 1
                self.notify(f"Delivered {p.id} to safety! +{pts}", PRIORITY_COLORS["RESCUED"])
                self.sound.play("rescue")
                self.carrying = None
                self.current_result = None
                self._check_level_complete()
                if self.state == STATE_PLAYING:
                    self.request_target()
        elif self.pending_action == "EVACUATE":
            if self.grid.is_exit(*pos):
                self.oxygen = min(100, self.oxygen + 40)
                self.notify("Reached exit - oxygen replenished", (160, 220, 255))
                self.current_result = None
                self.status_lines.append("At exit. Press SPACE to resume rescue operations.")
        elif self.pending_action == "EXTINGUISH":
            self._extinguish_step()

    def _check_level_complete(self):
        if not self.grid.living_unrescued_persons() and self.carrying is None:
            clean = self.lost_count == 0
            bonus = LEVEL_CLEAR_BONUS_CLEAN if clean else LEVEL_CLEAR_BONUS_LOSSES
            self.score += bonus
            self.state = STATE_LEVEL_COMPLETE
            self.sound.play("level_complete")

    # ------------------------------------------------------------------
    def handle_key_menu(self, key):
        if key == pygame.K_UP:
            self.selected_level_idx = (self.selected_level_idx - 1) % len(LEVELS)
        elif key == pygame.K_DOWN:
            self.selected_level_idx = (self.selected_level_idx + 1) % len(LEVELS)
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            self.start_level(self.selected_level_idx)
        elif key == pygame.K_ESCAPE:
            pygame.quit()
            sys.exit(0)

    def handle_key_playing(self, key):
        if key in (pygame.K_1, pygame.K_2, pygame.K_3):
            self.algorithm_key = chr(key)
            self.status_lines = [f"Algorithm set to {ALGORITHM_LABELS[self.algorithm_key]}."]
            if self.current_target:
                self._plan_path()
        elif key == pygame.K_SPACE:
            self.request_target()
        elif key == pygame.K_l:
            self._run_resolution_check()
        elif key == pygame.K_w:
            self._manual_spray()
        elif key == pygame.K_v:
            self.show_explored = not self.show_explored
        elif key == pygame.K_p:
            self.state = STATE_PAUSED
        elif key == pygame.K_r:
            self.reset_level()
        elif key == pygame.K_ESCAPE:
            self.state = STATE_MENU

    def handle_key_paused(self, key):
        if key == pygame.K_p:
            self.state = STATE_PLAYING
        elif key == pygame.K_ESCAPE:
            self.state = STATE_MENU

    def handle_key_end_state(self, key):
        if key in (pygame.K_RETURN, pygame.K_SPACE):
            if self.state == STATE_LEVEL_COMPLETE and self.level_index + 1 < len(LEVELS):
                self.start_level(self.level_index + 1)
            else:
                self.state = STATE_MENU
        elif key == pygame.K_r:
            self.reset_level()
        elif key == pygame.K_ESCAPE:
            self.state = STATE_MENU

    def _run_resolution_check(self):
        x, y = self.firefighter
        conclusion, clauses = self.expert.resolve_cell_safety(x, y)
        self.trace_lines = [f"-- Resolution check at ({x},{y}) --"] + clauses + [f"=> {conclusion}"]
        self.status_lines.append(f"Resolution: safe={conclusion['safe']} visible={conclusion['visible']}")

    # ------------------------------------------------------------------
    def update(self, now):
        if self.state != STATE_PLAYING:
            return

        if self.auto_fire and now - self.last_fire_tick > FIRE_TICK_MS:
            self.grid.spread_fire(spread_chance=self.cfg.get("fire_spread_chance", 0.28))
            newly_lost = self.grid.apply_fire_damage_to_persons()
            for p in newly_lost:
                self.lost_count += 1
                self.score = max(0, self.score - DEATH_PENALTY)
                self.notify(f"{p.id} was lost to the fire. -{DEATH_PENALTY}", PRIORITY_COLORS["LOST"])
                self.sound.play("death")
                if self.current_target_person is p:
                    self.current_target_person = None
                    self.current_result = None
            if newly_lost:
                self._check_level_complete()
            self.water = min(WATER_MAX, self.water + WATER_REGEN_PER_FIRE_TICK)
            self.last_fire_tick = now
            if self.grid.smoke[self.firefighter[1]][self.firefighter[0]] == 0:
                self.oxygen = min(100, self.oxygen + 1)

        if now - self.last_move_tick > MOVE_TICK_MS:
            self.advance_step()
            self.last_move_tick = now

        self.notifications = [n for n in self.notifications if n.expires > now]

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def draw(self):
        self.screen.fill(COLOR_BG)
        if self.state == STATE_MENU:
            self._draw_menu()
        else:
            self._draw_header()
            self._draw_grid()
            self._draw_side_panel()
            self._draw_footer()
            if self.state == STATE_PAUSED:
                self._draw_overlay_text("PAUSED", "Press P to resume, ESC for menu")
            elif self.state == STATE_LEVEL_COMPLETE:
                self._draw_level_complete()
            elif self.state == STATE_GAME_OVER:
                self._draw_game_over()
        pygame.display.flip()

    def _draw_menu(self):
        title = self.font_big.render("Firefighter AI: Intelligent Emergency Rescue Game", True, COLOR_TEXT)
        self.screen.blit(title, (self.win_w // 2 - title.get_width() // 2, 60))
        sub = self.font_small.render(
            "BFS - A* - Hill Climbing - Expert System - Resolution",
            True, COLOR_DIM)
        self.screen.blit(sub, (self.win_w // 2 - sub.get_width() // 2, 95))

        y = 170
        for i, cfg in enumerate(LEVELS):
            selected = i == self.selected_level_idx
            color = (255, 220, 120) if selected else COLOR_TEXT
            prefix = "> " if selected else "  "
            line = self.font_mid.render(f"{prefix}{cfg['name']}", True, color)
            self.screen.blit(line, (self.win_w // 2 - 220, y))
            detail = self.font_small.render(
                f"   {len(cfg['person_specs'])} people to rescue | "
                f"fire spread {cfg['fire_spread_chance']:.2f} | oxygen {cfg['start_oxygen']}",
                True, COLOR_DIM)
            self.screen.blit(detail, (self.win_w // 2 - 220, y + 26))
            y += 64

        hint = self.font.render("UP/DOWN select  -  ENTER start  -  ESC quit", True, COLOR_DIM)
        self.screen.blit(hint, (self.win_w // 2 - hint.get_width() // 2, y + 30))

        score_txt = self.font.render(f"Total score so far: {self.score}", True, (180, 220, 255))
        self.screen.blit(score_txt, (self.win_w // 2 - score_txt.get_width() // 2, y + 60))

    def _draw_header(self):
        title = self.font_mid.render(self.cfg["name"], True, COLOR_TEXT)
        self.screen.blit(title, (12, 8))
        carrying_txt = f"Carrying: {self.carrying.id}" if self.carrying else "Carrying: -"
        line1 = self.font.render(
            f"Algo[1-3]: {ALGORITHM_LABELS[self.algorithm_key]}   Oxygen: {int(self.oxygen)}   "
            f"Water: {int(self.water)}   Score: {self.score}   {carrying_txt}",
            True, (200, 200, 210))
        self.screen.blit(line1, (12, 34))
        line2 = self.font.render(
            f"Rescued: {self.rescued_count}/{len(self.grid.persons)}   Lost: {self.lost_count}   "
            f"Auto-Fire[F]: {'ON' if self.auto_fire else 'OFF'}   Overlay[V]: {'ON' if self.show_explored else 'OFF'}",
            True, (200, 200, 210))
        self.screen.blit(line2, (12, 56))
        hint = self.font_small.render(
            "SPACE=ask Expert System  W=spray water  L=resolution check  P=pause  R=restart  ESC=menu",
            True, COLOR_DIM)
        self.screen.blit(hint, (12, 76))

    def _draw_grid(self):
        explored = set(self.current_result["explored"]) if (self.current_result and self.show_explored) else set()
        path = set(self.current_result["path"]) if self.current_result and self.current_result["path"] else set()

        for y in range(self.grid.height):
            for x in range(self.grid.width):
                rx = x * CELL
                ry = MARGIN_TOP + y * CELL
                if self.grid.is_wall(x, y):
                    color = COLOR_WALL
                elif self.grid.is_exit(x, y):
                    color = COLOR_EXIT
                else:
                    color = COLOR_FLOOR
                    fire_i = self.grid.fire[y][x]
                    smoke_d = self.grid.smoke[y][x]
                    if fire_i > 0:
                        color = lerp_color(COLOR_FLOOR, COLOR_FIRE, fire_i / FIRE_MAX)
                    elif smoke_d > 0:
                        color = lerp_color(COLOR_FLOOR, COLOR_SMOKE, smoke_d / SMOKE_MAX)
                    if (x, y) in explored and (x, y) not in path:
                        color = lerp_color(color, COLOR_EXPLORED, 0.5)
                    if (x, y) in path:
                        color = lerp_color(color, COLOR_PATH, 0.6)
                    if self.extinguish_cell == (x, y):
                        color = lerp_color(color, (70, 150, 255), 0.6)
                pygame.draw.rect(self.screen, color, (rx, ry, CELL - 1, CELL - 1))

        for p in self.grid.persons:
            if p.rescued or p.health <= 0:
                continue
            cx = p.x * CELL + CELL // 2
            cy = MARGIN_TOP + p.y * CELL + CELL // 2
            priority, _ = self.expert.evaluate_person(p, self.oxygen, log=False)
            if self.grid.fire[p.y][p.x] > 0:
                priority = "CRITICAL"
            c = PRIORITY_COLORS.get(priority, COLOR_TEXT)
            pygame.draw.circle(self.screen, c, (cx, cy), CELL // 3)
            label = self.font_small.render(p.id, True, (15, 15, 15))
            self.screen.blit(label, (cx - 10, cy - 7))

        now = pygame.time.get_ticks()
        t = min(1.0, (now - self.anim_start) / MOVE_TICK_MS) if self.state == STATE_PLAYING else 1.0
        fx0, fy0 = self.anim_from
        fx1, fy1 = self.anim_to
        px = (fx0 + (fx1 - fx0) * t) * CELL + CELL // 2
        py = MARGIN_TOP + (fy0 + (fy1 - fy0) * t) * CELL + CELL // 2
        ring_color = (255, 210, 90) if self.carrying else (255, 255, 255)
        pygame.draw.circle(self.screen, COLOR_FIREFIGHTER, (int(px), int(py)), CELL // 2 - 3)
        pygame.draw.circle(self.screen, ring_color, (int(px), int(py)), CELL // 2 - 3, 2)

    def _draw_side_panel(self):
        px0 = self.grid.width * CELL
        panel_rect = (px0, MARGIN_TOP, self.win_w - px0, self.grid.height * CELL)
        pygame.draw.rect(self.screen, COLOR_PANEL, panel_rect)

        y = MARGIN_TOP + 8
        header = self.font.render("Triage Board", True, (255, 210, 120))
        self.screen.blit(header, (px0 + 10, y))
        y += 24

        board = self._triage_board()
        for p, status, facts in board:
            color = PRIORITY_COLORS.get(status, COLOR_TEXT)
            pygame.draw.circle(self.screen, color, (px0 + 18, y + 7), 6)
            carried_tag = " (carried)" if self.carrying is p else ""
            line = f"{p.id}: {status}{carried_tag}"
            self.screen.blit(self.font_small.render(line, True, COLOR_TEXT), (px0 + 32, y))
            y += 16
            if facts:
                detail = f"  hp={facts.get('health','-')} fire_d={facts.get('fire_distance','-')}"
                self.screen.blit(self.font_small.render(detail, True, COLOR_DIM), (px0 + 32, y))
                y += 16
            y += 4

        y += 10
        pygame.draw.line(self.screen, (60, 60, 70), (px0 + 10, y), (self.win_w - 10, y))
        y += 10

        header2 = self.font.render("Legend", True, (255, 210, 120))
        self.screen.blit(header2, (px0 + 10, y))
        y += 22
        legend_items = [
            (COLOR_FIRE, "Fire (impassable if intense)"),
            (COLOR_SMOKE, "Smoke (oxygen drain)"),
            (COLOR_EXIT, "Exit"),
            (COLOR_EXPLORED, "Explored by algorithm"),
            (COLOR_PATH, "Planned path"),
            ((70, 150, 255), "Being sprayed (extinguish target)"),
            (COLOR_FIREFIGHTER, "Firefighter"),
            (PRIORITY_COLORS["CRITICAL"], "Priority: CRITICAL"),
            (PRIORITY_COLORS["HIGH"], "Priority: HIGH"),
            (PRIORITY_COLORS["MEDIUM"], "Priority: MEDIUM"),
            (PRIORITY_COLORS["LOW"], "Priority: LOW"),
        ]
        for color, label in legend_items:
            pygame.draw.rect(self.screen, color, (px0 + 12, y, 12, 12))
            self.screen.blit(self.font_small.render(label, True, COLOR_DIM), (px0 + 30, y - 1))
            y += 18

    def _triage_board(self):
        order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "RESCUED": 4, "LOST": 5}
        board = []
        for p in self.grid.persons:
            if p.rescued:
                board.append((p, "RESCUED", {}))
            elif p.health <= 0:
                board.append((p, "LOST", {}))
            else:
                priority, facts = self.expert.evaluate_person(p, self.oxygen, log=False)
                if self.grid.fire[p.y][p.x] > 0:
                    priority = "CRITICAL"
                board.append((p, priority, facts))
        board.sort(key=lambda r: order.get(r[1], 9))
        return board

    def _draw_footer(self):
        y0 = MARGIN_TOP + self.grid.height * CELL + 6
        pygame.draw.rect(self.screen, COLOR_PANEL, (0, y0, self.win_w, FOOTER_H - 6))

        y = y0 + 6
        self.screen.blit(self.font.render("Status:", True, (255, 210, 120)), (12, y))
        y += 20
        for line in self.status_lines[-3:]:
            self.screen.blit(self.font_small.render(line[:95], True, COLOR_TEXT), (12, y))
            y += 16

        y2 = y0 + 6
        self.screen.blit(self.font.render("Expert System / Resolution Trace:", True, (255, 210, 120)),
                          (440, y2))
        y2 += 20
        for line in self.trace_lines[-6:]:
            self.screen.blit(self.font_small.render(line[:100], True, (190, 210, 255)), (440, y2))
            y2 += 15

        ny = y0 + FOOTER_H - 34
        now = pygame.time.get_ticks()
        for n in self.notifications[-3:]:
            alpha_hint = n.expires - now
            if alpha_hint > 0:
                self.screen.blit(self.font_small.render(n.text, True, n.color), (12, ny))
                ny -= 16

    def _draw_overlay_text(self, title, subtitle):
        overlay = pygame.Surface((self.win_w, self.win_h))
        overlay.set_alpha(150)
        overlay.fill((0, 0, 0))
        self.screen.blit(overlay, (0, 0))
        t = self.font_big.render(title, True, (255, 230, 150))
        self.screen.blit(t, (self.win_w // 2 - t.get_width() // 2, self.win_h // 2 - 30))
        s = self.font.render(subtitle, True, COLOR_TEXT)
        self.screen.blit(s, (self.win_w // 2 - s.get_width() // 2, self.win_h // 2 + 6))

    def _draw_level_complete(self):
        clean = self.lost_count == 0
        subtitle = (f"Rescued {self.rescued_count}/{len(self.grid.persons)}  Lost {self.lost_count}  "
                     f"Score: {self.score}  |  ENTER next level, R retry, ESC menu")
        title = "LEVEL COMPLETE - Clean Rescue!" if clean else "LEVEL COMPLETE - With Losses"
        self._draw_overlay_text(title, subtitle)

    def _draw_game_over(self):
        self._draw_overlay_text(
            "OUT OF OXYGEN",
            f"Score: {self.score}  |  ENTER/ESC menu, R retry level")

    # ------------------------------------------------------------------
    def handle_key(self, key):
        if self.state == STATE_MENU:
            self.handle_key_menu(key)
        elif self.state == STATE_PLAYING:
            self.handle_key_playing(key)
        elif self.state == STATE_PAUSED:
            self.handle_key_paused(key)
        elif key == pygame.K_f and self.state == STATE_PLAYING:
            self.auto_fire = not self.auto_fire
        elif self.state in (STATE_LEVEL_COMPLETE, STATE_GAME_OVER):
            self.handle_key_end_state(key)

    def run(self):
        while True:
            now = pygame.time.get_ticks()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                if event.type == pygame.KEYDOWN:
                    if self.state == STATE_PLAYING and event.key == pygame.K_f:
                        self.auto_fire = not self.auto_fire
                    else:
                        self.handle_key(event.key)

            self.update(now)
            self.draw()
            self.clock.tick(FPS)


if __name__ == "__main__":
    Game().run()