from dataclasses import dataclass


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
    body: list[Node]


@dataclass
class IsrDefNode(Node):
    name: str
    body: list[Node]


@dataclass
class IfNode(Node):
    true_branch: list[Node]
    false_branch: list[Node] | None


@dataclass
class LoopNode(Node):
    body: list[Node]


@dataclass
class TickNode(Node):
    name: str
