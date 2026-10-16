"""Demo launch-plan room: a fixed team memory (main + planner + scheduler) for the demo and the UI.

Fixed fact ids (`seed-<entity>-<predicate>`) make the room the same on every run, so the demo can
point at `seed-launch-deadline` and expect the same dependents every time.
"""

from git0.core.models import CommitRequest, Derivation, Episode, NewFact
from git0.core.repo import MemoryRepo

BRANCHES = ["main", "planner", "scheduler"]
LAUNCH_DEADLINE = "seed-launch-deadline"
KICKOFF = "Kickoff: launch plan"
SCHEDULE = "Book the venue and send invites for Friday"

# (entity, predicate, value). One value per (entity, predicate): a commit holds one value per key.
MAIN_FACTS: list[tuple[str, str, str]] = [
    ("launch", "deadline", "friday"),
    ("launch", "owner", "asha"),
    ("launch", "location", "hall b"),
    ("launch", "budget", "50000 inr"),
    ("website", "deadline", "wednesday"),
    ("website", "owner", "ravi"),
    ("website", "status", "in review"),
    ("website", "depends_on", "press_kit"),
    ("press_kit", "deadline", "thursday"),
    ("press_kit", "owner", "mei"),
    ("press_kit", "status", "draft"),
    ("press_kit", "location", "shared drive"),
    ("qa", "deadline", "wednesday"),
    ("qa", "owner", "tomas"),
    ("qa", "status", "in progress"),
    ("qa", "depends_on", "beta"),
    ("beta", "deadline", "tuesday"),
    ("beta", "owner", "priya"),
    ("beta", "status", "recruiting"),
    ("beta", "contact", "priya on slack"),
    ("docs", "owner", "leo"),
    ("docs", "status", "outline"),
    ("docs", "deadline", "thursday"),
    ("demo_video", "owner", "sam"),
    ("demo_video", "status", "script approved"),
    ("demo_video", "budget", "12000 inr"),
    ("demo_video", "deadline", "thursday"),
    ("social", "owner", "nadia"),
    ("social", "status", "calendar drafted"),
    ("social", "preference", "short posts, no hashtag spam"),
    ("sponsors", "owner", "dev"),
    ("sponsors", "budget", "30000 inr"),
    ("sponsors", "status", "three in talks"),
    ("swag", "budget", "8000 inr"),
    ("swag", "decision", "tote bags over tees"),
    ("caterer_shortlist", "status", "three quotes in"),
    ("caterer_shortlist", "budget", "15000 inr"),
]

# Written on `scheduler`; each one is derived from the launch deadline it is scheduled around.
SCHEDULER_FACTS: list[tuple[str, str, str]] = [
    ("venue", "status", "booked friday"),
    ("invites", "status", "sent for friday"),
    ("catering", "deadline", "thursday"),
]


def _fact(entity: str, predicate: str, value: str) -> NewFact:
    return NewFact(id=_fact_id(entity, predicate), s=entity, p=predicate, o=value)


def _fact_id(entity: str, predicate: str) -> str:
    return f"seed-{entity}-{predicate}".replace("_", "-")


async def seed(repo: MemoryRepo) -> dict:
    await repo.init()
    try:
        await repo.head("scheduler")
        created = False
    except KeyError:
        # The scheduler branch is what marks a seeded room, so a second call writes nothing.
        await _write_room(repo)
        created = True
    return {
        "created": created,
        "branches": BRANCHES,
        "facts_on_main": len(await repo.checkout("main")),
        "facts_on_scheduler": len(await repo.checkout("scheduler")),
    }


async def _write_room(repo: MemoryRepo) -> None:
    await repo.commit(
        CommitRequest(
            branch="main",
            agent_id="planner",
            msg=KICKOFF,
            kind="seed",
            facts=[_fact(*f) for f in MAIN_FACTS],
            episodes=[Episode(id="seed-ep-main", text=KICKOFF, session_id="seed")],
        )
    )
    await repo.create_branch("planner", from_branch="main")
    await repo.create_branch("scheduler", from_branch="main")
    await repo.commit(
        CommitRequest(
            branch="scheduler",
            agent_id="scheduler",
            msg=SCHEDULE,
            kind="seed",
            facts=[_fact(*f) for f in SCHEDULER_FACTS],
            derived=[Derivation(child=_fact_id(e, p), parent=LAUNCH_DEADLINE) for e, p, _ in SCHEDULER_FACTS],
            episodes=[Episode(id="seed-ep-scheduler", text=SCHEDULE, session_id="seed")],
        )
    )
