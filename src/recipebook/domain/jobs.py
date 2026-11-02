"""Slow model calls, and what became of them.

An import or a revision is a minute of waiting on the model. The form post
writes a job row and returns at once; the call runs on the server, and its
result is written to the row whether or not a browser is still watching. This
module is the row's life:

  running   the call is in flight
  done      the result is stored — a revision row, or an import's recipe doc
  failed    the call came back with nothing, and `error` says why

A job is *closed* once someone has dealt with it: the import was saved or
discarded, the failure was dismissed. Revise jobs are never closed here — the
revision's own status already says whether it has been decided, and two
records of one fact drift apart.

Everything done-but-not-dealt-with is listed on the index. That is the whole
answer to "I closed the tab": the work is not lost, it is waiting there.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from recipebook.models import Job, Revision

INTERRUPTED = (
    "The server restarted while this was running, so the answer never arrived. "
    "Nothing was saved. Try again."
)


def start_job(session: Session, *, kind: str, text: str, recipe_id: uuid.UUID | None = None) -> Job:
    """Write the row a call will report back to, and flush so it has an id."""
    job = Job(kind=kind, status="running", input=text, recipe_id=recipe_id)
    session.add(job)
    session.flush()
    return job


def finish(job: Job) -> None:
    job.status = "done"
    job.finished_at = datetime.now(UTC)


def fail(job: Job, message: str) -> None:
    job.status = "failed"
    job.error = message
    job.finished_at = datetime.now(UTC)


def close(job: Job) -> None:
    """Dealt with. Idempotent, so a back button and a second press is harmless."""
    if job.closed_at is None:
        job.closed_at = datetime.now(UTC)


def interrupt_running(session: Session) -> int:
    """Fail every job still marked running. For startup only.

    The call runs on a thread inside the server process, so a restart takes it
    with it and nothing will ever finish the row. Without this the waiting page
    would wait forever. It assumes one server process, which is how this app
    runs: with several, one starting up would fail jobs another is still
    working on.
    """
    jobs = list(session.scalars(select(Job).where(Job.status == "running")))
    for job in jobs:
        fail(job, INTERRUPTED)
    return len(jobs)


def result_url(job: Job) -> str | None:
    """Where a finished job's result is reviewed, or None while there is none."""
    if job.status != "done":
        return None
    if job.kind == "revise" and job.revision_id is not None:
        return f"/revisions/{job.revision_id}"
    if job.kind == "import":
        return f"/imports/{job.id}"
    return None


def waiting(session: Session) -> list[Job]:
    """Everything still in flight or still needing a decision, newest first.

    A finished revise job stays listed exactly as long as its revision is
    pending; deciding it on the review screen is what takes it off.
    """
    statement = (
        select(Job)
        .outerjoin(Revision, Revision.id == Job.revision_id)
        .where(Job.closed_at.is_(None))
        .where(
            or_(
                Job.status != "done",
                Job.kind == "import",
                and_(Job.kind == "revise", Revision.status == "pending"),
            )
        )
        .order_by(Job.created_at.desc())
    )
    return list(session.scalars(statement))
