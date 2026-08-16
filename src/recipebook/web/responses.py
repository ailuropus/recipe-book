"""Response helpers with the ordering guarantees this app needs."""

from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session


def see_other(session: Session, url: str) -> RedirectResponse:
    """Commit, then tell the browser where to go.

    The commit has to finish before the redirect is sent. FastAPI runs a
    yield-dependency's exit code after the response has left, so leaving the
    commit to the session dependency means the browser can be told to go and
    read a page before the write it just made has landed. A browser follows a
    303 in single-digit milliseconds, which is well inside that window.

    The symptom is a page showing its old content once, and being correct after
    a refresh — which reads like a caching problem and is not one.

    The dependency still commits afterwards; by then there is nothing to do.
    """
    session.commit()
    return RedirectResponse(url=url, status_code=303)
