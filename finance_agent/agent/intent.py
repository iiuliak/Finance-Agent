import re
from collections.abc import Sequence

# A refusal wins over a transfer word later in the same message.
_NO = re.compile(
    r"\b(?:don't|do not|dont|never mind|stop|cancel|no thanks)\b|^no\b",
    re.IGNORECASE,
)

# Direct requests, including the demo question and a few typos and German verbs.
# "move" counts only next to a money word, so "move house" does not.
_TRANSFER = re.compile(
    r"\b(?:transfer|trasfer|tranfer|trnsfer|überweis\w*|ueberweis\w*|umbuch\w*)\b"
    r"|\b(?:move|moove)\b(?:\W+\w+){0,8}\W+\b(?:reserve|vat|tax|money|cash|aside|asside)\b"
    r"|\b(?:reserve|vat|tax)\b(?:\W+\w+){0,8}\W+\b(?:move|moove)\b"
    r"|\b(?:set|put)\b(?:\W+\w+){0,6}\W+\b(?:aside|asside)\b"
    r"|\b(?:zurückleg\w*|zurueckleg\w*|beiseite)\b"
    r"|\bhow\s+much\s+should\s+i\s+(?:move|transfer|set)\b"
    r"|\bproposal\b",
    re.IGNORECASE,
)

_YES = re.compile(
    r"^(?:yes|yeah|yep|yup|ok|okay|sure|please|do it|go ahead|just do it|"
    r"sounds good|i'?d like that|let'?s do it|lets do it|do that)\b",
    re.IGNORECASE,
)

# The previous reply offered a transfer, so a short "yes" is the request.
_OFFERED = re.compile(
    r"\b(?:shall i|would you like|if you(?:'d| would) like|set it aside|set aside|transfer|prepare)\b",
    re.IGNORECASE,
)


def refuses_transfer(message: str) -> bool:
    """True when the user is telling the assistant not to move money."""
    return _NO.search(message.strip()) is not None


def wants_transfer(message: str, history: Sequence[tuple[str, str]] = ()) -> bool:
    """True when this turn is asking for a reserve transfer, not merely for figures."""
    text = message.strip()
    if _NO.search(text):
        return False
    if _TRANSFER.search(text):
        return True
    if _YES.search(text):
        for role, earlier in reversed(history):
            if role == "assistant":
                return _OFFERED.search(earlier) is not None
    return False
