from isa import Opcode
from utils.ast_nodes import *

class CodeGenerator:
    
    def __init__(self):
        self.code = []
        self.data_memory = [0] * 8192

        self.data_ptr = 1   # 0 адрес зарезервирован под temp 

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
        start_label = self.get_label("start")
        self.add_instruction(Opcode.JMP, start_label)

        for node in ast:
            if isinstance(node, (FuncDefNode, IsrDefNode)):
                self.visit(node)
                
        self.add_temp_label(start_label)
        
        for node in ast:
            if not isinstance(node, (FuncDefNode, IsrDefNode)):
                self.visit(node)

        self.add_instruction(Opcode.HALT)

        self.resolve_labels()
        return self.code, self.data_memory

    def visit(self, node: Node):
        if isinstance(node, VariableDefNode):
            self.variables[node.name] = self.data_ptr
            self.data_ptr += 1
        
        elif isinstance(node, FuncDefNode):
            label = self.get_label("func", node.name)
            self.functions[node.name] = label
            self.add_temp_label(label)

            for child in node.body:
                self.visit(child)
            
            self.add_instruction(Opcode.RET)

        elif isinstance(node, IsrDefNode):
            label = self.get_label("isr", node.name)
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
            
            self.emit(Opcode.LOAD_IMM, str_start_addr)
            self.emit(Opcode.INC_SP)
            self.emit(Opcode.STORE_SP)

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
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.STORE, 0)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.ADD, 0)
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
            self.add_instruction(Opcode.STORE, 0)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.LOAD_SP)
            self.add_instruction(Opcode.INC_SP)
            self.add_instruction(Opcode.STORE_SP)
            self.add_instruction(Opcode.DEC_SP)
            self.add_instruction(Opcode.LOAD, 0)
            self.add_instruction(Opcode.STORE_SP)
            self.add_instruction(Opcode.INC_SP)
        
        # TODO: other commands & linker

        else:
            raise Exception(f"Ошибка: Неизвестное слово '{word}'")



    def math_helper(self, operation: Opcode):
        self.add_instruction(Opcode.LOAD_SP)
        self.add_instruction(Opcode.STORE, 0)
        self.add_instruction(Opcode.DEC_SP)
        self.add_instruction(Opcode.LOAD_SP)
        self.add_instruction(operation, 0)
        self.add_instruction(Opcode.STORE_SP)