# Лабораторная работа №4. Эксперимент: транслятор и модель процессора

**Автор:** Бойко Георгий Александрович, P3216.  
**Дисциплина:** Архитектура компьютера.

## Вариант

```
forth | acc | harv | hw | tick | binary | trap | mem | cstr | prob1 | superscalar
```

| Параметр       | Значение                                                                 |
|----------------|--------------------------------------------------------------------------|
| `forth`        | Исходный язык — Forth-подобный (стек-ориентированный)                    |
| `acc`          | Аккумуляторная архитектура                                               |
| `harv`         | Гарвардская: память команд и память данных раздельны                     |
| `hw`           | Hardwired Control Unit                                                   |
| `tick`         | Tick-accurate моделирование (точность — такт)                            |
| `binary`       | Бинарное представление машинного кода (см. также `.hex`-листинг)         |
| `trap`         | Ввод-вывод через прерывания (trap-based IO)                              |
| `mem`          | Memory-mapped IO (адреса 3 = INPUT, 4 = OUTPUT)                          |
| `cstr`         | C-строки (нуль-терминированные) в памяти данных                          |
| `prob1`        | Алгоритм 1 из Project Euler (сумма кратных 3 или 5 ниже N)               |
| `superscalar`  | Усложнение: 2× суперскалярность через AC_SHADOW                          |

## Содержание

1. [Язык программирования](#язык-программирования)
2. [Организация памяти](#организация-памяти)
3. [Система команд (ISA)](#система-команд-isa)
4. [Транслятор](#транслятор)
5. [Модель процессора](#модель-процессора)
6. [Суперскалярность (AC_SHADOW)](#суперскалярность-ac_shadow)
7. [Прерывания и I/O](#прерывания-и-io)
8. [Тесты](#тесты)
9. [Структура репозитория](#структура-репозитория)
10. [Запуск](#запуск)

---

## Язык программирования

Реализован Forth-подобный язык с обратной польской записью. Все вычисления идут через **стек данных** (хранится в памяти, растёт вниз от адреса `INITIAL_SP=8191`).

### BNF

```ebnf
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

### Семантика ключевых слов

| Слово       | Стек до → после            | Описание                                    |
|-------------|----------------------------|---------------------------------------------|
| `dup`       | `( a -- a a )`             | Дублировать вершину                          |
| `drop`      | `( a -- )`                 | Снять вершину                                |
| `swap`      | `( a b -- b a )`           | Поменять местами две верхние                 |
| `over`      | `( a b -- a b a )`         | Скопировать предпоследнее на вершину         |
| `rot`       | `( a b c -- b c a )`       | Третье снизу на вершину                      |
| `+ - * / mod` | `( a b -- (a op b) )`    | Арифметика                                   |
| `= < >`     | `( a b -- flag )`          | Сравнение (0/1)                              |
| `and or xor not` | `( a b -- r )` / `( a -- r )` | Побитовая логика                       |
| `@`         | `( addr -- val )`          | Прочитать ячейку памяти                      |
| `!`         | `( val addr -- )`          | Записать в ячейку памяти                     |
| `key`       | `( -- ch )`                | Прочитать `mem[INPUT_ADDR]`                  |
| `emit`      | `( ch -- )`                | Записать `mem[OUTPUT_ADDR]`                  |
| `'` *word*  | `( -- xt )`                | Положить execution token (адрес функции)     |
| `execute`   | `( xt -- )`                | Вызвать функцию по адресу с вершины          |
| `variable n` | —                         | Резервирует ячейку, делает `n` адресной константой |
| `: f … ;`   | —                         | Определение слова `f`                        |
| `:isr h … ;`| —                         | Определение обработчика прерывания (ISR)     |
| `if … else … endif` | `( flag -- )`      | Условие (0 = false, иначе true)              |
| `begin … until`     | `( -- ) … ( flag -- )` | Цикл с пост-условием                  |

### «Массивов» как типа нет

Массив — это просто непрерывный участок памяти данных, адресуемый арифметически:

```forth
: arr 1500 ;          \ база массива
arr i @ + @           \ читаем arr[i]:  mem[1500 + i]
arr i @ + value !     \ пишем arr[i]:   mem[1500 + i] = value
```

### Строки (C-style)

Строковые литералы `"…"` укладываются в статическую память данных как нуль-терминированные (C-строки). Первый байт строки даётся на стек как её адрес, дальнейший вывод — посимвольный через `emit`.

---

## Организация памяти

Архитектура **Гарвардская** — память команд и память данных раздельны.

### Память данных (`DATA_MEMORY_SIZE = 8192` 32-битных слов)

```
Адрес    Содержимое                                         Назначение
─────    ──────────────────────────────────────────         ─────────────────────────
   0     IVT[0]                                             Адрес ISR
   1     TEMP0                                              Временный регистр
   2     TEMP1                                              Временный регистр
   3     INPUT                                              MMIO: ввод
   4     OUTPUT                                             MMIO: вывод
   5     ISR_ACC                                            Сохранённый ACC при IRQ
   6..M  user vars + static strings + heap                  Переменные, литералы строк
   …
   8191 ← INITIAL_SP                                        SP-старт
```

### Память команд

* Байтовая. PC хранит **байтовый адрес**.

---

## Система команд (ISA)

### Кодирование

| Тип инструкции    | Размер | Формат                                   |
|-------------------|--------|------------------------------------------|
| Без аргумента     | 1 байт | `[opcode]`                               |
| С 32-битным арг.  | 5 байт | `[opcode] [b3] [b2] [b1] [b0]` (Big-Endian, signed) |

Все адреса меток / `CALL` / `JUMP` — **байтовые**, вычисляются линкером.

### Список опкодов

| Группа        | Опкоды                                                                 | Аргумент?       |
|---------------|------------------------------------------------------------------------|-----------------|
| Управление    | `HALT`, `JUMP`, `CALL`, `CALL_ACC`, `RET`, `IRET`                      | JUMP/CALL — да |
| Ветвления     | `BEQZ`, `BNEZ`, `BGTZ`, `BLTZ`, `BGEZ`, `BLEZ`, `BVS`, `BVC`, `BCS`, `BCC` | да           |
| Загрузка ACC  | `LOAD addr`, `LOAD_IMM imm`, `LOAD_ACC`, `LOAD_SP`                     | LOAD/LOAD_IMM — да |
| Запись ACC    | `STORE addr`, `STORE_IND addr`, `STORE_SP`                             | STORE/STORE_IND — да |
| Стек          | `INC_SP`, `DEC_SP`                                                     | нет             |
| Сдвиги        | `SHIFTL`, `SHIFTR`                                                     | нет             |
| Арифметика    | `ADD addr`, `SUB addr`, `MUL addr`, `DIV addr`, `MOD addr`, `INC`, `DEC` | ADD/…/MOD — да |
| Логика        | `AND`, `OR`, `XOR addr`, `NOT`                                         | AND/OR/XOR — да |
| Флаги         | `CLC`, `CLV`                                                           | нет             |

### Семантика основных инструкций

* `LOAD addr` — `ACC ← mem[addr]`
* `LOAD_IMM imm` — `ACC ← imm` (знаковый 32-битный)
* `LOAD_ACC` — `ACC ← mem[ACC]` (косвенная)
* `STORE addr` — `mem[addr] ← ACC`
* `STORE_IND addr` — `mem[mem[addr]] ← ACC` (косвенная по указателю)
* `LOAD_SP / STORE_SP` — работа с вершиной стека данных (SP-relative)
* `ADD addr` — `ACC ← ACC + mem[addr]`, обновляет NZVC
* `CALL addr` — `RS.push(PC_next); PC ← addr` (RS — аппаратный стек возвратов)
* `CALL_ACC` — то же, но `PC ← ACC`. Единственная инструкция, где PC берётся из ACC (`execute`).
* `RET` — `PC ← RS.pop()`
* `IRET` — `PC ← RS.pop(); ACC ← mem[ISR_ACC]; IE ← 1`

### Флаги АЛУ

| Флаг | Значение                          | Используется в           |
|------|-----------------------------------|--------------------------|
| Z    | Zero                              | BEQZ, BNEZ, BGTZ, BLEZ   |
| N    | Negative (sign)                   | BLTZ, BGEZ, BGTZ, BLEZ   |
| V    | Overflow (signed)                 | BVS, BVC                 |
| C    | Carry (unsigned)                  | BCS, BCC                 |

---

## Транслятор

`translator.py` → `Lexer` → `Parser` → `CodeGenerator`.

### Pipeline

```
*.forth ─► parse_tokens (lex)
       ─► Parser.parse() (AST: WordNode/IfNode/LoopNode/FuncDefNode/TickNode/…)
       ─► CodeGenerator.generate() ─► список dict-инструкций
       ─► resolve_labels() ─► байтовые адреса
       ─► isa.to_bytes() ─► бинарь .bin
       ─► isa.to_hex() ─► читаемый листинг .bin.hex
       + аналогично для статической памяти данных (.mem.bin / .mem.bin.hex)
```

### Компиляция стек-операций

Поскольку аккумуляторная архитектура не имеет «вершины стека» как явного регистра, операции Forth-стека компилируются через data stack в памяти: `LOAD_SP` читает `mem[SP]`, `STORE_SP` пишет `mem[SP]`. 
Инкремент/декремент SP отдельными инструкциями `INC_SP`/`DEC_SP`.


### Литералы строк

`"Hello"` укладывается в статическую память (C-строка с `\0`), на стек кладётся её базовый адрес. Печать строки реализуется циклом по `@ … emit` до встречи `0`.

---

## Модель процессора

### Граница CU / DataPath

| Компонент            | Где живёт   | Обоснование |
|----------------------|-------------|-------------|
| PC                   | ControlUnit | Поток управления |
| IR (8 бит)           | ControlUnit | Декодер инструкции |
| DR (32 бит)          | ControlUnit | Операнд из шины команд |
| fetch_phase (FSM)    | ControlUnit | Микро-управление |
| Return Stack         | ControlUnit | Поток управления (`CALL/RET/IRET`) |
| ACC                  | DataPath    | Данные |
| ALU + flags N,Z,V,C  | DataPath    | Данные |
| AC_SHADOW            | DataPath    | Данные (буферный регистр) |
| Data Memory          | DataPath    | Данные |
| SP                   | DataPath    | Данные (адрес в data memory) |
| Program Memory       | ControlUnit | Команды (Гарвард) |

**PC mux** — мультиплексор источников нового PC:
* `PC + instr_size` — инкрементер CU (нормальная последовательная выборка)
* `DR` — операнд (`JUMP / Bxx / CALL imm`); регистр CU
* `pop_return()` — стек возвратов CU (`RET / IRET`)
* `ACC` — единственный кросс-доменный сигнал DataPath→CU (только `CALL_ACC` и подъём ISR)

### Трёх-фазный fetch-FSM

В каждом такте процессор находится в одной из трёх фаз:

```
┌──────────────┐    ┌──────────────┐    ┌─────────────┐
│ 0: FETCH_OP  │───▶│ 1: FETCH_ARG │───▶│ 2: EXECUTE  │──┐
│              │    │  (опц.)      │    │             │  │
│ read 32b @PC │    │ read 32b @PC │    │ decode IR   │  │
│ IR <- hi byte│    │ DR <- signed │    │ +DR, run    │  │
│ PC += 1      │    │ PC += 4      │    │ tick(s)     │  │
└──────────────┘    └──────────────┘    └─────────────┘  │
       ▲                                                  │
       └──────── signal_latch_pc(...)  ◀──────────────────┘
                  
```

* Если опкод не требует аргумента → пропускаем FETCH_ARG.
* `signal_latch_pc(addr)` ставит `pc = addr; fetch_phase = 0; ir = None` — сброс машины выборки.
* `_complete_instruction()` — fall-through для большинства инструкций: PC уже инкрементирован в фазах fetch, остаётся только сбросить машину выборки.

### Шина команд

32 бита. На фазе FETCH_OP читаются 4 байта; используется только старший. На фазе FETCH_ARG читаются ещё 4 байта (адресуясь от PC, который уже на 1 байт впереди опкода).

---

## Суперскалярность (AC_SHADOW)

Один аккумулятор → нельзя одновременно загружать и хранить.
Решение — **shadow-регистр** `AC_SHADOW`, в который параллельно «отложенно» сохраняется ACC. Три ключевых сценария:

### 1. Deferred store (отложенная запись)

`STORE addr` при пустом shadow → ACC ↔ AC_SHADOW свапаются (`signal_shadow_swap`), фактическая запись в память откладывается до момента, когда shadow понадобится для другой цели. **0 обращений к памяти за такт.**

### 2. Shadow forwarding / dead-load elimination

`LOAD addr`, если `shadow_addr == addr` → значение уже в shadow → копируем `AC_SHADOW → ACC` без чтения памяти.  
Если `acc_addr == addr` → значение уже в ACC → пропускаем чтение (dead-load elim).

### 3. Parallel flush (2 операции памяти за 1 такт)

Когда shadow занят чужим адресом, а нужен новый `STORE` или `LOAD`: **параллельно** записываем `shadow_value → mem[shadow_addr]` и выполняем основную операцию (`signal_shadow_parallel_flush`,`signal_shadow_flush_and_load`).

### Барьеры

Перед сменой потока управления (JUMP, Bxx, CALL, RET, IRET, HALT) shadow обязательно сбрасывается через [`_flush_shadow`](control_unit.py:171). Это гарантирует, что отложенный store произойдёт до изменения PC.

### Корректность для MMIO

`signal_shadow_parallel_flush` и `signal_shadow_flush_and_load` идут через `_mem_write` для записи shadow.

---

## Прерывания и I/O

* **Trap-based**: ввод не опрашивается, а доставляется через прерывание по расписанию `[(tick, char_code), …]`, сохранённому в `input.json` теста.
* **MMIO**: `mem[3]=INPUT`, `mem[4]=OUTPUT`. Слово `key` компилируется в `LOAD INPUT_ADDR`, `emit` — в запись в `OUTPUT_ADDR`.
* **IVT**: `mem[0]` хранит байтовый адрес ISR (заполняется компилятором при наличии `:isr`).
* **Поведение CU при IRQ** ([`control_unit.py`](control_unit.py:632)):
  1. сохраняем ACC в `ISR_ACC`,
  2. push PC в return stack,
  3. PC ← `mem[0]`,
  4. IE ← 0 (запрет вложенных прерываний),
  5. в `IRET`: PC ← RS.pop, ACC ← `mem[5]`, IE ← 1.

Прерывание принимается только между инструкциями (когда `fetch_phase == 0` и `step == 0`).

---

## Тесты

### Golden-тесты

Тестирование реализовано с помощью плагина `pytest-golden`.
Каждый кейс представляет собой YAML-файл в директории `golden/`:

```yaml
source: |
  \ Исходный код на Forth
input:
  - [10, 104] \ Расписание прерываний: [tick, char_code]
translator_output: |
  \ Ожидаемый вывод транслятора
machine_output: |
  \ Ожидаемый вывод симулятора (stdout)
machine_err: |
  \ Ожидаемый вывод симулятора (stderr)
log: |
  \ Ожидаемый лог работы процессора
```

### Список реализованных кейсов

| Кейс              | Описание                                                            |
|-------------------|---------------------------------------------------------------------|
| `hello`           | «Hello, World!» через статическую строку и `emit`                  |
| `cat`             | Чтение из ввода до символа `\n`, перевывод (echo)                  |
| `hello_user_name` | Печать prompt, чтение имени, печать приветствия                    |
| `prob1`           | Project Euler #1 (`prob1` варианта): сумма кратных 3 и 5 ниже N=10 |
| `sort`            | Пузырьковая сортировка массива из ввода                            |
| `double_precision`| Сложение/вычитание двух 64-битных чисел (hi/lo) через флаги C/V    |

### Запуск тестов

```bash
# Запуск тестов
pytest golden/

# Обновление эталонов (если изменилась логика или формат вывода)
pytest --update-goldens golden/
```

---

## Запуск

### Транслятор

```bash
python3 translator.py <source.forth> <code.bin> <memory.bin>
# Создаёт также <code.bin.hex> и <memory.bin.hex> с человекочитаемым листингом.
```

### Симулятор

```bash
python3 machine.py <code.bin> <memory.bin> <input.json> [--debug] [--no-superscalar]
```

* `--debug` — печать tick-accurate лога;
* `--no-superscalar` — отключение суперскалярности.


### Сравнение superscalar vs baseline

| Кейс | Такты (Superscalar) | Такты (Baseline) | Ускорение |
|---|---|---|---|
| `cat` | 1315 | 1312 | -0.2% |
| `double_precision` | 7848 | 8766 | 10.5% |
| `hello` | 1214 | 1351 | 10.1% |
| `hello_user_name` | 3267 | 3630 | 10.0% |
| `prob1` | 270184 | 299830 | 9.9% |
| `sort` | 252331 | 284450 | 11.3% |

*Примечание: в тесте `cat` наблюдается небольшое замедление (-0.2%). Это связано с накладными расходами на механизм суперскалярности в условиях частых ветвлений. Перед любой инструкцией, меняющей поток управления (`JUMP`, `BEQZ`, `CALL` и т.д.), процессор обязан принудительно сбросить (flush) теневой регистр `AC_SHADOW` в память, что занимает 1 дополнительный такт. Код `cat` состоит из очень короткого цикла с частыми проверками условий, где полезных параллельных операций почти не происходит, а накладные расходы на сброс теневого регистра перед прыжками перевешивают выгоду.*