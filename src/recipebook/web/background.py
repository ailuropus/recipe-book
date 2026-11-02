"""Running a job's call off the request thread.

A plain daemon thread per job, not FastAPI's BackgroundTasks. Those run inside
the request's own ASGI call, behind the HTTP middleware, and work that is
bound to a connection is exactly what this exists to get away from: the whole
point is that the browser can go away and the call still finishes.

The thread opens its own session. The request's session has committed the job
row before the thread starts, and is closed by the time the call comes back.
"""

import logging
import threading
import uuid
from collections.abc import Callable

from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from recipebook.db import session_context
from recipebook.domain.jobs import fail, finish
from recipebook.models import Job
from recipebook.web.responses import see_other

log = logging.getLogger(__name__)

Work = Callable[[Session, Job], None]


def _thread(target: Callable[..., None], *args: object) -> None:
    threading.Thread(target=target, args=args, daemon=True).start()


# Swapped for a direct call in the tests, so a request has finished its job by
# the time it returns and nothing has to be waited on.
start: Callable[..., None] = _thread


def launch_and_redirect(session: Session, job: Job, work: Work) -> RedirectResponse:
    """Commit the job, start its work, and send the browser to wait on it.

    In that order. The thread reads the row from a session of its own, so the
    row has to be committed before the thread can look for it.
    """
    response = see_other(session, f"/jobs/{job.id}")
    start(_run, job.id, work)
    return response


def _run(job_id: uuid.UUID, work: Work) -> None:
    try:
        with session_context() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            work(session, job)
            finish(job)
    except Exception as exc:
        # Everything, not just the failures the call is known to raise: an
        # exception here has no request to surface in, and a job left running
        # is a waiting page that never stops waiting.
        log.exception("job %s failed", job_id)
        with session_context() as session:
            job = session.get(Job, job_id)
            if job is not None:
                fail(job, str(exc) or type(exc).__name__)
