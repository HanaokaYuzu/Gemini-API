"""Optional, application-owned request attestation without browser dependencies."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .exceptions import AttestationError


@dataclass(frozen=True, repr=False)
class AttestationRequest:
    """Exact outgoing prompt and conversation/parent IDs for one request attempt.

    ``rid`` and ``rcid`` are the parent response and candidate IDs (the browser's
    ``prqid`` and ``prsid``). New conversations use empty IDs. Providers must bind
    the proof to these values and a fresh nonce; they must not cache proofs.
    """

    prompt: str
    cid: str
    rid: str
    rcid: str


@dataclass(frozen=True, repr=False)
class Attestation:
    """Opaque proof and its matching, fresh 32-character lowercase hex nonce."""

    proof: str
    nonce: str


AttestationProvider = Callable[[AttestationRequest], Awaitable[Attestation]]


async def get_attestation(
    provider: AttestationProvider, request: AttestationRequest
) -> Attestation:
    """Validate provider output without exposing proofs or provider error details."""
    try:
        result = await provider(request)
        if (
            not isinstance(result, Attestation)
            or not isinstance(result.proof, str)
            or not result.proof.startswith("!")
            or len(result.proof) < 2
            or any(char.isspace() for char in result.proof)
            or not isinstance(result.nonce, str)
            or re.fullmatch(r"[0-9a-f]{32}", result.nonce) is None
        ):
            raise ValueError
    except Exception:
        raise AttestationError(
            "Request attestation failed; no generation request was sent."
        ) from None
    return result
