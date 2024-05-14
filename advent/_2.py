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

    def to_int(self, move: Expr, base: str):
        return move - Int(ord(base))

    # A for Rock, B for Paper, and C for Scissors.
    # X for Rock, Y for Paper, and Z for Scissors.
    def score(self, a: Expr, b: Expr):
        return (
            b
            + Int(1)
            + If(a == b)
            .Then(Int(3))
            .ElseIf(Mod(a + Int(1), Int(3)) == b)
            .Then(Int(6))
            .Else(Int(0))
        )

    # X=0 lose, Y=1 draw, Z=2 win
    def score_strat(self, a: Expr, b: Expr):
        return self.score(a, Mod(a + Int(2) + b, Int(3)))

    @internal(TealType.uint64)
    def solve_impl(self):
        total = SScratchVar(TealType.uint64)
        total_2 = SScratchVar(TealType.uint64)
        state = dict(total=total, total_2=total_2)
        return Seq(
            total.store(0),
            total_2.store(0),
            self.load_work(state),
            While(self.reader_available()).Do(
                self.check_low_budget(state),
                (line := ScratchVar(TealType.bytes)).store(self.reader_next(Int(4))),
                (move_a := ScratchVar(TealType.uint64)).store(
                    self.to_int(GetByte(line.load(), Int(0)), "A")
                ),
                (move_b := ScratchVar(TealType.uint64)).store(
                    self.to_int(GetByte(line.load(), Int(2)), "X")
                ),
                total.inc(self.score(move_a.load(), move_b.load())),
                total_2.inc(self.score_strat(move_a.load(), move_b.load())),
            ),
            self.set_solution(total, total_2),
            Return(TRUE),
        )
