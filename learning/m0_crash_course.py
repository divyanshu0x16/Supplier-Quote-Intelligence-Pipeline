"""M0 crash-course exercises (type hints, dataclass vs Pydantic, context managers).

Run: uv run python learning/m0_crash_course.py
"""


def cheapest(quotes: list[tuple[str, float]]) -> str | None:
    """Given a list of (supplier_name, unit_price) pairs, return the
    supplier name with the lowest price, or None if the list is empty.

    >>> cheapest([("Acme", 4.10), ("Globex", 3.95), ("Initech", 5.00)])
    'Globex'
    >>> cheapest([])  # returns None
    """
    if not quotes:
        return None
    name, _ = min(quotes, key=lambda p: p[1])
    return name


# ---------------------------------------------------------------------------
# Exercise 2: dataclass vs Pydantic
# ---------------------------------------------------------------------------
from dataclasses import dataclass  # noqa: E402  (imports normally go at the top)
from pydantic import BaseModel, Field, ValidationError # noqa: E402

@dataclass
class QuoteDC:
    supplier: str
    unit_price: float
    moq: int | None = None

class QuoteModel(BaseModel):
    supplier: str
    unit_price: float = Field(gt=0)
    moq: int | None = None

def demo() -> None:
    print(QuoteDC("Acme", "4.10"))
    print(QuoteDC("Acme", -1))
    print(QuoteDC("Acme", "banana"))
    try:
        print(QuoteModel(supplier="Acme", unit_price="4.10"))
    except ValidationError as e:
        print(e)
    try:
        print(QuoteModel(supplier="Acme", unit_price=1))
    except ValidationError as e:
        print(e)
    try:
        print(QuoteModel(supplier="Acme", unit_price="banana"))
    except ValidationError as e:
        print(e)


# ---------------------------------------------------------------------------
# Exercise 3: context managers
# ---------------------------------------------------------------------------
import time  # noqa: E402
from collections.abc import Generator  # noqa: E402
from contextlib import contextmanager  # noqa: E402


@contextmanager
def timed(label: str) -> Generator[None, None, None]:
    """Print how long the `with` block took, e.g. "parse_pdf took 12.3 ms".
    Must print even if the block raises an exception.
    (We'll use this exact pattern in M3 to log LLM latency.)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        print(f"{label} took {elapsed * 1000:.1f} ms")


def demo_timed() -> None:
    with timed("sleep"):
        time.sleep(1)

    try:
        with timed("divide"):
            1/0
    except ZeroDivisionError:
        print("caught the error")


if __name__ == "__main__":
    print(cheapest([("Acme", 4.10), ("Globex", 3.95), ("Initech", 5.00)]))  # Globex
    print(cheapest([]))  # None
    demo()
    demo_timed()
