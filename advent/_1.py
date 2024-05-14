from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE

from .base import Base
from .utils import SScratchVar, Swap, Nop


class Solution(Base):
    work_ints: Final[AccountStateValue] = ReservedAccountStateValue(
        stack_type=TealType.uint64, max_keys=4
    )

    @internal(TealType.uint64)
    def solve_impl(self):
        current = SScratchVar(TealType.uint64)
        top1 = SScratchVar(TealType.uint64)
        top2 = SScratchVar(TealType.uint64)
        top3 = SScratchVar(TealType.uint64)
        state = dict(current=current, top1=top1, top2=top2, top3=top3)

        return Seq(
            current.store(0),
            top1.store(0),
            top2.store(0),
            top3.store(0),
            (input := SScratchVar(TealType.uint64)).store(0),
            self.load_work(state),
            While(self.reader_available()).Do(
                self.check_low_budget(state),
                (got_input := ScratchVar()).store(self.reader_next_uint(input)),
                If(got_input.load()).Then(current.inc(input.load())),
                If(Or(Not(got_input.load()), self.reader_done())).Then(
                    If(current.load() > top3.load()).Then(top3.store(current.load())),
                    If(top3.load() > top2.load()).Then(Swap(top2, top3)),
                    If(top2.load() > top1.load()).Then(Swap(top1, top2)),
                    current.store(0),
                ),
                Nop(),  # Without pyteal fails
            ),
            self.set_solution(top1, top1.load() + top2.load() + top3.load()),
            Return(TRUE),
        )
