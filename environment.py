"""
environment.py
Grid-based emergency building model: walls, fire, smoke, trapped persons, exits.
"""

import random

FIRE_IMPASSABLE = 8   # intensity at/above this = cell cannot be entered
SMOKE_MAX = 10
FIRE_MAX = 10


class Person:
    def __init__(self, pid, x, y, health=100, age_group="adult", mobility="trapped"):
        self.id = pid
        self.x = x
        self.y = y
        self.health = health
        self.age_group = age_group      # "child" | "adult"
        self.mobility = mobility        # "mobile" | "trapped"
        self.rescued = False

    def pos(self):
        return (self.x, self.y)

    def take_fire_damage(self, fire_intensity):
        """Called each fire tick if this person's cell is burning.
        Returns True if the person just died (health crossed to 0)."""
        if self.rescued or self.health <= 0:
            return False
        dmg = max(0, fire_intensity - 3) * 4  # only meaningfully damaging once intensity > 3
        if dmg <= 0:
            return False
        self.health = max(0, self.health - dmg)
        return self.health == 0


class Grid:
    """
    cell types: '.' floor, '#' wall, 'E' exit
    fire[y][x]  : 0-10 intensity
    smoke[y][x] : 0-10 density
    """

    def __init__(self, layout):
        self.layout = [list(row) for row in layout]
        self.height = len(self.layout)
        self.width = len(self.layout[0])
        self.fire = [[0 for _ in range(self.width)] for _ in range(self.height)]
        self.smoke = [[0 for _ in range(self.width)] for _ in range(self.height)]
        self.persons = []
        self.exits = []
        self._scan_layout()

    def _scan_layout(self):
        for y in range(self.height):
            for x in range(self.width):
                if self.layout[y][x] == 'E':
                    self.exits.append((x, y))

    def in_bounds(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def is_wall(self, x, y):
        return self.layout[y][x] == '#'

    def is_exit(self, x, y):
        return (x, y) in self.exits

    def is_passable(self, x, y):
        """Walls are always impassable. Fire above threshold is impassable."""
        if not self.in_bounds(x, y):
            return False
        if self.is_wall(x, y):
            return False
        if self.fire[y][x] >= FIRE_IMPASSABLE:
            return False
        return True

    def neighbors(self, x, y):
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):  # 4-directional
            nx, ny = x + dx, y + dy
            if self.is_passable(nx, ny):
                yield (nx, ny)

    def ignite(self, x, y, intensity=6):
        if self.in_bounds(x, y) and not self.is_wall(x, y):
            self.fire[y][x] = intensity

    def spread_fire(self, spread_chance=0.28, growth=1):
        """Called every simulation tick. Fire grows and spreads to neighbors;
        smoke diffuses slightly further than fire itself."""
        new_fire = [row[:] for row in self.fire]
        new_smoke = [row[:] for row in self.smoke]

        for y in range(self.height):
            for x in range(self.width):
                if self.is_wall(x, y):
                    continue
                if self.fire[y][x] > 0:
                    # existing fire grows
                    new_fire[y][x] = min(FIRE_MAX, self.fire[y][x] + growth)
                    new_smoke[y][x] = min(SMOKE_MAX, self.smoke[y][x] + growth)
                    # chance to spread to neighbors
                    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                        nx, ny = x + dx, y + dy
                        if self.in_bounds(nx, ny) and not self.is_wall(nx, ny):
                            if random.random() < spread_chance:
                                new_fire[ny][nx] = max(new_fire[ny][nx], 2)
                            # smoke spreads further/easier than flame
                            if random.random() < spread_chance + 0.25:
                                new_smoke[ny][nx] = min(SMOKE_MAX, new_smoke[ny][nx] + 2)

        self.fire = new_fire
        self.smoke = new_smoke

    def add_person(self, pid, x, y, **kwargs):
        p = Person(pid, x, y, **kwargs)
        self.persons.append(p)
        return p

    def living_unrescued_persons(self):
        return [p for p in self.persons if not p.rescued and p.health > 0]

    def lost_persons(self):
        return [p for p in self.persons if not p.rescued and p.health <= 0]

    def apply_fire_damage_to_persons(self):
        """Call once per fire-spread tick. Returns list of Person objects
        that died this tick (health just hit 0)."""
        newly_lost = []
        for p in self.living_unrescued_persons():
            if self.fire[p.y][p.x] > 0:
                if p.take_fire_damage(self.fire[p.y][p.x]):
                    newly_lost.append(p)
        return newly_lost

    def spray_water(self, x, y, fire_reduction=4, smoke_reduction=3, radius=1):
        """Douse fire/smoke in a small Manhattan-radius around (x, y).
        Returns True if anything was actually reduced."""
        changed = False
        for yy in range(max(0, y - radius), min(self.height, y + radius + 1)):
            for xx in range(max(0, x - radius), min(self.width, x + radius + 1)):
                if self.is_wall(xx, yy):
                    continue
                if abs(xx - x) + abs(yy - y) > radius:
                    continue
                if self.fire[yy][xx] > 0:
                    self.fire[yy][xx] = max(0, self.fire[yy][xx] - fire_reduction)
                    changed = True
                if self.smoke[yy][xx] > 0:
                    self.smoke[yy][xx] = max(0, self.smoke[yy][xx] - smoke_reduction)
                    changed = True
        return changed

    def step_cost(self, x, y, w_fire=5, w_smoke=2):
        """g(n) contribution for entering cell (x, y)."""
        return 1 + self.fire[y][x] * w_fire / FIRE_MAX + self.smoke[y][x] * w_smoke / SMOKE_MAX


def _generate_maze_layout(rooms_w=11, rooms_h=8, extra_loop_chance=0.12, seed=7):
    """
    Randomized-DFS 'recursive backtracker' maze, guaranteed fully connected
    by construction (it's a spanning tree over the room grid). A few extra
    walls are then knocked down at random (extra_loop_chance) so multiple
    routes exist between areas -- otherwise BFS/DFS/A*/Hill-Climbing would
    all be forced onto the identical single corridor, which makes for a
    boring algorithm comparison.
    """
    rng = random.Random(seed)
    width = rooms_w * 2 + 1
    height = rooms_h * 2 + 1
    grid = [['#'] * width for _ in range(height)]

    def room_cell(rx, ry):
        return (rx * 2 + 1, ry * 2 + 1)

    visited = [[False] * rooms_w for _ in range(rooms_h)]
    stack = [(0, 0)]
    visited[0][0] = True
    gx, gy = room_cell(0, 0)
    grid[gy][gx] = '.'

    while stack:
        rx, ry = stack[-1]
        neighbors = []
        for drx, dry in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nrx, nry = rx + drx, ry + dry
            if 0 <= nrx < rooms_w and 0 <= nry < rooms_h and not visited[nry][nrx]:
                neighbors.append((nrx, nry, drx, dry))
        if not neighbors:
            stack.pop()
            continue
        nrx, nry, drx, dry = rng.choice(neighbors)
        visited[nry][nrx] = True
        cx, cy = room_cell(rx, ry)
        nx, ny = room_cell(nrx, nry)
        wall_x, wall_y = cx + drx, cy + dry
        grid[wall_y][wall_x] = '.'   # knock down wall between the two rooms
        grid[ny][nx] = '.'
        stack.append((nrx, nry))

    # knock down a handful of extra walls between adjacent rooms to create loops
    for ry in range(rooms_h):
        for rx in range(rooms_w):
            for drx, dry in ((1, 0), (0, 1)):
                nrx, nry = rx + drx, ry + dry
                if nrx < rooms_w and nry < rooms_h and rng.random() < extra_loop_chance:
                    cx, cy = room_cell(rx, ry)
                    wall_x, wall_y = cx + drx, cy + dry
                    grid[wall_y][wall_x] = '.'

    return [''.join(row) for row in grid]


DEFAULT_LAYOUT = _generate_maze_layout()


def _verify_connectivity(grid):
    """BFS flood-fill from first exit; returns True if every floor/exit cell
    is reachable, and prints unreachable cells if not (used at import time
    as a self-check for the hand-authored layout)."""
    from collections import deque
    start = grid.exits[0]
    seen = {start}
    q = deque([start])
    while q:
        cx, cy = q.popleft()
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nx, ny = cx + dx, cy + dy
            if grid.in_bounds(nx, ny) and not grid.is_wall(nx, ny) and (nx, ny) not in seen:
                seen.add((nx, ny))
                q.append((nx, ny))
    unreachable = []
    for y in range(grid.height):
        for x in range(grid.width):
            if not grid.is_wall(x, y) and (x, y) not in seen:
                unreachable.append((x, y))
    return unreachable


def build_level(rooms_w=11, rooms_h=8, seed=7, person_specs=None,
                 fire_rooms=((6, 2, 5), (4, 5, 4))):
    """
    person_specs: list of dicts with keys rx, ry (room coords), id, health,
                  age_group, mobility. If None, a default set is generated.
    fire_rooms: list of (rx, ry, intensity) ignition points, in room coords.
    """
    layout_rows = _generate_maze_layout(rooms_w, rooms_h, seed=seed)
    raw = [list(row) for row in layout_rows]

    def room_cell(rx, ry):
        return (rx * 2 + 1, ry * 2 + 1)  # always an open floor cell by construction

    exit1 = room_cell(0, 0)
    exit2 = room_cell(rooms_w - 1, rooms_h - 1)
    raw[exit1[1]][exit1[0]] = 'E'
    raw[exit2[1]][exit2[0]] = 'E'

    layout = [''.join(row) for row in raw]
    width = max(len(r) for r in layout)
    layout = [r.ljust(width, '#') for r in layout]
    grid = Grid(layout)

    unreachable = _verify_connectivity(grid)
    if unreachable:
        raise RuntimeError(f"Generated layout has unreachable floor cells: {unreachable}")

    for rx, ry, intensity in fire_rooms:
        grid.ignite(*room_cell(rx, ry), intensity=intensity)

    if person_specs is None:
        person_specs = [
            dict(id="P1", rx=5, ry=1, health=80, age_group="child", mobility="trapped"),
            dict(id="P2", rx=8, ry=6, health=60, age_group="adult", mobility="trapped"),
            dict(id="P3", rx=2, ry=7, health=95, age_group="adult", mobility="mobile"),
        ]
    for spec in person_specs:
        x, y = room_cell(spec["rx"], spec["ry"])
        grid.add_person(spec["id"], x, y, health=spec.get("health", 80),
                         age_group=spec.get("age_group", "adult"),
                         mobility=spec.get("mobility", "trapped"))

    return grid


def build_default_grid():
    return build_level()


# ---------------------------------------------------------------------------
# Level definitions: increasing size / danger / person count.
# ---------------------------------------------------------------------------
LEVELS = [
    dict(
        name="Level 1 - Apartment Fire",
        rooms_w=11, rooms_h=8, seed=7,
        fire_rooms=[(6, 2, 5), (4, 5, 4)],
        person_specs=[
            dict(id="P1", rx=5, ry=1, health=80, age_group="child", mobility="trapped"),
            dict(id="P2", rx=8, ry=6, health=60, age_group="adult", mobility="trapped"),
            dict(id="P3", rx=2, ry=7, health=95, age_group="adult", mobility="mobile"),
        ],
        fire_spread_chance=0.28, start_oxygen=100,
    ),
    dict(
        name="Level 2 - Office Block Blaze",
        rooms_w=13, rooms_h=9, seed=21,
        fire_rooms=[(3, 2, 6), (9, 3, 5), (6, 7, 4)],
        person_specs=[
            dict(id="P1", rx=1, ry=6, health=70, age_group="adult", mobility="trapped"),
            dict(id="P2", rx=11, ry=1, health=40, age_group="child", mobility="trapped"),
            dict(id="P3", rx=6, ry=4, health=90, age_group="adult", mobility="mobile"),
            dict(id="P4", rx=10, ry=7, health=55, age_group="adult", mobility="trapped"),
        ],
        fire_spread_chance=0.33, start_oxygen=100,
    ),
    dict(
        name="Level 3 - High-Rise Inferno",
        rooms_w=15, rooms_h=10, seed=99,
        fire_rooms=[(2, 2, 7), (12, 2, 6), (7, 5, 5), (4, 8, 4)],
        person_specs=[
            dict(id="P1", rx=1, ry=1, health=50, age_group="child", mobility="trapped"),
            dict(id="P2", rx=13, ry=1, health=35, age_group="child", mobility="trapped"),
            dict(id="P3", rx=7, ry=8, health=85, age_group="adult", mobility="mobile"),
            dict(id="P4", rx=13, ry=8, health=45, age_group="adult", mobility="trapped"),
            dict(id="P5", rx=4, ry=4, health=25, age_group="adult", mobility="trapped"),
        ],
        fire_spread_chance=0.38, start_oxygen=90,
    ),
]


def build_level_by_index(i):
    cfg = LEVELS[i % len(LEVELS)]
    grid = build_level(rooms_w=cfg["rooms_w"], rooms_h=cfg["rooms_h"], seed=cfg["seed"],
                        person_specs=cfg["person_specs"], fire_rooms=cfg["fire_rooms"])
    return grid, cfg