from pyteal import *
from beaker import *
from beaker.decorators import *
from beaker.consts import TRUE

from .base import Base
from .utils import (
    AbsDiff,
    BoxScratchStore,
    Nop,
    SScratchVar,
    BoxAllocator,
    itoa,
)


class Solution(Base):
    work_bytes = ReservedAccountStateValue(TealType.bytes, max_keys=1)

    part_one: AccountStateValue = AccountStateValue(TealType.bytes)
    part_two: AccountStateValue = AccountStateValue(TealType.bytes, key=Bytes("P"))
    part_two2: AccountStateValue = AccountStateValue(TealType.bytes, key=Bytes("Q"))

    @external
    def get_solution(self, *, output: abi.Tuple2[abi.String, abi.String]):
        return Seq(
            (part_one := abi.String()).set(self.part_one.get()),
            (tmp := SScratchVar()).store(
                Concat(self.part_two.get(), self.part_two2.get())
            ),
            (part_two := abi.String()).set(
                Concat(
                    *[
                        j
                        for i in range(6)
                        for j in [
                            Extract(tmp.load(), Int(i * 40), Int(40)),
                            Bytes("\n"),
                        ]
                    ]
                )
            ),
            output.set(part_one, part_two),
        )

    def work_box_size(self):
        return 8 * 3 + 40 * 6

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
            x := SScratchVar(TealType.uint64),
            cycle := SScratchVar(TealType.uint64),
            total := SScratchVar(TealType.uint64),
            (crt := SScratchVar(TealType.bytes), 40 * 6),
        )
        cached = [scratch]
        midpoint = 2**32

        imm = SScratchVar(TealType.uint64)
        imm_sig = SScratchVar(TealType.uint64)

        @Subroutine(TealType.none)
        def Cycle():
            return Seq(
                Seq(
                    [
                        If(cycle == i - 1).Then(
                            If(x >= midpoint)
                            .Then(total.inc((x - midpoint) * Int(i)))
                            .Else(total.dec((Int(midpoint) - x.load()) * Int(i)))
                        )
                        for i in [20, 60, 100, 140, 180, 220]
                    ]
                ),
                If(AbsDiff(Int(midpoint) + (cycle % Int(40)), x.load()) < Int(2)).Then(
                    crt.store(SetByte(crt.load(), cycle.load(), Int(ord("#"))))
                ),
                cycle.inc(),
            )

        return Seq(
            imm.store(0),
            imm_sig.store(0),
            self.init_state(state),
            self.load_work(state),
            If(work_box == "")
            .Then(
                work_box.store(self.work_box()),
                Seq([x.cache() for x in cached]),
                x.store(midpoint + 1),
                cycle.store(0),
                total.store(midpoint),
                crt.store("." * 40 * 6),
            )
            .Else(Seq([x.cache() for x in cached])),
            #
            While(self.reader_available()).Do(
                self.check_low_budget(self.flush(state, cached), 1),
                (op := SScratchVar()).store(self.reader_next(Int(4))),
                self.reader_index().inc(),
                If(op == "noop")
                .Then(
                    Cycle(),
                )
                .ElseIf(op == "addx")
                .Then(
                    Cycle(),
                    Cycle(),
                    Assert(self.reader_next_int(imm, imm_sig)),
                    If(imm_sig.load()).Then(x.dec(imm)).Else(x.inc(imm)),
                ),
                Nop(),
            ),
            self.flush(state, cached),
            If(total >= midpoint)
            .Then(self.set_solution(itoa(total - midpoint)))
            .Else(
                self.set_solution(
                    Concat(Bytes("-"), itoa(Int(midpoint) - total.load()))
                )
            ),
            self.part_two.set(Extract(crt.load(), Int(0), Len(crt.load()) / Int(2))),
            self.part_two2.set(Suffix(crt.load(), Len(crt.load()) / Int(2))),
            Return(TRUE),
        )
