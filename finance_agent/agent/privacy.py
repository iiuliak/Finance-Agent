import re

# A withheld turn is replaced by this in later history. It is not the user's text.
PERSONAL_INFORMATION = "personal_information"
PERSONAL_INFORMATION_REPLY = (
    "Your message contains personal information (e.g., a name, surname, IBAN, "
    "email, or phone number). Please remove it from your message."
)

_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+\s*@\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
_IBAN = re.compile(
    r"\b[A-Z]{2}\s?\d{2}(?:\s?[A-Z0-9]){11,30}\b",
    re.IGNORECASE,
)
_IBAN_WORD = re.compile(r"\biban\b", re.IGNORECASE)
# "IBAN 676767676767" has no country code, so it is not a formal IBAN, but it is still one.
_IBAN_NUMBER = re.compile(
    r"\biban\b(?:\W+\w+){0,4}\W+\d(?:[\s-]*\d){5,}",
    re.IGNORECASE,
)
_MONEY = re.compile(
    r"€\s?\d[\d.,]*|\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?\b|\b\d+[.,]\d{2}\b"
)
_DATE = re.compile(r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b")
_PHONE = re.compile(r"(?<!\w)\+?\d(?:[\s()./-]*\d){7,}(?!\w)")
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß'’-]+")
_LABELED_NAME = re.compile(
    r"\b(?:my name is|my surname is|my last name is|my first name is|my family name is|"
    r"mein name ist|ich heiße|ich heisse|"
    r"nachname|familienname|vorname|surname|last name|first name|family name)"
    r"\s*[:\-]?\s*([A-Za-zÄÖÜäöüß'’-]+)",
    re.IGNORECASE,
)
_I_AM = re.compile(
    r"\b(?:i am|i'm|this is|ich bin)\s+([A-Za-zÄÖÜäöüß'’-]+)",
    re.IGNORECASE,
)

# Title-case words that show up in ordinary questions. They are not treated as a name.
_ORDINARY = frozenset(
    """
    how what which when where why who please the this that these those can could would
    should shall will may might must let yes no thank thanks hello dear and but for from
    into with your our not much many move moove set put transfer proposal invoice invoices
    expense expenses operating account quarter input estimated balance reserve tax vat
    unpaid paid books house aside asside money cash euro euros open new old pending exactly
    good morning evening night today tomorrow
    previous instructions approve review december november october september august july
    june may april march february january monday tuesday wednesday thursday friday saturday
    sunday wie viel soll ich auf die der das den dem nicht keine rücklage ruecklage
    umsatzsteuer mehrwertsteuer rechnung ausgabe quartal überweisen ueberweisen beiseite
    """.split()
)
# A following word that means a sentence-initial capital is ordinary English, not a name.
_FUNCTION = frozenset(
    """
    the a an to of in on for and or but my your our is are was be do does did can could
    should would will shall may might must with from into at by if then that this these
    those it we he she they how what which when where why who much many please not no
    """.split()
)
_STOP = _ORDINARY | _FUNCTION | frozenset(
    "a an of on is was to for and or my me in at by it as if be do we he so no not field here there you are due owe".split()
)

_GIVEN = frozenset(
    """
    ada adam alex alexander alexandra alice amy andrea andreas andrew angela anna anne
    annette anthony anton antonio arthur barbara benjamin bernd bettina birgit brigitte
    carl carla carlo carmen caroline catherine charles charlotte christian christina
    christine christopher claudia daniel daniela david diana dieter dirk doris edward
    elena elisabeth elizabeth emma eric erik erika eva felix florian franz franziska
    friedrich gabriel georg george hanna hannah hans heike heinrich helga helmut henry
    ina ingrid irene jack jacob jakob james jane jasmin jennifer jessica joachim johann
    johanna john jonas jonathan julia julian juliane julie julius jürgen juergen iuliia
    yuliia katharina kathrin klaus laura lena leo leon linda lisa lucas luca luisa lukas
    luna magdalena manfred manuel marco marcus margarete maria marie mario markus martin
    mary matthias maximilian melanie michael michelle mike monika nadine natalie nicole
    nina oliver olivia oscar patrick paul paula peter petra philipp philip pia rachel
    ralf ralph rebecca renate richard robert sabine samuel sandra sarah sebastian simon
    sofia sophia sophie stefan stefanie stephanie susan susanne thomas tobias tom ursula
    ute vanessa vera verena victoria werner william wolfgang yvonne
    """.split()
)
_SURNAMES = frozenset(
    """
    müller mueller schmidt schneider fischer weber meyer wagner becker hoffmann schulz
    richter zimmermann krüger krueger hofmann hartmann schmitt krause meier lehmann
    schmid schulze maier herrmann huber scholz berger keller lovelace
    """.split()
)


def contains_personal_information(text: str) -> bool:
    """True when the text has a name, surname, email, IBAN, or phone number.

    Ordinary questions about VAT, amounts, and dates are not personal information.
    A lowercase given name with no label such as "my name is" is not detected.
    """
    if _EMAIL.search(text) or _has_iban(text) or _has_phone(text):
        return True
    if _labeled_name(text) or _introduces_self(text):
        return True
    return _has_name(text)


def _has_iban(text: str) -> bool:
    if _IBAN_NUMBER.search(text):
        return True
    labeled = _IBAN_WORD.search(text) is not None
    for match in _IBAN.finditer(text):
        compact = re.sub(r"\s+", "", match.group()).upper()
        if not 15 <= len(compact) <= 34:
            continue
        if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", compact):
            continue
        if labeled or _iban_checksum(compact):
            return True
    return False


def _iban_checksum(compact: str) -> bool:
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def _has_phone(text: str) -> bool:
    stripped = _DATE.sub(" ", _MONEY.sub(" ", text))
    for match in _PHONE.finditer(stripped):
        digits = re.sub(r"\D", "", match.group())
        if match.group().startswith("+") and len(digits) >= 8:
            return True
        if len(digits) >= 10:
            return True
    return False


def _labeled_name(text: str) -> bool:
    for match in _LABELED_NAME.finditer(text):
        if match.group(1).casefold() not in _STOP:
            return True
    return False


def _introduces_self(text: str) -> bool:
    for match in _I_AM.finditer(text):
        word = match.group(1)
        if word.casefold() in _STOP:
            continue
        if word[0].isupper() or word.casefold() in _GIVEN or word.casefold() in _SURNAMES:
            return True
    return False


def _has_name(text: str) -> bool:
    words = _WORD.findall(text)
    previous = False
    for word in words:
        title = _title(word)
        if title and word.casefold() in _GIVEN | _SURNAMES:
            return True
        if title and previous:
            return True
        previous = title
    return False


def _title(word: str) -> bool:
    if len(word) < 3 or not word[0].isupper():
        return False
    if not any(character.islower() for character in word[1:]):
        return False
    return word.casefold() not in _ORDINARY
