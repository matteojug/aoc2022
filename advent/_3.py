from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE

from .base import Base
from .utils import SScratchVar, Bitmask


BITMASK_SIZE = 53


class Solution(Base):
    work_ints: Final[AccountStateValue] = ReservedAccountStateValue(
        stack_type=TealType.uint64, max_keys=6
    )

    def char_to_pri(self, i: Expr):
        return (
            If(i < Int(ord("a")))
            .Then(i - Int(ord("A") - 27))
            .Else(i - Int(ord("a") - 1))
        )

    @internal(TealType.uint64)
    def solve_impl(self):
        total = SScratchVar(TealType.uint64)
        total2 = SScratchVar(TealType.uint64)
        line_num = SScratchVar(TealType.uint64)
        group = [Bitmask(BITMASK_SIZE) for _ in range(3)]

        state = dict(
            total=total,
            total2=total2,
            line_num=line_num,
            **{f"group{i}": g.scratch for i, g in enumerate(group)},
        )

        return Seq(
            total.store(0),
            total2.store(0),
            line_num.store(0),
            Seq([g.create() for g in group]),
            self.load_work(state),
            While(self.reader_available()).Do(
                self.check_low_budget(state, 6),
                (line := ScratchVar(TealType.bytes)).store(self.reader_next_line()),
                (mask1 := Bitmask(BITMASK_SIZE)).create(),
                (mask2 := Bitmask(BITMASK_SIZE)).create(),
                (size := ScratchVar()).store(Len(line.load()) / Int(2)),
                (line_2 := ScratchVar()).store(Suffix(line.load(), size.load())),
                For((i := SScratchVar()).store(0), i < size, i.inc()).Do(
                    mask1.set(self.char_to_pri(GetByte(line.load(), i.load()))),
                    mask2.set(self.char_to_pri(GetByte(line_2.load(), i.load()))),
                ),
                For((i := SScratchVar()).store(1), i < BITMASK_SIZE, i.inc()).Do(
                    If(mask1.get(i.load())).Then(If(mask2.get(i.load())).Then(Break()))
                ),
                total.inc(i),
                If(line_num % 3 == Int(0))
                .Then(group[0].store(mask1 | mask2))
                .ElseIf(line_num % 3 == Int(1))
                .Then(group[1].store(mask1 | mask2))
                .Else(
                    group[2].store(mask1 | mask2),
                    For((i := SScratchVar()).store(1), i < BITMASK_SIZE, i.inc()).Do(
                        If(
                            group[0].get(i.load())
                            & group[1].get(i.load())
                            & group[2].get(i.load())
                        ).Then(Break()),
                    ),
                    total2.inc(i),
                ),
                line_num.inc(),
            ),
            self.set_solution(total, total2),
            Return(TRUE),
        )
