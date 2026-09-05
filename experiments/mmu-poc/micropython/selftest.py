import gc

def fib(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a

assert fib(20) == 6765
assert fib(47) == 2971215073
assert 2 ** 100 == 1267650600228229401496703205376
assert sum([i * i for i in range(10)]) == 285
assert {"answer": 42}["answer"] == 42
print("PASS: arithmetic, big integers, lists and dictionaries")

class Box:
    def __init__(self, value):
        self.value = value
assert Box("hello").value == "hello"

try:
    1 // 0
    assert False
except ZeroDivisionError:
    pass
print("PASS: classes and caught exceptions")

roots = [["root", i] for i in range(30)]
for i in range(300):
    temporary = [j for j in range(40)]
    if i % 10 == 0:
        gc.collect()
    assert roots[i % 30][1] == i % 30
    assert temporary[39] == 39
gc.collect()
print("PASS: GC stress and retained roots")
print("MICROPYTHON MMU SELFTEST PASS")
