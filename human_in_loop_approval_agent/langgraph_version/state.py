from typing import TypedDict, Optional, Any


class State(TypedDict, total=False):
    input: str
    stage: str
    audit: dict
    human_input: Optional[str]
    result: Optional[Any]
