from utils.ast_nodes import (
    FuncDefNode,
    IfNode,
    IsrDefNode,
    LoopNode,
    Node,
    NumberNode,
    StringNode,
    TickNode,
    VariableDefNode,
    WordNode,
)


class Parser:
    CLOSING_TOKENS = (";", "until", "else", "endif")

    RESERVED_WORDS = (
        ":",
        ";",
        ":isr",
        "variable",
        "begin",
        "until",
        "if",
        "else",
        "endif",
        "recursive",
        "rot",
        "over",
        "dup",
        "drop",
        "swap",
        "+",
        "-",
        "*",
        "/",
        "mod",
        "=",
        "<",
        ">",
        "and",
        "or",
        "xor",
        "not",
        "key",
        "emit",
        "@",
        "!",
        "'",
        "execute",
    )

    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.pos = 0

    def current_token(self) -> str | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def advance(self):
        self.pos += 1

    def expect(self, expected_token: str):
        token = self.current_token()
        if token != expected_token:
            raise SyntaxError(
                f"Синтаксическая ошибка! Ожидалось '{expected_token}', а встречено '{token}' (позиция {self.pos})"
            )
        self.advance()

    def read_and_validate_name(self, context: str) -> str:
        name = self.current_token()
        if name is None or name in self.CLOSING_TOKENS:
            raise SyntaxError(f"Ожидалось имя {context}, а встречен конец блока или файла.")
        if name in self.RESERVED_WORDS:
            raise SyntaxError(f"Нельзя использовать зарезервированное слово '{name}' как имя {context}!")
        self.advance()
        return name

    def parse(self) -> list[Node]:
        nodes = self.parse_block()

        if self.current_token() is not None:
            raise SyntaxError(f"Синтаксическая ошибка: лишнее слово '{self.current_token()}' вне любого блока!")

        return nodes

    def parse_block(self) -> list[Node]:
        nodes: list[Node] = []

        while self.current_token() is not None:
            token = self.current_token()
            
            assert token is not None

            if token in self.CLOSING_TOKENS:
                break

            self.advance()

            if token == ":":
                name = self.read_and_validate_name("функции")

                is_recursive = False
                if self.current_token() == "recursive":
                    is_recursive = True
                    self.advance()

                body = self.parse_block()
                self.expect(";")
                nodes.append(FuncDefNode(name, is_recursive, body))

            elif token == ":isr":
                name = self.read_and_validate_name("обработчика прерывания")
                body = self.parse_block()
                self.expect(";")
                nodes.append(IsrDefNode(name, body))

            elif token == "variable":
                name = self.read_and_validate_name("переменной")
                nodes.append(VariableDefNode(name))

            elif token.startswith('"'):
                nodes.append(StringNode(token.strip('"')))

            elif token == "begin":
                body = self.parse_block()
                self.expect("until")
                nodes.append(LoopNode(body))

            elif token == "if":
                true_branch = self.parse_block()
                false_branch = None

                if self.current_token() == "else":
                    self.advance()
                    false_branch = self.parse_block()

                self.expect("endif")
                nodes.append(IfNode(true_branch, false_branch))

            elif token == "'":
                func_name = self.read_and_validate_name("функции")
                nodes.append(TickNode(func_name))

            else:
                try:
                    nodes.append(NumberNode(int(token)))
                except ValueError:
                    nodes.append(WordNode(token))

        return nodes
