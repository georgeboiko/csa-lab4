from isa import Opcode
from utils.ast_nodes import *

class CodeGenerator:

    TEMP0_ADDR = 0
    TEMP1_ADDR = 1
    INPUT_ADDR = 2
    OUTPUT_ADDR = 3
    
    def __init__(self):
        self.code = []
        self.data_memory = [0] * 8192

        """
        0, 1 адреса зарезервированы под temp
        2, 3 - под memory mapped io
        """

        self.data_ptr = 4

        self.variables = {}
        self.functions = {}
        
        self.label_counter = 0
    
    def get_label(self, prefix: str, name: str) -> str:
        return f".{prefix}_{name}"

    def add_instruction(self, opcode: Opcode, arg=0):
        self.code.append({"opcode": opcode, "arg": arg})

    def add_temp_label(self, name: str):
        self.code.append({"opcode": "LABEL", "arg": name})

    def generate(self, ast: List[Node]):
        # регистрируем резервируем адреса в памяти данных под все переменные
        for node in ast:
            if isinstance(node, VariableDefNode):
                self.variables[node.name] = self.data_ptr
                self.data_ptr += 1

        # регистрируем имена всех функций и обработчиков прерываний (без компиляции тел)
        for node in ast:
            if isinstance(node, FuncDefNode):
                self.functions[node.name] = self.get_label("func", node.name)
            elif isinstance(node, IsrDefNode):
                self.functions[node.name] = self.get_label("isr", node.name)

        start_label = self.get_label("start", self.label_counter)
        self.add_instruction(Opcode.JUMP, start_label)

        # компилируем тела функций и обработчиков прерываний
        for node in ast:
            if isinstance(node, (FuncDefNode, IsrDefNode)):
                self.visit(node)

        self.add_temp_label(start_label)

        # компилируем основной код
        for node in ast:
            if not isinstance(node, (FuncDefNode, IsrDefNode, VariableDefNode)):
                self.visit(node)

        self.add_instruction(Opcode.HALT)

        self.resolve_labels()
        return self.code, self.data_memory

    def visit(self, node: Node):
        if isinstance(node, FuncDefNode):
            label = self.functions[node.name]
            self.add_temp_label(label)

            # если функция не рекурсивная — скрываем её имя при компиляции тела,
            # чтобы вызов самой себя внутри тела был ошибкой
            if not node.is_recursive:
                del self.functions[node.name]

            for child in node.body:
                self.visit(child)

            if not node.is_recursive:
                self.functions[node.name] = label
            
            self.add_instruction(Opcode.RET)

        elif isinstance(node, IsrDefNode):
            label = self.functions[node.name]
            self.add_temp_label(label)

            for child in node.body:
                self.visit(child)
            
            self.add_instruction(Opcode.IRET)
        
        elif isinstance(node, NumberNode):
            self.add_instruction(Opcode.LOAD_IMM, node.value)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.STORE_SP)

        elif isinstance(node, StringNode):
            str_start_addr = self.data_ptr

            for char in node.value:
                self.data_memory[self.data_ptr] = ord(char)
                self.data_ptr += 1

            self.data_memory[self.data_ptr] = 0
            self.data_ptr += 1
            
            self.add_instruction(Opcode.LOAD_IMM, str_start_addr)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.STORE_SP)

        elif isinstance(node, LoopNode):
            self.label_counter += 1
            begin_label = self.get_label("loop_begin", self.label_counter)
            self.add_temp_label(begin_label)

            for child in node.body:
                self.visit(child)
            
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.BEQZ, begin_label)

        elif isinstance(node, IfNode):
            self.label_counter += 1
            else_label = self.get_label("else", self.label_counter)

            self.label_counter += 1
            end_label = self.get_label("endif", self.label_counter)

            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.DEC_SP)

            target = else_label if node.false_branch else end_label
            self.add_instruction(Opcode.BEQZ, target)

            for child in node.true_branch:
                self.visit(child)
            self.add_instruction(Opcode.JUMP, end_label)

            if node.false_branch:
                self.add_temp_label(else_label)
                for child in node.false_branch:
                    self.visit(child)
                    
            self.add_temp_label(end_label)

        elif isinstance(node, TickNode):
            func_label = self.functions[node.name]
            self.add_instruction(Opcode.LOAD_IMM, func_label)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.STORE_SP)

        elif isinstance(node, WordNode):
            self.compile_word(node.name)

    def compile_word(self, word: str):
        if word in self.functions:
            self.add_instruction(Opcode.CALL, self.functions[word])

        elif word in self.variables:
            addr = self.variables[word]
            self.add_instruction(Opcode.LOAD_IMM, addr)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.STORE_SP)

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
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.NOT)
            self.add_instruction(Opcode.STORE_SP)

        elif word == "dup":
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.STORE_SP)

        elif word == "over":
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.STORE_SP)
            
        elif word == "drop":
            self.add_instruction(Opcode.DEC_SP)

        elif word == "swap":
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.STORE, self.TEMP0_ADDR)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.STORE_SP)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.LOAD, self.TEMP0_ADDR)
            self.add_instruction(Opcode.STORE_SP)
            self.add_instruction(Opcode.INC_SP)
        
        elif word == "rot":
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.STORE, self.TEMP0_ADDR)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.STORE, self.TEMP1_ADDR)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.STORE_SP)
            self.add_instruction(Opcode.LOAD, self.TEMP0_ADDR)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.STORE_SP)
            self.add_instruction(Opcode.LOAD, self.TEMP1_ADDR)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.STORE_SP)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.INC_SP)

        elif word == "=":
            self.compare_helper(Opcode.BEQZ)

        elif word == "<":
            self.compare_helper(Opcode.BLTZ)

        elif word == ">":
            self.compare_helper(Opcode.BGTZ)

        elif word == "@":
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.LOAD_ACC)
            self.add_instruction(Opcode.STORE_SP)

        elif word == "!":
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.STORE, self.TEMP0_ADDR)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.STORE_IND, self.TEMP0_ADDR)
            self.add_instruction(Opcode.DEC_SP)

        elif word == "emit":
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.STORE, self.OUTPUT_ADDR)

        elif word == "key":
            self.add_instruction(Opcode.LOAD, self.INPUT_ADDR)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.STORE_SP)

        elif word == "execute":
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.CALL_ACC)            
    
        else:
            raise Exception(f"Ошибка: Неизвестное слово '{word}'")

    def math_helper(self, operation: Opcode):
        self.add_instruction(Opcode.LOAD_SP)
        self.add_instruction(Opcode.STORE, self.TEMP0_ADDR)
        self.add_instruction(Opcode.DEC_SP)
        self.add_instruction(Opcode.LOAD_SP)
        self.add_instruction(operation, self.TEMP0_ADDR)
        self.add_instruction(Opcode.STORE_SP)

    def compare_helper(self, jump_opcode: Opcode):
        self.label_counter += 1
        true_lbl = self.get_label("cmp_true", str(self.label_counter))
        self.label_counter += 1
        end_lbl = self.get_label("cmp_end", str(self.label_counter))

        self.add_instruction(Opcode.LOAD_SP)
        self.add_instruction(Opcode.STORE, self.TEMP0_ADDR)
        self.add_instruction(Opcode.DEC_SP)
        self.add_instruction(Opcode.LOAD_SP)
        self.add_instruction(Opcode.SUB, self.TEMP0_ADDR)

        self.add_instruction(jump_opcode, true_lbl)

        self.add_instruction(Opcode.LOAD_IMM, 0)
        self.add_instruction(Opcode.JUMP, end_lbl)

        self.add_temp_label(true_lbl)
        self.add_instruction(Opcode.LOAD_IMM, 1)

        self.add_temp_label(end_lbl)
        self.add_instruction(Opcode.STORE_SP)


    
    def resolve_labels(self):
        resolved_code = []
        labels_map = {}
        
        current_address = 0
        for instr in self.code:
            if instr["opcode"] == "LABEL":
                labels_map[instr["arg"]] = current_address
            else:
                current_address += 1
                
        for instr in self.code:
            if instr["opcode"] == "LABEL":
                continue 
                
            arg = instr["arg"]
            if isinstance(arg, str) and arg.startswith("."):
                if arg not in labels_map:
                    raise Exception(f"Линкер: Неизвестная метка перехода '{arg}'")
                arg = labels_map[arg]
                
            resolved_code.append({"opcode": instr["opcode"], "arg": arg})
            
        self.code = resolved_code
