import os, sys, re

from utils.parser import Parser
from utils.codegen import CodeGenerator

from isa import *

def parse_tokens(source):
    """
    Функция токенизации исходного кода.
    Включает в себя удаление всех комментариев из кода
    и разбиение на токены:
        1) Слова - любой набор символов без пробелов
        2) Строки - кавычка + любые символы без кавычек + кавычка
    
    """

    source = re.sub(r'\\.*', '', source)
    source = re.sub(r'\(.*?\)', '', source, flags=re.DOTALL)

    token_pattern = re.compile(r'"[^"]*"|\S+')
    return token_pattern.findall(source)

def parse_syntax(tokens):
    """
    Функция парсит токены и возвращает синтаксический дерево.
    """
    return Parser(tokens).parse()


def translate(source):
    """Функция трансляции исходного кода в машинный код."""
    
    tokens = parse_tokens(source)
    tree = parse_syntax(tokens)
    code, memory = CodeGenerator().generate(tree)
    return code, memory



def main(source, target, memory_target):
    """Функция запуска транслятора. Параметры -- исходный и целевой файлы."""
    with open(source, encoding="utf-8") as f:
        source = f.read()

    code, memory = translate(source)
    # for instr in code:
    #     print(instr)
    # print(memory[0:100], memory[8100:8191])

    binary_code = to_bytes(code)
    hex_code = to_hex(code)

    binary_memory = to_bytes_memory(memory)
    hex_memory = to_hex_memory(memory)

    os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(memory_target)) or ".", exist_ok=True)


    if target.endswith(".bin"):
        with open(target, "wb") as f:
            f.write(binary_code)
        with open(target + ".hex", "w") as f:
            f.write(hex_code)
        with open(memory_target, "wb") as f:
            f.write(binary_memory)
        with open(memory_target + ".hex", "w") as f:
            f.write(hex_memory)
    else:
       write_json(target, memory_target, code, memory)

    print("source LoC:", len(source.split("\n")), "code instr:", len(code))


if __name__ == "__main__":
    assert len(sys.argv) == 4, "Wrong arguments: translator.py <input_file> <target_file> <memory_file>"
    _, source, target, memory_target = sys.argv
    main(source, target, memory_target)