from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE

from .base import Base
from .utils import SScratchVar


class Solution(Base):
    work_ints: Final[AccountStateValue] = ReservedAccountStateValue(
        stack_type=TealType.uint64, max_keys=2
    )

    @internal(TealType.uint64)
    def solve_impl(self):
        total = SScratchVar(TealType.uint64)
        total2 = SScratchVar(TealType.uint64)

        state = dict(
            total=total,
            total2=total2,
        )

        return Seq(
            total.store(0),
            total2.store(0),
            self.load_work(state),
            (first_l := SScratchVar()).store(0),
            (first_r := SScratchVar()).store(0),
            (second_l := SScratchVar()).store(0),
            (second_r := SScratchVar()).store(0),
            While(self.reader_available()).Do(
                self.check_low_budget(state),
                Assert(self.reader_next_uint(first_l)),
                Assert(self.reader_next_uint(first_r)),
                Assert(self.reader_next_uint(second_l)),
                Assert(self.reader_next_uint(second_r)),
                If(
                    Or(
                        And(first_l <= second_l, first_r >= second_r),
                        And(second_l <= first_l, second_r >= first_r),
                    )
                ).Then(total.inc()),
                If(Not(Or(first_r < second_l, second_r < first_l))).Then(total2.inc()),
            ),
            self.set_solution(total, total2),
            Return(TRUE),
        )
