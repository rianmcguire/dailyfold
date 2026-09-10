from dataclasses import dataclass


@dataclass(eq=False)
class Block:
    level: int
    text: str
    code_lang: str | None = None
    collapsed: bool = False
    properties: tuple[str, ...] = ()
