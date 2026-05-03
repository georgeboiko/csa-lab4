from dataclasses import dataclass
from typing import List, Optional

class Node:
    pass

@dataclass
class NumberNode(Node):
    value: int

@dataclass
class StringNode(Node):
    value: str

@dataclass
class WordNode(Node):
    name: str

@dataclass
class VariableDefNode(Node):
    name: str

@dataclass
class FuncDefNode(Node):
    name: str
    is_recursive: bool
    body: List[Node]

@dataclass
class IsrDefNode(Node):
    name: str
    body: List[Node]

@dataclass
class IfNode(Node):
    true_branch: List[Node]
    false_branch: Optional[List[Node]]

@dataclass
class LoopNode(Node):
    body: List[Node]

@dataclass
class TickNode(Node):
    name: str