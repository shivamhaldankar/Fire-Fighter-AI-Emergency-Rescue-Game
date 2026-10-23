# 🔥 Firefighter AI: Intelligent Emergency Rescue Game

A grid-based emergency rescue simulation demonstrating **8 classic AI search &
reasoning techniques** on a genuine problem: finding safe, efficient rescue
routes through a building as fire and smoke spread dynamically.

## Setup

```bash
pip install pygame
python3 main.py
```

Requires Python 3.9+.

## Controls

| Key | Action |
|---|---|
| `1`–`6` | Select algorithm (see table below) |
| `SPACE` | Ask the Expert System for the next rescue priority, then plan + move to it with the selected algorithm |
| `R` | Reset simulation |
| `F` | Toggle automatic fire spreading on/off |
| `ESC` | Quit |

## Project structure

```
environment.py     Grid world: walls, fire, smoke, persons, exits, fire-spread simulation
algorithms.py       BFS, DFS, Best-First, Hill Climbing, Random-Restart HC, A*
expert_system.py    Forward-chaining rule engine + propositional resolution trace
main.py             Pygame app: rendering, input, animation, game loop
```

## Algorithms → code map

| # | Algorithm | Function | Role |
|---|---|---|---|
| 1 | BFS | `algorithms.bfs` | Shortest path in steps, ignores fire/smoke cost |
| 2 | DFS | `algorithms.dfs` | Explore rooms / connectivity checking |
| 3 | Best-First Search | `algorithms.best_first_search` | Fast greedy route using only the heuristic |
| 4 | Hill Climbing | `algorithms.hill_climbing` | Greedy local descent — deliberately gets stuck at dead ends/local maxima (try it against a target that requires a detour) |
| 5 | Random-Restart Hill Climbing | `algorithms.random_restart_hill_climbing` | Retries from randomized reachable points to escape local maxima |
| 6 | A* | `algorithms.a_star` | Optimal, safety-aware route: `f(n) = g(n) + h(n)` |
| 7 | Expert System (rule-based) | `expert_system.ExpertSystem.rank_targets` | Decides *who* to rescue first and *when* to abort for oxygen |
| 8 | Resolution | `expert_system.ExpertSystem.resolve_cell_safety` | Propositional-logic derivation of cell safety/visibility |

## A* cost function

```
f(n) = g(n) + h(n)

g(n) = g(n-1) + 1 + fire_intensity(n)/10 * W_FIRE + smoke_density(n)/10 * W_SMOKE
h(n) = manhattan_distance(n, goal)          # admissible: never overestimates
```

Fire above intensity 8 is **impassable**. Below that threshold it's passable
but heavily penalized, and smoke adds a smaller penalty — mirroring real
triage logic (smoke slows you down, fire can kill you).

## Expert System rule base (forward chaining)

| Rule | Condition | Conclusion |
|---|---|---|
| R1 | health < 30 AND trapped | priority = CRITICAL |
| R2 | child AND fire_distance < 3 | priority = CRITICAL |
| R3 | fire_distance < 2 | priority = HIGH |
| R4 | mobile AND fire_distance > 5 | priority = LOW (can self-evacuate) |
| R5 | firefighter oxygen < 20 | action = RETURN_TO_EXIT (overrides rescue) |
| R6 | no safe exit reachable | action = ALERT_NO_SAFE_EXIT |
| R7 | multiple CRITICAL targets | break tie by nearest (A* cost) |

The rule trace is displayed live in the bottom-right panel each time you
press `SPACE`, so you can see exactly which facts and rules fired.

## Dynamic replanning

Fire spreads automatically every ~1.8s (toggle with `F`). If a previously
planned route becomes blocked (fire intensity reaches the impassable
threshold on a path cell), the firefighter automatically **replans** with
the currently selected algorithm — this is what makes the "dynamically
changing environment" claim real rather than cosmetic.

## Suggested demo flow for evaluation

1. Press `4` (Hill Climbing), then `SPACE` — watch it get stuck at a dead
   end/local maximum in the maze.
2. Press `5` (Random-Restart Hill Climbing), then `SPACE` — same target,
   now it escapes the local maximum via a randomized restart.
3. Press `6` (A*), then `SPACE` — compare path cost/length against BFS (`1`)
   on the same target: BFS finds *a* shortest-step path but may walk
   through smoke/fire; A* avoids it.
4. Leave auto-fire on and watch a route get cut off mid-traversal, forcing
   a live replan.
5. Let all "trapped" persons get rescued, then watch rule R4 classify the
   last "mobile" survivor as LOW priority instead of triggering a rescue.

## Possible extensions

- Swap the periodic full replan for **D\*** (incremental replanning) for
  efficiency at scale.
- Add **Simulated Annealing** alongside Hill Climbing as a probabilistic
  local-search comparison.
- Log every Expert System decision + Resolution trace to a file for a
  written report appendix.
