# Typed surface of the PyYAML names this repository uses. PyYAML 6.0.3 ships
# no `py.typed`; these signatures were read from its source. `safe_load` is
# typed `object` and every caller narrows it; `SafeLoader` is subclassed by
# the gate checker's repeated-key refusal.
from typing import IO

class YAMLError(Exception): ...

class Node:
    value: object

class MappingNode(Node):
    value: list[tuple[Node, Node]]

class SafeLoader:
    def __init__(self, stream: str | bytes | IO[str] | IO[bytes]) -> None: ...
    def get_single_data(self) -> object: ...
    def dispose(self) -> None: ...
    def construct_object(self, node: Node, deep: bool = False) -> object: ...
    def construct_mapping(
        self, node: MappingNode, deep: bool = False
    ) -> dict[object, object]: ...

def safe_load(stream: str | bytes | IO[str] | IO[bytes]) -> object: ...
