Вариант:
forth | acc | harv | hw | tick | binary | trap | mem | cstr | prob1 | superscalar

язык форт, аккумуляторная архитектура
гарвардская архитектура - отдельно память команд и память данных
hardwired control unit
моделирование с точностью до такта
бинарное представление машинного кода
ввод-вывод через прерывания
memory-mapped io
c-строки
алгоритм 1
суперскаляр

```
<program> ::= { <variable> | <definition> | <command> }

<variable> ::= "variable" <name>

<definition> ::= <function_definition> | <isr_definition> 

<function_definition> ::= ":" <name> [ "recursive" ] <definition_body> ";"
<isr_definition> ::= ":isr" <name> <definition_body> ";"

<definition_body> ::= { <command> }

<command> ::= <control_flow> | <word>

<word> ::=  <reserved_word> | <user_word> | <number> | <string> | <commentary> 

<reserved_word> ::= <stack_operation> | <number_operation> | <compare_operator> | <logical_operator> | <io_operation> | <memory_operation> | <execution_token_operation>

<user_word> ::= <name>

<number> ::= [ "-" ] <digit> { <digit> }

<string> ::= "\"" { <any character exclude quote> } "\""

<control_flow> ::= <condition> | <loop>

<condition> ::= "if" <condition_body> [ "else" <condition_body> ] "endif"

<loop> ::= "begin" <loop_body> "until"
<loop_body> ::= { <command> }

<commentary> ::= "(" { <any character except ")" > } ")" | "\" { <any character except "\n"> } "\n"

<condition_body> ::= { <command> }

<stack_operation> ::= "rot" | "over" | "dup" | "drop" | "swap"
<number_operation> ::= "+" | "-" | "*" | "/" | "mod" | "/mod"
<compare_operator> ::= "=" | "<" | ">"
<logical_operator> ::= "and" | "or" | "xor" | "not"
<io_operation> ::= "key" | "emit"
<memory_operation> ::= "@" | "!"
<execution_token_operation> ::= "'" | "execute"

<name> ::= <letter> { <letter> | <digit> | "_" }

<letter> ::= "a" | "b" | "c" | ... | "z" | "A" | "B" | "C" | ... | "Z"
<digit> ::= "0" | "1" | "2" | ... | "9"
```