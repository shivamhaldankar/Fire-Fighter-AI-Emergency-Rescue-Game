"""
expert_system.py
Forward-chaining rule-based inference for rescue priority decisions,
plus a small propositional-resolution trace for safety reasoning.

This is a simplified, self-contained stand-in for a Prolog-style expert
system: facts are asserted, rules fire, conclusions are derived and logged.
"""

from algorithms import manhattan


def fire_distance(grid, pos):
    """Distance from pos to the nearest burning cell (Manhattan, capped scan)."""
    best = None
    for y in range(grid.height):
        for x in range(grid.width):
            if grid.fire[y][x] > 0:
                d = manhattan(pos, (x, y))
                if best is None or d < best:
                    best = d
    return best if best is not None else 999


class ExpertSystem:
    """Forward-chaining rule engine over Person + Firefighter facts."""

    def __init__(self, grid):
        self.grid = grid
        self.trace = []  # human-readable log of fired rules / resolved facts

    def log(self, msg):
        self.trace.append(msg)

    # -----------------------------------------------------------------
    # Rule base (priority-ordered). Each rule: condition -> conclusion
    # -----------------------------------------------------------------
    def evaluate_person(self, person, firefighter_oxygen, log=True):
        facts = {
            "health": person.health,
            "age_group": person.age_group,
            "mobility": person.mobility,
            "fire_distance": fire_distance(self.grid, person.pos()),
        }
        priority = "LOW"
        reasons = []

        # R1: critical health + trapped
        if facts["health"] < 30 and facts["mobility"] == "trapped":
            priority = "CRITICAL"
            reasons.append("R1: health<30 AND trapped -> CRITICAL")

        # R2: child near fire
        if facts["age_group"] == "child" and facts["fire_distance"] < 3:
            priority = "CRITICAL"
            reasons.append("R2: child AND fire_distance<3 -> CRITICAL")

        # R3: fire closing in fast
        if priority != "CRITICAL" and facts["fire_distance"] < 2:
            priority = "HIGH"
            reasons.append("R3: fire_distance<2 -> HIGH (rescue window closing)")

        # R4: mobile and far from fire -> can likely self-evacuate
        if priority == "LOW" and facts["mobility"] == "mobile" and facts["fire_distance"] > 5:
            priority = "LOW"
            reasons.append("R4: mobile AND fire_distance>5 -> LOW (can self-evacuate)")
        elif priority == "LOW":
            priority = "MEDIUM"
            reasons.append("default: trapped, no acute trigger -> MEDIUM")

        if log:
            self.log(f"[{person.id}] facts={facts} => priority={priority}")
            for r in reasons:
                self.log(f"   fired {r}")

        return priority, facts

    def rank_targets(self, firefighter_oxygen, carrying=False):
        """
        R5: low oxygen overrides all rescues -> return to exit.
        R7: among multiple CRITICAL targets, break tie by real path cost (A*),
            not evaluated here (handled by caller after ranking).
        R8: already carrying a survivor -> ignore new targets, head to exit.
        R9: a person whose current cell is on fire is flagged URGENT -
            every tick of delay risks losing them (see Grid.apply_fire_damage_to_persons).
        Returns (action, ranked_list, trace) where ranked_list is EVERY
        living unrescued person in priority order (not just the top pick),
        so the UI can render a full triage board.
        """
        self.trace.clear()
        order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        results = []

        if carrying:
            self.log("R8: firefighter already carrying a survivor -> action(DELIVER_TO_EXIT)")
            return "DELIVER_TO_EXIT", [], list(self.trace)

        if firefighter_oxygen < 20:
            self.log("R5: firefighter.oxygen < 20 -> action(RETURN_TO_EXIT) [overrides rescue]")
            return "RETURN_TO_EXIT", [], list(self.trace)

        for p in self.grid.living_unrescued_persons():
            priority, facts = self.evaluate_person(p, firefighter_oxygen)
            on_fire_now = self.grid.fire[p.y][p.x] > 0
            if on_fire_now and priority != "CRITICAL":
                priority = "CRITICAL"
                self.log(f"R9: {p.id} standing in active fire -> escalated to CRITICAL")
            results.append((p, priority, facts))

        results.sort(key=lambda r: (order[r[1]], fire_distance(self.grid, r[0].pos())))

        if not self.grid.exits:
            self.log("R6: no exit registered -> action(ALERT_NO_SAFE_EXIT)")

        if len(results) >= 2 and results[0][1] == results[1][1] == "CRITICAL":
            self.log("R7: multiple CRITICAL targets -> RESCUE_NEAREST_FIRST (break tie via A* cost)")

        if not results:
            return "NONE", [], list(self.trace)

        return "RESCUE", results, list(self.trace)

    # -----------------------------------------------------------------
    # Propositional resolution demo: derive whether a cell is safely
    # enterable from base clauses about fire/smoke/visibility.
    #   ¬safe(x,y) v passable(x,y)
    #   fire_intensity>8 -> ¬safe(x,y)
    #   smoke_density>8 -> ¬visibility(x,y)
    #   ¬visibility(x,y) ^ trapped_person_here -> requires(thermal_sensor)
    # -----------------------------------------------------------------
    def resolve_cell_safety(self, x, y):
        clauses_fired = []
        fire_i = self.grid.fire[y][x]
        smoke_d = self.grid.smoke[y][x]

        safe = True
        if fire_i > 8:
            safe = False
            clauses_fired.append(f"fire_intensity({x},{y})={fire_i} > 8  =>  ¬safe({x},{y})")

        visible = True
        if smoke_d > 8:
            visible = False
            clauses_fired.append(f"smoke_density({x},{y})={smoke_d} > 8  =>  ¬visibility({x},{y})")

        requires_sensor = False
        person_here = any(p.pos() == (x, y) and not p.rescued for p in self.grid.persons)
        if not visible and person_here:
            requires_sensor = True
            clauses_fired.append(
                f"¬visibility({x},{y}) ^ trapped_person({x},{y}) => requires(thermal_sensor)")

        clauses_fired.append(f"¬safe({x},{y}) v passable({x},{y})  [base clause]")

        conclusion = {
            "safe": safe,
            "visible": visible,
            "requires_thermal_sensor": requires_sensor,
        }
        return conclusion, clauses_fired