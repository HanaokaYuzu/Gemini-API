from pydantic import BaseModel


class Citation(BaseModel):
    """A web source backing one of the `[cite: N]` markers in a reply.

    Citations are not a deep research feature - an ordinary chat turn can carry them too,
    though only sometimes: most grounded answers cite nothing, so an empty list is the
    common case rather than a sign of a parsing failure. Research reports are where they
    turn up reliably. Whenever markers are present the sources are published separately,
    so without resolving them the markers are dead references - the reply text never names
    what it cites.

    Parameters
    ----------
    id: `int`
        The number used by the `[cite: N]` markers that refer to this source.
    title: `str`, optional
        Title of the page, as Gemini reports it.
    url: `str`, optional
        Address of the page.
    favicon: `str`, optional
        Icon for the site, when one is supplied.

    """

    id: int
    title: str | None = None
    url: str | None = None
    favicon: str | None = None

    def __repr__(self) -> str:
        return f"Citation(id={self.id!r}, title={self.title!r}, url={self.url!r})"

    def __str__(self) -> str:
        return f"[{self.id}] {self.title or self.url or ''}".strip()
