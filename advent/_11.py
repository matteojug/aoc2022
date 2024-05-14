from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE

from .base import Base
from .utils import (
    BoxArrayStruct,
    BoxScratchStore,
    Forever,
    SScratchVar,
    BoxAllocator,
    Swap,
)

MAX_ITEMS = 50
MAX_MONKEYS = 10


class Item:
    value = Int
    monkey = Int


class Monkey:
    cnt = Int
    op = Bytes, 1
    arg = Int
    test = Int
    if_true = Int
    if_false = Int


class Solution(Base):
    work_bytes = ReservedAccountStateValue(TealType.bytes, max_keys=1)

    def work_box_size(self):
        return 8 * 6 + 2 * (
            MAX_ITEMS * BoxArrayStruct.element_size(Item)
            + MAX_MONKEYS * BoxArrayStruct.element_size(Monkey)
        )

    def flush(self, state: dict, cached):
        return Seq(self.save_work(state), Seq([x.flush() for x in cached]))

    @internal(TealType.uint64)
    def solve_impl(self):
        state = dict(
            work_box=(work_box := SScratchVar(TealType.bytes)),
        )
        alloc = BoxAllocator(work_box.load())
        scratch = BoxScratchStore(
            alloc,
            phase := SScratchVar(TealType.uint64),
            round := SScratchVar(TealType.uint64),
            turn := SScratchVar(TealType.uint64),
            cnt_monkey := SScratchVar(TealType.uint64),
            cnt_items := SScratchVar(TealType.uint64),
            mod := SScratchVar(TealType.uint64),
        )
        items = BoxArrayStruct(alloc, Item, MAX_ITEMS)
        monkeys = BoxArrayStruct(alloc, Monkey, MAX_MONKEYS)
        items_bak = alloc.alloc(items.area.size)
        monkeys_bak = alloc.alloc(monkeys.area.size)
        cached = [scratch, items, monkeys]

        tmp = SScratchVar()
        OLD = 2**64 - 1

        return Seq(
            tmp.store(0),
            self.init_state(state),
            self.load_work(state),
            If(work_box == "")
            .Then(
                work_box.store(self.work_box()),
                Seq([x.cache() for x in cached]),
                scratch.init(),
                mod.store(1),
                While(self.reader_available()).Do(
                    self.reader_index().inc(7),
                    Assert(self.reader_next_uint(tmp)),
                    Assert(tmp == cnt_monkey),
                    monkeys[cnt_monkey].cnt.set(0),
                    self.reader_index().inc(19),
                    Forever().Do(
                        Assert(self.reader_next_uint(tmp)),
                        items[cnt_items].value.set(tmp),
                        items[cnt_items].monkey.set(cnt_monkey),
                        cnt_items.inc(),
                        If(
                            self.reader_get(self.reader_index() - 1, Int(1))
                            == Bytes("\n")
                        ).Then(Break()),
                        self.reader_index().inc(),
                    ),
                    #
                    Assert(
                        self.reader_next(Int(23)) == Bytes("  Operation: new = old ")
                    ),
                    monkeys[cnt_monkey].op.set(self.reader_next(Int(1))),
                    tmp.store(monkeys[cnt_monkey].op),
                    Assert(Or(tmp == "*", tmp == "+")),
                    self.reader_index().inc(),
                    If(
                        self.reader_get(self.reader_index().load(), Int(1))
                        == Bytes("o")
                    )
                    .Then(
                        monkeys[cnt_monkey].arg.set(OLD),
                        self.reader_index().inc(4),
                    )
                    .Else(
                        Assert(self.reader_next_uint(tmp)),
                        monkeys[cnt_monkey].arg.set(tmp),
                    ),
                    #
                    Assert(self.reader_next(Int(21)) == Bytes("  Test: divisible by ")),
                    Assert(self.reader_next_uint(tmp)),
                    monkeys[cnt_monkey].test.set(tmp),
                    mod.store(mod * tmp),
                    #
                    Assert(
                        self.reader_next(Int(29))
                        == Bytes("    If true: throw to monkey ")
                    ),
                    Assert(self.reader_next_uint(tmp)),
                    monkeys[cnt_monkey].if_true.set(tmp),
                    #
                    Assert(
                        self.reader_next(Int(30))
                        == Bytes("    If false: throw to monkey ")
                    ),
                    Assert(self.reader_next_uint(tmp)),
                    monkeys[cnt_monkey].if_false.set(tmp),
                    #
                    cnt_monkey.inc(),
                    If(self.reader_available()).Then(self.reader_index().inc()),
                ),
                monkeys_bak.copy(monkeys.area),
                items_bak.copy(items.area),
            )
            .Else(Seq([x.cache() for x in cached])),
            #
            Forever().Do(
                self.check_low_budget(self.flush(state, cached), 5),
                (insp := SScratchVar(TealType.uint64)).store(monkeys[turn].cnt),
                (arg := SScratchVar()).store(monkeys[turn].arg),
                (op := SScratchVar()).store(monkeys[turn].op),
                (test := SScratchVar()).store(monkeys[turn].test),
                (if_false := SScratchVar()).store(monkeys[turn].if_false),
                (if_true := SScratchVar()).store(monkeys[turn].if_true),
                For(
                    (i := SScratchVar(TealType.uint64)).store(0), i < cnt_items, i.inc()
                ).Do(
                    If(items[i].monkey.get() != turn.load()).Then(Continue()),
                    insp.inc(),
                    (old := SScratchVar()).store(items[i].value),
                    tmp.store(arg),
                    If(tmp == OLD).Then(tmp.store(old)),
                    If(op == "+").Then(old.store(old + tmp)).Else(old.store(old * tmp)),
                    If(phase == 0)
                    .Then(
                        old.store(old / 3),
                    )
                    .Else(
                        old.store(old % mod),
                    ),
                    items[i].value.set(old),
                    If(old % test)
                    .Then(items[i].monkey.set(if_false))
                    .Else(items[i].monkey.set(if_true)),
                ),
                monkeys[turn].cnt.set(insp),
                turn.inc(),
                If(turn == cnt_monkey).Then(
                    turn.store(0),
                    round.inc(),
                    If(Or(And(phase == 0, round == 20), round == 10000)).Then(
                        (top0 := SScratchVar()).store(0),
                        (top1 := SScratchVar()).store(0),
                        For((i := SScratchVar()).store(0), i < cnt_monkey, i.inc()).Do(
                            tmp.store(monkeys[i].cnt.get()),
                            If(tmp > top1).Then(
                                top1.store(tmp), If(top1 > top0).Then(Swap(top0, top1))
                            ),
                        ),
                        If(phase == 0)
                        .Then(
                            self.set_solution(part_one=top0 * top1),
                            phase.inc(),
                            round.store(0),
                            monkeys.area.copy(monkeys_bak),
                            items.area.copy(items_bak),
                        )
                        .Else(
                            self.set_solution(part_two=top0 * top1),
                            Break(),
                        ),
                    ),
                ),
            ),
            self.flush(state, cached),
            Return(TRUE),
        )
