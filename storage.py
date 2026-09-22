"""Logseq-compatible Markdown loading and daily journal storage."""

from datetime import date
import os
import re
import stat
import tempfile

from block_markdown import parse_document, serialize_document


JOURNAL_FILE_RE = re.compile(r"^(\d{4})_(\d{2})_(\d{2})\.md$")
DATA_DIR_ENV = "DAILYFOLD_DATA_DIR"


def default_data_dir(environ=None):
    """Return the configured journal directory, following the XDG convention."""
    environ = os.environ if environ is None else environ
    configured = environ.get(DATA_DIR_ENV)
    if configured:
        return os.path.abspath(os.path.expanduser(configured))

    xdg_data_home = environ.get("XDG_DATA_HOME")
    if not xdg_data_home:
        xdg_data_home = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.abspath(
        os.path.join(os.path.expanduser(xdg_data_home), "dailyfold")
    )


def journal_path(data_dir, day):
    """Return the Markdown path for a calendar day."""
    return os.path.join(
        os.path.abspath(os.path.expanduser(data_dir)),
        f"{day.strftime('%Y_%m_%d')}.md",
    )


def journal_dates(data_dir):
    """Return all valid Logseq-dated Markdown pages in *data_dir*."""
    try:
        names = os.listdir(data_dir)
    except FileNotFoundError:
        return set()

    days = set()
    for name in names:
        match = JOURNAL_FILE_RE.match(name)
        if match is None:
            continue
        try:
            day = date(*(int(part) for part in match.groups()))
        except ValueError:
            continue
        if os.path.isfile(os.path.join(data_dir, name)):
            days.add(day)
    return days


def seed_journal_from_template(data_dir, day, template_path):
    """Create *day* from *template_path* when the data directory is empty."""
    try:
        with os.scandir(data_dir) as entries:
            if next(entries, None) is not None:
                return False
    except FileNotFoundError:
        pass

    document = load_document(template_path)
    save_journal_document(journal_path(data_dir, day), document)
    return True


def document_is_empty(document):
    """Return whether a journal has no user-authored content or metadata."""
    if any(line.strip() for line in document.preamble):
        return False
    return all(
        block.code_lang is None
        and not block.text.strip()
        and not block.properties
        and not block.collapsed
        for block in document.blocks
    )


def load_document(path):
    with open(path, encoding="utf-8", newline=None) as handle:
        return parse_document(handle.read())


def save_document(path, document):
    """Atomically replace path with the serialized document."""
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    existing_mode = None
    try:
        existing_mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        pass

    fd, temporary_path = tempfile.mkstemp(
        dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".tmp"
    )
    try:
        if existing_mode is not None:
            os.fchmod(fd, existing_mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialize_document(document))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def save_journal_document(path, document):
    """Save a journal, removing its file instead when the journal is empty."""
    if document_is_empty(document):
        try:
            os.unlink(os.path.abspath(os.path.expanduser(path)))
        except FileNotFoundError:
            pass
        return
    save_document(path, document)
