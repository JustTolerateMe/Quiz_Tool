# project-starter

A universal foundation for every project. Clone → fill in 5 fields → start building.

Designed around one principle: **Claude should spend zero tokens figuring out what the project is, where things live, or what patterns to follow.** All of that is pre-answered.

---

## How to use

```bash
# 1. Copy this to your new project
cp -r project-starter/ my-new-project/
cd my-new-project/

# 2. Run setup (replaces [PROJECT_NAME] everywhere, inits git)
bash scripts/setup.sh

# 3. Fill in the 5 things that matter before writing any code:
#    PRD.md        → problem + requirements
#    ARCHITECTURE.md → stack + structure
#    CLAUDE.md     → commands + patterns
#    DEVLOG.md     → already initialised
#    .claudeignore → already complete
```

---

## What each file does and why it exists

### `CLAUDE.md` — Session instructions
Claude reads this at the start of every session. Tells it what the project is, where things live, what commands to run, and what patterns to follow. Keeps every session focused without re-explaining context.

**Fill in:** stack, directory structure, build commands, project-specific patterns.
**Keep under 200 lines** — longer degrades Claude's instruction-following.

### `PRD.md` — What we're building
Written before any code. Defines the problem, requirements (MoSCoW), what's explicitly out of scope, build order, and open questions. Claude reads this to understand intent, not just implementation.

**Fill in:** problem statement, requirements, build order.
**Update when scope changes** — don't let it go stale.

### `ARCHITECTURE.md` — How we're building it
Stack decisions with rationale, directory structure, data flow, module boundaries, known constraints, and anti-patterns. Claude uses this instead of guessing conventions.

**Fill in:** stack table, directory tree, key decisions as you make them.
**Update when you make a non-obvious technical call.** This is where "we use X because Y" lives.

### `DEVLOG.md` — Running changelog
One entry per session. Claude reads the last 3 entries at session start instead of re-reading all previous files. Replaces "what did we build last time?" entirely.

**Format is fixed** — don't change it. Consistency makes it scannable.
**Append at the top.** Newest first.

### `.claudeignore` — What Claude should never read
Covers: `node_modules`, `dist`, lock files, binary assets, logs, secrets, IDE noise. Already comprehensive. Prevents wasted reads on files that add no signal.

**Edit if:** your stack has unusual generated directories. Otherwise leave it alone.

### `.claude/settings.json` — Permissions
Auto-approves safe commands (npm, pip, git status/diff/log). Blocks destructive ones (git push, rm -rf). Adjust to match your trust level.

### `.claude/memory/MEMORY.md` — Cross-session learning
Claude writes here automatically when it learns something non-obvious. Builds up over time. Don't edit manually unless removing stale entries.

---

## Token savings this foundation delivers

| Without template | With template |
|-----------------|---------------|
| Claude reads 8-10 files to understand project structure | Reads 3 files (CLAUDE.md + PRD.md + DEVLOG last entries) |
| Re-explains stack preferences every session | Encoded in CLAUDE.md permanently |
| Claude reads node_modules looking for context | `.claudeignore` blocks it entirely |
| Guesses architectural patterns | ARCHITECTURE.md states them explicitly |
| Makes wrong assumptions about requirements | PRD.md answers intent before code starts |
| DEVLOG missing — re-reads entire codebase | 3 DEVLOG entries = full context in ~400 tokens |

Rough estimate: **50-70% reduction in context-building tokens per session** on a mid-size project.

---

## When to add Graphify

When your codebase hits ~30 source files, run:

```bash
pip install graphifyy
/graphify ./src
```

This generates a knowledge graph. Instead of reading 10 files to answer "what uses storageService?", you query the graph. Most useful for:
- Navigation queries ("where is X used?", "what depends on Y?")
- Starting a session on a large, stable codebase
- Cross-module impact analysis before a refactor

**Not useful for:** active development on small projects, or when you need to read actual file content to edit it.

---

## The PRD.md and ARCHITECTURE.md question

**"What's universal about them if every project is different?"**

The *structure* is universal. The *content* is specific. Every project needs:
- PRD: a problem statement, MoSCoW requirements, explicit out-of-scope, build order, risks
- ARCHITECTURE: a stack table with rationale, directory structure, data flow, module boundaries, known gotchas

What changes is what you fill in. What stays constant is the shape — which means Claude always knows where to find what it needs.

**PRD gives Claude intent.** Without it, Claude optimises for plausibility ("this is how apps usually work") instead of your actual requirements.

**ARCHITECTURE gives Claude constraints.** Without it, Claude makes decisions based on common patterns, not your specific choices. It will use `.then()` chains, put logic in components, and pick the obvious library instead of the one you already have.

---

## Recommended workflow per project

1. **Copy template** → run `setup.sh`
2. **Write PRD.md first** — 20 minutes, before any code
3. **Write ARCHITECTURE.md stack section** — stack + directory structure + first key decision
4. **Update CLAUDE.md** — commands for this stack
5. **Start building** — Claude now has full context from line 1
6. **Every session:** Claude reads CLAUDE.md → PRD.md → ARCHITECTURE.md → last 3 DEVLOG entries
7. **Every session end:** Claude updates DEVLOG
8. **As you make decisions:** Add them to ARCHITECTURE.md Key Decisions section
9. **At ~30 files:** Run graphify, add to workflow

---

## Adapts to any stack

This template is stack-agnostic. It's been used with:
- React + Vite (PWA, local-first)
- Python + FastAPI
- Next.js + Supabase
- Go + htmx
- Electron desktop apps

The only change per stack is what you fill into the placeholder sections.
