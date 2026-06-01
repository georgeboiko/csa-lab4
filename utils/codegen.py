from config import (
    DATA_MEMORY_SIZE,
    DATA_SP_ADDR,
    INPUT_ADDR,
    IVT_INPUT_ADDR,
    OUTPUT_ADDR,
    TEMP0_ADDR,
    TEMP0_SAVE_ADDR,
    TEMP1_ADDR,
    TEMP1_SAVE_ADDR,
    TEMP2_ADDR,
    TEMP2_SAVE_ADDR,
)
from isa import Opcode
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


class CodeGenerator:
    """
    Codegen обходит AST и генерирует список инструкций + память данных.
    """

    def __init__(self):
        self.code = []
        self.data_memory = [0] * DATA_MEMORY_SIZE

        self.data_ptr = TEMP2_SAVE_ADDR + 1

        self.variables = {}
        self.functions = {}

        self.label_counter = 0

    def get_label(self, prefix: str, name: str) -> str:
        return f".{prefix}_{name}"

    def add_instruction(self, opcode: Opcode, arg=0):
        self.code.append({"opcode": opcode, "arg": arg})

    def add_temp_label(self, name: str):
        self.code.append({"opcode": "LABEL", "arg": name})

    def dec_sp(self):
        self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
        self.add_instruction(Opcode.SUB_IMM, 4)
        self.add_instruction(Opcode.STORE, DATA_SP_ADDR)

    def inc_sp(self):
        self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
        self.add_instruction(Opcode.ADD_IMM, 4)
        self.add_instruction(Opcode.STORE, DATA_SP_ADDR)

    def load_sp(self):
        self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
        self.add_instruction(Opcode.LOAD_ACC)

    def store_sp(self):
        self.add_instruction(Opcode.STORE_IND, DATA_SP_ADDR)

    def push_acc(self):
        self.add_instruction(Opcode.STORE, TEMP0_ADDR)
        self.dec_sp()
        self.add_instruction(Opcode.LOAD, TEMP0_ADDR)
        self.store_sp()

    def push_imm(self, value: int):
        self.dec_sp()
        self.add_instruction(Opcode.LOAD_IMM, value)
        self.store_sp()

    def pop_to_acc(self):
        self.load_sp()
        self.add_instruction(Opcode.STORE, TEMP0_ADDR)
        self.inc_sp()
        self.add_instruction(Opcode.LOAD, TEMP0_ADDR)

    def generate(self, ast: list[Node]):
        # Резервируем адреса в памяти данных под все перемеренные
        for node in ast:
            if isinstance(node, VariableDefNode):
                self.variables[node.name] = self.data_ptr
                self.data_ptr += 1

        # Регистрируем имена всех функций и ISR (без компиляции тел)
        for node in ast:
            if isinstance(node, FuncDefNode):
                self.functions[node.name] = self.get_label("func", node.name)
            elif isinstance(node, IsrDefNode):
                self.functions[node.name] = self.get_label("isr", node.name)

        self.add_instruction(Opcode.LOAD_IMM, DATA_MEMORY_SIZE // 2 - 1)
        self.add_instruction(Opcode.STORE, DATA_SP_ADDR)

        start_label = self.get_label("start", str(self.label_counter))
        self.add_instruction(Opcode.JUMP, start_label)

        # Компилируем тела функций и ISR
        for node in ast:
            if isinstance(node, (FuncDefNode, IsrDefNode)):
                self.visit(node)

        self.add_temp_label(start_label)

        # Компилируем основной код
        main_nodes = [n for n in ast if not isinstance(n, (FuncDefNode, IsrDefNode, VariableDefNode))]
        self.visit_sequence(main_nodes)

        self.add_instruction(Opcode.HALT)

        self.resolve_labels()

        # Записываем адрес ISR ввода в таблицу векторов прерываний.
        for node in ast:
            if isinstance(node, IsrDefNode):
                label = self.get_label("isr", node.name)
                if label in self._resolved_labels:
                    self.data_memory[IVT_INPUT_ADDR] = self._resolved_labels[label]
                break

        return self.code, self.data_memory

    def _is_var(self, node: Node) -> int | None:
        if isinstance(node, WordNode) and node.name in self.variables:
            return self.variables[node.name]
        return None

    def _is_word(self, node: Node, name: str) -> bool:
        return isinstance(node, WordNode) and node.name == name

    def _is_number(self, node: Node) -> int | None:
        if isinstance(node, NumberNode):
            return node.value
        return None

    def visit_sequence(self, nodes: list[Node]):
        """Обработка списка нод с попыткой оптимизации."""
        i = 0
        while i < len(nodes):
            consumed = self._try_patterns(nodes, i)
            if consumed > 0:
                i += consumed
            else:
                self.visit(nodes[i])
                i += 1

    def _try_patterns(self, nodes: list[Node], i: int) -> int:
        """Попытка найти и скомпилировать оптимизированные паттерны на индесе i.
        Возвращается количество обработанных нод, или 0 если ни один паттерн не подошел.
        """
        n = len(nodes)

        # var @ number swap ! - сохранить number по адресу var
        if i + 4 < n:
            var_addr = self._is_var(nodes[i])
            if (
                var_addr is not None
                and self._is_word(nodes[i + 1], "@")
                and self._is_number(nodes[i + 2]) is not None
                and self._is_word(nodes[i + 3], "swap")
                and self._is_word(nodes[i + 4], "!")
            ):
                num_val = self._is_number(nodes[i + 2])
                self.add_instruction(Opcode.LOAD_IMM, num_val)
                self.add_instruction(Opcode.STORE_IND, var_addr)
                return 5

        # var1 @ number + var2 ! - сохранить number + var1 по адресу var2
        if i + 4 < n:
            var1 = self._is_var(nodes[i])
            if var1 is not None and self._is_word(nodes[i + 1], "@"):
                num_val = self._is_number(nodes[i + 2])
                if num_val is not None and self._is_word(nodes[i + 3], "+"):
                    var2 = self._is_var(nodes[i + 4])
                    if var2 is not None and self._is_word(nodes[i + 5], "!") if i + 5 < n else False:
                        self.add_instruction(Opcode.LOAD, var1)
                        self.add_instruction(Opcode.ADD_IMM, num_val)
                        self.add_instruction(Opcode.STORE, var2)
                        return 6

        # var1 @ var2 ! - сохранить var1 по адресу var2
        if i + 3 < n:
            var1 = self._is_var(nodes[i])
            if var1 is not None and self._is_word(nodes[i + 1], "@"):
                var2 = self._is_var(nodes[i + 2])
                if var2 is not None and self._is_word(nodes[i + 3], "!"):
                    self.add_instruction(Opcode.LOAD, var1)
                    self.add_instruction(Opcode.STORE, var2)
                    return 4

        # var @ emit - записать var по адресу OUTPUT_ADDR
        if i + 2 < n:
            var_addr = self._is_var(nodes[i])
            if var_addr is not None and self._is_word(nodes[i + 1], "@") and self._is_word(nodes[i + 2], "emit"):
                self.add_instruction(Opcode.LOAD, var_addr)
                self.add_instruction(Opcode.STORE, OUTPUT_ADDR)
                return 3

        # var @ ! - сохранить вершину стека данных по адресу var
        if i + 2 < n:
            var_addr = self._is_var(nodes[i])
            if var_addr is not None and self._is_word(nodes[i + 1], "@") and self._is_word(nodes[i + 2], "!"):
                self.load_sp()
                self.add_instruction(Opcode.STORE_IND, var_addr)
                self.inc_sp()
                return 3

        # var @ @ - косвенная загрузка
        if i + 2 < n:
            var_addr = self._is_var(nodes[i])
            if var_addr is not None and self._is_word(nodes[i + 1], "@") and self._is_word(nodes[i + 2], "@"):
                self.add_instruction(Opcode.LOAD, var_addr)
                self.add_instruction(Opcode.LOAD_ACC)
                self.push_acc()
                return 3

        # number var ! - сохранить number по адресу var
        if i + 2 < n:
            num_val = self._is_number(nodes[i])
            var_addr = self._is_var(nodes[i + 1])
            if num_val is not None and var_addr is not None and self._is_word(nodes[i + 2], "!"):
                self.add_instruction(Opcode.LOAD_IMM, num_val)
                self.add_instruction(Opcode.STORE, var_addr)
                return 3

        # var @ - положить на стек данных значение переменной var
        if i + 1 < n:
            var_addr = self._is_var(nodes[i])
            if var_addr is not None and self._is_word(nodes[i + 1], "@"):
                self.add_instruction(Opcode.LOAD, var_addr)
                self.push_acc()
                return 2

        # 1 + - инкремент вершины стека данных
        if i + 1 < n:
            num_val = self._is_number(nodes[i])
            if num_val == 1 and self._is_word(nodes[i + 1], "+"):
                self.load_sp()
                self.add_instruction(Opcode.INC)
                self.store_sp()
                return 2

        # 1 - - декремент вершины стека данных
        if i + 1 < n:
            num_val = self._is_number(nodes[i])
            if num_val == 1 and self._is_word(nodes[i + 1], "-"):
                self.load_sp()
                self.add_instruction(Opcode.DEC)
                self.store_sp()
                return 2

        # number + - увеличение вершины стека данных на number (immediate)
        if i + 1 < n:
            num_val = self._is_number(nodes[i])
            if num_val is not None and 2 <= num_val <= 0x7FFFFF and self._is_word(nodes[i + 1], "+"):
                self.load_sp()
                self.add_instruction(Opcode.ADD_IMM, num_val)
                self.store_sp()
                return 2

        # number - - уменьшение вершины стека данных на number (immediate)
        if i + 1 < n:
            num_val = self._is_number(nodes[i])
            if num_val is not None and 2 <= num_val <= 0x7FFFFF and self._is_word(nodes[i + 1], "-"):
                self.load_sp()
                self.add_instruction(Opcode.SUB_IMM, num_val)
                self.store_sp()
                return 2

        # number = - сравнение вершины стека данных с number (immediate)
        if i + 1 < n:
            num_val = self._is_number(nodes[i])
            if num_val is not None and self._is_word(nodes[i + 1], "="):
                self.label_counter += 1
                true_lbl = self.get_label("cmp_true", str(self.label_counter))
                self.label_counter += 1
                end_lbl = self.get_label("cmp_end", str(self.label_counter))
                self.load_sp()
                if num_val == 0:
                    self.add_instruction(Opcode.BEQZ, true_lbl)
                else:
                    self.add_instruction(Opcode.SUB_IMM, num_val)
                    self.add_instruction(Opcode.BEQZ, true_lbl)
                self.add_instruction(Opcode.LOAD_IMM, 0)
                self.add_instruction(Opcode.JUMP, end_lbl)
                self.add_temp_label(true_lbl)
                self.add_instruction(Opcode.LOAD_IMM, 1)
                self.add_temp_label(end_lbl)
                self.store_sp()
                return 2

        # dup @ - положить на стек данных значение по адресу
        if i + 1 < n and self._is_word(nodes[i], "dup") and self._is_word(nodes[i + 1], "@"):
            self.load_sp()
            self.add_instruction(Opcode.LOAD_ACC)
            self.push_acc()
            return 2

        return 0

    def visit(self, node: Node):
        if isinstance(node, FuncDefNode):
            label = self.functions[node.name]
            self.add_temp_label(label)

            # Если функция не рекурсивная — скрываем её имя при компиляции тела
            if not node.is_recursive:
                del self.functions[node.name]

            self.visit_sequence(node.body)

            # Восстанавливаем имя после компиляции тела
            if not node.is_recursive:
                self.functions[node.name] = label

            self.add_instruction(Opcode.RET)

        elif isinstance(node, IsrDefNode):
            label = self.functions[node.name]
            self.add_temp_label(label)

            self.add_instruction(Opcode.LOAD, TEMP0_ADDR)
            self.add_instruction(Opcode.STORE, TEMP0_SAVE_ADDR)
            self.add_instruction(Opcode.LOAD, TEMP1_ADDR)
            self.add_instruction(Opcode.STORE, TEMP1_SAVE_ADDR)
            self.add_instruction(Opcode.LOAD, TEMP2_ADDR)
            self.add_instruction(Opcode.STORE, TEMP2_SAVE_ADDR)

            self.visit_sequence(node.body)

            self.add_instruction(Opcode.LOAD, TEMP2_SAVE_ADDR)
            self.add_instruction(Opcode.STORE, TEMP2_ADDR)
            self.add_instruction(Opcode.LOAD, TEMP1_SAVE_ADDR)
            self.add_instruction(Opcode.STORE, TEMP1_ADDR)
            self.add_instruction(Opcode.LOAD, TEMP0_SAVE_ADDR)
            self.add_instruction(Opcode.STORE, TEMP0_ADDR)

            self.add_instruction(Opcode.IRET)

        elif isinstance(node, NumberNode):
            self.push_imm(node.value)

        elif isinstance(node, StringNode):
            str_start_addr = self.data_ptr
            for char in node.value:
                self.data_memory[self.data_ptr] = ord(char)
                self.data_ptr += 1
            self.data_memory[self.data_ptr] = 0
            self.data_ptr += 1

            self.push_imm(str_start_addr)

        elif isinstance(node, LoopNode):
            self.label_counter += 1
            begin_label = self.get_label("loop_begin", str(self.label_counter))
            self.add_temp_label(begin_label)

            self.visit_sequence(node.body)

            self.pop_to_acc()
            self.add_instruction(Opcode.BEQZ, begin_label)

        elif isinstance(node, IfNode):
            self.label_counter += 1
            else_label = self.get_label("else", str(self.label_counter))
            self.label_counter += 1
            end_label = self.get_label("endif", str(self.label_counter))

            self.pop_to_acc()

            target = else_label if node.false_branch else end_label
            self.add_instruction(Opcode.BEQZ, target)

            self.visit_sequence(node.true_branch)
            self.add_instruction(Opcode.JUMP, end_label)

            if node.false_branch:
                self.add_temp_label(else_label)
                self.visit_sequence(node.false_branch)

            self.add_temp_label(end_label)

        elif isinstance(node, TickNode):
            func_label = self.functions[node.name]
            self.push_imm(func_label)

        elif isinstance(node, WordNode):
            self.compile_word(node.name)

    def compile_word(self, word: str):
        if word in self.functions:
            self.add_instruction(Opcode.CALL, self.functions[word])

        elif word in self.variables:
            addr = self.variables[word]
            self.push_imm(addr)

        elif word == "+":
            self.math_helper(Opcode.ADD)

        elif word == "-":
            self.math_helper(Opcode.SUB)

        elif word == "*":
            self.math_helper(Opcode.MUL)

        elif word == "/":
            self.math_helper(Opcode.DIV)

        elif word == "mod":
            self.math_helper(Opcode.MOD)

        elif word == "and":
            self.math_helper(Opcode.AND)

        elif word == "or":
            self.math_helper(Opcode.OR)

        elif word == "xor":
            self.math_helper(Opcode.XOR)

        elif word == "not":
            self.load_sp()
            self.add_instruction(Opcode.NOT)
            self.store_sp()

        elif word == "dup":
            self.load_sp()
            self.push_acc()

        elif word == "over":
            self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
            self.add_instruction(Opcode.ADD_IMM, 4)
            self.add_instruction(Opcode.LOAD_ACC)
            self.push_acc()

        elif word == "drop":
            self.inc_sp()

        elif word == "swap":
            self.load_sp()
            self.add_instruction(Opcode.STORE, TEMP0_ADDR)
            self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
            self.add_instruction(Opcode.ADD_IMM, 4)
            self.add_instruction(Opcode.LOAD_ACC)
            self.store_sp()
            self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
            self.add_instruction(Opcode.ADD_IMM, 4)
            self.add_instruction(Opcode.STORE, TEMP1_ADDR)
            self.add_instruction(Opcode.LOAD, TEMP0_ADDR)
            self.add_instruction(Opcode.STORE_IND, TEMP1_ADDR)

        elif word == "rot":
            self.load_sp()
            self.add_instruction(Opcode.STORE, TEMP0_ADDR)
            self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
            self.add_instruction(Opcode.ADD_IMM, 4)
            self.add_instruction(Opcode.LOAD_ACC)
            self.add_instruction(Opcode.STORE, TEMP1_ADDR)
            self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
            self.add_instruction(Opcode.ADD_IMM, 8)
            self.add_instruction(Opcode.LOAD_ACC)
            self.store_sp()
            self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
            self.add_instruction(Opcode.ADD_IMM, 4)
            self.add_instruction(Opcode.STORE, TEMP2_ADDR)
            self.add_instruction(Opcode.LOAD, TEMP0_ADDR)
            self.add_instruction(Opcode.STORE_IND, TEMP2_ADDR)
            self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
            self.add_instruction(Opcode.ADD_IMM, 8)
            self.add_instruction(Opcode.STORE, TEMP2_ADDR)
            self.add_instruction(Opcode.LOAD, TEMP1_ADDR)
            self.add_instruction(Opcode.STORE_IND, TEMP2_ADDR)

        elif word == "=":
            self.compare_helper(Opcode.BEQZ)

        elif word == "<":
            self.compare_helper(Opcode.BLTZ)

        elif word == ">":
            self.compare_helper(Opcode.BGTZ)

        elif word == "@":
            self.load_sp()
            self.add_instruction(Opcode.LOAD_ACC)
            self.store_sp()

        elif word == "!":
            self.load_sp()
            self.add_instruction(Opcode.STORE, TEMP0_ADDR)
            self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
            self.add_instruction(Opcode.ADD_IMM, 4)
            self.add_instruction(Opcode.LOAD_ACC)
            self.add_instruction(Opcode.STORE_IND, TEMP0_ADDR)
            self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
            self.add_instruction(Opcode.ADD_IMM, 8)
            self.add_instruction(Opcode.STORE, DATA_SP_ADDR)

        elif word == "emit":
            self.load_sp()
            self.add_instruction(Opcode.STORE, OUTPUT_ADDR)
            self.inc_sp()

        elif word == "key":
            self.add_instruction(Opcode.LOAD, INPUT_ADDR)
            self.push_acc()

        elif word == "execute":
            self.load_sp()
            self.add_instruction(Opcode.STORE, TEMP0_ADDR)
            self.inc_sp()
            self.add_instruction(Opcode.LOAD, TEMP0_ADDR)
            self.add_instruction(Opcode.CALL_ACC)

        else:
            raise Exception(f"Ошибка: Неизвестное слово '{word}'")

    def math_helper(self, operation: Opcode):
        self.load_sp()
        self.add_instruction(Opcode.STORE, TEMP0_ADDR)
        self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
        self.add_instruction(Opcode.ADD_IMM, 4)
        self.add_instruction(Opcode.STORE, DATA_SP_ADDR)
        self.add_instruction(Opcode.LOAD_ACC)
        self.add_instruction(operation, TEMP0_ADDR)
        self.store_sp()

    def compare_helper(self, jump_opcode: Opcode):
        self.label_counter += 1
        true_lbl = self.get_label("cmp_true", str(self.label_counter))
        self.label_counter += 1
        end_lbl = self.get_label("cmp_end", str(self.label_counter))

        self.load_sp()
        self.add_instruction(Opcode.STORE, TEMP0_ADDR)
        self.add_instruction(Opcode.LOAD, DATA_SP_ADDR)
        self.add_instruction(Opcode.ADD_IMM, 4)
        self.add_instruction(Opcode.STORE, DATA_SP_ADDR)
        self.add_instruction(Opcode.LOAD_ACC)
        self.add_instruction(Opcode.SUB, TEMP0_ADDR)

        self.add_instruction(jump_opcode, true_lbl)

        self.add_instruction(Opcode.LOAD_IMM, 0)
        self.add_instruction(Opcode.JUMP, end_lbl)

        self.add_temp_label(true_lbl)
        self.add_instruction(Opcode.LOAD_IMM, 1)

        self.add_temp_label(end_lbl)
        self.store_sp()  # [SP] = flag

    def resolve_labels(self):
        """
        Линкер: разрешает символические метки в байтовые адреса.
        """
        from isa import INSTR_BYTES

        resolved_code = []
        labels_map: dict[str, int] = {}

        # Первый проход: вычисляем байтовые адреса меток.
        current_byte_addr = 0
        for instr in self.code:
            op = instr["opcode"]
            if op == "LABEL":
                labels_map[instr["arg"]] = current_byte_addr
            else:
                current_byte_addr += INSTR_BYTES

        # Второй проход: подставляем адреса в аргументы.
        for instr in self.code:
            op = instr["opcode"]
            if op == "LABEL":
                continue

            arg = instr["arg"]
            if isinstance(arg, str) and arg.startswith("."):
                if arg not in labels_map:
                    raise Exception(f"Линкер: Неизвестная метка перехода '{arg}'")
                arg = labels_map[arg]

            resolved_code.append({"opcode": op, "arg": arg})

        self.code = resolved_code
        self._resolved_labels = labels_map
