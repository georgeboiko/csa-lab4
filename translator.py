import os, sys, re

from utils.parser import Parser

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
    return tree



def main(source, target):
    """Функция запуска транслятора. Параметры -- исходный и целевой файлы."""
    with open(source, encoding="utf-8") as f:
        source = f.read()

    code = translate(source)
    print(code)

    #binary_code = to_bytes(code)
    #hex_code = to_hex(code)

    # Убедимся, что каталог назначения существует
    #os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)

    # # Запишим выходные файлы
    # if target.endswith(".bin"):
    #     with open(target, "wb") as f:
    #         f.write(binary_code)
    #     with open(target + ".hex", "w") as f:
    #         f.write(hex_code)
    # else:
    #    write_json(target, code)

    # Обратите внимание, что память данных не экспортируется в файл, так как
    # в случае brainfuck она может быть инициализирована только 0.
    #print("source LoC:", len(source.split("\n")), "code instr:", len(code))


if __name__ == "__main__":
    assert len(sys.argv) == 3, "Wrong arguments: translator.py <input_file> <target_file>"
    _, source, target = sys.argv
    main(source, target)