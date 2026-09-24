# Typed surface of the PyYAML names this repository uses (the gate checker
# and the loopback stand-in). PyYAML 6.0.3 ships no `py.typed`; these
# signatures were read from its source. `safe_load` answers plain data --
# a mapping, a list, a scalar or None -- so it is typed `object`, and every
# caller narrows it before use.
from typing import IO

class YAMLError(Exception): ...

def safe_load(stream: str | bytes | IO[str] | IO[bytes]) -> object: ...
