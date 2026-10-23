"""
algorithms.py
BFS, A* and Hill Climbing operating on environment.Grid.

Every function returns a dict:
{
    "path": [(x,y), ...] or None,
    "explored": [(x,y), ...]   # cells visited, for visualization
    "cost": float or None,
    "name": str
}
"""

import heapq
import random
from collections import deque


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def reconstruct_path(came_from, start, goal):
    if goal not in came_from and goal != start:
        return None
    path = [goal]
    cur = goal
    while cur != start:
        cur = came_from[cur]
        path.append(cur)
    path.reverse()
    return path


# ---------------------------------------------------------------------------
# 1. BFS - shortest path in NUMBER OF STEPS, ignores fire/smoke cost.
#    Used to find nearest trapped person / nearest exit quickly.
# ---------------------------------------------------------------------------
def bfs(grid, start, goal):
    frontier = deque([start])
    came_from = {start: None}
    explored = []

    while frontier:
        current = frontier.popleft()
        explored.append(current)
        if current == goal:
            break
        for nxt in grid.neighbors(*current):
            if nxt not in came_from:
                came_from[nxt] = current
                frontier.append(nxt)

    path = reconstruct_path(came_from, start, goal) if goal in came_from else None
    return {"path": path, "explored": explored, "cost": len(path) - 1 if path else None,
            "name": "BFS"}


# ---------------------------------------------------------------------------
# 2. A* Search - optimal & safety-aware. f(n) = g(n) + h(n)
#    g(n): accumulated real cost (movement + fire penalty + smoke penalty)
#    h(n): Manhattan distance (admissible, since base move cost >= 1 >= weight)
# ---------------------------------------------------------------------------
def a_star(grid, start, goal, w_fire=5, w_smoke=2):
    counter = 0
    frontier = [(manhattan(start, goal), counter, start)]
    came_from = {start: None}
    g_score = {start: 0}
    explored = []

    while frontier:
        _, _, current = heapq.heappop(frontier)
        explored.append(current)
        if current == goal:
            break
        for nxt in grid.neighbors(*current):
            step = grid.step_cost(*nxt, w_fire=w_fire, w_smoke=w_smoke)
            tentative_g = g_score[current] + step
            if nxt not in g_score or tentative_g < g_score[nxt]:
                g_score[nxt] = tentative_g
                came_from[nxt] = current
                f = tentative_g + manhattan(nxt, goal)
                counter += 1
                heapq.heappush(frontier, (f, counter, nxt))

    path = reconstruct_path(came_from, start, goal) if goal in came_from else None
    cost = g_score.get(goal)
    return {"path": path, "explored": explored, "cost": cost, "name": "A*"}


# ---------------------------------------------------------------------------
# 3. Hill Climbing - greedily steps to the neighbor that most reduces
#    Manhattan distance to goal. No backtracking -> can get stuck
#    (local maximum / dead end). Demonstrates the weakness of pure local search.
# ---------------------------------------------------------------------------
def hill_climbing(grid, start, goal, max_steps=500):
    current = start
    path = [current]
    explored = [current]
    visited = {current}

    for _ in range(max_steps):
        if current == goal:
            break
        neighbors = list(grid.neighbors(*current))
        candidates = [n for n in neighbors if n not in visited]
        if not candidates:
            break  # stuck: local maximum / dead end, no unvisited move improves us
        best = min(candidates, key=lambda n: manhattan(n, goal))
        if manhattan(best, goal) >= manhattan(current, goal):
            break  # no neighbor improves the heuristic -> stuck at local optimum
        current = best
        visited.add(current)
        path.append(current)
        explored.append(current)

    success = current == goal
    return {"path": path if success else None, "explored": explored,
            "cost": len(path) - 1 if success else None,
            "name": "Hill Climbing", "stuck_at": None if success else current}


ALGORITHMS = {
    "1": bfs,
    "2": a_star,
    "3": hill_climbing,
}

ALGORITHM_LABELS = {
    "1": "BFS",
    "2": "A* Search",
    "3": "Hill Climbing",
}